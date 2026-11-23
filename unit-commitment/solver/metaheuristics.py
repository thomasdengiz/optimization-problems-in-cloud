"""
Unit Commitment - Metaheuristics: evolutionary algorithm (EA) and particle swarm optimization (PSO)

Both algorithms search over the same three groups of decision variables, one value per hour:
  u[t, g]  on/off state of conventional plant g          (EA: 0 or 1, PSO: position in [0, 1], on if >= 0.5)
  p[t, g]  requested output as a fraction of pmax         (0 ... 1)
  s[t, k]  pump-storage setpoint: >0 turbine, <0 pump     (-1 ... 1, fraction of the rated power)

A candidate made of random values violates the constraints almost always. Therefore every candidate is
repaired before its cost is computed (see `Problem.repair`). The repair does not optimize anything: it
changes the requested values only as far as needed to satisfy the constraints of the exact model
(minimum up/down time, pmax, ramp limits, biomass energy budget, pump-storage reservoir limits and
demand coverage). The repaired values are written back into the candidate, so the search continues
from a feasible point.

The whole population is processed at once with numpy arrays of shape (hours, candidates, plants).
"""
import time

import numpy as np

from .exact import count_decision_variables, hourly_generation_cost, load_data
from .priority_list import FINAL_SOC_MAX, FINAL_SOC_MIN, check_feasibility

# Cost (EUR per MWh) of demand that could not be covered or of biomass energy above its limit.
# Much higher than any marginal cost, so candidates with remaining violations lose every comparison.
PENALTY_EUR_PER_MWH = 10_000.0

EPS          = 1e-12
FRESH_HOURS  = 10**6   # "no minimum time pending" for the counters of the first hour
ELITE_COUNT  = 2       # EA: best candidates copied unchanged into the next generation
TOURNAMENT   = 3       # EA: candidates compared in one selection tournament
SIGMA_P      = 0.15    # EA: standard deviation of the mutation of p genes
SIGMA_S      = 0.30    # EA: standard deviation of the mutation of s genes
VELOCITY_MAX = 0.5     # PSO: largest step per iteration as a fraction of the value range

DEFAULT_SEED = 42

# Defaults found by trying values on the small scenario (day and week): a low mutation rate works best
# for the EA because a plan has thousands of genes; PSO needs a high inertia and large steps to keep
# exploring instead of collapsing onto the first best plan.
EA_DEFAULTS = {
    "population_size": 40,
    "generations":     300,
    "mutation_rate":   0.002,
    "crossover_rate":  0.8,
}
PSO_DEFAULTS = {
    "swarm_size": 40,
    "iterations": 300,
    "inertia":    0.9,
    "cognitive":  1.5,
    "social":     1.5,
}


def estimate_metaheuristic_memory_mb(
    scenario: str, month: int, data_dir: str, horizon: str, population_size: int,
) -> float:
    """Roughly estimate the peak memory (MB): about 150 MB base plus ~60 bytes per (hour, candidate, plant)."""
    data = load_data(scenario, month, data_dir, horizon)
    n_plants = sum(1 for p in data["plants"] if p["type"] != "pump_storage")
    return 150 + 60 * data["T"] * population_size * n_plants / 1e6


