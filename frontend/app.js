/**
 * HETA Smart Filter Monitoring – Frontend-Applikation
 * Pollt die REST-API, steuert Onboarding-Assistent und passwortgeschützten Einstellungsbereich.
 */

const API_BASE = "";
const POLL_INTERVAL_MS = 1500;

// Lernrelevante Parameter – Änderung löst Reset der Lernphasen aus
const LEARNING_SENSITIVE = ["dp_limit_bar", "dp_clean_bar", "flow_max_l_min", "pressure_range_bar"];

// Chart.js Instanzen
const MAX_CHART_POINTS = 120;
let charts = {};

// Session-Token für Einstellungsbereich (wird im sessionStorage gehalten)
const TOKEN_KEY = "heta_settings_token";

// ============================================================
// Init
// ============================================================

document.addEventListener("DOMContentLoaded", async () => {
  initCharts();
  await checkOnboarding();
  startPolling();
  loadSettingsIntoForm();

  // Betriebsart-Karten koppeln
  document.querySelectorAll(".mode-card").forEach(card => {
    card.addEventListener("click", () => {
      document.querySelectorAll(".mode-card").forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");
      card.querySelector("input").checked = true;
    });
  });
});

// ============================================================
// Onboarding
// ============================================================

let _wizardStep = 1;
const WIZARD_TOTAL = 6;

async function checkOnboarding() {
  try {
    const data = await apiFetch("/api/onboarding/status");
    if (data && !data.onboarding_complete) {
      showOnboarding();
    }
  } catch (e) {
    console.warn("Onboarding-Status konnte nicht abgerufen werden.", e);
  }
}

function showOnboarding() {
  document.getElementById("onboarding-overlay").classList.remove("hidden");
  _wizardStep = 1;
  renderWizardStep();
}

function renderWizardStep() {
  // Alle Schritte ausblenden, aktuellen einblenden
  document.querySelectorAll(".wizard-step").forEach(s => s.classList.add("hidden"));
  const current = document.querySelector(`.wizard-step[data-step="${_wizardStep}"]`);
  if (current) current.classList.remove("hidden");

  // Schritt-Punkte rendern
  const dotsContainer = document.getElementById("wizard-steps");
  dotsContainer.innerHTML = "";
  for (let i = 1; i <= WIZARD_TOTAL; i++) {
    const dot = document.createElement("div");
    dot.className = "wizard-dot" + (i === _wizardStep ? " active" : i < _wizardStep ? " done" : "");
    dotsContainer.appendChild(dot);
  }

  // Schritt-Label
  document.getElementById("wizard-step-label").textContent = `Schritt ${_wizardStep} von ${WIZARD_TOTAL}`;

  // Zurück-Button
  document.getElementById("wizard-back").style.display = _wizardStep > 1 ? "inline-flex" : "none";

  // Weiter-Button Text
  const nextBtn = document.getElementById("wizard-next");
  nextBtn.textContent = _wizardStep === WIZARD_TOTAL ? "Einrichtung abschließen" : "Weiter";

  // Schritt 6: Zusammenfassung befüllen
  if (_wizardStep === WIZARD_TOTAL) buildSummary();
}

function wizardNext() {
  if (!validateWizardStep(_wizardStep)) return;
  if (_wizardStep === WIZARD_TOTAL) {
    completeOnboarding();
    return;
  }
  _wizardStep++;
  renderWizardStep();
}

function wizardBack() {
  if (_wizardStep > 1) { _wizardStep--; renderWizardStep(); }
}

function validateWizardStep(step) {
  if (step === 5) {
    const pw  = document.getElementById("ob-password").value;
    const pw2 = document.getElementById("ob-password-confirm").value;
    if (pw.length < 4) { showMsg("ob-pw-msg", "Passwort muss mindestens 4 Zeichen haben.", true); return false; }
    if (pw !== pw2)     { showMsg("ob-pw-msg", "Passwörter stimmen nicht überein.", true); return false; }
    showMsg("ob-pw-msg", "", false);
  }
  return true;
}

