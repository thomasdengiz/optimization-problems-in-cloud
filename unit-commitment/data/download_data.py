"""
Download German power system data from ENTSO-E for 2023.
Builds three optimization horizons per month:
- representative day
- second consecutive week of the month
- full month
Saves results to data/entsoe_2023.json
"""
import os
import json
import pandas as pd
import numpy as np
from entsoe import EntsoePandasClient
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))
API_KEY = os.getenv("ENTSOE_API_KEY")
if not API_KEY:
    raise ValueError("ENTSOE_API_KEY not found in .env file")

client  = EntsoePandasClient(api_key=API_KEY)
START   = pd.Timestamp("2023-01-01", tz="Europe/Berlin")
END     = pd.Timestamp("2023-12-31 23:00", tz="Europe/Berlin")
COUNTRY = "DE_LU"

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def horizon_payload(name: str, month_name: str, data: pd.DataFrame) -> dict:
    start_date = str(data.index[0].date())
    end_date = str(data.index[-1].date())
    date = start_date if start_date == end_date else f"{start_date} to {end_date}"

    return {
        "horizon":      name,
        "month_name":   month_name,
        "date":         date,
        "start_date":   start_date,
        "end_date":     end_date,
        "hours":        len(data),
        "load_mw":      data["load_mw"].tolist(),
        "wind_mw":      data["wind_mw"].tolist(),
        "pv_mw":        data["pv_mw"].tolist(),
        "peak_load_mw": float(data["load_mw"].max()),
        "avg_wind_mw":  float(data["wind_mw"].mean()),
        "avg_pv_mw":    float(data["pv_mw"].mean()),
    }

print("Downloading load data...")
load = client.query_load(COUNTRY, start=START, end=END)
load = load.resample("1h").mean()

print("Downloading generation data...")
gen = client.query_generation(COUNTRY, start=START, end=END)
gen = gen.resample("1h").mean()

wind_cols = [c for c in gen.columns if "Wind" in str(c)]
pv_cols   = [c for c in gen.columns if "Solar" in str(c)]

wind = gen[wind_cols].sum(axis=1) if wind_cols else pd.Series(0, index=gen.index)
pv   = gen[pv_cols].sum(axis=1)   if pv_cols   else pd.Series(0, index=gen.index)

df = pd.DataFrame({
    "load_mw": load.squeeze(),
    "wind_mw": wind,
    "pv_mw":   pv,
}).dropna()

# Select representative day per month
# = day whose hourly profile is closest to the monthly mean profile
representative_days = {}
horizons = {}

for month in range(1, 13):
    monthly        = df[df.index.month == month]
    monthly_hourly = monthly.groupby(monthly.index.hour).mean()
    month_name     = MONTH_NAMES[month - 1]

    best_day, best_score = None, float("inf")
    for day_ts in monthly.resample("D").mean().index:
        day_data = monthly[monthly.index.date == day_ts.date()]
        if len(day_data) < 24:
            continue
        profile = day_data.groupby(day_data.index.hour).mean()
        score   = float(((profile - monthly_hourly) ** 2).sum().sum())
        if score < best_score:
            best_score = score
            best_day   = day_ts

    if best_day is None:
        continue

    day_data = df[df.index.date == best_day.date()]

    week_start = pd.Timestamp(year=START.year, month=month, day=8, tz="Europe/Berlin")
    week_end = week_start + pd.DateOffset(days=7)
    week_data = df[(df.index >= week_start) & (df.index < week_end)]

    representative_days[month] = horizon_payload("day", month_name, day_data)
    horizons[month] = {
        "day":   representative_days[month],
        "week":  horizon_payload("week", month_name, week_data),
        "month": horizon_payload("month", month_name, monthly),
    }

    print(
        f"  {month_name}: representative day = {best_day.date()}, "
        f"second week = {week_data.index[0].date()} to {week_data.index[-1].date()}, "
        f"month hours = {len(monthly)}"
    )

output = {
    "year":                          2023,
    "country":                       "Germany",
    "resolution_hours":              1,
    "total_installed_capacity_mw":   80000,
    "representative_days":           representative_days,
    "horizons":                      horizons,
}

out_path = os.path.join(os.path.dirname(__file__), "entsoe_2023.json")
with open(out_path, "w") as f:
    json.dump(output, f, indent=2)

print(f"\nSaved: {out_path}")
print(f"Representative days: {len(representative_days)}/12")