class Problem:
    """Plant data as numpy arrays plus the repair and evaluation of a whole population."""

    def __init__(self, scenario: str, month: int, data_dir: str, horizon: str) -> None:
        self.data  = load_data(scenario, month, data_dir, horizon)
        plants     = self.data["plants"]
        self.conv  = [p for p in plants if p["type"] != "pump_storage"]
        self.pumps = [p for p in plants if p["type"] == "pump_storage"]
        self.T, self.G, self.K = self.data["T"], len(self.conv), len(self.pumps)

        self.pmax      = np.array([p["pmax_mw"] for p in self.conv])
        self.ramp_up   = np.array([p["ramp_up_mw_per_h"] for p in self.conv])
        self.ramp_down = np.array([p["ramp_down_mw_per_h"] for p in self.conv])
        self.min_up    = np.array([p["min_uptime_h"] for p in self.conv])
        self.min_down  = np.array([p["min_downtime_h"] for p in self.conv])
        self.cost      = np.array([p["marginal_cost"] for p in self.conv])
        self.is_biomass = np.array([p["type"] == "biomass" for p in self.conv])
        self.bio_limit = np.array([p.get("biomass_limit_mwh", np.inf) for p in self.conv])

        self.s_pmax = np.array([p["pmax_mw"] for p in self.pumps])
        self.s_cap  = np.array([p["energy_capacity_mwh"] for p in self.pumps])
        self.s_eff  = np.array([p["efficiency"] for p in self.pumps])

        # Demand that conventional plants and storage have to cover: load - wind - pv
        self.net_base = np.array(self.data["load"]) - np.array(self.data["wind"]) - np.array(self.data["pv"])

    def repair(self, u: np.ndarray, p: np.ndarray, s: np.ndarray, keep_schedule: bool = False) -> dict:
        """Make every candidate feasible, hour by hour, and write the repaired values back into u, p and s.

        Per hour (the same order for all candidates):
          1. Pump storage: turn the setpoint into charge/discharge power and clip it so the reservoir
             stays between empty and full and can still reach 49-51% at the end of the horizon.
          2. Plants: allowed range [lo, hi] from ramp limits, pmax, minimum up/down time and biomass budget.
             The requested output is clipped into this range.
          3. Demand: a shortage is distributed over the running plants in proportion to their remaining
             headroom, a surplus is removed in proportion to the output above their lower limit.
             If a shortage remains, plants that are off (and not blocked by their minimum down time)
             are started in the same proportional way.
        Returns the cost per candidate, the remaining violations and, if keep_schedule is True,
        the schedule arrays (generation, online, pumping, turbining).
        """
        T, P, G = u.shape
        K = self.K

        p_prev    = np.zeros((P, G))
        on_prev   = np.zeros((P, G), dtype=bool)
        hours_on  = np.zeros((P, G), dtype=np.int64)
        hours_off = np.full((P, G), FRESH_HOURS, dtype=np.int64)
        energy    = np.zeros((P, G))
        soc       = np.tile(0.5 * self.s_cap, (P, 1))
        cost      = np.zeros(P)
        unserved  = np.zeros(P)

        if keep_schedule:
            generation = np.zeros((T, P, G))
            online     = np.zeros((T, P, G), dtype=bool)
            pumping    = np.zeros((T, P, K))
            turbining  = np.zeros((T, P, K))

        for t in range(T):
            # 1. Pump storage ------------------------------------------------------------------
            net_storage = np.zeros(P)
            if K:
                hours_left = T - 1 - t
                # Reservoir bounds: physical limits, one hour of pumping/turbining, and what is
                # still needed to reach the final band 49-51% of the capacity
                low = np.maximum(
                    np.maximum(0.0, FINAL_SOC_MIN * self.s_cap - self.s_eff * self.s_pmax * hours_left),
                    soc - self.s_pmax,
                )
                high = np.minimum(
                    np.minimum(self.s_cap, FINAL_SOC_MAX * self.s_cap + self.s_pmax * hours_left),
                    soc + self.s_eff * self.s_pmax,
                )
                high = np.maximum(high, low)
                delta   = -s[t] * self.s_pmax * np.where(s[t] < 0, self.s_eff, 1.0)  # stored energy change
                new_soc = np.clip(soc + delta, low, high)
                delta   = new_soc - soc
                pump_t  = np.where(delta > 0, delta / self.s_eff, 0.0)
                turb_t  = np.where(delta < 0, -delta, 0.0)
                s[t]    = np.where(delta > 0, -pump_t, turb_t) / self.s_pmax
                soc     = new_soc
                net_storage = (turb_t - pump_t).sum(axis=1)
                if keep_schedule:
                    pumping[t], turbining[t] = pump_t, turb_t

            required = np.maximum(self.net_base[t] - net_storage, 0.0)  # MW the plants must deliver

            # 2. Allowed output range per plant ------------------------------------------------
            wanted_on = u[t] >= 0.5
            if t == 0:  # no ramp limits and no minimum times in the first hour, like in the exact model
                lo      = np.zeros((P, G))
                cap_up  = np.broadcast_to(self.pmax, (P, G))
                blocked = np.zeros((P, G), dtype=bool)
                run     = wanted_on
            else:
                lo        = np.maximum(p_prev - self.ramp_down, 0.0)
                cap_up    = np.minimum(self.pmax, p_prev + self.ramp_up)
                must_stay = on_prev & (hours_on < self.min_up)     # minimum up time still running
                blocked   = ~on_prev & (hours_off < self.min_down)  # minimum down time still running
                run       = (wanted_on | must_stay) & ~blocked
            cap_up = np.where(self.is_biomass, np.minimum(cap_up, np.maximum(self.bio_limit - energy, 0.0)), cap_up)
            cap_up = np.maximum(cap_up, lo)
            hi     = np.where(run, cap_up, lo)  # a plant that is not running only ramps down

            want = np.clip(p[t] * self.pmax, lo, hi)

            # 3. Demand coverage -----------------------------------------------------------------
            diff      = required - want.sum(axis=1)
            head      = hi - want
            slack     = want - lo
            head_sum  = head.sum(axis=1)
            slack_sum = slack.sum(axis=1)
            raise_by  = np.where(head_sum > 0, np.minimum(np.maximum(diff, 0.0) / np.maximum(head_sum, EPS), 1.0), 0.0)
            lower_by  = np.where(slack_sum > 0, np.minimum(np.maximum(-diff, 0.0) / np.maximum(slack_sum, EPS), 1.0), 0.0)
            gen = want + head * raise_by[:, None] - slack * lower_by[:, None]

            short = required - gen.sum(axis=1)
            if (short > 1e-9).any():  # start plants that are off
                extra     = np.where(~run & ~blocked, np.maximum(cap_up - gen, 0.0), 0.0)
                extra_sum = extra.sum(axis=1)
                start_by  = np.where(extra_sum > 0, np.minimum(np.maximum(short, 0.0) / np.maximum(extra_sum, EPS), 1.0), 0.0)
                gen = gen + extra * start_by[:, None]

            unserved += np.maximum(required - gen.sum(axis=1), 0.0)
            on_now = run | (gen > 0)

            # Write the repaired values back and update the counters
            u[t] = np.where(wanted_on == on_now, u[t], on_now)
            p[t] = gen / self.pmax
            if t == 0:
                hours_on  = np.where(on_now, FRESH_HOURS, 0)
                hours_off = np.where(on_now, 0, FRESH_HOURS)
            else:
                hours_on  = np.where(on_now, np.where(on_prev, hours_on + 1, 1), 0)
                hours_off = np.where(on_now, 0, np.where(on_prev, 1, hours_off + 1))
            energy += gen
            cost   += gen @ self.cost
            p_prev, on_prev = gen, on_now
            if keep_schedule:
                generation[t], online[t] = gen, on_now

        bio_excess = np.maximum(energy - self.bio_limit, 0.0).sum(axis=1)
        result = {"cost": cost, "unserved": unserved, "bio_excess": bio_excess}
        if keep_schedule:
            result.update(generation=generation, online=online, pumping=pumping, turbining=turbining)
        return result

    def evaluate(self, u: np.ndarray, p: np.ndarray, s: np.ndarray) -> np.ndarray:
        """Repair the candidates (in place) and return their fitness: cost plus penalties, lower is better."""
        r = self.repair(u, p, s)
        return r["cost"] + PENALTY_EUR_PER_MWH * (r["unserved"] + r["bio_excess"])


