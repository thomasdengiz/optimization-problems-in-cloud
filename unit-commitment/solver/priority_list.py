"""
Unit Commitment – Priority List Heuristic (literature-based)

Classic approach from power systems literature:
1. Sort plants by marginal cost (cheapest first = merit order)
2. Each hour: commit plants until demand is covered
3. Respect ramp limits and minimum up/down times greedily
4. Pump storage: pump during cheap hours, generate during expensive hours
   (planned first, so the conventional units cover the resulting net demand)

The heuristic is checked afterwards against the same constraints as the exact
model (see `check_feasibility`). If any constraint is violated, the reasons are
returned in `infeasibility_reasons`.
"""
from .exact import count_decision_variables, hourly_generation_cost, load_data

TOLERANCE     = 1e-6  # numerical tolerance in MW / MWh
FINAL_SOC_MIN = 0.49  # same band as the exact model
FINAL_SOC_MAX = 0.51


def _plan_pump(p: dict, net_demand: list[float], median_net: float) -> tuple[list[float], list[float]]:
    """Plan the pump-storage unit for the whole horizon before the other plants are dispatched.

    Rules: pump (store energy) in hours with low net demand, turbine (release energy) in
    hours with high net demand. Net demand = load - wind - pv; 'low' is below 85% and
    'high' above 110% of the median net demand. The reservoir starts at 50% of its capacity.
    Afterwards the last hours are corrected so the reservoir ends at 50% again, as the
    exact model requires. Returns (pumping_mw, turbining_mw), one value per hour.
    """
    T         = len(net_demand)
    e_max     = p["energy_capacity_mwh"]
    eff       = p["efficiency"]
    pmax      = p["pmax_mw"]
    target    = 0.5 * e_max
    current_e = target
    pumping   = [0.0] * T
    turbining = [0.0] * T

    # Walk through the hours; current_e is the energy in the reservoir (MWh)
    for t in range(T):
        # Cheap hour: pump as much as the power rating and the free reservoir space allow.
        # Only eff (82%) of the pumped energy ends up stored.
        if net_demand[t] < median_net * 0.85 and current_e < e_max * 0.9:
            pw          = min(pmax, (e_max - current_e) / eff)
            pumping[t]  = pw
            current_e  += pw * eff
        # Expensive hour: release as much as the power rating and the stored energy allow
        elif net_demand[t] > median_net * 1.10 and current_e > e_max * 0.1:
            tw           = min(pmax, current_e)
            turbining[t] = tw
            current_e   -= tw

    # Repair the end of the horizon so the final state of charge is back at 50%
    diff = current_e - target
    for t in range(T - 1, -1, -1):
        if abs(diff) <= 1e-9:
            break
        if diff > 0:  # too full: pump less, turbine more
            dec = min(pumping[t], diff / eff)
            pumping[t] -= dec
            diff       -= dec * eff
            inc = min(pmax - turbining[t], diff)
            turbining[t] += inc
            diff         -= inc
        else:         # too empty: turbine less, pump more
            need = -diff
            dec  = min(turbining[t], need)
            turbining[t] -= dec
            need         -= dec
            inc = min(pmax - pumping[t], need / eff)
            pumping[t] += inc
            need       -= inc * eff
            diff        = -need

    return pumping, turbining


def _soc_profile(p: dict, pumping: list[float], turbining: list[float]) -> list[float]:
    """Return the reservoir energy (state of charge, MWh) at the end of every hour."""
    e   = 0.5 * p["energy_capacity_mwh"]
    soc = []
    for pw, tw in zip(pumping, turbining):
        e += p["efficiency"] * pw - tw
        soc.append(e)
    return soc


def _summarize(name: str, violations: list[tuple[int, float, str]]) -> str | None:
    """Condense (hour, magnitude, detail) violations into one readable line."""
    if not violations:
        return None
    worst = max(violations, key=lambda v: v[1])
    return f"{name}: violated in {len(violations)} hour(s); worst at hour {worst[0]} ({worst[2]})"