function buildSummary() {
  const mode = document.querySelector("input[name='op-mode']:checked")?.value === "hardware"
    ? "Hardwaremodus" : "Simulationsmodus";
  const lines = [
    ["Betriebsart", mode],
    ["dp-Grenzwert", `${document.getElementById("ob-dp-limit").value} bar`],
    ["Sauberwiderstand", `${document.getElementById("ob-dp-clean").value} bar`],
    ["Max. Durchfluss", `${document.getElementById("ob-flow-max").value} l/min`],
    ["Druckbereich", `${document.getElementById("ob-pressure-range").value} bar`],
    ["Temperatur", `${document.getElementById("ob-temp-min").value} – ${document.getElementById("ob-temp-max").value} °C`],
    ["Passwort", "••••••"],
  ];
  document.getElementById("ob-summary").innerHTML = lines
    .map(([k, v]) => `<strong>${k}:</strong> ${v}<br>`)
    .join("");
}

async function completeOnboarding() {
  const simMode = document.querySelector("input[name='op-mode']:checked")?.value !== "hardware";
  const payload = {
    simulation_mode:    simMode,
    dp_limit_bar:       parseFloat(document.getElementById("ob-dp-limit").value),
    dp_clean_bar:       parseFloat(document.getElementById("ob-dp-clean").value),
    flow_max_l_min:     parseFloat(document.getElementById("ob-flow-max").value),
    pressure_range_bar: parseFloat(document.getElementById("ob-pressure-range").value),
    temperature_min_c:  parseFloat(document.getElementById("ob-temp-min").value),
    temperature_max_c:  parseFloat(document.getElementById("ob-temp-max").value),
    password:           document.getElementById("ob-password").value,
  };

  const result = await apiFetch("/api/onboarding/complete", "POST", payload);
  if (result?.success) {
    document.getElementById("onboarding-overlay").classList.add("hidden");
    window._settings = { ...window._settings, ...payload };
    showMsg("heta-msg", "Einrichtung abgeschlossen. System startet.", false);
    setTimeout(() => location.reload(), 1500);
  } else {
    showMsg("ob-final-msg", result?.message ?? "Fehler beim Speichern.", true);
  }
}

// ============================================================
// Einstellungsbereich (passwortgeschützt)
// ============================================================

function openSettings() {
  const token = sessionStorage.getItem(TOKEN_KEY);
  document.getElementById("settings-overlay").classList.remove("hidden");
  if (token) {
    // Prüfen ob Token noch gültig
    apiFetch(`/api/settings/auth-check?token=${token}`).then(r => {
      if (r?.authenticated) showSettingsForm();
      else                   showSettingsLogin();
    });
  } else {
    showSettingsLogin();
  }
}

function closeSettings() {
  document.getElementById("settings-overlay").classList.add("hidden");
  showMsg("settings-login-msg", "", false);
  showMsg("settings-save-msg", "", false);
}

function showSettingsLogin() {
  document.getElementById("settings-login-area").classList.remove("hidden");
  document.getElementById("settings-form-area").classList.add("hidden");
  setTimeout(() => document.getElementById("settings-pw-input")?.focus(), 100);
}

function showSettingsForm() {
  document.getElementById("settings-login-area").classList.add("hidden");
  document.getElementById("settings-form-area").classList.remove("hidden");
  loadSettingsIntoForm();
  watchSettingsChanges();
}

async function settingsLogin() {
  const pw = document.getElementById("settings-pw-input").value;
  const result = await apiFetch("/api/settings/login", "POST", { password: pw });
  if (result?.success) {
    sessionStorage.setItem(TOKEN_KEY, result.token);
    document.getElementById("settings-pw-input").value = "";
    showSettingsForm();
  } else {
    showMsg("settings-login-msg", result?.message ?? "Fehler.", true);
  }
}

async function settingsLogout() {
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (token) await apiFetch("/api/settings/logout", "POST", { token });
  sessionStorage.removeItem(TOKEN_KEY);
  showSettingsLogin();
}