# ---------------------------------------------------------------------------------------------
# Evolutionary algorithm
# ---------------------------------------------------------------------------------------------

def _tournament(rng: np.random.Generator, fitness: np.ndarray, count: int) -> np.ndarray:
    """Pick `count` parents: each one is the best of TOURNAMENT randomly drawn candidates."""
    drawn = rng.integers(0, len(fitness), size=(count, TOURNAMENT))
    return drawn[np.arange(count), np.argmin(fitness[drawn], axis=1)]


def _crossover(rng: np.random.Generator, genes: tuple, rate: float) -> None:
    """Neighbouring pairs swap everything from a random hour onwards (one-point crossover in time)."""
    T, n_children = genes[0].shape[0], genes[0].shape[1]
    n_pairs = n_children // 2
    cut  = np.where(rng.random(n_pairs) < rate, rng.integers(1, T, size=n_pairs), T)
    swap = (np.arange(T)[:, None] >= cut[None, :])[:, :, None]
    for x in genes:
        a = x[:, 0:2 * n_pairs:2].copy()
        b = x[:, 1:2 * n_pairs:2].copy()
        x[:, 0:2 * n_pairs:2] = np.where(swap, b, a)
        x[:, 1:2 * n_pairs:2] = np.where(swap, a, b)


def _mutate(rng: np.random.Generator, u: np.ndarray, p: np.ndarray, s: np.ndarray, rate: float) -> None:
    """Flip on/off genes and add Gaussian noise to the output genes, each gene with probability `rate`."""
    flip = rng.random(u.shape, dtype=np.float32) < rate
    u[flip] = 1.0 - u[flip]
    for x, sigma, low in ((p, SIGMA_P, 0.0), (s, SIGMA_S, -1.0)):
        if x.size == 0:
            continue
        noise = rng.standard_normal(x.shape, dtype=np.float32) * np.float32(sigma)
        x += np.where(rng.random(x.shape, dtype=np.float32) < rate, noise, np.float32(0.0))
        np.clip(x, low, 1.0, out=x)