def check_feasibility(
    d: dict,
    conv: list[dict],
    generation: list[list[float]],
    online: list[list[int]],
    pumps: list[dict],
    pumping: list[list[float]],
    turbining: list[list[float]],
) -> list[str]:
    """Check a schedule against all constraints of the exact model. Returns human-readable violations."""
    T       = d["T"]
    reasons = []

    # Demand coverage: conventional + net storage + wind + pv >= load
    demand_viol = []
    for t in range(T):
        supply = (
            sum(generation[i][t] for i in range(len(conv)))
            + sum(turbining[k][t] - pumping[k][t] for k in range(len(pumps)))
            + d["wind"][t] + d["pv"][t]
        )
        shortfall = d["load"][t] - supply
        if shortfall > TOLERANCE:
            demand_viol.append((t, shortfall, f"load {d['load'][t]:.1f} MW, supply {supply:.1f} MW, short by {shortfall:.1f} MW"))
    if demand_viol:
        total = sum(v[1] for v in demand_viol)
        worst = max(demand_viol, key=lambda v: v[1])
        reasons.append(
            f"Demand not covered in {len(demand_viol)} of {T} hours "
            f"(total unserved {total:.1f} MWh); worst at hour {worst[0]}: {worst[2]}"
        )

    for i, p in enumerate(conv):
        g, on, pid = generation[i], online[i], p["id"]

        out_viol = [(t, g[t] - p["pmax_mw"] * on[t], f"{g[t]:.1f} MW while online={on[t]}, pmax {p['pmax_mw']:.1f} MW")
                    for t in range(T) if g[t] > p["pmax_mw"] * on[t] + TOLERANCE]
        if msg := _summarize(f"{pid}: output above pmax / while offline", out_viol):
            reasons.append(msg)

        up_viol = [(t, g[t] - g[t-1] - p["ramp_up_mw_per_h"], f"increase {g[t] - g[t-1]:.1f} MW > ramp-up {p['ramp_up_mw_per_h']:.1f} MW")
                   for t in range(1, T) if g[t] - g[t-1] > p["ramp_up_mw_per_h"] + TOLERANCE]
        if msg := _summarize(f"{pid}: ramp-up limit", up_viol):
            reasons.append(msg)

        down_viol = [(t, g[t-1] - g[t] - p["ramp_down_mw_per_h"], f"decrease {g[t-1] - g[t]:.1f} MW > ramp-down {p['ramp_down_mw_per_h']:.1f} MW")
                     for t in range(1, T) if g[t-1] - g[t] > p["ramp_down_mw_per_h"] + TOLERANCE]
        if msg := _summarize(f"{pid}: ramp-down limit", down_viol):
            reasons.append(msg)

        uptime_viol, downtime_viol = [], []
        for t in range(1, T):
            if on[t] == 1 and on[t-1] == 0:  # start-up
                end = min(t + p["min_uptime_h"], T)
                if any(on[s] == 0 for s in range(t, end)):
                    uptime_viol.append((t, 1.0, f"started at hour {t}, off again before {p['min_uptime_h']} h"))
            if on[t] == 0 and on[t-1] == 1:  # shut-down
                end = min(t + p["min_downtime_h"], T)
                if any(on[s] == 1 for s in range(t, end)):
                    downtime_viol.append((t, 1.0, f"shut down at hour {t}, restarted before {p['min_downtime_h']} h"))
        if msg := _summarize(f"{pid}: minimum up-time", uptime_viol):
            reasons.append(msg)
        if msg := _summarize(f"{pid}: minimum down-time", downtime_viol):
            reasons.append(msg)

        if p["type"] == "biomass" and sum(g) > p["biomass_limit_mwh"] + TOLERANCE:
            reasons.append(
                f"{pid}: biomass energy limit exceeded ({sum(g):.1f} MWh > {p['biomass_limit_mwh']:.1f} MWh)"
            )

    for k, p in enumerate(pumps):
        pid   = p["id"]
        e_max = p["energy_capacity_mwh"]
        soc   = _soc_profile(p, pumping[k], turbining[k])

        power_viol = [(t, max(pumping[k][t], turbining[k][t]) - p["pmax_mw"], "power above rated capacity")
                      for t in range(T)
                      if max(pumping[k][t], turbining[k][t]) > p["pmax_mw"] + TOLERANCE]
        if msg := _summarize(f"{pid}: pump/turbine power limit", power_viol):
            reasons.append(msg)

        low_viol = [(t, -soc[t], f"state of charge {soc[t]:.1f} MWh < 0") for t in range(T) if soc[t] < -TOLERANCE]
        if msg := _summarize(f"{pid}: reservoir empty", low_viol):
            reasons.append(msg)

        high_viol = [(t, soc[t] - e_max, f"state of charge {soc[t]:.1f} MWh > capacity {e_max:.1f} MWh")
                     for t in range(T) if soc[t] > e_max + TOLERANCE]
        if msg := _summarize(f"{pid}: reservoir overfull", high_viol):
            reasons.append(msg)

        final = soc[-1] / e_max
        if not FINAL_SOC_MIN - 1e-9 <= final <= FINAL_SOC_MAX + 1e-9:
            reasons.append(
                f"{pid}: final state of charge {100 * final:.1f}% is outside "
                f"{100 * FINAL_SOC_MIN:.0f}-{100 * FINAL_SOC_MAX:.0f}%"
            )

    return reasons


