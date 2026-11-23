/**
 * Pure helper functions (no DOM access) used by app.js.
 */

export const HOURS_PER_DAY = 24;

/** Number of day slices contained in a result with T hourly values. */
export function numberOfDays(hours) {
  return Math.ceil(hours / HOURS_PER_DAY);
}

/**
 * Algorithm parameters the user can set per metaheuristic. The names are the field names of
 * POST /solve and the suffix of the input ids ("opt-population_size").
 */
export const METHOD_PARAMS = {
  ea: ["population_size", "generations", "mutation_rate", "crossover_rate", "seed"],
  pso: ["swarm_size", "iterations", "inertia", "cognitive", "social", "seed"],
};

/**
 * Build the JSON body for POST /solve from the form values.
 * The MIP gap is entered in percent in the UI but sent as a fraction.
 * The time limit is sent for the exact method and the metaheuristics, the gap only for the exact
 * method, and the algorithm parameters (form.params, name -> text) only for the chosen metaheuristic.
 * Empty parameters are left out so the server uses its default.
 */
export function buildSolveRequest(form) {
  const request = {
    method: form.method,
    scenario: form.scenario,
    horizon: form.horizon,
    month: Number(form.month),
  };
  const isMetaheuristic = form.method in METHOD_PARAMS;
  if (form.method === "exact" || isMetaheuristic) {
    request.time_limit = Number(form.timeLimit);
  }
  if (form.method === "exact" && form.mipGapPercent !== "" && form.mipGapPercent !== null) {
    request.mip_gap = Number(form.mipGapPercent) / 100;
  }
  if (isMetaheuristic) {
    for (const name of METHOD_PARAMS[form.method]) {
      const value = form.params?.[name];
      if (value !== "" && value !== null && value !== undefined) request[name] = Number(value);
    }
  }
  return request;
}

/** Format a number with a fixed number of decimals for the given locale ("de-DE" or "en-US"). */
export function formatNumber(value, decimals = 0, locale = "de-DE") {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/** Format a relative gap (0.01) as a percentage string ("1,000 %"), or "n/a" if unknown. */
export function formatGap(gap, locale = "de-DE") {
  return gap === null || gap === undefined ? "n/a" : `${formatNumber(gap * 100, 3, locale)} %`;
}

/** Date (YYYY-MM-DD) of day number `dayIndex` of a result whose date is "YYYY-MM-DD" or "YYYY-MM-DD to YYYY-MM-DD". */
export function dayDate(resultDate, dayIndex) {
  const start = new Date(`${resultDate.slice(0, 10)}T00:00:00Z`);
  start.setUTCDate(start.getUTCDate() + dayIndex);
  return start.toISOString().slice(0, 10);
}

/** Format a "YYYY-MM-DD" date for the locale, e.g. "08.09.2023" for "de-DE". */
export function formatDate(isoDate, locale = "de-DE") {
  const [year, month, day] = isoDate.slice(0, 10).split("-").map(Number);
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
}

/**
 * Split a result into one profile per day (24 hours each; the last day may be shorter).
 *
 * Every profile contains:
 *  - date:    the calendar date of the day
 *  - labels:  hour labels for the x axis
 *  - stacks:  list of { key, color, values, costEur } for the stacked supply (negative = pump consumption);
 *             `key` names the series ("hard_coal", "wind", ...) and is translated by the caller;
 *             costEur is the generation cost of the day (output times marginal cost; 0 without fuel cost)
 *  - load:    the demand line
 *  - costEur: generation cost of this day (null if the result has no hourly costs)
 * Generation of all plants of the same type is summed up.
 */
export function buildDayProfiles(result) {
  const profiles = [];
  for (let day = 0; day < numberOfDays(result.T); day += 1) {
    const start = day * HOURS_PER_DAY;
    const end = Math.min(start + HOURS_PER_DAY, result.T);
    const slice = (values) => values.slice(start, end);

    const byType = new Map();
    for (const plant of result.schedule) {
      const values = slice(plant.generation);
      if (!byType.has(plant.type)) {
        byType.set(plant.type, { key: plant.type, color: plant.color, values: values.map(() => 0), costEur: 0 });
      }
      const entry = byType.get(plant.type);
      values.forEach((value, i) => { entry.values[i] += value; });
      entry.costEur += values.reduce((sum, value) => sum + value * plant.marginal_cost, 0);
    }

    const stacks = [...byType.values()];
    stacks.push({ key: "wind", color: "#6baed6", values: slice(result.wind), costEur: 0 });
    stacks.push({ key: "pv", color: "#fdd835", values: slice(result.pv), costEur: 0 });

    if (result.pump_schedule.length > 0) {
      const turbining = new Array(end - start).fill(0);
      const pumping = new Array(end - start).fill(0);
      for (const pump of result.pump_schedule) {
        slice(pump.turbining).forEach((value, i) => { turbining[i] += value; });
        slice(pump.pumping).forEach((value, i) => { pumping[i] -= value; });
      }
      stacks.push({ key: "pump_turbining", color: "#17becf", values: turbining, costEur: 0 });
      stacks.push({ key: "pump_charging", color: "#9edae5", values: pumping, costEur: 0 });
    }

    const hourlyCosts = result.hourly_cost_eur;
    profiles.push({
      date: dayDate(result.date, day),
      labels: Array.from({ length: end - start }, (_, i) => `${i}:00`),
      stacks,
      load: slice(result.load),
      costEur: hourlyCosts ? slice(hourlyCosts).reduce((sum, value) => sum + value, 0) : null,
    });
  }
  return profiles;
}

/**
 * Generation mix of one day profile.
 *  - demandMWh:          sum of the load over the day (hourly MW values, so MWh)
 *  - totalGenerationMWh: sum of all generation of the day (pump charging is consumption and not counted)
 *  - sources:            list of { key, color, energyMWh, costEur, share } with share in % of the total generation,
 *                        sorted by energy; sources without generation are left out
 */
export function buildDayMix(profile) {
  const sources = profile.stacks
    .filter((stack) => stack.key !== "pump_charging")
    .map((stack) => ({
      key: stack.key,
      color: stack.color,
      energyMWh: stack.values.reduce((sum, value) => sum + Math.max(value, 0), 0),
      costEur: stack.costEur,
    }))
    .filter((source) => source.energyMWh > 0)
    .sort((a, b) => b.energyMWh - a.energyMWh);

  const totalGenerationMWh = sources.reduce((sum, source) => sum + source.energyMWh, 0);
  for (const source of sources) {
    source.share = (source.energyMWh / totalGenerationMWh) * 100;
  }
  return {
    demandMWh: profile.load.reduce((sum, value) => sum + value, 0),
    totalGenerationMWh,
    sources,
  };
}