def _random_genes(rng: np.random.Generator, T: int, n: int, G: int, K: int, continuous_u: bool) -> tuple:
    """Random start candidates: on/off genes (binary for the EA, continuous for PSO), outputs and storage."""
    u = rng.random((T, n, G), dtype=np.float32)
    if not continuous_u:
        u = (u < 0.5).astype(np.float32)
    p = rng.random((T, n, G), dtype=np.float32)
    s = rng.uniform(-1.0, 1.0, size=(T, n, K)).astype(np.float32)
    return u, p, s


def _run_ea(problem: Problem, rng: np.random.Generator, deadline: float, population_size: int,
            generations: int, mutation_rate: float, crossover_rate: float):
    """Generational EA with tournament selection, crossover, mutation and elitism (see module docstring)."""
    T, P = problem.T, population_size
    elite_count = min(ELITE_COUNT, P - 2)
    u, p, s = _random_genes(rng, T, P, problem.G, problem.K, continuous_u=False)
    fitness = problem.evaluate(u, p, s)
    history = [float(fitness.min())]
    stopped = False

    for _ in range(generations):
        if time.perf_counter() >= deadline:
            stopped = True
            break
        elite     = np.argsort(fitness)[:elite_count]
        n_off     = P - elite_count
        n_pairs   = (n_off + 1) // 2
        parents   = _tournament(rng, fitness, 2 * n_pairs)
        cu, cp, cs = u[:, parents], p[:, parents], s[:, parents]
        _crossover(rng, (cu, cp, cs), crossover_rate)
        cu, cp, cs = cu[:, :n_off], cp[:, :n_off], cs[:, :n_off]
        _mutate(rng, cu, cp, cs, mutation_rate)
        child_fitness = problem.evaluate(cu, cp, cs)

        u = np.concatenate([u[:, elite], cu], axis=1)
        p = np.concatenate([p[:, elite], cp], axis=1)
        s = np.concatenate([s[:, elite], cs], axis=1)
        fitness = np.concatenate([fitness[elite], child_fitness])
        history.append(float(fitness.min()))

    best = int(np.argmin(fitness))
    return (u[:, best:best + 1], p[:, best:best + 1], s[:, best:best + 1]), history, stopped


