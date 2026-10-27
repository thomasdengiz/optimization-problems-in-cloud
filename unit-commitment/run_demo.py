import os
import time

from solver.exact import HORIZONS, solve_exact
from solver.priority_list import solve_priority_list


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SCENARIOS = ["small", "medium", "large"]
METHODS = {
    "exact": {
        "label": "Exact (HiGHS/Pyomo)",
        "scenarios": ["small", "medium", "large"],
    },
    "priority_list": {
        "label": "Priority List Heuristic",
        "scenarios": ["small", "medium", "large"],
    },
}


def prompt_choice(title: str, options: list[str], default: str) -> str:
    print(f"\n{title}")
    for idx, option in enumerate(options, start=1):
        marker = " (default)" if option == default else ""
        print(f"  {idx}. {option}{marker}")

    while True:
        raw = input("> ").strip()
        if not raw:
            return default
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        if raw in options:
            return raw
        print("Please enter a valid option name or number.")


def prompt_month(default: int = 1) -> int:
    print("\nChoose month")
    print(f"  Enter a number from 1 to 12. 1 stands for January and 12 for December (default: {default})")

    while True:
        raw = input("> ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= 12:
            return int(raw)
        print("Please enter a whole number between 1 and 12.")


def solve(method: str, scenario: str, month: int, horizon: str) -> dict:
    if method == "exact":
        return solve_exact(scenario, month, DATA_DIR, horizon)
    return solve_priority_list(scenario, month, DATA_DIR, horizon)


def print_summary(result: dict, scenario: str, solve_time_seconds: float) -> None:
    reported_solver_time = result.get("solve_time_seconds")
    if reported_solver_time is None:
        reported_solver_time = solve_time_seconds

    mip_gap = result.get("mip_gap")
    mip_gap_text = "n/a"
    if mip_gap is not None:
        mip_gap_text = f"{100 * mip_gap:.3f}%"

    print("\nResult")
    print(f"  Method:   {result['method']}")
    print(f"  Scenario: {scenario}")
    print(f"  Horizon:  {result['horizon']} ({result['T']} hours)")
    print(f"  Month:    {result['month_name']} ({result['date']})")
    print(f"  Feasible: {result['feasible']}")
    print(f"  Cost:     {result['total_cost_eur']:.2f} EUR")
    print(f"  MIP Gap:  {mip_gap_text}")
    print(f"  Plants:   {len(result['schedule'])} conventional, {len(result['pump_schedule'])} pump storage")
    print(f"  Solver Time: {reported_solver_time:.1f} s")
    print(f"  Total Time:  {solve_time_seconds:.1f} s")

    reasons = result.get("infeasibility_reasons")
    if reasons:
        print("\nWhy the solution is infeasible")
        for reason in reasons:
            print(f"  - {reason}")


def main() -> None:
    print("Unit Commitment Demo Runner")
    print("This is a simple terminal interface for testing the project.\n")

    scenario = prompt_choice("Choose scenario", SCENARIOS, "small")
    horizon = prompt_choice("Choose optimization horizon", HORIZONS, "day")

    allowed_methods = [
        method for method, cfg in METHODS.items()
        if scenario in cfg["scenarios"]
    ]
    method = prompt_choice("Choose method", allowed_methods, allowed_methods[0])
    month = prompt_month(default=1)

    print("\nSolving...")
    start_time = time.perf_counter()
    result = solve(method, scenario, month, horizon)
    end_time = time.perf_counter()
    solve_time_seconds = end_time - start_time
    print_summary(result, scenario, solve_time_seconds)


if __name__ == "__main__":
    main()
