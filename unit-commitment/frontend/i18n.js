/**
 * Texts of the web page in German and English.
 *
 * To change a text, edit it here. Short explanations below the selection fields use the keys
 * "info.<field>.<value>" (for example "info.method.exact"); if there is no entry for a value,
 * "info.<field>.default" is used. Placeholders like {month} are replaced by translate().
 */

export const LANGUAGES = ["de", "en"];

export const TRANSLATIONS = {
  de: {
    "page.title": "Unit Commitment Optimizer",
    "page.subtitle": "Kraftwerkseinsatzplanung: Methode, Land, Szenario und Zeitraum wählen und die Optimierung in der Cloud starten.",
    "language.label": "Sprache",
    "banner.starting": "Server wird gestartet … das kann bei kostenlosem Hosting bis zu einer Minute dauern.",

    "inputs.heading": "Eingaben",
    "country.label": "Land (Karte)",
    "country.hint": "Bitte Deutschland auf der Karte anklicken.",
    "country.selected": "Ausgewählt: {country}",
    "country.DE": "Deutschland",
    "method.label": "Optimierungsmethode",
    "method.soon": "(bald)",
    "method.exact": "Exakt (HiGHS/Pyomo)",
    "method.priority_list": "Prioritätslisten-Heuristik",
    "method.ea": "Evolutionärer Algorithmus",
    "method.pso": "Partikelschwarm-Optimierung",
    "method.custom": "Eigene Heuristik",
    "method.ml": "ML-basierte Heuristik",
    "timeLimit.label": "Zeitlimit des Solvers (Sekunden)",
    "timeLimit.hint": "Das Zeitlimit gilt nur für die reine Solver-Zeit (HiGHS). Modellaufbau und Datenverarbeitung kommen dazu. HiGHS prüft das Limit nur zwischen einzelnen Rechenschritten und kann es deshalb überschreiten.",
    "mipGap.label": "MIP-Gap (%)",
    "mipGap.hint": "Der Solver stoppt, sobald die Lücke zwischen bester Lösung und Schranke kleiner ist.",
    "scenario.label": "Szenario",
    "scenario.small": "klein",
    "scenario.medium": "mittel",
    "scenario.large": "groß",
    "horizon.label": "Zeitraum",
    "horizon.day": "Tag",
    "horizon.week": "Woche",
    "horizon.month": "Monat",
    "month.label": "Monat",
    "solve.button": "Optimierung starten",

    "info.method.exact": "Gemischt-ganzzahliges Modell, mit HiGHS über Pyomo gelöst. Liefert die kostenoptimale Lösung bzw. eine Lösung mit bekannter Lücke, braucht bei großen Fällen aber viel Zeit und Speicher.",
    "info.method.priority_list": "Schnelle Heuristik: Kraftwerke werden stundenweise nach steigenden Grenzkosten zugeschaltet. Keine Optimalitätsgarantie.",
    "info.method.default": "Diese Methode ist noch nicht implementiert.",
    "info.scenario.small": "Verkleinertes System (etwa 1/8 des deutschen Kraftwerksparks, 20 Anlagen).",
    "info.scenario.medium": "Mittleres System (etwa die Hälfte des deutschen Kraftwerksparks, 80 Anlagen).",
    "info.scenario.large": "Vollständiges System (160 Anlagen). Exakte Läufe über lange Zeiträume brauchen viel Rechenzeit und Speicher.",
    "info.month.default": "Last-, Wind- und Solardaten für {month} 2023 (ENTSO-E).",

    "result.heading": "Ergebnis",
    "result.none": "Noch kein Ergebnis.",
    "result.cost": "Gesamtkosten",
    "result.solverTime": "Solver-Zeit",
    "result.buildTime": "Modellaufbau",
    "result.totalTime": "Gesamtzeit",
    "result.variables": "Entscheidungsvariablen",
    "result.variablesValue": "{total} (davon {binary} binär)",
    "result.gap": "MIP-Gap",
    "result.feasible": "Zulässig (feasible)",
    "result.yes": "ja",
    "result.no": "nein",
    "result.limitReached": "Der Solver wurde am Zeitlimit gestoppt. Die Lösung ist die beste bis dahin gefundene; das MIP-Gap zeigt, wie weit sie höchstens vom Optimum entfernt ist.",
    "profile.heading": "Lastprofile",
    "profile.day": "Tag {n} – {date}",
    "profile.cost": "Kosten: {cost}",
    "profile.axis": "MW",

    "series.hard_coal": "Steinkohle",
    "series.lignite": "Braunkohle",
    "series.gas": "Gas",
    "series.biomass": "Biomasse",
    "series.wind": "Wind",
    "series.pv": "PV",
    "series.pump_turbining": "Pumpspeicher (Turbine)",
    "series.pump_charging": "Pumpspeicher (Laden)",
    "series.load": "Last",

    "status.connecting": "Verbinde mit dem Server …",
    "status.waking": "Server wird aufgeweckt … das kann bis zu einer Minute dauern.",
    "status.sending": "Auftrag wird gesendet …",
    "status.queued": "In der Warteschlange … {seconds} s",
    "status.running": "Berechnung läuft … {seconds} s",
    "status.retry": "Server nicht erreichbar, neuer Versuch ({n}/{max}) …",
    "status.done": "Fertig.",
    "status.error": "Fehler: {message}",

    "error.unreachable": "Server nicht erreichbar (möglicherweise Kaltstart oder Neustart). Bitte in einer Minute erneut versuchen. Details stehen in der Browser-Konsole (F12).",
    "error.lost": "Der Auftrag ging verloren (der Server wurde vermutlich neu gestartet). Bitte erneut starten.",
    "error.worker_killed": "Der Rechenprozess wurde vom Betriebssystem beendet, vermutlich wegen zu wenig Arbeitsspeicher auf dem Server. Bitte ein kleineres Szenario oder einen kürzeren Zeitraum wählen.",
    "error.no_solution": "Der Solver hat keine Lösung gefunden. Vielleicht ist das Zeitlimit zu kurz.",
    "error.memory_too_small": "Für diese Kombination braucht die exakte Methode etwa {needed} MB Arbeitsspeicher, der Server hat {limit} MB. Bitte ein kleineres Szenario, einen kürzeren Zeitraum oder die Heuristik wählen.",
    "error.rejected": "Anfrage abgelehnt (HTTP {status})",
    "error.http": "Server meldet Fehler (HTTP {status})",
  },

  en: {
    "page.title": "Unit Commitment Optimizer",
    "page.subtitle": "Power plant scheduling: choose method, country, scenario and period, then run the optimization in the cloud.",
    "language.label": "Language",
    "banner.starting": "Server is starting … with free hosting this can take up to a minute.",

    "inputs.heading": "Inputs",
    "country.label": "Country (map)",
    "country.hint": "Please click Germany on the map.",
    "country.selected": "Selected: {country}",
    "country.DE": "Germany",
    "method.label": "Optimization method",
    "method.soon": "(coming soon)",
    "method.exact": "Exact (HiGHS/Pyomo)",
    "method.priority_list": "Priority list heuristic",
    "method.ea": "Evolutionary algorithm",
    "method.pso": "Particle swarm optimization",
    "method.custom": "Custom heuristic",
    "method.ml": "ML-based heuristic",
    "timeLimit.label": "Solver time limit (seconds)",
    "timeLimit.hint": "The limit applies only to the pure solver time (HiGHS). Model building and data processing come on top. HiGHS checks the limit only between work steps, so it can overrun it.",
    "mipGap.label": "MIP gap (%)",
    "mipGap.hint": "The solver stops as soon as the gap between the best solution and the bound is smaller.",
    "scenario.label": "Scenario",
    "scenario.small": "small",
    "scenario.medium": "medium",
    "scenario.large": "large",
    "horizon.label": "Period",
    "horizon.day": "Day",
    "horizon.week": "Week",
    "horizon.month": "Month",
    "month.label": "Month",
    "solve.button": "Start optimization",

    "info.method.exact": "Mixed-integer model solved with HiGHS via Pyomo. Finds the cost-optimal solution, or one with a known gap, but needs a lot of time and memory for large cases.",
    "info.method.priority_list": "Fast heuristic: plants are switched on hour by hour in order of increasing marginal cost. No optimality guarantee.",
    "info.method.default": "This method is not implemented yet.",
    "info.scenario.small": "Scaled-down system (about 1/8 of the German power plant fleet, 20 plants).",
    "info.scenario.medium": "Medium system (about half of the German power plant fleet, 80 plants).",
    "info.scenario.large": "Full system (160 plants). Exact runs over long periods need a lot of computing time and memory.",
    "info.month.default": "Load, wind and solar data for {month} 2023 (ENTSO-E).",

    "result.heading": "Result",
    "result.none": "No result yet.",
    "result.cost": "Total cost",
    "result.solverTime": "Solver time",
    "result.buildTime": "Model building",
    "result.totalTime": "Total time",
    "result.variables": "Decision variables",
    "result.variablesValue": "{total} ({binary} binary)",
    "result.gap": "MIP gap",
    "result.feasible": "Feasible",
    "result.yes": "yes",
    "result.no": "no",
    "result.limitReached": "The solver was stopped at the time limit. The solution is the best one found until then; the MIP gap shows how far it can be from the optimum at most.",
    "profile.heading": "Load profiles",
    "profile.day": "Day {n} – {date}",
    "profile.cost": "Cost: {cost}",
    "profile.axis": "MW",

    "series.hard_coal": "Hard coal",
    "series.lignite": "Lignite",
    "series.gas": "Gas",
    "series.biomass": "Biomass",
    "series.wind": "Wind",
    "series.pv": "PV",
    "series.pump_turbining": "Pumped storage (turbine)",
    "series.pump_charging": "Pumped storage (pumping)",
    "series.load": "Load",

    "status.connecting": "Connecting to the server …",
    "status.waking": "Waking up the server … this can take up to a minute.",
    "status.sending": "Sending job …",
    "status.queued": "Queued … {seconds} s",
    "status.running": "Calculating … {seconds} s",
    "status.retry": "Server not reachable, retrying ({n}/{max}) …",
    "status.done": "Done.",
    "status.error": "Error: {message}",

    "error.unreachable": "Server not reachable (possibly a cold start or restart). Please try again in a minute. Details are in the browser console (F12).",
    "error.lost": "The job was lost (the server probably restarted). Please start it again.",
    "error.worker_killed": "The calculation process was killed by the operating system, probably because the server ran out of memory. Please choose a smaller scenario or a shorter period.",
    "error.no_solution": "The solver found no solution. The time limit may be too short.",
    "error.memory_too_small": "The exact method needs about {needed} MB of memory for this combination, the server has {limit} MB. Please choose a smaller scenario, a shorter period or the heuristic.",
    "error.rejected": "Request rejected (HTTP {status})",
    "error.http": "Server reports an error (HTTP {status})",
  },
};

export const MONTH_NAMES = {
  de: ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
    "August", "September", "Oktober", "November", "Dezember"],
  en: ["January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"],
};

/** Locale used for number formatting in each language. */
export const LOCALES = { de: "de-DE", en: "en-US" };

/** Pick the start language: the saved choice, else the browser language (German or English). */
export function detectLanguage(savedLanguage, browserLanguage) {
  if (LANGUAGES.includes(savedLanguage)) return savedLanguage;
  return (browserLanguage || "").toLowerCase().startsWith("de") ? "de" : "en";
}

/** Translate a key and replace {placeholders}; unknown keys are returned unchanged. */
export function translate(language, key, params = {}) {
  const text = TRANSLATIONS[language][key];
  if (text === undefined) return key;
  return text.replace(/\{(\w+)\}/g, (_, name) => (name in params ? String(params[name]) : `{${name}}`));
}

/** Text for the short explanation below a field: the specific entry or the field's default. */
export function infoText(language, field, value, params = {}) {
  const specific = `info.${field}.${value}`;
  const key = specific in TRANSLATIONS[language] ? specific : `info.${field}.default`;
  return translate(language, key, params);
}
