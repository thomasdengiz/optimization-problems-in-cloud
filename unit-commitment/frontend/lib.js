/**
 * Pure helper functions (no DOM access) used by app.js.
 */

export const HOURS_PER_DAY = 24;

/**
 * Turn an error into a message for the user.
 * fetch() rejects with a TypeError when the server cannot be reached at all (server asleep,
 * restarting, no internet, blocked by CORS); the browser console shows the technical details.
 */
export function friendlyErrorMessage(error) {
  if (error instanceof TypeError) {
    return "Server nicht erreichbar (möglicherweise Kaltstart oder Neustart). "
      + "Bitte in einer Minute erneut versuchen. Details stehen in der Browser-Konsole (F12).";
  }
  return error.message;
}

/** Number of day slices contained in a result with T hourly values. */
export function numberOfDays(hours) {
  return Math.ceil(hours / HOURS_PER_DAY);
}

/**
 * Build the JSON body for POST /solve from the form values.
 * The MIP gap is entered in percent in the UI but sent as a fraction.
 * Time limit and gap are only sent for the exact method.
 */
export function buildSolveRequest(form) {
  const request = {
    method: form.method,
    scenario: form.scenario,
    horizon: form.horizon,
    month: Number(form.month),
  };
  if (form.method === "exact") {
    request.time_limit = Number(form.timeLimit);
    if (form.mipGapPercent !== "" && form.mipGapPercent !== null) {
      request.mip_gap = Number(form.mipGapPercent) / 100;
    }
  }
  return request;
}

/** Format a number with a fixed number of decimals in German notation. */
export function formatNumber(value, decimals = 0) {
  return new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/** Format a relative gap (0.01) as a percentage string ("1,000 %"), or "n/a" if unknown. */
export function formatGap(gap) {
  return gap === null || gap === undefined ? "n/a" : `${formatNumber(gap * 100, 3)} %`;
}

/**
 * Prepare the stacked load profile of one day for the chart.
 *
 * Returns { labels, stacks, load } where stacks is a list of
 * { label, color, values } (negative values = pump consumption) and load is the demand line.
 * Generation of all plants of the same type is summed up.
 */
export function buildDayProfile(result, day) {
  const start = day * HOURS_PER_DAY;
  const end = Math.min(start + HOURS_PER_DAY, result.T);
  const slice = (values) => values.slice(start, end);

  const byType = new Map();
  for (const plant of result.schedule) {
    const values = slice(plant.generation);
    if (!byType.has(plant.type)) {
      byType.set(plant.type, { label: plant.type, color: plant.color, values: values.map(() => 0) });
    }
    const entry = byType.get(plant.type);
    values.forEach((value, i) => { entry.values[i] += value; });
  }

  const stacks = [...byType.values()];
  stacks.push({ label: "wind", color: "#6baed6", values: slice(result.wind) });
  stacks.push({ label: "pv", color: "#fdd835", values: slice(result.pv) });

  if (result.pump_schedule.length > 0) {
    const hours = end - start;
    const turbining = new Array(hours).fill(0);
    const pumping = new Array(hours).fill(0);
    for (const pump of result.pump_schedule) {
      slice(pump.turbining).forEach((value, i) => { turbining[i] += value; });
      slice(pump.pumping).forEach((value, i) => { pumping[i] -= value; });
    }
    stacks.push({ label: "pump turbining", color: "#17becf", values: turbining });
    stacks.push({ label: "pump charging", color: "#9edae5", values: pumping });
  }

  return {
    labels: Array.from({ length: end - start }, (_, i) => `${i}:00`),
    stacks,
    load: slice(result.load),
  };
}
