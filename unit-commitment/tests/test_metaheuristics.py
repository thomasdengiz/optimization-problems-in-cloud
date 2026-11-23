"""Unit tests for the evolutionary algorithm and particle swarm optimization (no HTTP involved)."""
import numpy as np
import pytest

from solver.exact import solve_exact
from solver.metaheuristics import (
    EA_DEFAULTS, PSO_DEFAULTS, Problem, _build_result, solve_ea, solve_pso,
)

# Small settings so the tests stay fast
EA_QUICK  = {"population_size": 12, "generations": 10}
PSO_QUICK = {"swarm_size": 12, "iterations": 10}


@pytest.mark.parametrize("solve, quick", [(solve_ea, EA_QUICK), (solve_pso, PSO_QUICK)])
def test_result_is_feasible_and_has_the_usual_structure(data_dir, solve, quick):
    result = solve("small", 1, data_dir, "day", time_limit=60, **quick)

    problem = Problem("small", 1, data_dir, "day")
    assert result["feasible"] is True
    assert result["infeasibility_reasons"] == []
    assert len(result["schedule"]) == problem.G
    assert all(len(entry["generation"]) == result["T"] for entry in result["schedule"])
    assert all(entry["marginal_cost"] >= 0 for entry in result["schedule"])
    assert result["total_cost_eur"] == pytest.approx(sum(e["cost_eur"] for e in result["schedule"]), abs=1.0)
    assert sum(result["hourly_cost_eur"]) == pytest.approx(result["total_cost_eur"], abs=1.0)
    assert result["num_variables"] == result["num_binary_variables"] + result["num_continuous_variables"]
    assert result["mip_gap"] is None
    assert result["stopped_at_time_limit"] is False


@pytest.mark.parametrize("solve, quick", [(solve_ea, EA_QUICK), (solve_pso, PSO_QUICK)])
def test_same_seed_gives_the_same_result(data_dir, solve, quick):
    first  = solve("small", 1, data_dir, "day", seed=7, **quick)
    second = solve("small", 1, data_dir, "day", seed=7, **quick)
    other  = solve("small", 1, data_dir, "day", seed=8, **quick)

    assert first["total_cost_eur"] == second["total_cost_eur"]
    assert first["total_cost_eur"] != other["total_cost_eur"]


@pytest.mark.parametrize("solve, quick", [(solve_ea, EA_QUICK), (solve_pso, PSO_QUICK)])
def test_cost_is_never_below_the_exact_lower_bound(data_dir, solve, quick):
    exact  = solve_exact("small", 1, data_dir, "day", time_limit=60, mip_gap=0.01)
    result = solve("small", 1, data_dir, "day", **quick)

    assert result["total_cost_eur"] >= exact["objective_lower_bound"] - 1.0


def test_ea_improves_the_best_cost_over_the_generations(data_dir):
    result = solve_ea("small", 1, data_dir, "day", population_size=20, generations=40)

    history = result["best_cost_history"]
    assert len(history) == 41
    assert history[-1] < history[0]
    assert all(later <= earlier + 1e-6 for earlier, later in zip(history, history[1:]))  # elitism: never worse


def test_pso_best_cost_never_gets_worse(data_dir):
    result = solve_pso("small", 1, data_dir, "day", swarm_size=20, iterations=40)

    history = result["best_cost_history"]
    assert all(later <= earlier + 1e-6 for earlier, later in zip(history, history[1:]))


@pytest.mark.parametrize("solve", [solve_ea, solve_pso])
def test_time_limit_stops_the_search_but_still_returns_a_feasible_plan(data_dir, solve):
    result = solve("small", 1, data_dir, "week", time_limit=0.001)

    assert result["stopped_at_time_limit"] is True
    assert result["iterations_run"] == 0
    assert result["feasible"] is True


@pytest.mark.parametrize("horizon", ["day", "week"])
def test_repair_makes_random_candidates_feasible(data_dir, horizon):
    """Extreme random genes (all plants on, all off, random) must come out of the repair feasible."""
    problem = Problem("small", 1, data_dir, horizon)
    rng = np.random.default_rng(0)
    T, G, K = problem.T, problem.G, problem.K

    candidates = {
        "random":  (rng.random((T, 1, G)) < 0.5, rng.random((T, 1, G)), rng.uniform(-1, 1, (T, 1, K))),
        "all on":  (np.ones((T, 1, G)), np.ones((T, 1, G)), np.ones((T, 1, K))),
        "all off": (np.zeros((T, 1, G)), np.zeros((T, 1, G)), -np.ones((T, 1, K))),
        "flip":    ((np.arange(T)[:, None, None] % 2) * np.ones((T, 1, G)), rng.random((T, 1, G)), np.zeros((T, 1, K))),
    }
    for name, (u, p, s) in candidates.items():
        genes = (u.astype(np.float32), p.astype(np.float32), s.astype(np.float32))
        result = _build_result(problem, "ea", genes, [0.0], False, 0.0, {})

        assert result["feasible"], f"{name}: {result['infeasibility_reasons']}"


def test_repair_is_idempotent(data_dir):
    """Repairing an already repaired candidate does not change its schedule."""
    problem = Problem("small", 1, data_dir, "day")
    rng = np.random.default_rng(1)
    T, G, K = problem.T, problem.G, problem.K
    u = (rng.random((T, 1, G)) < 0.5).astype(np.float32)
    p = rng.random((T, 1, G)).astype(np.float32)
    s = rng.uniform(-1, 1, (T, 1, K)).astype(np.float32)

    first  = problem.repair(u, p, s, keep_schedule=True)
    second = problem.repair(u, p, s, keep_schedule=True)

    np.testing.assert_allclose(first["generation"], second["generation"], atol=1e-3)
    assert (first["online"] == second["online"]).all()


@pytest.mark.parametrize("solve, key, value", [
    (solve_ea, "population_size", 2),
    (solve_pso, "swarm_size", 1),
])
def test_too_small_population_is_rejected(data_dir, solve, key, value):
    with pytest.raises(ValueError):
        solve("small", 1, data_dir, "day", **{key: value})


def test_defaults_are_used_when_no_parameters_are_given(data_dir):
    result = solve_ea("small", 1, data_dir, "day", generations=2)

    assert result["parameters"]["population_size"] == EA_DEFAULTS["population_size"]
    assert result["parameters"]["mutation_rate"] == EA_DEFAULTS["mutation_rate"]
    assert set(PSO_DEFAULTS) == {"swarm_size", "iterations", "inertia", "cognitive", "social"}