# ---------------------------------------------------------------------------------------------
# Particle swarm optimization
# ---------------------------------------------------------------------------------------------

def _run_pso(problem: Problem, rng: np.random.Generator, deadline: float, swarm_size: int,
             iterations: int, inertia: float, cognitive: float, social: float):
    """PSO with a global best: each particle is pulled towards its own best and the swarm's best position."""
    T, P = problem.T, swarm_size
    x      = list(_random_genes(rng, T, P, problem.G, problem.K, continuous_u=True))
    bounds = [(0.0, 1.0), (0.0, 1.0), (-1.0, 1.0)]
    v      = [rng.uniform(-VELOCITY_MAX, VELOCITY_MAX, size=a.shape).astype(np.float32) * np.float32(hi - lo)
              for a, (lo, hi) in zip(x, bounds)]

    fitness      = problem.evaluate(*x)
    best_pos     = [a.copy() for a in x]
    best_fitness = fitness.copy()
    leader       = int(np.argmin(best_fitness))
    history = [float(best_fitness[leader])]
    stopped = False

    for _ in range(iterations):
        if time.perf_counter() >= deadline:
            stopped = True
            break
        for i, (lo, hi) in enumerate(bounds):
            # One random factor per particle (not per gene): a particle moves along a line towards
            # its best and the swarm's best plan, which keeps the hour-to-hour structure of the plan
            r1 = rng.random((1, P, 1), dtype=np.float32)
            r2 = rng.random((1, P, 1), dtype=np.float32)
            leader_pos = best_pos[i][:, leader:leader + 1]
            v[i] = (np.float32(inertia) * v[i]
                    + np.float32(cognitive) * r1 * (best_pos[i] - x[i])
                    + np.float32(social) * r2 * (leader_pos - x[i]))
            limit = np.float32(VELOCITY_MAX * (hi - lo))
            np.clip(v[i], -limit, limit, out=v[i])
            x[i] += v[i]
            np.clip(x[i], lo, hi, out=x[i])

        fitness  = problem.evaluate(*x)
        improved = fitness < best_fitness
        for i in range(3):
            best_pos[i][:, improved] = x[i][:, improved]
        best_fitness[improved] = fitness[improved]
        leader = int(np.argmin(best_fitness))
        history.append(float(best_fitness[leader]))

    return tuple(a[:, leader:leader + 1].copy() for a in best_pos), history, stopped


# ---------------------------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------------------------

