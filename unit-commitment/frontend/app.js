/**
 * Main script of the web page: map, form handling, job polling, result display and language.
 * Pure helper functions live in lib.js, all texts in i18n.js.
 */
import {
  buildDayMix, buildDayProfiles, buildSolveRequest, formatGap, formatNumber,
} from "./lib.js";
import {
  detectLanguage, infoText, LOCALES, MONTH_NAMES, translate,
} from "./i18n.js";

const API = window.APP_CONFIG.API_BASE_URL.replace(/\/$/, "");
const POLL_INTERVAL_MS = 1000;
const HEALTH_RETRY_MS = 3000;
const WAKE_UP_TIMEOUT_MS = 3 * 60 * 1000;   // how long to wait for a sleeping server
const MAX_POLL_FAILURES = 5;                 // consecutive failed status requests before giving up
const POLL_RETRY_MS = 2000;
const LANGUAGE_STORAGE_KEY = "uc-language";
// Only these countries can be selected on the map (the data exists only for Germany so far)
const SELECTABLE_COUNTRIES = ["DE"];
// Icon shown in the chart legend for each series key (files in frontend/icons/)
const SERIES_ICONS = {
  hard_coal: "icons/hard_coal.svg",
  lignite: "icons/lignite.svg",
  gas: "icons/gas.svg",
  biomass: "icons/biomass.svg",
  wind: "icons/wind.svg",
  pv: "icons/pv.svg",
  pump_turbining: "icons/pump_turbining.svg",
  pump_charging: "icons/pump_charging.svg",
  load: "icons/load.svg",
};

// Global Chart.js look: system font and a softer grey for text
Chart.defaults.font.family = "system-ui, sans-serif";
Chart.defaults.color = "#57606a";
// Colour of the load line and its legend swatch
const LOAD_COLOR = "#1f2328";