def solve_priority_list(
    scenario: str,
    month: int,
    data_dir: str,
    horizon: str = "day",
) -> dict:
    """Build a unit commitment schedule with the priority list heuristic and check its feasibility.

    Steps: (1) plan pump storage, (2) dispatch the other plants hour by hour in merit order,
    (3) compute cost and verify all constraints. Returns the same result dict as the exact solver.
    """
    d      = load_data(scenario, month, data_dir, horizon)
    plants = d["plants"]
    T      = d["T"]

    conv  = [p for p in plants if p["type"] != "pump_storage"]
    pumps = [p for p in plants if p["type"] == "pump_storage"]

    # Step 1: plan pump storage first so its effect is part of the demand the units must cover
    net_demand = [max(d["load"][t] - d["wind"][t] - d["pv"][t], 0.0) for t in range(T)]
    median_net = sorted(net_demand)[T // 2]

    pumping_plans, turbining_plans = [], []
    for p in pumps:
        pumping, turbining = _plan_pump(p, net_demand, median_net)
        pumping_plans.append(pumping)
        turbining_plans.append(turbining)

    # Step 2: hourly merit-order dispatch with ramp limits and min up/down times
    # Merit order: cheapest marginal cost first
    merit_order = sorted(range(len(conv)), key=lambda i: conv[i]["marginal_cost"])

    # State per plant, carried from hour to hour:
    #   on         - is the plant currently running?
    #   hours_on   - consecutive hours it has been running (for minimum up-time)
    #   hours_off  - consecutive hours it has been off (for minimum down-time)
    #   energy     - MWh produced so far (for the biomass energy limit)
    on        = [False] * len(conv)
    hours_on  = [0] * len(conv)
    hours_off = [conv[i]["min_downtime_h"] for i in range(len(conv))]
    energy    = [0.0] * len(conv)  # produced energy so far (for biomass limit)

    generation = [[0.0] * T for _ in range(len(conv))]
    online     = [[0]   * T for _ in range(len(conv))]

    # The schedule is built hour by hour; every hour only looks at the previous hour's state
    for t in range(T):
        # Power the conventional plants must deliver this hour: net demand plus
        # what the pump consumes, minus what the turbine delivers
        required = (
            net_demand[t]
            + sum(pumping_plans[k][t] - turbining_plans[k][t] for k in range(len(pumps)))
        )

        # For every plant compute the output range allowed this hour:
        #   lo = lowest allowed output (limited by ramp-down from last hour's output)
        #   hi = highest allowed output (limited by pmax, ramp-up, min down-time, biomass budget)
        lo = [0.0] * len(conv)
        hi = [0.0] * len(conv)
        for i, p in enumerate(conv):
            g_prev = generation[i][t - 1] if t > 0 else 0.0
            lo[i]  = max(0.0, g_prev - p["ramp_down_mw_per_h"])         # cannot drop faster than ramp-down
            hi[i]  = min(p["pmax_mw"], g_prev + p["ramp_up_mw_per_h"])  # cannot rise faster than ramp-up
            if not on[i] and hours_off[i] < p["min_downtime_h"]:
                hi[i] = 0.0                                              # still in minimum downtime
            if p["type"] == "biomass":
                hi[i] = min(hi[i], max(p["biomass_limit_mwh"] - energy[i], 0.0))
            hi[i] = max(hi[i], lo[i])

        # Start with the forced minimum: plants that cannot ramp down quickly enough must keep producing
        gen       = lo[:]
        remaining = required - sum(gen)

        # Fill the remaining demand, cheapest plant first, each up to its hi limit
        # (a plant that is off may be started here, but only up to its ramp-up rate)
        for i in merit_order:
            if remaining <= 0:
                break
            add        = min(hi[i] - gen[i], remaining)
            gen[i]    += add
            remaining -= add

        # Store this hour's result and update the on/off counters for the next hour
        for i, p in enumerate(conv):
            generation[i][t] = gen[i]
            energy[i]       += gen[i]

            keep_on = on[i] and hours_on[i] < p["min_uptime_h"]  # minimum uptime still running
            if gen[i] > 0 or keep_on:
                online[i][t] = 1
                hours_on[i]  = hours_on[i] + 1 if on[i] else 1
                hours_off[i] = 0
                on[i]        = True
            else:
                online[i][t] = 0
                hours_off[i] = 1 if on[i] else hours_off[i] + 1
                hours_on[i]  = 0
                on[i]        = False

    # Step 3: result assembly, cost and feasibility check
    pump_schedule = []
    for k, p in enumerate(pumps):
        pump_schedule.append({
            "plant_id":  p["id"],
            "type":      "pump_storage",
            "color":     p["color"],
            "pumping":   pumping_plans[k],
            "turbining": turbining_plans[k],
            "soc":       _soc_profile(p, pumping_plans[k], turbining_plans[k]),
        })

    schedule   = []
    total_cost = 0.0
    for i, p in enumerate(conv):
        cost = sum(p["marginal_cost"] * generation[i][t] for t in range(T))
        total_cost += cost
        schedule.append({
            "plant_id":   p["id"],
            "type":       p["type"],
            "color":      p["color"],
            "generation": generation[i],
            "online":     online[i],
            "cost_eur":   round(cost, 2),
        })

    reasons = check_feasibility(d, conv, generation, online, pumps, pumping_plans, turbining_plans)
    counts  = count_decision_variables(len(conv), len(pumps), T)

    return {
        "method":         "priority_list",
        "feasible":       not reasons,
        "infeasibility_reasons": reasons,
        "total_cost_eur": round(total_cost, 2),
        "objective_lower_bound": None,
        "objective_upper_bound": None,
        "mip_gap":        None,
        "solve_time_seconds": None,
        "model_build_seconds": None,
        "stopped_at_time_limit": False,
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
