"""
Generate synthetic but realistic power plant parameters for Germany.
Three scenarios: small (20), medium (80), large (160) plants.
Parameters based on literature values with realistic random variation.
"""
import json
import numpy as np
import os

np.random.seed(42)

PLANT_TYPES = {
    "hard_coal": {
        "pmin_factor":    (0.35, 0.45),
        "pmax_mw":        (200, 700),
        "fuel_cost":      (10, 16),
        "co2_factor":     (0.32, 0.36),
        "ramp_up":        (0.02, 0.04),
        "ramp_down":      (0.02, 0.04),
        "min_uptime_h":   (4, 8),
        "min_downtime_h": (4, 6),
        "co2_price":      45.0,
        "color":          "#4a4a4a",
    },
    "lignite": {
        "pmin_factor":    (0.50, 0.60),
        "pmax_mw":        (300, 900),
        "fuel_cost":      (5, 9),
        "co2_factor":     (0.38, 0.42),
        "ramp_up":        (0.01, 0.02),
        "ramp_down":      (0.01, 0.02),
        "min_uptime_h":   (6, 12),
        "min_downtime_h": (6, 10),
        "co2_price":      45.0,
        "color":          "#8B4513",
    },
    "gas": {
        "pmin_factor":    (0.20, 0.35),
        "pmax_mw":        (100, 500),
        "fuel_cost":      (28, 48),
        "co2_factor":     (0.18, 0.22),
        "ramp_up":        (0.06, 0.10),
        "ramp_down":      (0.06, 0.10),
        "min_uptime_h":   (1, 3),
        "min_downtime_h": (1, 2),
        "co2_price":      45.0,
        "color":          "#FF8C00",
    },
    "biomass": {
        "pmin_factor":    (0.30, 0.50),
        "pmax_mw":        (20, 150),
        "fuel_cost":      (15, 22),
        "co2_factor":     (0.0, 0.0),
        "ramp_up":        (0.02, 0.05),
        "ramp_down":      (0.02, 0.05),
        "min_uptime_h":   (2, 4),
        "min_downtime_h": (2, 4),
        "co2_price":      0.0,
        "color":          "#228B22",
        "biomass_limit_factor": (0.60, 0.80),
    },
    "pump_storage": {
        "pmax_mw":               (100, 400),
        "energy_capacity_hours": (6, 10),
        "efficiency":            (0.75, 0.85),
        "color":                 "#1E90FF",
    },
}

REFERENCE_SYSTEM_SIZE_MW = 80000
TARGET_RESERVE_MARGIN = 1.15

SCENARIOS = {
    "small": {
        "n_plants": 20,
        "mix": {"hard_coal": 4, "lignite": 4, "gas": 7, "biomass": 4, "pump_storage": 1},
        # Rough toy-system sizing: about 500 MW target demand scale per plant.
        "target_system_size_mw": 10000,
    },
    "medium": {
        "n_plants": 80,
        "mix": {"hard_coal": 16, "lignite": 14, "gas": 34, "biomass": 12, "pump_storage": 4},
        "target_system_size_mw": 40000,
    },
    "large": {
        "n_plants": 160,
        "mix": {"hard_coal": 30, "lignite": 25, "gas": 70, "biomass": 25, "pump_storage": 10},
        "target_system_size_mw": 80000,
    },
}


def rand(lo, hi):
    return float(np.random.uniform(lo, hi))