async function loadSettingsIntoForm() {
  try {
    const s = await apiFetch("/api/settings");
    if (!s) return;
    window._settings = s;
    setInputVal("s-dp-limit",       s.dp_limit_bar);
    setInputVal("s-dp-clean",        s.dp_clean_bar);
    setInputVal("s-flow-max",        s.flow_max_l_min);
    setInputVal("s-pressure-range",  s.pressure_range_bar);
    setInputVal("s-temp-min",        s.temperature_min_c);
    setInputVal("s-temp-max",        s.temperature_max_c);
    setInputVal("s-interval",        s.sampling_interval_seconds);
    const cb = document.getElementById("s-simulation-mode");
    if (cb) cb.checked = !!s.simulation_mode;
    setText("dp-limit-hint", `Limit: ${Number(s.dp_limit_bar).toFixed(2)} bar`);
  } catch (e) { console.warn("Einstellungen konnten nicht geladen werden.", e); }
}

function watchSettingsChanges() {
  const warnEl = document.getElementById("settings-reset-warning");
  const sensitiveIds = {
    "s-dp-limit": "dp_limit_bar",
    "s-dp-clean": "dp_clean_bar",
    "s-flow-max": "flow_max_l_min",
    "s-pressure-range": "pressure_range_bar",
  };
  function check() {
    const s = window._settings || {};
    const changed = Object.entries(sensitiveIds).some(([id, key]) => {
      const el = document.getElementById(id);
      return el && parseFloat(el.value) !== parseFloat(s[key]);
    });
    warnEl.classList.toggle("hidden", !changed);
  }
  Object.keys(sensitiveIds).forEach(id => {
    document.getElementById(id)?.addEventListener("input", check);
  });
}

async function saveSettings() {
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (!token) { showMsg("settings-save-msg", "Sitzung abgelaufen. Bitte neu anmelden.", true); showSettingsLogin(); return; }

  const newPw    = document.getElementById("s-new-pw").value;
  const oldPw    = document.getElementById("s-old-pw").value;

  const payload = {
    dp_limit_bar:              parseFloat(document.getElementById("s-dp-limit").value),
    dp_clean_bar:              parseFloat(document.getElementById("s-dp-clean").value),
    flow_max_l_min:            parseFloat(document.getElementById("s-flow-max").value),
    pressure_range_bar:        parseFloat(document.getElementById("s-pressure-range").value),
    temperature_min_c:         parseFloat(document.getElementById("s-temp-min").value),
    temperature_max_c:         parseFloat(document.getElementById("s-temp-max").value),
    sampling_interval_seconds: parseInt(document.getElementById("s-interval").value, 10),
    simulation_mode:           document.getElementById("s-simulation-mode").checked,
  };
  if (newPw) { payload.new_password = newPw; payload.old_password = oldPw; }

  const result = await apiFetchAuth("/api/settings", "POST", payload, token);
  if (result?.success) {
    window._settings = result.settings;
    document.getElementById("settings-reset-warning").classList.add("hidden");
    document.getElementById("s-new-pw").value = "";
    document.getElementById("s-old-pw").value = "";
    if (result.learning_reset) clearCharts();
    showMsg("settings-save-msg", result.message, false);
  } else if (result === null) {
    sessionStorage.removeItem(TOKEN_KEY);
    showSettingsLogin();
  } else {
    showMsg("settings-save-msg", result?.message ?? "Fehler.", true);
  }
}

// ============================================================
// Polling
// ============================================================

function startPolling() {
  fetchStatus();
  setInterval(fetchStatus, POLL_INTERVAL_MS);
}

async function fetchStatus() {
  try {
    const resp = await fetch(`${API_BASE}/api/status`);
    if (!resp.ok) return;
    const data = await resp.json();
    updateDashboard(data);
  } catch (e) {
    console.warn("Polling-Fehler:", e);
  }
}

// ============================================================
// Dashboard aktualisieren
// ============================================================

