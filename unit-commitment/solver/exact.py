"""
Unit Commitment - Exact Solver (Pyomo + HiGHS)

Current model:
  objective:
    minimize variable generation cost

  constraints:
    demand coverage
    unit maximum output when online
    ramp-up and ramp-down limits
    minimum up/down time
    biomass daily energy limit
    pump-storage state-of-charge balance
    pump-storage final state of charge near 50%
"""
import importlib.util
import json
import os
import time

import pyomo.environ as pyo

HORIZONS = ["day", "week", "month"]


def highs_available() -> bool:
    """Check whether the HiGHS solver backend (highspy) is installed."""
    return importlib.util.find_spec("highspy") is not None


def relative_mip_gap(upper_bound: float | None, lower_bound: float | None) -> float | None:
    """Compute the relative MIP gap between the best found (upper) and best possible (lower) bound."""
    if upper_bound is None or lower_bound is None:
        return None
    if abs(upper_bound) < 1e-9:
        return 0.0 if abs(upper_bound - lower_bound) < 1e-9 else None
    return abs(upper_bound - lower_bound) / abs(upper_bound)


def count_decision_variables(n_conventional: int, n_storage: int, hours: int) -> dict:
    """Count the decision variables of the unit commitment model.

    Per conventional unit and hour: one binary on/off variable and one continuous generation
    variable. Per storage unit and hour: charging power, discharging power and stored energy
    (all continuous). Used for both methods so their sizes are comparable.
    """
    binary = n_conventional * hours
    continuous = n_conventional * hours + 3 * n_storage * hours
    return {"binary": binary, "continuous": continuous, "total": binary + continuous}


def load_data(scenario: str, month: int, data_dir: str, horizon: str = "day") -> dict:
    """Load and scale plant fleet and demand/renewables data for the given scenario, month and horizon."""
    with open(os.path.join(data_dir, "power_plants.json")) as f:
        plants_all = json.load(f)
    with open(os.path.join(data_dir, "entsoe_2023.json")) as f:
        entsoe = json.load(f)

    if horizon not in HORIZONS:
        raise ValueError(f"Invalid horizon '{horizon}'. Choose one of: {', '.join(HORIZONS)}")

    scenario_data = plants_all[scenario]
    plants = scenario_data["plants"]
    scale = scenario_data["scale_factor"]

    if "horizons" in entsoe:
        horizon_data = entsoe["horizons"][str(month)][horizon]
    elif horizon == "day":
        horizon_data = entsoe["representative_days"][str(month)]
    else:
        raise ValueError(
            "The current entsoe_2023.json only contains representative days. "
            "Run data/download_data.py again to create week and month horizons."
        )

    return {
        "plants": plants,
        "scale": scale,
        "horizon": horizon,
        "load": [x * scale for x in horizon_data["load_mw"]],
        "wind": [x * scale for x in horizon_data["wind_mw"]],
        "pv": [x * scale for x in horizon_data["pv_mw"]],
        "T": len(horizon_data["load_mw"]),
        "date": horizon_data["date"],
        "month_name": horizon_data["month_name"],
    }