/** Hex colour to rgba string with the given alpha (non-hex colours are returned unchanged). */
function withAlpha(color, alpha) {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return color;
  const n = parseInt(color.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/** Bar fill: vertical gradient, softer at the bottom and full colour at the top. */
function barFill(color) {
  return ({ chart }) => {
    const { ctx, chartArea } = chart;
    if (!chartArea) return color;
    const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
    gradient.addColorStop(0, withAlpha(color, 0.7));
    gradient.addColorStop(1, color);
    return gradient;
  };
}

/** Light column behind the hovered hour, so the active time slot is easy to see. */
const hoverColumn = {
  id: "hoverColumn",
  beforeDatasetsDraw(chart) {
    const active = chart.getActiveElements();
    if (!active.length) return;
    const { ctx, chartArea } = chart;
    const slot = (chartArea.right - chartArea.left) / chart.data.labels.length;
    ctx.save();
    ctx.fillStyle = "rgba(31, 35, 40, 0.06)";
    ctx.fillRect(active[0].element.x - slot / 2, chartArea.top, slot, chartArea.bottom - chartArea.top);
    ctx.restore();
  },
};

const $ = (id) => document.getElementById(id);
const state = {
  language: detectLanguage(localStorage.getItem(LANGUAGE_STORAGE_KEY), navigator.language),
  country: null,
  methods: {},
  result: null,
  view: "load", // "load" (load profile, default) or "mix" (generation mix donut)
  charts: [],
  status: null,   // { key, params } of the status line, or { text } for untranslated text
  running: false,
};

/** Translate a key in the selected language. */
const t = (key, params) => translate(state.language, key, params);

/** Pause for the given number of milliseconds. */
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Raised when the server no longer knows a job (it restarted and forgot all jobs). */
class JobLostError extends Error {}

/** An error reported by the server, with a code the page translates (see "error.*" in i18n.js). */
class ApiError extends Error {
  constructor(message, code = null, params = {}) {
    super(message);
    this.code = code;
    this.params = params;
  }
}

/** Message for the user: translated if the error has a known code, else the server's text. */
function errorText(error) {
  if (error instanceof JobLostError) return t("error.lost");
  if (error instanceof TypeError) return t("error.unreachable");   // fetch() could not connect
  if (error instanceof ApiError && error.code && t(`error.${error.code}`) !== `error.${error.code}`) {
    return t(`error.${error.code}`, error.params);
  }
  return error.message;
}

/** Show a status message below the solve button; keyed messages follow the language. */
function setStatus(key, params = {}) {
  state.status = { key, params };
  renderStatus();
}

/** Show an error in the status line. */
function setErrorStatus(error) {
  state.status = { text: errorText(error) };
  renderStatus();
}

/** Write the current status into the page (again after a language change). */
function renderStatus() {
  const status = state.status;
  if (!status) {
    $("status").textContent = "";
  } else if (status.key) {
    $("status").textContent = t(status.key, status.params);
  } else {
    $("status").textContent = t("status.error", { message: status.text });
  }
}

/** Enable the solve button only if a country is chosen, the chosen method exists and no job runs. */
function updateSolveButton() {
  const method = state.methods[$("method").value];
  $("solve").disabled = !(state.country && method && method.available && !state.running);
}

/** Month names in the selected language; keeps the selected month. */
function renderMonthOptions() {
  const select = $("month");
  const selected = select.value || "1";
  select.replaceChildren();
  MONTH_NAMES[state.language].forEach((name, index) => {
    const option = document.createElement("option");
    option.value = String(index + 1);
    option.textContent = name;
    select.appendChild(option);
  });
  select.value = selected;
}

/** Method names in the selected language; unavailable methods are greyed out and cannot be chosen. */
function renderMethodOptions() {
  const select = $("method");
  const selected = select.value || "priority_list";
  select.replaceChildren();
  for (const [key, info] of Object.entries(state.methods)) {
    const label = t(`method.${key}`) === `method.${key}` ? info.label : t(`method.${key}`);
    const option = document.createElement("option");
    option.value = key;
    option.disabled = !info.available;
    option.textContent = info.available ? label : `${label} ${t("method.soon")}`;
    select.appendChild(option);
  }
  if (select.options.length > 0) select.value = selected;
}

/** Short explanations below method, scenario and month; they change with the selection. */
function renderInfoTexts() {
  $("params-exact").hidden = $("method").value !== "exact";   // time limit and gap only apply to the exact method
  const method = $("method").value;
  $("method-info").textContent = method ? infoText(state.language, "method", method) : "";
  $("scenario-info").textContent = infoText(state.language, "scenario", $("scenario").value);
  $("horizon-info").textContent = infoText(state.language, "horizon", $("horizon").value);
  const monthName = MONTH_NAMES[state.language][Number($("month").value) - 1];
  $("month-info").textContent = infoText(state.language, "month", $("month").value, { month: monthName });
}

/** Show the country hint or the selected country. */
function renderCountryInfo() {
  $("country-info").textContent = state.country
    ? t("country.selected", { country: t(`country.${state.country}`) })
    : t("country.hint");
}

/** Keep the custom language picker in sync with the selected language. */
function renderLanguagePicker() {
  const selected = document.querySelector(`[data-language="${state.language}"]`);
  const trigger = $("language");
  const triggerImage = trigger.querySelector("img");
  const triggerText = trigger.querySelector("span");
  triggerImage.src = selected.querySelector("img").getAttribute("src");
  triggerImage.alt = selected.querySelector("img").alt;
  triggerText.textContent = selected.querySelector("span").textContent;
  document.querySelectorAll("[data-language]").forEach((option) => {
    option.setAttribute("aria-selected", String(option === selected));
  });
}

/** Apply the selected language to the whole page (static texts, dropdowns, status, results). */
function applyLanguage() {
  document.documentElement.lang = state.language;
  document.title = t("page.title");
  renderLanguagePicker();
  for (const element of document.querySelectorAll("[data-i18n]")) {
    element.textContent = t(element.dataset.i18n);
  }
  renderMonthOptions();
  renderMethodOptions();
  renderInfoTexts();
  renderCountryInfo();
  renderStatus();
  if (state.result) renderResult();
}

/**
 * Wait until the backend answers /health. A free host puts the server to sleep when it is not
 * used, so the first requests can fail for up to a minute. onWaiting is called before each retry.
 */
async function waitForServer(onWaiting, timeoutMs = Infinity) {
  const startedAt = Date.now();
  for (;;) {
    try {
      const response = await fetch(`${API}/health`);
      if (response.ok) return;
    } catch (error) {
      console.warn("Server not reachable yet:", error);
    }
    if (Date.now() - startedAt > timeoutMs) {
      throw new TypeError("Server did not answer /health in time");
    }
    onWaiting();
    await sleep(HEALTH_RETRY_MS);
  }
}

/** Wait for the backend and then load the method list. */
async function connectToServer() {
  const banner = $("server-banner");
  await waitForServer(() => { banner.hidden = false; });
  banner.hidden = true;

  state.methods = await (await fetch(`${API}/methods`)).json();
  renderMethodOptions();
  $("method").value = "priority_list";
  renderInfoTexts();
  updateSolveButton();
}

/** Create the Europe map in which only the selectable countries react to clicks. */
async function initMap() {
  const map = L.map("map", { zoomControl: true, attributionControl: false }).setView([52, 12], 3);
  const geojson = await (await fetch("data/europe.geojson")).json();

  const baseStyle = { color: "#8c959f", weight: 1, fillColor: "#d0d7de", fillOpacity: 1 };
  const selectableStyle = { color: "#0b6e4f", weight: 1.5, fillColor: "#7fc8a9", fillOpacity: 1 };
  const selectedStyle = { color: "#084c37", weight: 2, fillColor: "#0b6e4f", fillOpacity: 1 };

  let selectedLayer = null;
  const layer = L.geoJSON(geojson, {
    style: (feature) => (SELECTABLE_COUNTRIES.includes(feature.properties.id) ? selectableStyle : baseStyle),
    interactive: true,
    onEachFeature: (feature, featureLayer) => {
      const id = feature.properties.id;
      if (!SELECTABLE_COUNTRIES.includes(id)) {
        featureLayer.options.interactive = false; // grey countries ignore clicks
        return;
      }
      featureLayer.bindTooltip(() => t(`country.${id}`));
      featureLayer.on("click", () => {
        if (selectedLayer) selectedLayer.setStyle(selectableStyle);
        selectedLayer = featureLayer;
        featureLayer.setStyle(selectedStyle);
        state.country = id;
        renderCountryInfo();
        updateSolveButton();
      });
    },
  }).addTo(map);
  map.fitBounds(layer.getBounds());
}

/**
 * Ask the server for the state of a job until it is done. Short connection problems are
 * retried (the server may be restarting); a job the server forgot raises JobLostError.
 */
async function waitForJob(jobId) {
  const startedAt = Date.now();
  let failures = 0;
  for (;;) {
    let job;
    try {
      const response = await fetch(`${API}/jobs/${jobId}`);
      if (response.status === 404) throw new JobLostError();
      if (!response.ok) throw new ApiError(t("error.http", { status: response.status }));
      job = await response.json();
      failures = 0;
    } catch (error) {
      if (error instanceof JobLostError) throw error;
      failures += 1;
      console.warn(`Status request failed (${failures}/${MAX_POLL_FAILURES}):`, error);
      if (failures >= MAX_POLL_FAILURES) throw error;
      setStatus("status.retry", { n: failures, max: MAX_POLL_FAILURES });
      await sleep(POLL_RETRY_MS);
      continue;
    }

    if (job.status === "done") return job.result;
    if (job.status === "failed") throw new ApiError(job.error, job.error_code);

    const seconds = Math.round((Date.now() - startedAt) / 1000);
    setStatus(job.status === "queued" ? "status.queued" : "status.running", { seconds });
    await sleep(POLL_INTERVAL_MS);
  }
}

/** Turn a rejected /solve response into an ApiError (the server sends a text or {code, message, ...}). */
async function rejectionError(response) {
  const body = await response.json().catch(() => ({}));
  const detail = body.detail;
  if (detail && typeof detail === "object") {
    return new ApiError(detail.message, detail.code, { needed: detail.needed_mb, limit: detail.limit_mb });
  }
  return new ApiError(typeof detail === "string" ? detail : t("error.rejected", { status: response.status }));
}

/** Start a job, poll until it is finished and display the outcome. */
async function solve() {
  const request = buildSolveRequest({
    method: $("method").value,
    scenario: $("scenario").value,
    horizon: $("horizon").value,
    month: $("month").value,
    timeLimit: $("time-limit").value,
    mipGapPercent: $("mip-gap").value,
  });

  state.running = true;
  updateSolveButton();

  // Hide the previous result immediately when a new run starts.
  state.result = null;
  state.charts.forEach((chart) => chart.destroy());
  state.charts = [];
  $("days").replaceChildren();
  $("result").hidden = true;
  $("no-result").hidden = false;
  $("computing").hidden = false;

  try {
    // The server may have fallen asleep since the page was loaded: wake it up first
    setStatus("status.connecting");
    await waitForServer(() => setStatus("status.waking"), WAKE_UP_TIMEOUT_MS);

    setStatus("status.sending");
    const response = await fetch(`${API}/solve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    if (!response.ok) throw await rejectionError(response);
    const { job_id: jobId } = await response.json();

    state.result = await waitForJob(jobId);
    renderResult();
    setStatus("status.done");
  } catch (error) {
    console.error("Solve failed:", error);
    setErrorStatus(error);
  } finally {
    state.running = false;
    $("computing").hidden = true;
    updateSolveButton();
  }
}

/** Fill the result cards, the reasons list and one load profile chart per day. */
function renderResult() {
  const result = state.result;
  const locale = LOCALES[state.language];
  $("no-result").hidden = true;
  $("result").hidden = false;

  const solverSeconds = result.solve_time_seconds ?? result.solve_time_ms / 1000;
  const seconds = (value) => (value === null || value === undefined ? "–" : `${formatNumber(value, 2, locale)} s`);
  $("r-cost").textContent = `${formatNumber(result.total_cost_eur, 0, locale)} €`;
  $("r-solver-time").textContent = seconds(solverSeconds);
  $("r-build-time").textContent = seconds(result.model_build_seconds);
  $("r-total-time").textContent = seconds(result.solve_time_ms / 1000);
  $("r-vars").textContent = t("result.variablesValue", {
    total: formatNumber(result.num_variables, 0, locale),
    binary: formatNumber(result.num_binary_variables, 0, locale),
  });
  $("r-gap").textContent = formatGap(result.mip_gap, locale);

  const feasible = $("r-feasible");
  feasible.textContent = result.feasible ? t("result.yes") : t("result.no");
  feasible.className = result.feasible ? "feasible-yes" : "feasible-no";
  $("limit-note").hidden = !result.stopped_at_time_limit;

  const reasons = $("reasons");
  reasons.replaceChildren();
  for (const reason of result.infeasibility_reasons ?? []) {
    const item = document.createElement("li");
    item.textContent = reason; // textContent: server text is never interpreted as HTML
    reasons.appendChild(item);
  }

  renderDays(locale);
}

/** One section with title, daily cost and chart per day, shown one below the other. */
function renderDays(locale) {
  const container = $("days");
  state.charts.forEach((chart) => chart.destroy());
  state.charts = [];
  container.replaceChildren();

  buildDayProfiles(state.result).forEach((profile, index) => {
    const section = document.createElement("section");
    section.className = "day";
    section.setAttribute("data-testid", "day-section");

    const heading = document.createElement("h4");
    const title = document.createElement("span");
    title.textContent = t("profile.day", { n: index + 1, date: profile.date });
    heading.appendChild(title);
    if (profile.costEur !== null) {
      const cost = document.createElement("span");
      cost.className = "day-cost";
      cost.setAttribute("data-testid", "day-cost");
      cost.textContent = t("profile.cost", { cost: `${formatNumber(profile.costEur, 0, locale)} €` });
      heading.appendChild(cost);
    }
    section.appendChild(heading);

    if (state.view === "mix") {
      const box = document.createElement("div");
      box.className = "chart-box donut-box";
      const canvas = document.createElement("canvas");
      box.appendChild(canvas);
      section.appendChild(box);
      container.appendChild(section);
      state.charts.push(drawDonut(canvas, profile, locale));
      return;
    }

    const box = document.createElement("div");
    box.className = "chart-box";
    const canvas = document.createElement("canvas");
    box.appendChild(canvas);
    section.appendChild(box);
    section.appendChild(buildLegend(profile));
    container.appendChild(section);

    state.charts.push(drawChart(canvas, profile, locale));
  });
}

/** HTML legend under a chart: colour swatch, icon and name for each series (follows the language). */
function buildLegend(profile) {
  const list = document.createElement("ul");
  list.className = "legend";
  const entries = [
    ...profile.stacks.map((stack) => ({ key: stack.key, color: stack.color })),
    { key: "load", color: LOAD_COLOR },
  ];
  for (const entry of entries) {
    const item = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.backgroundColor = entry.color;
    item.appendChild(swatch);
    if (SERIES_ICONS[entry.key]) {
      const icon = document.createElement("img");
      icon.src = SERIES_ICONS[entry.key];
      icon.alt = "";
      icon.width = 16;
      icon.height = 16;
      item.appendChild(icon);
    }
    const name = document.createElement("span");
    name.textContent = t(`series.${entry.key}`);
    item.appendChild(name);
    list.appendChild(item);
  }
  return list;
}

/** Draw the stacked generation chart with the demand line for one day. */
function drawChart(canvas, profile, locale) {
  const datasets = profile.stacks.map((stack) => ({
    type: "bar",
    order: 1,                       // higher order = drawn behind the load line
    label: t(`series.${stack.key}`),
    seriesKey: stack.key,
    seriesColor: stack.color,       // plain colour, used by the legend-like tooltip swatch
    data: stack.values,
    backgroundColor: barFill(stack.color),
    stack: "supply",
    barPercentage: 0.8,
    categoryPercentage: 0.9,
    borderWidth: 0,
    borderRadius: 3,
    borderSkipped: false,
  }));
  datasets.push({
    type: "line",
    order: 0,                       // lower order = drawn on top of the bars
    label: t("series.load"),
    seriesKey: "load",
    seriesColor: LOAD_COLOR,
    data: profile.load,
    borderColor: LOAD_COLOR,
    backgroundColor: LOAD_COLOR,
    borderWidth: 2.5,
    borderCapStyle: "round",
    borderJoinStyle: "round",
    tension: 0.3,
    pointRadius: 0,
    pointHoverRadius: 5,
    pointHoverBackgroundColor: "#fff",
    pointHoverBorderColor: LOAD_COLOR,
    pointHoverBorderWidth: 2,
  });

  // The tooltip is a separate HTML card (it can show icons), placed inside the chart box.
  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip";
  tooltip.hidden = true;
  canvas.parentElement.appendChild(tooltip);

  return new Chart(canvas, {
    data: { labels: profile.labels, datasets },
    plugins: [hoverColumn],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 800, easing: "easeOutQuart" },
      interaction: { mode: "index", intersect: false },   // hovering an hour shows all its series
      plugins: {
        legend: { display: false },   // the HTML legend from buildLegend() is used instead
        tooltip: {
          enabled: false,             // replaced by the HTML card below
          external: (context) => renderTooltip(tooltip, context, locale),
        },
      },
      scales: {
        x: {
          stacked: true,
          border: { display: false },
          grid: { display: false },
          // every hour is shown; labels rotate only if the chart is too narrow for them
          ticks: { autoSkip: false, minRotation: 0, maxRotation: 45, font: { size: 11 } },
        },
        y: {
          stacked: true,
          border: { display: false },
          grid: { color: "#eef1f4", borderDash: [4, 4] },
          ticks: { callback: (value) => formatNumber(value, 0, locale) },
          title: { display: true, text: t("profile.unit") },
        },
      },
    },
  });
}

/**
 * Fill the tooltip card for the hovered hour: title, then every series that has a value in
 * this hour (colour, icon, name, value with unit). The load is always listed at the end.
 */
function renderTooltip(element, context, locale) {
  const { chart, tooltip } = context;
  if (tooltip.opacity === 0 || tooltip.dataPoints.length === 0) {
    element.hidden = true;
    return;
  }

  const isLoad = (point) => point.dataset.seriesKey === "load";
  const rows = tooltip.dataPoints.filter((point) => isLoad(point) || Math.abs(point.raw) >= 0.05);
  rows.sort((a, b) => Number(isLoad(a)) - Number(isLoad(b)));   // load last

  element.replaceChildren();
  const title = document.createElement("div");
  title.className = "chart-tooltip-title";
  title.textContent = tooltip.title.join(" ");
  element.appendChild(title);

  for (const point of rows) {
    const { dataset } = point;
    const row = document.createElement("div");
    row.className = isLoad(point) ? "chart-tooltip-row is-load" : "chart-tooltip-row";

    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.backgroundColor = dataset.seriesColor;
    row.appendChild(swatch);

    if (SERIES_ICONS[dataset.seriesKey]) {
      const icon = document.createElement("img");
      icon.src = SERIES_ICONS[dataset.seriesKey];
      icon.alt = "";
      icon.width = 16;
      icon.height = 16;
      row.appendChild(icon);
    }

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = dataset.label;
    const value = document.createElement("span");
    value.className = "value";
    value.textContent = `${formatNumber(point.raw, 1, locale)} ${t("profile.unit")}`;
    row.append(name, value);
    element.appendChild(row);
  }

  // Place the card next to the hovered point, on the left side when near the right edge.
  element.hidden = false;
  const gap = 14;
  const { caretX, caretY } = tooltip;
  const left = caretX > chart.width / 2 ? caretX - element.offsetWidth - gap : caretX + gap;
  const top = Math.min(Math.max(caretY - element.offsetHeight / 2, 0), chart.height - element.offsetHeight);
  element.style.left = `${Math.max(left, 0)}px`;
  element.style.top = `${Math.max(top, 0)}px`;
}

/** Dark text on light colours, white text on dark colours. */
function textColorFor(hex) {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return "#fff";
  const value = parseInt(hex.slice(1), 16);
  const luminance = (0.299 * ((value >> 16) & 255) + 0.587 * ((value >> 8) & 255) + 0.114 * (value & 255)) / 255;
  return luminance > 0.6 ? "#1f2328" : "#fff";
}

/** Icon images for the donut labels, loaded once. The charts are redrawn when an icon has arrived. */
const iconImages = {};
function iconImage(key) {
  if (!SERIES_ICONS[key]) return null;
  if (!iconImages[key]) {
    const image = new Image();
    image.onload = () => state.charts.forEach((chart) => chart.draw());
    image.src = SERIES_ICONS[key];
    iconImages[key] = image;
  }
  return iconImages[key];
}

const DONUT_ICON_SIZE = 20;
const DONUT_LABEL_SPACING = 48; // minimum vertical distance between two outside labels on the same side
const DONUT_LABEL_REACH = 40; // distance from the ring edge to the label column
const DONUT_LABEL_BLOCK = 230; // estimated width of one label (icon, name, sum)
const DONUT_VERTICAL_MARGIN = 30; // free space above and below the ring

/**
 * Donut plugin: percentages inside the ring (large slices only), labels with leader lines outside
 * (icon, name, summed energy) and total demand in the centre.
 */
const donutLabels = {
  id: "donutLabels",
  afterDatasetsDraw(chart) {
    const options = chart.options.plugins.donutLabels;
    const arcs = chart.getDatasetMeta(0).data;
    if (!options || arcs.length === 0) return;
    const { ctx } = chart;
    const { x: cx, y: cy, outerRadius } = arcs[0];

    ctx.save();
    ctx.textBaseline = "middle";

    // percentages inside the ring
    ctx.textAlign = "center";
    ctx.font = "600 15px system-ui, sans-serif";
    arcs.forEach((arc, i) => {
      const item = options.items[i];
      if (item.share < 5) return;
      const angle = (arc.startAngle + arc.endAngle) / 2;
      const radius = (arc.innerRadius + arc.outerRadius) / 2;
      ctx.fillStyle = textColorFor(item.color);
      ctx.fillText(item.percentText, cx + radius * Math.cos(angle), cy + radius * Math.sin(angle));
    });

    // labels outside with leader lines
    const reach = outerRadius + DONUT_LABEL_REACH;
    const minY = 24;
    const maxY = chart.height - 24;
    const labels = arcs.map((arc, i) => {
      const angle = (arc.startAngle + arc.endAngle) / 2;
      const cos = Math.cos(angle);
      const sin = Math.sin(angle);
      return {
        item: options.items[i],
        dir: cos >= 0 ? 1 : -1,
        anchor: { x: cx + (outerRadius + 3) * cos, y: cy + (outerRadius + 3) * sin },
        elbow: { x: cx + (outerRadius + 18) * cos, y: cy + (outerRadius + 18) * sin },
        y: cy + (outerRadius + 18) * sin,
      };
    });
    // keep labels on each side apart and inside the canvas
    for (const dir of [1, -1]) {
      const side = labels.filter((label) => label.dir === dir).sort((a, b) => a.y - b.y);
      side.forEach((label, i) => {
        label.y = Math.min(Math.max(label.y, minY), maxY);
        if (i > 0) label.y = Math.max(label.y, side[i - 1].y + DONUT_LABEL_SPACING);
      });
      for (let i = side.length - 2; i >= 0; i--) {
        side[i].y = Math.min(side[i].y, side[i + 1].y - DONUT_LABEL_SPACING);
      }
    }

    ctx.textAlign = "left";
    for (const { item, dir, anchor, elbow, y } of labels) {
      const labelX = cx + dir * reach;

      ctx.strokeStyle = "#8c959f";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(anchor.x, anchor.y);
      ctx.lineTo(elbow.x, elbow.y);
      ctx.lineTo(labelX - dir * 4, y);
      ctx.stroke();

      const name = item.share < 5 ? `${item.name} (${item.percentText})` : item.name;
      ctx.font = "600 15px system-ui, sans-serif";
      const nameWidth = ctx.measureText(name).width;
      ctx.font = "13px system-ui, sans-serif";
      const sumWidth = ctx.measureText(item.sumText).width;
      const blockWidth = DONUT_ICON_SIZE + 8 + Math.max(nameWidth, sumWidth);
      const left = dir > 0 ? labelX : labelX - blockWidth;
      const textX = left + DONUT_ICON_SIZE + 8;

      const icon = iconImage(item.key);
      if (icon && icon.complete) {
        ctx.drawImage(icon, left, y - DONUT_ICON_SIZE / 2, DONUT_ICON_SIZE, DONUT_ICON_SIZE);
      }
      ctx.fillStyle = "#1f2328";
      ctx.font = "600 15px system-ui, sans-serif";
      ctx.fillText(name, textX, y - 10);
      ctx.fillStyle = "#6e7781";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText(item.sumText, textX, y + 10);
    }

    // total demand in the centre
    const center = options.center;
    ctx.textAlign = "center";
    ctx.fillStyle = "#57606a";
    ctx.font = "13px system-ui, sans-serif";
    ctx.fillText(center.caption, cx, cy - 20);
    ctx.fillStyle = "#1f2328";
    ctx.font = "700 26px system-ui, sans-serif";
    ctx.fillText(center.value, cx, cy + 6);
    ctx.fillStyle = "#57606a";
    ctx.font = "14px system-ui, sans-serif";
    ctx.fillText(center.unit, cx, cy + 30);

    ctx.restore();
  },
};

/** Donut chart with the generation mix of one day (shares of the total generation). */
function drawDonut(canvas, profile, locale) {
  const mix = buildDayMix(profile);
  // Size the ring so that the labels on both sides fit inside the box and the ring is centred.
  const boxWidth = canvas.parentElement.clientWidth;
  const boxHeight = canvas.parentElement.clientHeight;
  const radius = Math.max(
    60,
    Math.min((boxHeight - 2 * DONUT_VERTICAL_MARGIN) / 2, boxWidth / 2 - DONUT_LABEL_REACH - DONUT_LABEL_BLOCK),
  );
  const sideSpace = Math.max(0, (boxWidth - 2 * radius) / 2);
  const verticalSpace = Math.max(8, (boxHeight - 2 * radius) / 2);
  return new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: mix.sources.map((source) => t(`series.${source.key}`)),
      datasets: [
        {
          data: mix.sources.map((source) => source.energyMWh),
          backgroundColor: mix.sources.map((source) => source.color),
          borderColor: "#fff",
          borderWidth: 2,
          hoverOffset: 6,
        },
      ],
    },
    plugins: [donutLabels],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "62%",
      animation: { duration: 800, easing: "easeOutQuart" },
      layout: { padding: { left: sideSpace, right: sideSpace, top: verticalSpace, bottom: verticalSpace } },
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false },
        donutLabels: {
          center: {
            caption: t("mix.demand"),
            value: formatNumber(mix.demandMWh, 0, locale),
            unit: t("mix.unit"),
          },
          items: mix.sources.map((source) => ({
            key: source.key,
            name: t(`series.${source.key}`),
            color: source.color,
            share: source.share,
            percentText: `${formatNumber(source.share, 1, locale)} %`,
            sumText: `${formatNumber(source.energyMWh, 0, locale)} ${t("mix.unit")}`,
          })),
        },
      },
    },
  });
}

/** Switch between the load profile view and the generation mix view. */
function setView(view) {
  state.view = view;
  updateViewButtons();
  if (state.result) renderDays(LOCALES[state.language]);
}

function updateViewButtons() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.view === state.view));
  });
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});
updateViewButtons();

const languageTrigger = $("language");
const languageOptions = $("language-options");
const languageOptionButtons = [...languageOptions.querySelectorAll('[role="option"]')];

function closeLanguageOptions(restoreFocus = false) {
  languageOptions.hidden = true;
  languageTrigger.setAttribute("aria-expanded", "false");
  if (restoreFocus) languageTrigger.focus();
}

function openLanguageOptions(focusSelected = false) {
  languageOptions.hidden = false;
  languageTrigger.setAttribute("aria-expanded", "true");
  if (focusSelected) languageOptionButtons.find((option) => option.dataset.language === state.language)?.focus();
}

languageTrigger.addEventListener("click", () => {
  if (languageOptions.hidden) openLanguageOptions();
  else closeLanguageOptions();
});
languageTrigger.addEventListener("keydown", (event) => {
  if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
    event.preventDefault();
    openLanguageOptions(true);
  }
});
languageOptionButtons.forEach((option, index) => {
  option.addEventListener("click", () => {
    state.language = option.dataset.language;
    localStorage.setItem(LANGUAGE_STORAGE_KEY, state.language);
    applyLanguage();
    closeLanguageOptions(true);
  });
  option.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeLanguageOptions(true);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      languageOptionButtons[(index + step + languageOptionButtons.length) % languageOptionButtons.length].focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      languageOptionButtons[event.key === "Home" ? 0 : languageOptionButtons.length - 1].focus();
    }
  });
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".language")) closeLanguageOptions();
});
$("method").addEventListener("change", () => { renderInfoTexts(); updateSolveButton(); });
$("scenario").addEventListener("change", renderInfoTexts);
$("month").addEventListener("change", renderInfoTexts);
$("solve").addEventListener("click", solve);

applyLanguage();
initMap();
connectToServer();
