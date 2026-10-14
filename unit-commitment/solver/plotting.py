"""
Plotting utilities for unit commitment results.
"""
import os


TECH_ORDER = [
    "wind",
    "pv",
    "lignite",
    "hard_coal",
    "biomass",
    "gas",
    "pump_storage",
]

TECH_LABELS = {
    "wind": "Wind",
    "pv": "PV",
    "lignite": "Lignite",
    "hard_coal": "Hard Coal",
    "biomass": "Biomass",
    "gas": "Gas",
    "pump_storage": "Pump Storage",
}

TECH_COLORS = {
    "wind": "#5DADE2",
    "pv": "#F4D03F",
}


def _get_matplotlib():
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is not installed. Run 'pip install matplotlib' to create charts."
        ) from exc
    return plt


def _aggregate_by_technology(result: dict) -> tuple[dict, list[float]]:
    T = result["T"]
    generation = {
        "wind": [float(x) for x in result["wind"]],
        "pv": [float(x) for x in result["pv"]],
    }

    for entry in result["schedule"]:
        tech = entry["type"]
        generation.setdefault(tech, [0.0] * T)
        for t, value in enumerate(entry["generation"]):
            generation[tech][t] += float(value)
        TECH_COLORS.setdefault(tech, entry["color"])

    pumping = [0.0] * T
    for entry in result["pump_schedule"]:
        tech = entry["type"]
        generation.setdefault(tech, [0.0] * T)
        for t, value in enumerate(entry["turbining"]):
            generation[tech][t] += float(value)
        for t, value in enumerate(entry["pumping"]):
            pumping[t] += float(value)
        TECH_COLORS.setdefault(tech, entry["color"])

    return generation, pumping


def save_system_schedule_chart(result: dict, scenario: str, output_dir: str) -> str:
    plt = _get_matplotlib()
    generation, pumping = _aggregate_by_technology(result)
    hours = list(range(result["T"]))

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(
        output_dir,
        f"schedule_{result['method']}_{scenario}_{result['date']}.png",
    )

    fig, ax = plt.subplots(figsize=(14, 7))
    bottom = [0.0] * result["T"]

    for tech in TECH_ORDER:
        values = generation.get(tech)
        if not values or max(values) <= 0:
            continue
        ax.bar(
            hours,
            values,
            bottom=bottom,
            width=0.85,
            color=TECH_COLORS.get(tech, "#999999"),
            label=TECH_LABELS.get(tech, tech.replace("_", " ").title()),
            edgecolor="white",
            linewidth=0.3,
        )
        bottom = [bottom[t] + values[t] for t in range(result["T"])]

    if max(pumping, default=0.0) > 0:
        ax.bar(
            hours,
            [-x for x in pumping],
            width=0.85,
            color="#7F8C8D",
            alpha=0.55,
            label="Pump Storage Charging",
            edgecolor="white",
            linewidth=0.3,
        )

    ax.plot(hours, result["load"], color="black", linewidth=2.0, label="Load")
    ax.set_title(
        f"System Dispatch by Technology - {scenario.capitalize()} - "
        f"{result['month_name']} {result['date']}"
    )
    ax.set_xlabel("Hour")
    ax.set_ylabel("Power (MW)")
    ax.set_xticks(hours)
    ax.set_xlim(-0.5, result["T"] - 0.5)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(ncol=3, frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)

    return output_path