function updateDashboard(d) {
  setText("val-p1",    fmt(d.p1_bar, 3));
  setText("val-p2",    fmt(d.p2_bar, 3));
  setText("val-dp",    fmt(d.dp_bar, 3));
  setText("val-flow",  fmt(d.flow_l_min, 1));
  setText("val-temp",  fmt(d.temperature_c, 1));
  setText("val-reff",  fmt(d.r_eff, 5));

  // Beladungsgrad – nur bei aktivem HETA-Code anzeigen
  updateFilterHealth(d.filter_health_percent, d.show_filter_health);

  // Reststandzeit – Modus-Beschriftung
  setText("val-remaining", d.remaining_display ?? "–");
  updateRemainingMode(d.prediction_mode, d.learned_cycles, d.required_cycles);

  // HETA-Code
  setText("val-heta-code", d.heta_code || "(kein Code)");
  setText("val-heta-status", d.heta_activated ? "Aktiviert" : "nicht aktiviert");
  setText("val-service-msg", d.service_message || "–");
  setText("val-service-prio", d.service_priority || "–");
  styleServicePriority(d.service_priority);

  const banner = document.getElementById("filter-change-banner");
  if (banner) banner.classList.toggle("hidden", !d.awaiting_confirmation);

  updateStatusBadge(d.filter_status);
  updateSensorBadge(d.sensor_mode);
  setText("last-update", d.last_update ? new Date(d.last_update).toLocaleTimeString("de-DE") : "–");

  setText("info-sensor-mode", d.sensor_mode ?? "–");
  setText("info-cycles", d.learned_cycles ?? "–");
  setText("info-profile", d.profile_status ?? "–");
  setText("info-anomaly", d.anomaly_active
    ? `Ja (${fmt(d.anomaly_percent, 1)} % Abweichung)` : "Nein");
  setText("info-pred-mode", d.prediction_mode ?? "–");
  setText("info-sensor-err", d.sensor_error ? "JA" : "Nein");

  const dpLimit = window._settings?.dp_limit_bar ?? 2.5;
  setText("dp-limit-hint", `Limit: ${Number(dpLimit).toFixed(2)} bar`);
  styleCardByStatus("card-dp", d.filter_status);
  pushChartData(d);
}

// ============================================================
// Charts
// ============================================================

function initCharts() {
  const opts = (label, color) => ({
    type: "line",
    data: { labels: [], datasets: [{ label, data: [], borderColor: color,
      backgroundColor: color + "22", borderWidth: 2, pointRadius: 0, fill: true, tension: 0.3 }] },
    options: { animation: false, responsive: true, maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: { x: { display: false }, y: { ticks: { font: { size: 10 } } } } }
  });

  charts.dp        = new Chart(document.getElementById("chart-dp"),        opts("Δp [bar]", "#0077cc"));
  charts.flow      = new Chart(document.getElementById("chart-flow"),      opts("Q [l/min]", "#1a9e3c"));
  charts.reff      = new Chart(document.getElementById("chart-reff"),      opts("R_eff", "#7b1fa2"));
  charts.remaining = new Chart(document.getElementById("chart-remaining"), opts("Rest [min]", "#d4820a"));
}

function pushChartData(d) {
  const label  = new Date().toLocaleTimeString("de-DE");
  const remMin = d.remaining_seconds != null ? d.remaining_seconds / 60 : null;
  pushPoint(charts.dp,        label, d.dp_bar);
  pushPoint(charts.flow,      label, d.flow_l_min);
  pushPoint(charts.reff,      label, d.r_eff);
  pushPoint(charts.remaining, label, remMin);
}

function pushPoint(chart, label, value) {
  if (!chart) return;
  chart.data.labels.push(label);
  chart.data.datasets[0].data.push(value);
  if (chart.data.labels.length > MAX_CHART_POINTS) {
    chart.data.labels.shift();
    chart.data.datasets[0].data.shift();
  }
  chart.update("none");
}

// ============================================================
// Steuerungs-Buttons
// ============================================================

async function startSimulation() {
  await apiFetch("/api/simulation/start", "POST");
  showMsg("heta-msg", "Simulation gestartet.", false);
}

async function stopSimulation() {
  await apiFetch("/api/simulation/stop", "POST");
  showMsg("heta-msg", "Simulation gestoppt.", false);
}

