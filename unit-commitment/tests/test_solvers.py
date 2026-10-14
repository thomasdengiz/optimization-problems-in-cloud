"""Unit tests for the solver modules (no HTTP involved)."""
from solver.exact import count_decision_variables, load_data, solve_exact
from solver.priority_list import check_feasibility, solve_priority_list


def test_count_decision_variables_matches_model_structure():
    # 3 conventional units, 1 storage unit, 24 hours:
    # binaries = on/off (3*24); continuous = generation (3*24) + charge, discharge, energy (3*24)
    counts = count_decision_variables(n_conventional=3, n_storage=1, hours=24)

    assert counts["binary"] == 72
    assert counts["continuous"] == 144
    assert counts["total"] == 216


def test_priority_list_result_is_feasible_and_has_metrics(data_dir):
    result = solve_priority_list("small", 1, data_dir, "day")

    assert result["feasible"] is True
    assert result["infeasibility_reasons"] == []
    assert result["num_variables"] == result["num_binary_variables"] + result["num_continuous_variables"]
    assert result["num_binary_variables"] > 0


def test_check_feasibility_explains_uncovered_demand(data_dir):
    d = load_data("small", 1, data_dir, "day")
    conv = [p for p in d["plants"] if p["type"] != "pump_storage"]
    T = d["T"]
    nothing = [[0.0] * T for _ in conv]
    off = [[0] * T for _ in conv]

    reasons = check_feasibility(d, conv, nothing, off, [], [], [])

    assert any("Demand not covered" in reason for reason in reasons)


def test_exact_accepts_mip_gap_and_reports_metrics(data_dir):
    result = solve_exact("small", 1, data_dir, "day", time_limit=60, mip_gap=0.05)

    assert result["feasible"] is True
    assert result["num_variables"] > 0
    assert result["num_binary_variables"] > 0
    assert result["mip_gap"] is None or result["mip_gap"] <= 0.05 + 1e-9
