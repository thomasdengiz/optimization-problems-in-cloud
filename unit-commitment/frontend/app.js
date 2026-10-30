/**
 * Main script of the web page: map, form handling, job polling, result display and language.
 * Pure helper functions live in lib.js, all texts in i18n.js.
 */
import {
  buildDayProfiles, buildSolveRequest, formatGap, formatNumber,
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

const $ = (id) => document.getElementById(id);
const state = {
  language: detectLanguage(localStorage.getItem(LANGUAGE_STORAGE_KEY), navigator.language),
  country: null,
  methods: {},
  result: null,
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

    const box = document.createElement("div");
    box.className = "chart-box";
    const canvas = document.createElement("canvas");
    box.appendChild(canvas);
    section.appendChild(box);
    container.appendChild(section);

    state.charts.push(drawChart(canvas, profile));
  });
}

/** Draw the stacked generation chart with the demand line for one day. */
function drawChart(canvas, profile) {
  const datasets = profile.stacks.map((stack) => ({
    type: "bar",
    label: t(`series.${stack.key}`),
    data: stack.values,
    backgroundColor: stack.color,
    stack: "supply",
    barPercentage: 1,
    categoryPercentage: 1,
  }));
  datasets.push({
    type: "line",
    label: t("series.load"),
    data: profile.load,
    borderColor: "#000",
    backgroundColor: "#000",
    borderWidth: 2,
    pointRadius: 0,
  });

  return new Chart(canvas, {
    data: { labels: profile.labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { stacked: true },
        y: { stacked: true, title: { display: true, text: t("profile.axis") } },
      },
    },
  });
}

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