async function resetSystem() {
  if (!confirm("System wirklich zurücksetzen?")) return;
  await apiFetch("/api/simulation/reset", "POST");
  clearCharts();
  showMsg("heta-msg", "System zurückgesetzt.", false);
}

async function activateHetaCode() {
  const code = document.getElementById("input-heta-code").value.trim();
  const pin  = document.getElementById("input-pin").value.trim();
  if (!code || !pin) { showMsg("heta-msg", "HETA-Code und PIN eingeben.", true); return; }
  const result = await apiFetch("/api/heta/activate", "POST", { heta_code: code, pin });
  if (result?.valid) showMsg("heta-msg", `Aktivierung erfolgreich: ${result.heta_code}`, false);
  else showMsg("heta-msg", result?.message ?? "Fehler.", true);
}

async function showDemo() {
  const code = document.getElementById("input-heta-code").value.trim();
  if (!code) { showMsg("heta-msg", "Zuerst HETA-Code eingeben.", true); return; }
  const result = await apiFetch(`/api/heta/demo?heta_code=${encodeURIComponent(code)}`, "GET");
  if (result?.valid) {
    showMsg("heta-msg", `Demo-PIN für ${result.heta_code}: ${result.activation_code}`, false);
    document.getElementById("input-pin").value = result.activation_code;
  } else {
    showMsg("heta-msg", result?.message ?? "Ungültiges Format.", true);
  }
}

async function confirmFilterChange() {
  if (!confirm("Filterwechsel wirklich bestätigen? Der Filter wurde getauscht?")) return;
  const result = await apiFetch("/api/filter/confirm-change", "POST");
  if (result?.success) { showMsg("heta-msg", result.message, false); clearCharts(); }
}

async function exportCSV() {
  window.open(`${API_BASE}/api/export/csv/download`, "_blank");
}

async function generateServiceReport() {
  const result = await apiFetch("/api/service/request", "POST");
  if (result?.report_text) {
    document.getElementById("service-report-text").textContent = result.report_text;
    document.getElementById("service-section").classList.remove("hidden");
    document.getElementById("service-section").scrollIntoView({ behavior: "smooth" });
  }
}

function hideService() {
  document.getElementById("service-section").classList.add("hidden");
}

// ============================================================
// Hilfsfunktionen
// ============================================================

function fmt(val, decimals) {
  if (val == null || isNaN(val)) return "–";
  return Number(val).toFixed(decimals);
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setInputVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function showMsg(id, text, isError) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = "msg" + (isError ? " error" : "");
}

function updateStatusBadge(status) {
  const el = document.getElementById("status-badge");
  if (!el) return;
  const map = {
    OK:                  ["badge-ok",      "OK"],
    BEOBACHTEN:          ["badge-observe", "BEOBACHTEN"],
    WECHSEL:             ["badge-alert",   "WECHSEL"],
    WECHSEL_BESTAETIGEN: ["badge-alert",   "WECHSEL!"],
    WARNUNG:             ["badge-warn",    "WARNUNG"],
    FEHLER:              ["badge-error",   "FEHLER"],
  };
  const [cls, label] = map[status] ?? ["badge-warn", status ?? "–"];
  el.className = `badge ${cls}`;
  el.textContent = label;
}

function updateSensorBadge(mode) {
  const el = document.getElementById("sensor-mode-badge");
  if (!el) return;
  if (mode === "hardware") { el.className = "badge badge-hw"; el.textContent = "HW"; }
  else                     { el.className = "badge badge-sim"; el.textContent = "SIM"; }
}

function styleCardByStatus(cardId, status) {
  const el = document.getElementById(cardId);
  if (!el) return;
  el.className = "card card-highlight";
  if (status === "BEOBACHTEN") el.classList.add("status-observe");
  else if (["WECHSEL","WECHSEL_BESTAETIGEN"].includes(status)) el.classList.add("status-alert");
  else if (status === "WARNUNG") el.classList.add("status-warn");
  else el.classList.add("status-ok");
}

