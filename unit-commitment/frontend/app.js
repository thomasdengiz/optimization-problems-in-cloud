/**
 * Main script of the web page: map, form handling, job polling and result display.
 * Pure helper functions live in lib.js.
 */
import {
  buildDayProfile, buildSolveRequest, formatGap, formatNumber, friendlyErrorMessage, numberOfDays,
} from "./lib.js";

const API = window.APP_CONFIG.API_BASE_URL.replace(/\/$/, "");
const POLL_INTERVAL_MS = 1000;
const HEALTH_RETRY_MS = 3000;
const WAKE_UP_TIMEOUT_MS = 3 * 60 * 1000;   // how long to wait for a sleeping server
const MAX_POLL_FAILURES = 5;                 // consecutive failed status requests before giving up
const POLL_RETRY_MS = 2000;
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
  "August", "September", "Oktober", "November", "Dezember"];
// Only these countries can be selected on the map (the data exists only for Germany so far)
const SELECTABLE_COUNTRIES = { DE: "Deutschland" };

const $ = (id) => document.getElementById(id);
const state = { country: null, methods: {}, result: null, chart: null, running: false };

/** Show a message in the status line below the solve button. */
function setStatus(text) {
  $("status").textContent = text;
}

/** Enable the solve button only if a country is chosen, the chosen method exists and no job runs. */
function updateSolveButton() {
  const method = state.methods[$("method").value];
  $("solve").disabled = !(state.country && method && method.available && !state.running);
}

/** Pause for the given number of milliseconds. */
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Raised when the server no longer knows a job (it restarted and forgot all jobs). */
class JobLostError extends Error {}

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
  await waitForServer(() => {
    banner.textContent = "Server wird gestartet … das kann bei kostenlosem Hosting bis zu einer Minute dauern.";
  });
  banner.className = "banner ok";

  state.methods = await (await fetch(`${API}/methods`)).json();
  const select = $("method");
  for (const [key, info] of Object.entries(state.methods)) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = info.available ? info.label : `${info.label} (bald)`;
    select.appendChild(option);
  }
  select.value = "priority_list";
  onMethodChange();
}

/** Show the parameter fields that belong to the selected method. */
function onMethodChange() {
  const method = $("method").value;
  const info = state.methods[method];
  $("params-exact").hidden = method !== "exact";
  $("params-placeholder").hidden = !info || info.available;
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
    style: (feature) => (feature.properties.id in SELECTABLE_COUNTRIES ? selectableStyle : baseStyle),
    interactive: true,
    onEachFeature: (feature, featureLayer) => {
      const id = feature.properties.id;
      if (!(id in SELECTABLE_COUNTRIES)) {
        featureLayer.options.interactive = false; // grey countries ignore clicks
        return;
      }
      featureLayer.bindTooltip(SELECTABLE_COUNTRIES[id]);
      featureLayer.on("click", () => {
        if (selectedLayer) selectedLayer.setStyle(selectableStyle);
        selectedLayer = featureLayer;
        featureLayer.setStyle(selectedStyle);
        state.country = id;
        $("country-info").textContent = `Ausgewählt: ${SELECTABLE_COUNTRIES[id]}`;
        updateSolveButton();
      });
    },
  }).addTo(map);
  map.fitBounds(layer.getBounds());
}