def solve_exact(
    scenario: str,
    month: int,
    data_dir: str,
    horizon: str = "day",
    time_limit: int = 120,
    mip_gap: float | None = None,
) -> dict:
    """Build and solve the exact MILP unit commitment model with Pyomo/HiGHS, returning the schedule and cost results.

    time_limit is the solver time limit in seconds; mip_gap (e.g. 0.01 = 1%) lets HiGHS stop
    as soon as the relative gap between best solution and bound is small enough.
    """
    if not highs_available():
        raise RuntimeError(
            "HiGHS is not installed. "
            "Install 'highspy' or use the 'priority_list' method."
        )

    data = load_data(scenario, month, data_dir, horizon)
    plants = data["plants"]
    hours = list(range(data["T"]))
    transition_hours = [hour for hour in hours if hour > 0]
    final_hour = hours[-1]

    conventional_plants = [p for p in plants if p["type"] != "pump_storage"]
    storage_plants = [p for p in plants if p["type"] == "pump_storage"]
    conventional_unit_ids = list(range(len(conventional_plants)))
    storage_unit_ids = list(range(len(storage_plants)))
    counts = count_decision_variables(len(conventional_plants), len(storage_plants), data["T"])
    biomass_unit_ids = [
        unit_id
        for unit_id, plant in enumerate(conventional_plants)
        if plant["type"] == "biomass"
    ]

    min_uptime_index = [
        (unit_id, startup_hour, enforced_hour)
        for unit_id, plant in enumerate(conventional_plants)
        for startup_hour in transition_hours
        for enforced_hour in range(
            startup_hour,
            min(startup_hour + plant["min_uptime_h"], data["T"]),
        )
    ]
    min_downtime_index = [
        (unit_id, shutdown_hour, enforced_hour)
        for unit_id, plant in enumerate(conventional_plants)
        for shutdown_hour in transition_hours
        for enforced_hour in range(
            shutdown_hour,
            min(shutdown_hour + plant["min_downtime_h"], data["T"]),
        )
    ]

    model = pyo.ConcreteModel()

    model.var_unit_on = pyo.Var(conventional_unit_ids, hours, domain=pyo.Binary)
    model.var_power_generated = pyo.Var(
        conventional_unit_ids,
        hours,
        domain=pyo.NonNegativeReals,
    )
    model.var_storage_charging_power = pyo.Var(
        storage_unit_ids,
        hours,
        domain=pyo.NonNegativeReals,
    )
    model.var_storage_discharging_power = pyo.Var(
        storage_unit_ids,
        hours,
        domain=pyo.NonNegativeReals,
    )
    model.var_storage_energy = pyo.Var(
        storage_unit_ids,
        hours,
        domain=pyo.NonNegativeReals,
    )

    model.objective_total_generation_cost = pyo.Objective(
        expr=sum(
            conventional_plants[unit_id]["marginal_cost"]
            * model.var_power_generated[unit_id, hour]
            for unit_id in conventional_unit_ids
            for hour in hours
        ),
        sense=pyo.minimize,
    )

    def demand_coverage_rule(model, hour):
        """Total generation (conventional + net storage + renewables) must cover load each hour."""
        dispatchable_generation = sum(
            model.var_power_generated[unit_id, hour]
            for unit_id in conventional_unit_ids
        )
        net_storage_generation = sum(
            model.var_storage_discharging_power[storage_id, hour]
            - model.var_storage_charging_power[storage_id, hour]
            for storage_id in storage_unit_ids
        )
        renewable_generation = data["wind"][hour] + data["pv"][hour]

        return (
            dispatchable_generation + net_storage_generation + renewable_generation
            >= data["load"][hour]
        )

    model.constraint_demand_coverage = pyo.Constraint(
        hours,
        rule=demand_coverage_rule,
    )

    def unit_maximum_output_rule(model, unit_id, hour):
        """A unit can only generate up to its capacity, and only while online."""
        plant = conventional_plants[unit_id]
        return (
            model.var_power_generated[unit_id, hour]
            <= plant["pmax_mw"] * model.var_unit_on[unit_id, hour]
        )

    model.constraint_unit_maximum_output = pyo.Constraint(
        conventional_unit_ids,
        hours,
        rule=unit_maximum_output_rule,
    )

    def ramp_up_limit_rule(model, unit_id, hour):
        """Generation cannot increase faster than the unit's ramp-up rate between consecutive hours."""
        plant = conventional_plants[unit_id]
        return (
            model.var_power_generated[unit_id, hour]
            - model.var_power_generated[unit_id, hour - 1]
            <= plant["ramp_up_mw_per_h"]
        )

    model.constraint_ramp_up_limit = pyo.Constraint(
        conventional_unit_ids,
        transition_hours,
        rule=ramp_up_limit_rule,
    )

    def ramp_down_limit_rule(model, unit_id, hour):
        """Generation cannot decrease faster than the unit's ramp-down rate between consecutive hours."""
        plant = conventional_plants[unit_id]
        return (
            model.var_power_generated[unit_id, hour - 1]
            - model.var_power_generated[unit_id, hour]
            <= plant["ramp_down_mw_per_h"]
        )

    model.constraint_ramp_down_limit = pyo.Constraint(
        conventional_unit_ids,
        transition_hours,
        rule=ramp_down_limit_rule,
    )

    def storage_charging_power_limit_rule(model, storage_id, hour):
        """Pump-storage charging power cannot exceed the unit's rated capacity."""
        storage = storage_plants[storage_id]
        return model.var_storage_charging_power[storage_id, hour] <= storage["pmax_mw"]

    model.constraint_storage_charging_power_limit = pyo.Constraint(
        storage_unit_ids,
        hours,
        rule=storage_charging_power_limit_rule,
    )

    def storage_discharging_power_limit_rule(model, storage_id, hour):
        """Pump-storage discharging power cannot exceed the unit's rated capacity."""
        storage = storage_plants[storage_id]
        return model.var_storage_discharging_power[storage_id, hour] <= storage["pmax_mw"]

    model.constraint_storage_discharging_power_limit = pyo.Constraint(
        storage_unit_ids,
        hours,
        rule=storage_discharging_power_limit_rule,
    )

    def storage_energy_balance_rule(model, storage_id, hour):
        """State of charge evolves from the previous hour plus efficiency-weighted charging minus discharging; starts at 50% capacity."""
        storage = storage_plants[storage_id]
        efficiency = storage["efficiency"]
        energy_change = (
            efficiency * model.var_storage_charging_power[storage_id, hour]
            - model.var_storage_discharging_power[storage_id, hour]
        )

        if hour == 0:
            initial_energy = 0.5 * storage["energy_capacity_mwh"]
            return model.var_storage_energy[storage_id, hour] == initial_energy + energy_change

        return (
            model.var_storage_energy[storage_id, hour]
            == model.var_storage_energy[storage_id, hour - 1] + energy_change
        )

    model.constraint_storage_energy_balance = pyo.Constraint(
        storage_unit_ids,
        hours,
        rule=storage_energy_balance_rule,
    )

    def storage_energy_capacity_rule(model, storage_id, hour):
        """State of charge cannot exceed the reservoir's energy capacity."""
        storage = storage_plants[storage_id]
        return model.var_storage_energy[storage_id, hour] <= storage["energy_capacity_mwh"]

    model.constraint_storage_energy_capacity = pyo.Constraint(
        storage_unit_ids,
        hours,
        rule=storage_energy_capacity_rule,
    )

    def storage_final_energy_minimum_rule(model, storage_id):
        """Force the reservoir back to roughly 50% state of charge (lower bound) by the end of the horizon."""
        storage = storage_plants[storage_id]
        return (
            model.var_storage_energy[storage_id, final_hour]
            >= 0.49 * storage["energy_capacity_mwh"]
        )

    model.constraint_storage_final_energy_minimum = pyo.Constraint(
        storage_unit_ids,
        rule=storage_final_energy_minimum_rule,
    )

    def storage_final_energy_maximum_rule(model, storage_id):
        """Force the reservoir back to roughly 50% state of charge (upper bound) by the end of the horizon."""
        storage = storage_plants[storage_id]
        return (
            model.var_storage_energy[storage_id, final_hour]
            <= 0.51 * storage["energy_capacity_mwh"]
        )

    model.constraint_storage_final_energy_maximum = pyo.Constraint(
        storage_unit_ids,
        rule=storage_final_energy_maximum_rule,
    )

    def minimum_uptime_rule(model, unit_id, startup_hour, enforced_hour):
        """Once a unit starts up, it must stay online for at least its minimum uptime."""
        startup_indicator = (
            model.var_unit_on[unit_id, startup_hour]
            - model.var_unit_on[unit_id, startup_hour - 1]
        )
        return model.var_unit_on[unit_id, enforced_hour] >= startup_indicator

    model.constraint_minimum_uptime = pyo.Constraint(
        min_uptime_index,
        rule=minimum_uptime_rule,
    )

    def minimum_downtime_rule(model, unit_id, shutdown_hour, enforced_hour):
        """Once a unit shuts down, it must stay offline for at least its minimum downtime."""
        shutdown_indicator = (
            model.var_unit_on[unit_id, shutdown_hour - 1]
            - model.var_unit_on[unit_id, shutdown_hour]
        )
        return 1 - model.var_unit_on[unit_id, enforced_hour] >= shutdown_indicator

    model.constraint_minimum_downtime = pyo.Constraint(
        min_downtime_index,
        rule=minimum_downtime_rule,
    )

    def biomass_energy_limit_rule(model, unit_id):
        """Total energy produced by a biomass unit over the horizon is capped by its fuel/energy budget."""
        plant = conventional_plants[unit_id]
        return (
            sum(model.var_power_generated[unit_id, hour] for hour in hours)
            <= plant["biomass_limit_mwh"]
        )

    model.constraint_biomass_energy_limit = pyo.Constraint(
        biomass_unit_ids,
        rule=biomass_energy_limit_rule,
    )

    solver = pyo.SolverFactory("appsi_highs")
    solver.config.time_limit = time_limit
    if mip_gap is not None:
        solver.config.mip_gap = mip_gap
    solve_start = time.perf_counter()
    result = solver.solve(model, tee=False)
    solve_time_seconds = time.perf_counter() - solve_start
    objective_lower_bound = result.problem.lower_bound
    objective_upper_bound = result.problem.upper_bound
    mip_gap = relative_mip_gap(objective_upper_bound, objective_lower_bound)

    feasible = result.solver.termination_condition in [
        pyo.TerminationCondition.optimal,
        pyo.TerminationCondition.feasible,
    ]

    schedule = []
    total_cost = 0.0

    for unit_id in conventional_unit_ids:
        plant = conventional_plants[unit_id]
        generation = [
            round(pyo.value(model.var_power_generated[unit_id, hour]), 2)
            for hour in hours
        ]
        online = [
            int(round(pyo.value(model.var_unit_on[unit_id, hour])))
            for hour in hours
        ]
        cost = sum(plant["marginal_cost"] * value for value in generation)
        total_cost += cost
        schedule.append(
            {
                "plant_id": plant["id"],
                "type": plant["type"],
                "color": plant["color"],
                "generation": generation,
                "online": online,
                "cost_eur": round(cost, 2),
            }
        )

    pump_schedule = []
    for storage_id in storage_unit_ids:
        storage = storage_plants[storage_id]
        pump_schedule.append(
            {
                "plant_id": storage["id"],
                "type": "pump_storage",
                "color": storage["color"],
                "pumping": [
                    round(pyo.value(model.var_storage_charging_power[storage_id, hour]), 2)
                    for hour in hours
                ],
                "turbining": [
                    round(pyo.value(model.var_storage_discharging_power[storage_id, hour]), 2)
                    for hour in hours
                ],
                "soc": [
                    round(pyo.value(model.var_storage_energy[storage_id, hour]), 2)
                    for hour in hours
                ],
            }
        )

    return {
        "method": "exact_highs",
        "feasible": feasible,
        "total_cost_eur": round(total_cost, 2),
        "objective_lower_bound": objective_lower_bound,
        "objective_upper_bound": objective_upper_bound,
        "mip_gap": mip_gap,
        "solve_time_seconds": solve_time_seconds,
        "num_variables": counts["total"],
        "num_binary_variables": counts["binary"],
        "num_continuous_variables": counts["continuous"],
        "schedule": schedule,
        "pump_schedule": pump_schedule,
        "load": data["load"],
        "wind": data["wind"],
        "pv": data["pv"],
        "date": data["date"],
        "month_name": data["month_name"],
        "horizon": data["horizon"],
        "T": data["T"],
    }