def generate_plant(plant_type: str, idx: int) -> dict:
    p = PLANT_TYPES[plant_type]

    if plant_type == "pump_storage":
        pmax  = rand(*p["pmax_mw"])
        e_cap = pmax * rand(*p["energy_capacity_hours"])
        return {
            "id":                    f"{plant_type}_{idx}",
            "type":                  plant_type,
            "pmax_mw":               round(pmax, 1),
            "pmin_mw":               0.0,
            "energy_capacity_mwh":   round(e_cap, 1),
            "efficiency":            round(rand(*p["efficiency"]), 3),
            "initial_soc":           0.5,
            "final_soc":             0.5,
            "fuel_cost_per_mwh":     0.0,
            "co2_cost_per_mwh":      0.0,
            "marginal_cost":         0.0,
            "ramp_up_mw_per_h":      9999,
            "ramp_down_mw_per_h":    9999,
            "min_uptime_h":          0,
            "min_downtime_h":        0,
            "color":                 p["color"],
        }

    pmax       = rand(*p["pmax_mw"])
    pmin       = pmax * rand(*p["pmin_factor"])
    fuel_cost  = rand(*p["fuel_cost"])
    co2_factor = rand(*p["co2_factor"])
    co2_price  = p["co2_price"]
    marginal   = fuel_cost + co2_factor * co2_price
    ramp_up    = pmax * rand(*p["ramp_up"]) * 60
    ramp_down  = pmax * rand(*p["ramp_down"]) * 60

    plant = {
        "id":                      f"{plant_type}_{idx}",
        "type":                    plant_type,
        "pmax_mw":                 round(pmax, 1),
        "pmin_mw":                 round(pmin, 1),
        "fuel_cost_per_mwh":       round(fuel_cost, 2),
        "co2_factor_t_per_mwh":    round(co2_factor, 3),
        "co2_price_per_t":         co2_price,
        "marginal_cost":           round(marginal, 2),
        "ramp_up_mw_per_h":        round(ramp_up, 1),
        "ramp_down_mw_per_h":      round(ramp_down, 1),
        "min_uptime_h":            int(np.random.randint(*p["min_uptime_h"])),
        "min_downtime_h":          int(np.random.randint(*p["min_downtime_h"])),
        "color":                   p["color"],
    }

    if plant_type == "biomass":
        daily_max = pmax * 24
        plant["biomass_limit_mwh"] = round(
            daily_max * rand(*p["biomass_limit_factor"]), 1
        )

    return plant


def scale_capacity(plant: dict, factor: float) -> None:
    plant["pmax_mw"] = round(plant["pmax_mw"] * factor, 1)
    plant["pmin_mw"] = round(plant["pmin_mw"] * factor, 1)
    plant["ramp_up_mw_per_h"] = round(plant["ramp_up_mw_per_h"] * factor, 1)
    plant["ramp_down_mw_per_h"] = round(plant["ramp_down_mw_per_h"] * factor, 1)

    if plant["type"] == "biomass":
        plant["biomass_limit_mwh"] = round(plant["biomass_limit_mwh"] * factor, 1)
    if plant["type"] == "pump_storage":
        plant["energy_capacity_mwh"] = round(plant["energy_capacity_mwh"] * factor, 1)


def generate_scenario(name: str) -> dict:
    cfg = SCENARIOS[name]
    plants = []
    counters = {t: 0 for t in PLANT_TYPES}

    for plant_type, count in cfg["mix"].items():
        for _ in range(count):
            counters[plant_type] += 1
            plants.append(generate_plant(plant_type, counters[plant_type]))

    unscaled_conv = sum(
        p["pmax_mw"] for p in plants if p["type"] != "pump_storage"
    )
    target_conv = cfg["target_system_size_mw"] * TARGET_RESERVE_MARGIN
    capacity_scale_factor = target_conv / unscaled_conv

    # Keep the random technology mix, but calibrate total dispatchable capacity
    # so the scaled demand is not accidentally impossible to serve.
    for plant in plants:
        scale_capacity(plant, capacity_scale_factor)

    total_conv = sum(
        p["pmax_mw"] for p in plants if p["type"] != "pump_storage"
    )

    return {
        "scenario":                       name,
        "n_plants":                        cfg["n_plants"],
        "target_system_size_mw":           cfg["target_system_size_mw"],
        "reference_system_size_mw":        REFERENCE_SYSTEM_SIZE_MW,
        "scale_factor":                    cfg["target_system_size_mw"] / REFERENCE_SYSTEM_SIZE_MW,
        "target_reserve_margin":           TARGET_RESERVE_MARGIN,
        "capacity_scale_factor":           round(capacity_scale_factor, 4),
        "total_conventional_capacity_mw":  round(total_conv, 1),
        "plants":                          plants,
    }


if __name__ == "__main__":
    output = {s: generate_scenario(s) for s in SCENARIOS}

    out_path = os.path.join(os.path.dirname(__file__), "power_plants.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print("Power plant parameters generated:")
    for s, data in output.items():
        print(f"  {s}: {data['n_plants']} plants, "
              f"{data['total_conventional_capacity_mw']:.0f} MW conventional capacity")
    print(f"\nSaved to: {out_path}")