function styleServicePriority(prio) {
  const el = document.getElementById("val-service-prio");
  if (!el) return;
  el.style.color = prio === "HOCH" ? "var(--alert-red)"
    : prio === "MITTEL" ? "var(--warn-yellow)" : "var(--ok-green)";
}

function healthColor(pct) {
  if (pct > 50) return "var(--ok-green)";
  if (pct > 20) return "var(--warn-yellow)";
  return "var(--alert-red)";
}

function updateFilterHealth(healthPct, show) {
  const card = document.getElementById("card-health");
  const bar  = document.getElementById("health-bar");
  if (show) {
    const h = healthPct ?? 100;
    setText("val-health", fmt(h, 1));
    if (bar) { bar.style.width = `${Math.max(0, Math.min(100, h))}%`; bar.style.background = healthColor(h); }
    if (card) { card.classList.remove("card-health-hidden"); setText("card-health-note", ""); }
  } else {
    setText("val-health", "–");
    if (bar) bar.style.width = "0%";
    if (card) card.classList.add("card-health-hidden");
    setText("card-health-note", "HETA-Code erforderlich");
  }
}

function updateRemainingMode(mode, learnedCycles, requiredCycles) {
  const el = document.getElementById("remaining-mode");
  if (!el) return;
  const req = requiredCycles ?? 3;
  if (mode === "HETA_VALIDIERT") {
    el.textContent = "HETA-Validiert";
    el.style.color = "var(--ok-green)";
  } else if (mode === "HETA_LERNEND") {
    el.textContent = `HETA-Lernend (${learnedCycles ?? 0}/${req} Zyklen)`;
    el.style.color = "var(--warn-yellow)";
  } else {
    el.textContent = "Basis";
    el.style.color = "var(--text-muted)";
  }
}

function clearCharts() {
  Object.values(charts).forEach(c => {
    if (!c) return;
    c.data.labels = [];
    c.data.datasets[0].data = [];
    c.update("none");
  });
}

async function apiFetch(path, method = "GET", body = null) {
  try {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(`${API_BASE}${path}`, opts);
    return await resp.json();
  } catch (e) {
    console.error("API-Fehler:", e);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Software-Update via Git Pull
// ---------------------------------------------------------------------------

async function updateFromGit() {
  const token = sessionStorage.getItem("settingsToken");
  if (!token) return;

  const btn = document.getElementById("btn-git-update");
  const out  = document.getElementById("update-output");

  btn.disabled = true;
  btn.textContent = "⟳ Verbinde mit GitHub…";
  out.className   = "update-output";
  out.textContent = "git pull läuft…";

  const result = await apiFetchAuth("/api/update/pull", "POST", {}, token);

  if (!result) {
    btn.disabled    = false;
    btn.textContent = "↓ Update von GitHub holen";
    out.textContent = "Fehler: Sitzung abgelaufen. Bitte neu anmelden.";
    return;
  }

  out.textContent = result.output || "(keine Ausgabe)";

  if (result.restarting) {
    btn.textContent  = "⟳ Neustart läuft…";
    out.textContent += "\n\n✓ Änderungen geladen. Dienst wird neu gestartet…";
    // Warte auf Neustart, dann Seite neu laden
    setTimeout(() => {
      out.textContent += "\nSeite wird in 5 Sekunden neu geladen…";
      setTimeout(() => location.reload(), 5000);
    }, 3000);
  } else {
    btn.disabled    = false;
    btn.textContent = "↓ Update von GitHub holen";
    if (result.success && !result.changed) {
      out.textContent = "✓ Bereits auf dem aktuellen Stand.\n\n" + result.output;
    } else if (!result.success) {
      out.textContent = "✗ Fehler beim Update:\n\n" + result.output;
    }
  }
}


async function apiFetchAuth(path, method, body, token) {
  try {
    const opts = {
      method,
      headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(`${API_BASE}${path}`, opts);
    if (resp.status === 401) return null;  // Token abgelaufen
    return await resp.json();
  } catch (e) {
    console.error("Auth-API-Fehler:", e);
    return null;
  }
}