/** Fill the month dropdown with the twelve month names. */
function initMonths() {
  MONTHS.forEach((name, index) => {
    const option = document.createElement("option");
    option.value = String(index + 1);
    option.textContent = name;
    $("month").appendChild(option);
  });
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
      if (!response.ok) throw new Error(`Server meldet Fehler (HTTP ${response.status})`);
      job = await response.json();
      failures = 0;
    } catch (error) {
      if (error instanceof JobLostError) throw error;
      failures += 1;
      console.warn(`Status request failed (${failures}/${MAX_POLL_FAILURES}):`, error);
      if (failures >= MAX_POLL_FAILURES) throw error;
      setStatus(`Server nicht erreichbar, neuer Versuch (${failures}/${MAX_POLL_FAILURES}) …`);
      await sleep(POLL_RETRY_MS);
      continue;
    }

    if (job.status === "done") return job.result;
    if (job.status === "failed") throw new Error(job.error);

    const seconds = Math.round((Date.now() - startedAt) / 1000);
    setStatus(`${job.status === "queued" ? "In der Warteschlange" : "Berechnung läuft"} … ${seconds} s`);
    await sleep(POLL_INTERVAL_MS);
  }
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

  try {
    // The server may have fallen asleep since the page was loaded: wake it up first
    setStatus("Verbinde mit dem Server …");
    await waitForServer(
      () => setStatus("Server wird aufgeweckt … das kann bis zu einer Minute dauern."),
      WAKE_UP_TIMEOUT_MS,
    );

    setStatus("Auftrag wird gesendet …");
    const response = await fetch(`${API}/solve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : `Anfrage abgelehnt (${response.status})`);
    }
    const { job_id: jobId } = await response.json();

    showResult(await waitForJob(jobId));
    setStatus("Fertig.");
  } catch (error) {
    console.error("Solve failed:", error);
    if (error instanceof JobLostError) {
      setStatus("Fehler: Der Auftrag ging verloren (der Server wurde vermutlich neu gestartet). Bitte erneut starten.");
    } else {
      setStatus(`Fehler: ${friendlyErrorMessage(error)}`);
    }
  } finally {
    state.running = false;
    updateSolveButton();
  }
}

/** Fill the result cards, the reasons list and the day selector, then draw the chart. */
function showResult(result) {
  state.result = result;
  $("no-result").hidden = true;
  $("result").hidden = false;

  const solverSeconds = result.solve_time_seconds ?? result.solve_time_ms / 1000;
  $("r-cost").textContent = `${formatNumber(result.total_cost_eur)} €`;
  $("r-solver-time").textContent = `${formatNumber(solverSeconds, 2)} s`;
  $("r-total-time").textContent = `${formatNumber(result.solve_time_ms / 1000, 2)} s`;
  $("r-vars").textContent =
    `${formatNumber(result.num_variables)} (davon ${formatNumber(result.num_binary_variables)} binär)`;
  $("r-gap").textContent = formatGap(result.mip_gap);

  const feasible = $("r-feasible");
  feasible.textContent = result.feasible ? "ja" : "nein";
  feasible.className = result.feasible ? "feasible-yes" : "feasible-no";

  const reasons = $("reasons");
  reasons.replaceChildren();
  for (const reason of result.infeasibility_reasons ?? []) {
    const item = document.createElement("li");
    item.textContent = reason; // textContent: server text is never interpreted as HTML
    reasons.appendChild(item);
  }

  const daySelect = $("day");
  daySelect.replaceChildren();
  for (let day = 0; day < numberOfDays(result.T); day += 1) {
    const option = document.createElement("option");
    option.value = String(day);
    option.textContent = `Tag ${day + 1}`;
    daySelect.appendChild(option);
  }
  drawChart();
}

/** Draw the stacked generation chart with the demand line for the selected day. */
function drawChart() {
  const profile = buildDayProfile(state.result, Number($("day").value));
  const datasets = profile.stacks.map((stack) => ({
    type: "bar",
    label: stack.label,
    data: stack.values,
    backgroundColor: stack.color,
    stack: "supply",
    barPercentage: 1,
    categoryPercentage: 1,
  }));
  datasets.push({
    type: "line",
    label: "load",
    data: profile.load,
    borderColor: "#000",
    backgroundColor: "#000",
    borderWidth: 2,
    pointRadius: 0,
  });

  if (state.chart) state.chart.destroy();
  state.chart = new Chart($("chart"), {
    data: { labels: profile.labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { stacked: true },
        y: { stacked: true, title: { display: true, text: "MW" } },
      },
    },
  });
}

$("method").addEventListener("change", onMethodChange);
$("solve").addEventListener("click", solve);
$("day").addEventListener("change", drawChart);

initMonths();
initMap();
connectToServer();