def _build_result(problem: Problem, method: str, genes: tuple, history: list[float], stopped: bool,
                  runtime_seconds: float, parameters: dict) -> dict:
    """Repair the best candidate once more, check it against the exact model's constraints and build the result dict."""
    u, p, s = (a.copy() for a in genes)
    r = problem.repair(u, p, s, keep_schedule=True)
    T, conv, pumps, d = problem.T, problem.conv, problem.pumps, problem.data

    generation = r["generation"][:, 0, :].T.tolist()   # [plant][hour]
    online     = r["online"][:, 0, :].T.astype(int).tolist()
    pumping    = r["pumping"][:, 0, :].T.tolist()
    turbining  = r["turbining"][:, 0, :].T.tolist()

    pump_schedule = []
    for k, plant in enumerate(pumps):
        soc = 0.5 * plant["energy_capacity_mwh"] + np.cumsum(plant["efficiency"] * np.array(pumping[k]) - np.array(turbining[k]))
        pump_schedule.append({
            "plant_id":  plant["id"],
            "type":      "pump_storage",
            "color":     plant["color"],
            "pumping":   pumping[k],
            "turbining": turbining[k],
            "soc":       soc.tolist(),
        })

    schedule, total_cost = [], 0.0
    for i, plant in enumerate(conv):
        cost = plant["marginal_cost"] * sum(generation[i])
        total_cost += cost
        schedule.append({
            "plant_id":      plant["id"],
            "type":          plant["type"],
            "marginal_cost": plant["marginal_cost"],
            "color":         plant["color"],
            "generation":    generation[i],
            "online":        online[i],
            "cost_eur":      round(cost, 2),
        })

    reasons = check_feasibility(d, conv, generation, online, pumps, pumping, turbining)
    counts  = count_decision_variables(len(conv), len(pumps), T)

    return {
        "method":         method,
        "feasible":       not reasons,
        "infeasibility_reasons": reasons,
        "total_cost_eur": round(total_cost, 2),
        "objective_lower_bound": None,
        "objective_upper_bound": None,
        "mip_gap":        None,
        "solve_time_seconds": runtime_seconds,
        "model_build_seconds": None,
        "stopped_at_time_limit": stopped,
        "iterations_run": len(history) - 1,
        "best_cost_history": history,
        "parameters":     parameters,
        "hourly_cost_eur": hourly_generation_cost(conv, generation),
        "num_variables":  counts["total"],
        "num_binary_variables": counts["binary"],
        "num_continuous_variables": counts["continuous"],
        "schedule":       schedule,
        "pump_schedule":  pump_schedule,
        "load":           d["load"],
        "wind":           d["wind"],
        "pv":             d["pv"],
        "date":           d["date"],
        "month_name":     d["month_name"],
        "horizon":        d["horizon"],
        "T":              T,
    }


def solve_ea(
    scenario: str,
    month: int,
    data_dir: str,
    horizon: str = "day",
    time_limit: float = 60,
    population_size: int = EA_DEFAULTS["population_size"],
    generations: int = EA_DEFAULTS["generations"],
    mutation_rate: float = EA_DEFAULTS["mutation_rate"],
    crossover_rate: float = EA_DEFAULTS["crossover_rate"],
    seed: int | None = DEFAULT_SEED,
) -> dict:
    """Run the evolutionary algorithm until `generations` are done or `time_limit` seconds have passed."""
    if population_size < 4:
        raise ValueError("population_size must be at least 4")
    start    = time.perf_counter()
    problem  = Problem(scenario, month, data_dir, horizon)
    rng      = np.random.default_rng(seed)
    genes, history, stopped = _run_ea(
        problem, rng, start + time_limit, population_size, generations, mutation_rate, crossover_rate,
    )
    parameters = {
        "population_size": population_size, "generations": generations,
        "mutation_rate": mutation_rate, "crossover_rate": crossover_rate, "seed": seed,
    }
    return _build_result(problem, "ea", genes, history, stopped, time.perf_counter() - start, parameters)


def solve_pso(
    scenario: str,
    month: int,
    data_dir: str,
    horizon: str = "day",
    time_limit: float = 60,
    swarm_size: int = PSO_DEFAULTS["swarm_size"],
    iterations: int = PSO_DEFAULTS["iterations"],
    inertia: float = PSO_DEFAULTS["inertia"],
    cognitive: float = PSO_DEFAULTS["cognitive"],
    social: float = PSO_DEFAULTS["social"],
    seed: int | None = DEFAULT_SEED,
) -> dict:
    """Run particle swarm optimization until `iterations` are done or `time_limit` seconds have passed."""
    if swarm_size < 2:
        raise ValueError("swarm_size must be at least 2")
    start    = time.perf_counter()
    problem  = Problem(scenario, month, data_dir, horizon)
    rng      = np.random.default_rng(seed)
    genes, history, stopped = _run_pso(
        problem, rng, start + time_limit, swarm_size, iterations, inertia, cognitive, social,
    )
    parameters = {
        "swarm_size": swarm_size, "iterations": iterations,
        "inertia": inertia, "cognitive": cognitive, "social": social, "seed": seed,
    }
    return _build_result(problem, "pso", genes, history, stopped, time.perf_counter() - start, parameters)
