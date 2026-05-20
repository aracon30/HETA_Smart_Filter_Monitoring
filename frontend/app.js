/**
 * HETA Smart Filter Monitoring – Frontend-Applikation
 * Pollt die REST-API, steuert Onboarding-Assistent und passwortgeschützten Einstellungsbereich.
 */

const API_BASE = "";
const POLL_INTERVAL_MS = 1500;

// Lernrelevante Parameter – Änderung löst Reset der Lernphasen aus
const LEARNING_SENSITIVE = ["dp_limit_bar", "flow_max_l_min", "pressure_range_bar"];

// Chart.js Instanzen
const MAX_CHART_POINTS = 300;
let combinedChart = null;
let cycleModalChart = null;

// Cache für Referenzkurve; wird beim Zykluswechsel invalidiert
let _refCurveCache = null;
let _refCurveCacheCode = null;

// Zyklusverfolgung für das Referenz-Overlay im Live-Chart
let _knownCycleStart = null;

// Session-Token für Einstellungsbereich (wird im sessionStorage gehalten)
const TOKEN_KEY = "heta_settings_token";

// Aktuelle Toleranzwerte (als Fraktion; werden nach dem Laden der Einstellungen gesetzt)
let _tolDp   = 0.25;
let _tolReff = 0.25;
let _tolFlow = 0.25;
let _tolTempC = 10.0;

// Tab-Navigation
let _activeTab = "dashboard";
let _cyclesPollTick = 0;
let _prevAwaiting = false;

// ============================================================
// Init
// ============================================================

document.addEventListener("DOMContentLoaded", async () => {
  initCharts();
  initTabs();
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
  // Initiale Auswahl visuell markieren (checked-Attribut → selected-Klasse)
  const preselected = document.querySelector(".mode-card input:checked")?.closest(".mode-card");
  if (preselected) preselected.classList.add("selected");
});

// ============================================================
// Tab-Navigation
// ============================================================

function initTabs() {
  switchTab("dashboard");
}

function switchTab(tabName) {
  _activeTab = tabName;
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach(panel => {
    panel.classList.toggle("hidden", panel.id !== `tab-panel-${tabName}`);
  });
  if (tabName === "cycles") loadCyclesOverview();
}

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
    ["Grenzwert Filterwechsel (Δp)", `${document.getElementById("ob-dp-limit").value} bar`],
    ["Druckabfall sauberes Filter", "Wird automatisch aus Lernzyklen berechnet"],
    ["Maximaler Volumenstrom", `${document.getElementById("ob-flow-max").value} l/min`],
    ["Messbereich Drucksensoren", `${document.getElementById("ob-pressure-range").value} bar`],
    ["Messbereich Temperatur", `${document.getElementById("ob-temp-min").value} – ${document.getElementById("ob-temp-max").value} °C`],
    ["Toleranz Δp / Widerstandsfaktor", `±${document.getElementById("ob-tol-dp").value} % / ±${document.getElementById("ob-tol-reff").value} %`],
    ["Toleranz Volumenstrom / Temperatur", `±${document.getElementById("ob-tol-flow").value} % / ±${document.getElementById("ob-tol-temp").value} °C`],
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
    flow_max_l_min:     parseFloat(document.getElementById("ob-flow-max").value),
    pressure_range_bar: parseFloat(document.getElementById("ob-pressure-range").value),
    temperature_min_c:  parseFloat(document.getElementById("ob-temp-min").value),
    temperature_max_c:  parseFloat(document.getElementById("ob-temp-max").value),
    tolerance_dp_pct:   parseFloat(document.getElementById("ob-tol-dp").value)   / 100,
    tolerance_reff_pct: parseFloat(document.getElementById("ob-tol-reff").value) / 100,
    tolerance_flow_pct: parseFloat(document.getElementById("ob-tol-flow").value) / 100,
    tolerance_temp_c:   parseFloat(document.getElementById("ob-tol-temp").value),
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
  hideFactoryResetConfirm();
}

function showFactoryResetConfirm() {
  document.getElementById("factory-reset-confirm").classList.remove("hidden");
  document.getElementById("factory-reset-confirm-text").value = "";
  document.getElementById("factory-reset-pw").value = "";
  showMsg("factory-reset-msg", "", false);
  document.getElementById("factory-reset-confirm-text").focus();
}

function hideFactoryResetConfirm() {
  document.getElementById("factory-reset-confirm").classList.add("hidden");
  document.getElementById("factory-reset-confirm-text").value = "";
  document.getElementById("factory-reset-pw").value = "";
  showMsg("factory-reset-msg", "", false);
}

async function confirmFactoryReset() {
  const confirmText = document.getElementById("factory-reset-confirm-text").value.trim();
  if (confirmText !== "RESET") {
    showMsg("factory-reset-msg", 'Bitte genau "RESET" eingeben.', true);
    return;
  }
  const password = document.getElementById("factory-reset-pw").value;
  if (!password) {
    showMsg("factory-reset-msg", "Passwort eingeben.", true);
    return;
  }
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (!token) { showSettingsLogin(); return; }

  showMsg("factory-reset-msg", "Wird zurückgesetzt …", false);
  const result = await apiFetchAuth("/api/factory-reset", "POST", { password }, token);
  if (result?.success) {
    showMsg("factory-reset-msg", result.message, false);
    sessionStorage.removeItem(TOKEN_KEY);
    setTimeout(() => location.reload(), 1800);
  } else if (result === null) {
    sessionStorage.removeItem(TOKEN_KEY);
    showSettingsLogin();
  } else {
    showMsg("factory-reset-msg", result?.message ?? "Fehler.", true);
  }
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
    setInputVal("s-flow-max",        s.flow_max_l_min);
    setInputVal("s-pressure-range",  s.pressure_range_bar);
    setInputVal("s-temp-min",        s.temperature_min_c);
    setInputVal("s-temp-max",        s.temperature_max_c);
    setInputVal("s-interval",        s.sampling_interval_seconds);
    setInputVal("s-tol-dp",   Math.round((s.tolerance_dp_pct   ?? 0.25) * 100));
    setInputVal("s-tol-reff", Math.round((s.tolerance_reff_pct ?? 0.25) * 100));
    setInputVal("s-tol-flow", Math.round((s.tolerance_flow_pct ?? 0.25) * 100));
    setInputVal("s-tol-temp", s.tolerance_temp_c ?? 10);
    _tolDp    = s.tolerance_dp_pct   ?? 0.25;
    _tolReff  = s.tolerance_reff_pct ?? 0.25;
    _tolFlow  = s.tolerance_flow_pct ?? 0.25;
    _tolTempC = s.tolerance_temp_c   ?? 10.0;
    const cb = document.getElementById("s-simulation-mode");
    if (cb) {
      cb.checked = !!s.simulation_mode;
      const warnEl = document.getElementById("sim-mode-warning");
      if (warnEl) warnEl.classList.toggle("hidden", !s.simulation_mode);
    }
    setText("dp-limit-hint", `Limit: ${Number(s.dp_limit_bar).toFixed(2)} bar`);
    updateChartDpLimit(s.dp_limit_bar ?? 2.5);
    // p1-Regler-Maximum synchronisieren
    const slP1 = document.getElementById("sl-p1");
    if (slP1) slP1.max = s.pressure_range_bar ?? 10;

    // dp_clean aus Profil laden (wird aus Lernzyklen berechnet)
    const hetaCode = window._lastStatus?.heta_code;
    if (hetaCode) {
      try {
        const profile = await apiFetch(`/api/profile?heta_code=${encodeURIComponent(hetaCode)}`);
        const dpCleanEl = document.getElementById("s-dp-clean-display");
        if (dpCleanEl) {
          dpCleanEl.textContent = (profile?.reference_dp_clean > 0)
            ? fmt(profile.reference_dp_clean, 3)
            : "–";
        }
      } catch (_) { /* Profil noch nicht vorhanden */ }
    }
  } catch (e) { console.warn("Einstellungen konnten nicht geladen werden.", e); }
}

function watchSettingsChanges() {
  const warnEl = document.getElementById("settings-reset-warning");
  const sensitiveIds = {
    "s-dp-limit": "dp_limit_bar",
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
    flow_max_l_min:            parseFloat(document.getElementById("s-flow-max").value),
    pressure_range_bar:        parseFloat(document.getElementById("s-pressure-range").value),
    temperature_min_c:         parseFloat(document.getElementById("s-temp-min").value),
    temperature_max_c:         parseFloat(document.getElementById("s-temp-max").value),
    sampling_interval_seconds: parseInt(document.getElementById("s-interval").value, 10),
    simulation_mode:           document.getElementById("s-simulation-mode").checked,
    tolerance_dp_pct:   parseFloat(document.getElementById("s-tol-dp").value)   / 100,
    tolerance_reff_pct: parseFloat(document.getElementById("s-tol-reff").value) / 100,
    tolerance_flow_pct: parseFloat(document.getElementById("s-tol-flow").value) / 100,
    tolerance_temp_c:   parseFloat(document.getElementById("s-tol-temp").value),
  };
  if (newPw) { payload.new_password = newPw; payload.old_password = oldPw; }

  const result = await apiFetchAuth("/api/settings", "POST", payload, token);
  if (result?.success) {
    window._settings = result.settings;
    _tolDp    = result.settings.tolerance_dp_pct   ?? 0.25;
    _tolReff  = result.settings.tolerance_reff_pct ?? 0.25;
    _tolFlow  = result.settings.tolerance_flow_pct ?? 0.25;
    _tolTempC = result.settings.tolerance_temp_c   ?? 10.0;
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
  window._lastStatus = d;

  // Zyklen-Tab alle ~15 s aktualisieren (alle 10 Poll-Zyklen)
  if (_activeTab === "cycles") {
    _cyclesPollTick++;
    if (_cyclesPollTick % 10 === 1) loadCyclesOverview();
  } else {
    _cyclesPollTick = 0;
  }

  // Sensorfehler-Overlay (Hardwaremodus) hat Vorrang
  handleSensorFault(d);

  setText("val-p1",    fmt(d.p1_bar, 3));
  setText("val-p2",    fmt(d.p2_bar, 3));
  setText("val-dp",    fmt(d.dp_bar, 3));
  setText("val-flow",  fmt(d.flow_l_min, 1));
  setText("val-temp",  fmt(d.temperature_c, 1));
  if (d.r_rel_factor != null) {
    setText("val-reff",      "×" + d.r_rel_factor.toFixed(2));
    setText("val-reff-unit", "× Ref.");
  } else {
    setText("val-reff",      fmt(d.r_eff * 1000, 1));
    setText("val-reff-unit", "mbar·min/l");
  }

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
  const awaitingJustSet = d.awaiting_confirmation && !_prevAwaiting;
  if (d.running && (!d.awaiting_confirmation || awaitingJustSet)) {
    pushChartData(d);
    updateReferenceOverlay(d);
  }
  _prevAwaiting = !!d.awaiting_confirmation;
  updateSimDemoPanel(d);
  updateAnalysisSection(d);
}

// ============================================================
// Chart (kombiniert)
// ============================================================

// ── Farben ──────────────────────────────────────────────────────────────────
const DS_COLORS = {
  p1:      "#60a5fa",   // hellblau
  p2:      "#93c5fd",   // sehr hellblau
  dp:      "#38bdf8",   // cyan (Hauptmesswert)
  flow:    "#34d399",   // hellgrün
  temp:    "#fb923c",   // orange
  reff:    "#c084fc",   // lila
  remain:  "#fbbf24",   // amber
  refLine: "#00d4ff",   // cyan-blau (Referenz)
  tolBand: "rgba(0,212,255,0.08)", // Toleranzband-Füllung
  tolEdge: "rgba(0,212,255,0.30)",
};

function initCharts() {
  const ctx = document.getElementById("chart-combined");
  if (!ctx) return;
  const dpLimit = window._settings?.dp_limit_bar ?? 2.5;

  const mkDs = (label, color, yAxis, extra = {}) => ({
    label, yAxisID: yAxis, data: [], parsing: false,
    borderColor: color, backgroundColor: "transparent",
    borderWidth: 2, pointRadius: 0, tension: 0.3,
    ...extra,
  });

  combinedChart = new Chart(ctx, {
    type: "line",
    data: {
      datasets: [
        // ── Messwerte (Indizes 0–6) ──────────────────────────────────────
        mkDs("p1 [bar]",            DS_COLORS.p1,     "yPressure", { borderWidth: 1.5 }),
        mkDs("p2 [bar]",            DS_COLORS.p2,     "yPressure", { borderWidth: 1.5 }),
        mkDs("Δp [bar]",            DS_COLORS.dp,     "yPressure", {
          borderWidth: 2.5,
          backgroundColor: "rgba(56,189,248,0.07)",
          fill: "origin",
        }),
        mkDs("Q [l/min]",           DS_COLORS.flow,   "yFlow"),
        mkDs("Temp [°C]",           DS_COLORS.temp,   "yTemp"),
        mkDs("Widerstandsfaktor [×]", DS_COLORS.reff,  "yReff",   { borderDash: [5, 3] }),
        mkDs("Reststandzeit [min]", DS_COLORS.remain, "yTime",   { borderDash: [5, 3] }),
        // ── Referenz & Toleranz Δp (Indizes 7–9) ────────────────────────────
        // 7 = Toleranz Δp obere Grenze → füllt bis Dataset 8
        {
          label: "±Tol Δp",
          yAxisID: "yPressure", data: [], parsing: false,
          borderColor: DS_COLORS.tolEdge,
          backgroundColor: DS_COLORS.tolBand,
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: "+1",
        },
        // 8 = Toleranz Δp untere Grenze
        {
          label: "_tol_dp_lower",
          yAxisID: "yPressure", data: [], parsing: false,
          borderColor: DS_COLORS.tolEdge,
          backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: false,
        },
        // 9 = Referenz Δp-Linie
        mkDs("Ref Δp", DS_COLORS.refLine, "yPressure", {
          borderWidth: 1.5, borderDash: [10, 5],
        }),
        // ── Referenz & Toleranz Q (Indizes 10–12) ───────────────────────────
        // 10 = Toleranz Q obere Grenze → füllt bis Dataset 11
        {
          label: "±Tol Q",
          yAxisID: "yFlow", data: [], parsing: false,
          borderColor: "rgba(52,211,153,0.35)",
          backgroundColor: "rgba(52,211,153,0.08)",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: "+1",
        },
        // 11 = Toleranz Q untere Grenze
        {
          label: "_tol_flow_lower",
          yAxisID: "yFlow", data: [], parsing: false,
          borderColor: "rgba(52,211,153,0.35)",
          backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: false,
        },
        // 12 = Referenz Q-Linie
        mkDs("Ref Q", DS_COLORS.flow, "yFlow", {
          borderWidth: 1.5, borderDash: [10, 5],
        }),
        // ── Referenz & Toleranz Temp (Indizes 13–15) ────────────────────────
        // 13 = Toleranz T obere Grenze → füllt bis Dataset 14
        {
          label: "±Tol T",
          yAxisID: "yTemp", data: [], parsing: false,
          borderColor: "rgba(251,146,60,0.35)",
          backgroundColor: "rgba(251,146,60,0.08)",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: "+1",
        },
        // 14 = Toleranz T untere Grenze
        {
          label: "_tol_temp_lower",
          yAxisID: "yTemp", data: [], parsing: false,
          borderColor: "rgba(251,146,60,0.35)",
          backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: false,
        },
        // 15 = Referenz T-Linie
        mkDs("Ref T", DS_COLORS.temp, "yTemp", {
          borderWidth: 1.5, borderDash: [10, 5],
        }),
        // ── Referenz & Toleranz R_eff (Indizes 16–18) ───────────────────────
        // 16 = Toleranz R_eff obere Grenze → füllt bis Dataset 17
        {
          label: "±Tol R_eff",
          yAxisID: "yReff", data: [], parsing: false,
          borderColor: "rgba(192,132,252,0.35)",
          backgroundColor: "rgba(192,132,252,0.08)",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: "+1",
        },
        // 17 = Toleranz R_eff untere Grenze
        {
          label: "_tol_reff_lower",
          yAxisID: "yReff", data: [], parsing: false,
          borderColor: "rgba(192,132,252,0.35)",
          backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: false,
        },
        // 18 = Referenz R_eff-Linie
        mkDs("Ref R_eff", DS_COLORS.reff, "yReff", {
          borderWidth: 1.5, borderDash: [10, 5],
        }),
      ],
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: false,
        },
        tooltip: {
          mode: "index",
          intersect: false,
          backgroundColor: "rgba(12,22,38,0.95)",
          titleColor: "#a8c8f0",
          bodyColor: "#dde8f5",
          borderColor: "#1c3a5c",
          borderWidth: 1,
          padding: 10,
          usePointStyle: true,
          callbacks: {
            title: items => items[0]
              ? new Date(items[0].parsed.x).toLocaleTimeString("de-DE")
              : "",
            label: ctx => {
              if (ctx.dataset.label.startsWith("_")) return null;
              const v = ctx.parsed.y;
              if (v == null || isNaN(v)) return null;
              const dec = {
                "p1 [bar]": 3, "p2 [bar]": 3, "Δp [bar]": 3,
                "Q [l/min]": 1, "Temp [°C]": 1,
                "R_eff [bar·min/l]": 5, "Reststandzeit [min]": 1,
                "Referenz Δp": 3, "Toleranzband": 3,
              };
              return ` ${ctx.dataset.label}: ${v.toFixed(dec[ctx.dataset.label] ?? 2)}`;
            },
          },
        },
        zoom: {
          pan: { enabled: true, mode: "x" },
          zoom: {
            wheel: { enabled: true, speed: 0.08 },
            pinch: { enabled: true },
            mode: "x",
          },
        },
        annotation: {
          annotations: {
            dpLimitLine: {
              type: "line",
              scaleID: "yPressure",
              value: dpLimit,
              borderColor: "rgba(239,68,68,0.7)",
              borderWidth: 1.5,
              borderDash: [6, 3],
              label: {
                display: true,
                content: `dp-Limit (${Number(dpLimit).toFixed(2)} bar)`,
                position: "end",
                backgroundColor: "rgba(239,68,68,0.15)",
                color: "#f87171",
                font: { size: 10 },
                padding: { x: 5, y: 2 },
              },
            },
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          ticks: {
            maxTicksLimit: 8,
            maxRotation: 0,
            font: { size: 10 },
            color: "#64748b",
            callback: val => new Date(val).toLocaleTimeString("de-DE"),
          },
          grid: { color: "rgba(100,130,160,0.15)" },
        },
        yPressure: {
          type: "linear",
          position: "left",
          min: 0,
          title: { display: true, text: "Druck [bar]", font: { size: 10 }, color: DS_COLORS.dp },
          ticks: { font: { size: 10 }, color: DS_COLORS.dp },
          grid: { color: "rgba(100,130,160,0.15)" },
        },
        yFlow: {
          type: "linear",
          position: "right",
          min: 0,
          title: { display: true, text: "Durchfluss [l/min]", font: { size: 10 }, color: DS_COLORS.flow },
          ticks: { font: { size: 10 }, color: DS_COLORS.flow },
          grid: { drawOnChartArea: false },
        },
        yTemp: {
          type: "linear",
          position: "right",
          display: false,
          min: 0,
          grid: { drawOnChartArea: false },
        },
        yReff: {
          type: "linear",
          position: "right",
          display: false,
          min: 0,
          grid: { drawOnChartArea: false },
        },
        yTime: {
          type: "linear",
          position: "right",
          display: false,
          min: 0,
          grid: { drawOnChartArea: false },
        },
      },
    },
  });

  _buildChartToggleButtons();
  _buildAxisPanel();
}

function pushChartData(status) {
  if (!combinedChart) return;
  const now = Date.now();
  const remMin = status.remaining_seconds != null ? status.remaining_seconds / 60 : null;
  const ds = combinedChart.data.datasets;
  ds[0].data.push({ x: now, y: status.p1_bar ?? null });
  ds[1].data.push({ x: now, y: status.p2_bar ?? null });
  ds[2].data.push({ x: now, y: status.dp_bar ?? null });
  ds[3].data.push({ x: now, y: status.flow_l_min ?? null });
  ds[4].data.push({ x: now, y: status.temperature_c ?? null });
  ds[5].data.push({ x: now, y: status.r_rel_factor ?? status.r_eff ?? null });
  ds[6].data.push({ x: now, y: remMin });
  for (let i = 0; i < 7; i++) {
    if (ds[i].data.length > MAX_CHART_POINTS) ds[i].data.shift();
  }
  combinedChart.update("none");
}

function resetChartZoom() {
  if (combinedChart) combinedChart.resetZoom();
}

// ============================================================
// Referenz-Overlay im Live-Chart (Zyklus vs. Referenzkurve)
// ============================================================

async function _getRefCurve(hetaCode) {
  if (!hetaCode) return null;
  if (_refCurveCacheCode === hetaCode && _refCurveCache) return _refCurveCache;
  const data = await apiFetch(`/api/reference-curve?heta_code=${encodeURIComponent(hetaCode)}`);
  if (data?.profile_valid && data.curve?.length) {
    _refCurveCache = data;
    _refCurveCacheCode = hetaCode;
    return data;
  }
  return null;
}

async function updateReferenceOverlay(status) {
  if (!combinedChart) return;
  const hetaCode    = status?.heta_code;
  const cycleActive = !!status?.cycle_active;
  const startTime   = status?.cycle_start_time;
  const ds = combinedChart.data.datasets;

  if (!cycleActive || !hetaCode || !startTime) {
    const anyData = ds[9].data.length > 0 || ds[12].data.length > 0 ||
                    ds[15].data.length > 0 || ds[18].data.length > 0;
    if (anyData) {
      // Clear all reference datasets 7-18
      for (let i = 7; i <= 18; i++) ds[i].data = [];
      combinedChart.update("none");
      _refreshRefChips();
    }
    _knownCycleStart = null;
    return;
  }

  // Gleicher Zyklus + Referenz schon geladen → nichts tun
  if (startTime === _knownCycleStart && ds[9].data.length > 0) return;
  _knownCycleStart = startTime;

  const refCurve = await _getRefCurve(hetaCode);
  if (!refCurve?.curve?.length) return;

  const startMs  = startTime * 1000;
  const refDurMs       = (refCurve.reference_duration_seconds || 300) * 1000;
  const tolDp          = refCurve.tolerance_dp_pct   ?? refCurve.tolerance_pct ?? 0.25;
  const tolFlow        = refCurve.tolerance_flow_pct ?? 0.25;
  const tolReff        = refCurve.tolerance_reff_pct ?? 0.25;
  const tolTempC       = refCurve.tolerance_temp_c   ?? 10.0;
  const reffStartRef   = refCurve.reference_r_eff_start || 0;

  // Dp datasets (7=upper, 8=lower, 9=center)
  const dpUpper = [], dpLower = [], dpCenter = [];
  // Flow datasets (10=upper, 11=lower, 12=center)
  const flUpper = [], flLower = [], flCenter = [];
  // Temp datasets (13=upper, 14=lower, 15=center)
  const tpUpper = [], tpLower = [], tpCenter = [];
  // Reff datasets (16=upper, 17=lower, 18=center)
  const rfUpper = [], rfLower = [], rfCenter = [];

  for (const pt of refCurve.curve) {
    const xMs = startMs + (pt.t_pct / 100) * refDurMs;

    if (pt.dp != null) {
      dpCenter.push({ x: xMs, y: pt.dp });
      dpUpper.push({  x: xMs, y: pt.dp * (1 + tolDp) });
      dpLower.push({  x: xMs, y: Math.max(0, pt.dp * (1 - tolDp)) });
    }
    if (pt.flow != null) {
      flCenter.push({ x: xMs, y: pt.flow });
      flUpper.push({  x: xMs, y: pt.flow * (1 + tolFlow) });
      flLower.push({  x: xMs, y: Math.max(0, pt.flow * (1 - tolFlow)) });
    }
    if (pt.temp != null) {
      tpCenter.push({ x: xMs, y: pt.temp });
      tpUpper.push({  x: xMs, y: pt.temp + tolTempC });
      tpLower.push({  x: xMs, y: pt.temp - tolTempC });
    }
    if (pt.r_eff != null) {
      // Normieren auf Widerstandsfaktor: pt.r_eff / reference_r_eff_start
      const rfNorm = reffStartRef > 0 ? pt.r_eff / reffStartRef : pt.r_eff;
      rfCenter.push({ x: xMs, y: rfNorm });
      rfUpper.push({  x: xMs, y: rfNorm * (1 + tolReff) });
      rfLower.push({  x: xMs, y: Math.max(0, rfNorm * (1 - tolReff)) });
    }
  }

  ds[7].data = dpUpper;  ds[8].data = dpLower;  ds[9].data = dpCenter;
  ds[10].data = flUpper; ds[11].data = flLower; ds[12].data = flCenter;
  ds[13].data = tpUpper; ds[14].data = tpLower; ds[15].data = tpCenter;
  ds[16].data = rfUpper; ds[17].data = rfLower; ds[18].data = rfCenter;

  combinedChart.update("none");
  _refreshRefChips();
}

// ============================================================
// Zyklus-Diagramm Modal (vergangene Zyklen)
// ============================================================

function _buildCycleChartConfig(cycleLabel, cycleData, refCurve) {
  const tolPct = refCurve?.tolerance_dp_pct ?? refCurve?.tolerance_pct ?? 0.25;
  const refCenter = refCurve?.curve?.length
    ? refCurve.curve.map(p => ({ x: p.t_pct, y: p.dp })) : [];
  const refUpper  = refCurve?.curve?.length
    ? refCurve.curve.map(p => ({ x: p.t_pct, y: p.dp * (1 + tolPct) })) : [];
  const refLower  = refCurve?.curve?.length
    ? refCurve.curve.map(p => ({ x: p.t_pct, y: Math.max(0, p.dp * (1 - tolPct)) })) : [];

  const pct = tolPct * 100;
  return {
    type: "line",
    data: {
      datasets: [
        { label: `Toleranzband ±${pct.toFixed(0)} %`, data: refUpper,
          borderColor: DS_COLORS.tolEdge, backgroundColor: DS_COLORS.tolBand,
          borderWidth: 1, borderDash: [3, 4], pointRadius: 0, tension: 0.3,
          parsing: false, fill: "+1" },
        { label: "_tol_lower", data: refLower,
          borderColor: DS_COLORS.tolEdge, backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4], pointRadius: 0, tension: 0.3,
          parsing: false, fill: false },
        { label: "Referenz Δp", data: refCenter,
          borderColor: DS_COLORS.refLine, backgroundColor: "transparent",
          borderWidth: 1.5, borderDash: [10, 5], pointRadius: 0, tension: 0.3,
          parsing: false },
        { label: cycleLabel, data: cycleData,
          borderColor: DS_COLORS.dp, backgroundColor: "rgba(56,189,248,0.07)",
          borderWidth: 2.5, pointRadius: 0, tension: 0.3,
          parsing: false, fill: "origin" },
      ],
    },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true, position: "top",
          labels: { usePointStyle: true, padding: 14, font: { size: 11 }, color: "#cbd5e1",
            filter: item => !item.text.startsWith("_") },
        },
        tooltip: {
          backgroundColor: "rgba(12,22,38,0.95)",
          titleColor: "#a8c8f0", bodyColor: "#dde8f5",
          borderColor: "#1c3a5c", borderWidth: 1, padding: 9,
          usePointStyle: true,
          callbacks: {
            title: items => items[0] ? `Fortschritt: ${Number(items[0].parsed.x).toFixed(1)} %` : "",
            label: ctx => {
              if (ctx.dataset.label.startsWith("_")) return null;
              const v = ctx.parsed.y;
              if (v == null || isNaN(v)) return null;
              return ` ${ctx.dataset.label}: ${v.toFixed(3)} bar`;
            },
          },
        },
      },
      scales: {
        x: { type: "linear", min: 0,
          title: { display: true, text: "Zyklusfortschritt [%]", font: { size: 11 }, color: "#94a3b8" },
          ticks: { font: { size: 10 }, color: "#64748b" },
          grid: { color: "rgba(100,130,160,0.15)" } },
        y: { type: "linear", min: 0,
          title: { display: true, text: "Δp [bar]", font: { size: 11 }, color: "#94a3b8" },
          ticks: { font: { size: 10 }, color: "#64748b" },
          grid: { color: "rgba(100,130,160,0.15)" } },
      },
    },
  };
}

function _cycleDataFromSamples(samples, durationSeconds) {
  if (!samples?.length) return [];
  if (durationSeconds > 0)
    return samples.map(s => ({ x: (s.cycle_second / durationSeconds) * 100, y: s.dp_bar }));
  return samples.map(s => ({ x: s.cycle_second, y: s.dp_bar }));
}

async function openCycleModal(cycleId, cycleNum, dateStr, hetaCode, durationSeconds, eventsJson) {
  const overlay  = document.getElementById("cycle-modal-overlay");
  const titleEl  = document.getElementById("cycle-modal-title");
  const eventsEl = document.getElementById("cycle-modal-events");
  if (!overlay) return;

  if (titleEl) titleEl.textContent = `Filterzyklus #${cycleNum} – ${dateStr}`;

  let events = [];
  try { events = JSON.parse(eventsJson || "[]"); } catch (_) {}
  if (eventsEl) {
    if (!events.length) {
      eventsEl.innerHTML = '<p style="color:var(--ok-green);margin:0">&#10003; Keine Problemmeldungen in diesem Zyklus.</p>';
    } else {
      const sevColor = s => s === "FEHLER" ? "var(--alert-red)" : "var(--warn-yellow)";
      const rows = events.map(e => {
        const ts = e.ts ? new Date(e.ts * 1000).toLocaleTimeString("de-DE") : "";
        return `<div style="display:flex;gap:.75rem;padding:.4rem 0;border-bottom:1px solid var(--border)">
          <span style="color:${sevColor(e.severity)};font-weight:600;min-width:5rem">${e.severity}</span>
          <span style="color:var(--text-muted);min-width:4rem">${ts}</span>
          <span>${e.message}</span>
        </div>`;
      }).join("");
      eventsEl.innerHTML = `<h3 style="margin:0 0 .5rem;font-size:.9rem">Ereignisse</h3>${rows}`;
    }
  }

  overlay.classList.remove("hidden");

  const [samples, refCurve] = await Promise.all([
    apiFetch(`/api/cycle-samples/${cycleId}`),
    hetaCode ? _getRefCurve(hetaCode) : Promise.resolve(null),
  ]);

  const ctx = document.getElementById("chart-cycle-modal");
  if (!ctx) return;
  if (cycleModalChart) { cycleModalChart.destroy(); cycleModalChart = null; }
  cycleModalChart = new Chart(ctx,
    _buildCycleChartConfig(
      `Zyklus #${cycleNum} Δp`,
      _cycleDataFromSamples(samples || [], durationSeconds),
      refCurve,
    ));
}

function closeCycleModal() {
  const overlay = document.getElementById("cycle-modal-overlay");
  if (overlay) overlay.classList.add("hidden");
  if (cycleModalChart) { cycleModalChart.destroy(); cycleModalChart = null; }
}

function updateChartDpLimit(dpLimitBar) {
  if (!combinedChart) return;
  const ann = combinedChart.options.plugins.annotation.annotations.dpLimitLine;
  ann.value = dpLimitBar;
  ann.label.content = `dp-Limit (${Number(dpLimitBar).toFixed(2)} bar)`;
  combinedChart.update("none");
}

// ============================================================
// Chart Toggle Buttons & Axis Panel
// ============================================================

// Dataset metadata for toggle buttons and axis config
const DS_META = [
  { label: "p1",           color: DS_COLORS.p1,     live: true,  axisFixed: true,  unit: "bar",          axis: "yPressure" },
  { label: "p2",           color: DS_COLORS.p2,     live: true,  axisFixed: true,  unit: "bar",          axis: "yPressure" },
  { label: "Δp",           color: DS_COLORS.dp,     live: true,  axisFixed: true,  unit: "bar",          axis: "yPressure" },
  { label: "Q",            color: DS_COLORS.flow,   live: true,  axisFixed: false, unit: "l/min",        axis: "yFlow"     },
  { label: "T",            color: DS_COLORS.temp,   live: true,  axisFixed: false, unit: "°C",           axis: "yTemp"     },
  { label: "Widerstandsfaktor", color: DS_COLORS.reff, live: true, axisFixed: false, unit: "×",          axis: "yReff"     },
  { label: "Reststandzeit",color: DS_COLORS.remain, live: true,  axisFixed: false, unit: "min",          axis: "yTime"     },
  // Reference dp (indices 7,8,9)
  { label: "±Tol Δp",     color: "rgba(0,212,255,0.35)",  ref: true, refGroup: "dp",   groupLabel: "Δp",   isTolerancePair: [7,8], isTolUpper: true },
  { label: "_tol_dp_lo",  color: "rgba(0,212,255,0.35)",  ref: true, refGroup: "dp",   isToleranceLower: true },
  { label: "Ref Δp",      color: DS_COLORS.refLine,        ref: true, refGroup: "dp",   refLabel: "Ref Δp"  },
  // flow group (10, 11, 12)
  { label: "±Tol Q",      color: "rgba(52,211,153,0.35)",  ref: true, refGroup: "flow", groupLabel: "Q",    isTolerancePair: [10,11], isTolUpper: true },
  { label: "_tol_fl_lo",  color: "rgba(52,211,153,0.35)",  ref: true, refGroup: "flow", isToleranceLower: true },
  { label: "Ref Q",       color: DS_COLORS.flow,           ref: true, refGroup: "flow", refLabel: "Ref Q"   },
  // temp group (13, 14, 15)
  { label: "±Tol T",      color: "rgba(251,146,60,0.35)",  ref: true, refGroup: "temp", groupLabel: "T",    isTolerancePair: [13,14], isTolUpper: true },
  { label: "_tol_tp_lo",  color: "rgba(251,146,60,0.35)",  ref: true, refGroup: "temp", isToleranceLower: true },
  { label: "Ref T",       color: DS_COLORS.temp,           ref: true, refGroup: "temp", refLabel: "Ref T"   },
  // reff group (16, 17, 18)
  { label: "±Tol R",      color: "rgba(192,132,252,0.35)", ref: true, refGroup: "reff", groupLabel: "Wid.faktor", isTolerancePair: [16,17], isTolUpper: true },
  { label: "_tol_rf_lo",  color: "rgba(192,132,252,0.35)", ref: true, refGroup: "reff", isToleranceLower: true },
  { label: "Ref R",       color: DS_COLORS.reff,           ref: true, refGroup: "reff", refLabel: "Ref Wid.faktor" },
];

const AXIS_OPTIONS = [
  { id: "yPressure", label: "Links – Druck [bar]"              },
  { id: "yFlow",     label: "Rechts 1 – Durchfluss [l/min]"   },
  { id: "yTemp",     label: "Rechts 2 – Temperatur [°C]"      },
  { id: "yReff",     label: "Rechts 3 – Widerstandsfaktor [×]" },
  { id: "yTime",     label: "Rechts 4 – Reststandzeit [min]"  },
];

function _buildChartToggleButtons() {
  if (!combinedChart) return;

  // ── Live chips (indices 0-6) ─────────────────────────────────
  const liveContainer = document.getElementById("chart-live-chips");
  if (liveContainer) {
    liveContainer.innerHTML = "";
    for (let i = 0; i < 7; i++) {
      const meta = DS_META[i];
      const btn = document.createElement("button");
      btn.className = "chart-chip";
      btn.dataset.dsIndex = i;
      btn.style.setProperty("--chip-color", meta.color);
      btn.textContent = meta.label;
      // Initially active unless the dataset meta says hidden
      const hidden = combinedChart.getDatasetMeta(i).hidden;
      if (!hidden) btn.classList.add("active");
      btn.addEventListener("click", () => toggleChartDs(i));
      liveContainer.appendChild(btn);
    }
  }

  // ── Reference chips (grouped) ────────────────────────────────
  const refContainer = document.getElementById("chart-ref-chips");
  if (refContainer) {
    refContainer.innerHTML = "";

    // Groups: dp(7,8,9), flow(10,11,12), temp(13,14,15), reff(16,17,18)
    const groups = [
      { name: "dp",   label: "Δp",     refIdx: 9,  tolIdx: [7,8],   color: DS_COLORS.refLine,  tolColor: "rgba(0,212,255,0.35)"  },
      { name: "flow", label: "Q",      refIdx: 12, tolIdx: [10,11], color: DS_COLORS.flow,     tolColor: "rgba(52,211,153,0.35)" },
      { name: "temp", label: "T",      refIdx: 15, tolIdx: [13,14], color: DS_COLORS.temp,     tolColor: "rgba(251,146,60,0.35)" },
      { name: "reff", label: "R_eff",  refIdx: 18, tolIdx: [16,17], color: DS_COLORS.reff,     tolColor: "rgba(192,132,252,0.35)"},
    ];

    for (const grp of groups) {
      const wrapper = document.createElement("div");
      wrapper.className = "chart-chip-group";
      wrapper.dataset.refGroup = grp.name;

      // Ref chip
      const refBtn = document.createElement("button");
      refBtn.className = "chart-chip";
      refBtn.dataset.dsIndex = grp.refIdx;
      refBtn.dataset.refGroup = grp.name;
      refBtn.style.setProperty("--chip-color", grp.color);
      refBtn.textContent = `Ref ${grp.label}`;
      refBtn.classList.add("disabled");
      refBtn.disabled = true;
      refBtn.addEventListener("click", () => toggleChartDs(grp.refIdx));
      wrapper.appendChild(refBtn);

      // Tol chip (toggles both upper and lower together)
      const tolBtn = document.createElement("button");
      tolBtn.className = "chart-chip";
      tolBtn.dataset.dsIndex = grp.tolIdx[0];
      tolBtn.dataset.refGroup = grp.name;
      tolBtn.dataset.tolPair = JSON.stringify(grp.tolIdx);
      tolBtn.style.setProperty("--chip-color", grp.tolColor);
      tolBtn.textContent = `±Tol ${grp.label}`;
      tolBtn.classList.add("disabled");
      tolBtn.disabled = true;
      tolBtn.addEventListener("click", () => {
        const indices = JSON.parse(tolBtn.dataset.tolPair);
        toggleChartDs(indices[0], indices);
      });
      wrapper.appendChild(tolBtn);

      refContainer.appendChild(wrapper);
    }
  }
}

function _buildAxisPanel() {
  if (!combinedChart) return;
  const panel = document.getElementById("chart-axis-panel");
  if (!panel) return;
  panel.innerHTML = "";

  for (let i = 0; i < 7; i++) {
    const meta = DS_META[i];
    const row = document.createElement("div");
    row.className = "chart-axis-row";

    const dot = document.createElement("span");
    dot.className = "chart-axis-dot";
    dot.style.background = meta.color;
    row.appendChild(dot);

    const label = document.createElement("span");
    label.textContent = meta.label;
    label.style.flex = "0 0 auto";
    label.style.minWidth = "5rem";
    row.appendChild(label);

    if (meta.axisFixed) {
      // Read-only label for fixed-axis datasets (p1, p2, Δp)
      const fixedLabel = document.createElement("span");
      fixedLabel.className = "chart-axis-select";
      fixedLabel.style.opacity = "0.6";
      fixedLabel.style.cursor = "default";
      fixedLabel.textContent = "Links – Druck [bar]";
      row.appendChild(fixedLabel);
    } else {
      const sel = document.createElement("select");
      sel.className = "chart-axis-select";
      sel.dataset.dsIndex = i;
      for (const opt of AXIS_OPTIONS) {
        const o = document.createElement("option");
        o.value = opt.id;
        o.textContent = opt.label;
        if (opt.id === meta.axis) o.selected = true;
        sel.appendChild(o);
      }
      sel.addEventListener("change", () => setDatasetAxis(i, sel.value));
      row.appendChild(sel);
    }

    panel.appendChild(row);
  }
}

function toggleChartDs(primaryIndex, allIndices) {
  if (!combinedChart) return;
  const indices = allIndices || [primaryIndex];

  // Determine new state based on primary dataset
  const primaryMeta = combinedChart.getDatasetMeta(primaryIndex);
  const newHidden = !primaryMeta.hidden;

  for (const idx of indices) {
    combinedChart.getDatasetMeta(idx).hidden = newHidden;
  }

  // Update chip button active state
  // Find all buttons that reference this primary index
  document.querySelectorAll(`.chart-chip[data-ds-index="${primaryIndex}"]`).forEach(btn => {
    btn.classList.toggle("active", !newHidden);
  });

  updateAxisVisibility();
  combinedChart.update();
}

function setDatasetAxis(index, axisId) {
  if (!combinedChart) return;
  combinedChart.data.datasets[index].yAxisID = axisId;
  if (DS_META[index]) DS_META[index].axis = axisId;
  updateAxisVisibility();
  combinedChart.update();
}

function updateAxisVisibility() {
  if (!combinedChart) return;
  const scales = combinedChart.options.scales;
  const datasets = combinedChart.data.datasets;

  for (const axisId of Object.keys(scales)) {
    if (axisId === "x") continue;
    // yPressure always stays visible (has annotations)
    if (axisId === "yPressure") {
      scales[axisId].display = true;
      continue;
    }
    // Check if any dataset assigned to this axis is visible
    let hasVisible = false;
    datasets.forEach((ds, idx) => {
      if (ds.yAxisID === axisId) {
        const m = combinedChart.getDatasetMeta(idx);
        if (m.hidden !== true) hasVisible = true;
      }
    });
    scales[axisId].display = hasVisible;
  }
}

function toggleAxisPanel() {
  const panel = document.getElementById("chart-axis-panel");
  const chevron = document.getElementById("chart-axis-chevron");
  if (!panel) return;
  const isHidden = panel.classList.toggle("hidden");
  if (chevron) chevron.innerHTML = isHidden ? "&#9660;" : "&#9650;";
}

function _refreshRefChips() {
  if (!combinedChart) return;
  const ds = combinedChart.data.datasets;
  const hasData = ds[9].data.length > 0;

  // Groups and their indices
  const groupInfo = [
    { refIdx: 9,  tolIdx: [7,8]   },
    { refIdx: 12, tolIdx: [10,11] },
    { refIdx: 15, tolIdx: [13,14] },
    { refIdx: 18, tolIdx: [16,17] },
  ];

  for (const grp of groupInfo) {
    const grpHasData = ds[grp.refIdx].data.length > 0;

    // Find chips for this ref index and tol indices
    const refChip = document.querySelector(`#chart-ref-chips .chart-chip[data-ds-index="${grp.refIdx}"]`);
    const tolChip = document.querySelector(`#chart-ref-chips .chart-chip[data-ds-index="${grp.tolIdx[0]}"]`);

    if (refChip) {
      refChip.disabled = !grpHasData;
      refChip.classList.toggle("disabled", !grpHasData);
      if (grpHasData && !combinedChart.getDatasetMeta(grp.refIdx).hidden) {
        refChip.classList.add("active");
      } else if (!grpHasData) {
        refChip.classList.remove("active");
      }
    }
    if (tolChip) {
      tolChip.disabled = !grpHasData;
      tolChip.classList.toggle("disabled", !grpHasData);
      if (grpHasData && !combinedChart.getDatasetMeta(grp.tolIdx[0]).hidden) {
        tolChip.classList.add("active");
      } else if (!grpHasData) {
        tolChip.classList.remove("active");
      }
    }

    // When data first becomes available, make visible by default
    if (grpHasData) {
      [grp.refIdx, ...grp.tolIdx].forEach(idx => {
        if (combinedChart.getDatasetMeta(idx).hidden === undefined ||
            combinedChart.getDatasetMeta(idx).hidden === null) {
          // leave as is (default visible)
        }
      });
    }
  }

  // Also update the hint text
  const hintEl = document.getElementById("chart-ref-hint");
  if (hintEl) {
    hintEl.textContent = hasData ? "" : "Kein aktiver Zyklus mit HETA-Code";
  }
}

// ============================================================
// Steuerungs-Buttons
// ============================================================

async function startSimulation() {
  await apiFetch("/api/simulation/start", "POST");
  clearCharts();
  _prevAwaiting = false;
  showMsg("heta-msg", "Messung gestartet.", false);
}

async function stopSimulation() {
  await apiFetch("/api/simulation/stop", "POST");
  showMsg("heta-msg", "Messung gestoppt.", false);
}

async function resetSystem() {
  if (!confirm("System wirklich zurücksetzen?")) return;
  await apiFetch("/api/simulation/reset", "POST");
  clearCharts();
  showMsg("heta-msg", "System zurückgesetzt.", false);
}

function _getHetaCode() {
  const num = document.getElementById("input-heta-code").value.trim();
  return num ? "HETA-" + num : "";
}

async function activateHetaCode() {
  const code = _getHetaCode();
  const pin  = document.getElementById("input-pin").value.trim();
  if (!code || !pin) { showMsg("heta-msg", "HETA-Code und PIN eingeben.", true); return; }
  const result = await apiFetch("/api/heta/activate", "POST", { heta_code: code, pin });
  if (result?.valid) showMsg("heta-msg", `Aktivierung erfolgreich: ${result.heta_code}`, false);
  else showMsg("heta-msg", result?.message ?? "Fehler.", true);
}

async function showDemo() {
  const code = _getHetaCode();
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
  const map = {
    hardware:     ["badge badge-hw",      "REAL",   "Realbetrieb – echte Sensoren"],
    simulation:   ["badge badge-sim",     "SIM",    "Simulationsmodus (konfiguriert)"],
    sensor_fault: ["badge badge-error",   "FEHLER", "Sensorfehler – Messung gestoppt"],
  };
  const [cls, label, title] = map[mode] ?? ["badge badge-sim", "SIM", ""];
  el.className = cls;
  el.textContent = label;
  el.title = title;
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
  if (!combinedChart) return;
  combinedChart.data.labels = [];
  combinedChart.data.datasets.forEach(ds => { ds.data = []; });
  _knownCycleStart = null;
  _refCurveCache = null;
  _refCurveCacheCode = null;
  combinedChart.update("none");
  _refreshRefChips();
}

// ---------------------------------------------------------------------------
// Hardware-Diagnose
// ---------------------------------------------------------------------------

async function runDiagnostics() {
  const btn = document.getElementById("btn-diag");
  const results = document.getElementById("diag-results");
  btn.disabled = true;
  btn.textContent = "⟳ Selbstcheck läuft…";
  results.className = "diag-results";
  results.innerHTML = '<div class="diag-running">Komponenten werden geprüft…</div>';

  const data = await apiFetch("/api/diagnostics");

  btn.disabled = false;
  btn.textContent = "🔍 Selbstcheck starten";

  if (!data) {
    results.innerHTML = '<div class="diag-check diag-error"><span class="diag-icon">✗</span><div><strong>Verbindungsfehler</strong><span>API nicht erreichbar.</span></div></div>';
    return;
  }

  const overallClass = { ok: "diag-overall-ok", warning: "diag-overall-warn", error: "diag-overall-err" }[data.overall] ?? "diag-overall-err";
  const overallLabel = { ok: "Alle Komponenten OK", warning: "Warnungen vorhanden", error: "Fehler gefunden" }[data.overall] ?? "Unbekannt";

  let html = `<div class="diag-overall ${overallClass}">${overallLabel}</div>`;

  for (const c of data.checks) {
    const iconMap = { ok: "✓", warning: "⚠", error: "✗", info: "ℹ" };
    const icon = iconMap[c.status] ?? "?";
    const hintsHtml = c.hints.length
      ? `<ul class="diag-hints">${c.hints.map(h => `<li>${h}</li>`).join("")}</ul>`
      : "";
    html += `
      <div class="diag-check diag-${c.status}">
        <span class="diag-icon">${icon}</span>
        <div class="diag-body">
          <strong>${c.label}</strong>
          <span class="diag-detail">${c.detail}</span>
          ${hintsHtml}
        </div>
      </div>`;
  }

  results.innerHTML = html;
}

// ============================================================
// Sensorfehler-Behandlung
// ============================================================

function handleSensorFault(d) {
  const overlay = document.getElementById("sensor-fault-overlay");
  if (!overlay) return;

  if (!d.sensor_fault) {
    overlay.classList.add("hidden");
    return;
  }

  // Overlay einblenden
  overlay.classList.remove("hidden");
  setText("sensor-fault-message", d.sensor_fault_message || "Ein oder mehrere Sensoren sind nicht erreichbar.");

  // Ausgefallene Kanäle auflisten
  const listEl = document.getElementById("sensor-fault-channels");
  if (listEl) {
    const channels = d.sensor_fault_channels || [];
    const nameMap = {1: "Kanal 1 – p1 (Eintrittsdruck)", 2: "Kanal 2 – p2 (Austrittsdruck)",
                     3: "Kanal 3 – T (Temperatur)",       4: "Kanal 4 – Q (Durchfluss)"};
    listEl.innerHTML = channels.map(ch =>
      `<div class="sensor-fault-channel">⚠ ${nameMap[ch] || "Kanal " + ch}</div>`
    ).join("");
  }
}

function toggleSimLogin() {
  const panel = document.getElementById("sensor-fault-sim-login");
  const btn   = document.getElementById("btn-sim-toggle");
  const open  = panel.classList.toggle("hidden");
  btn.textContent = open
    ? "▶ Im Simulationsmodus fortfahren (Passwort erforderlich)"
    : "▼ Im Simulationsmodus fortfahren (Passwort erforderlich)";
  if (!open) setTimeout(() => document.getElementById("sensor-fault-pw")?.focus(), 50);
}

async function activateSimMode() {
  const pw  = document.getElementById("sensor-fault-pw").value;
  const btn = document.getElementById("btn-sim-confirm");
  if (!pw) { showMsg("sensor-fault-sim-msg", "Bitte Passwort eingeben.", true); return; }

  btn.disabled = true;
  btn.textContent = "…";
  showMsg("sensor-fault-sim-msg", "", false);

  // 1. Einstellungen-Login
  const loginRes = await apiFetch("/api/settings/login", "POST", { password: pw });
  if (!loginRes?.success) {
    showMsg("sensor-fault-sim-msg", loginRes?.message ?? "Falsches Passwort.", true);
    btn.disabled = false; btn.textContent = "Aktivieren";
    return;
  }
  const token = loginRes.token;
  sessionStorage.setItem(TOKEN_KEY, token);

  // 2. simulation_mode in Einstellungen speichern
  const saveRes = await apiFetchAuth("/api/settings", "POST", { simulation_mode: true }, token);
  if (!saveRes?.success) {
    showMsg("sensor-fault-sim-msg", saveRes?.message ?? "Fehler beim Speichern.", true);
    btn.disabled = false; btn.textContent = "Aktivieren";
    return;
  }

  // 3. Messung im Simulationsmodus starten (löscht sensor_fault, startet Thread)
  await apiFetch("/api/simulation/start", "POST");
  document.getElementById("sensor-fault-pw").value = "";
  btn.disabled = false; btn.textContent = "Aktivieren";
  showMsg("sensor-fault-sim-msg", "Simulationsmodus aktiviert.", false);
  // Overlay schließt sich beim nächsten Poll-Zyklus automatisch
}

async function recheckSensors() {
  const btn    = document.getElementById("btn-sensor-recheck");
  const result = document.getElementById("sensor-fault-result");

  btn.disabled = true;
  btn.textContent = "Prüfung läuft…";
  if (result) { result.classList.remove("hidden"); result.className = "sensor-fault-result checking"; result.textContent = "Sensorkanäle werden geprüft…"; }

  const data = await apiFetch("/api/sensor/recheck", "POST");

  btn.disabled = false;
  btn.textContent = "Alle Sensoren angeschlossen – System prüfen";

  if (!data) {
    if (result) { result.className = "sensor-fault-result error"; result.textContent = "Verbindungsfehler – Bitte erneut versuchen."; }
    return;
  }

  if (data.success) {
    // Overlay wird beim nächsten Poll-Zyklus automatisch ausgeblendet (sensor_fault = false)
    if (result) { result.className = "sensor-fault-result ok"; result.textContent = data.message; }
  } else {
    if (result) { result.className = "sensor-fault-result error"; result.textContent = data.message; }
  }
}

// ============================================================
// ============================================================
// Prozessanalyse (Sensor- UND Simulationsmodus)
// ============================================================

function updateAnalysisSection(d) {
  const section = document.getElementById("analysis-section");
  if (!section) return;

  const active = !!d.analysis_active;
  section.classList.toggle("hidden", !active);
  if (!active) return;

  // Modus-Badge
  const badge = document.getElementById("analysis-mode-badge");
  if (badge) {
    const isSim = d.simulation_mode || d.sensor_mode === "simulation";
    badge.textContent = isSim ? "Simulationswerte" : "Sensorwerte";
    badge.className   = "analysis-mode-badge " + (isSim ? "badge-sim" : "badge-hw");
  }

  const loadingEl = document.getElementById("analysis-loading");
  const contentEl = document.getElementById("analysis-content");
  const ready     = !!d.analysis_ready;
  if (loadingEl) loadingEl.classList.toggle("hidden", ready);
  if (contentEl) contentEl.classList.toggle("hidden", !ready);
  if (!ready) return;

  // Zyklusfortschritt
  const progressPct = d.analysis_cycle_progress_pct ?? 0;
  const progressBar = document.getElementById("analysis-progress-bar");
  if (progressBar) progressBar.style.width = Math.min(100, progressPct) + "%";
  setText("analysis-progress-pct", Math.round(progressPct) + " %");

  // Δp vs. Referenzkurve
  const dpRef = d.analysis_dp_ref ?? 0;
  const dpCur = d.dp_bar          ?? 0;
  const dpDev = d.analysis_dp_deviation_pct ?? 0;
  setText("an-dp-ref", fmt(dpRef, 3) + " bar");
  setText("an-dp-cur", fmt(dpCur, 3) + " bar");
  setAnalysisDev("an-dp-dev", dpDev, "%", _tolDp * 100, _tolDp * 200);

  // R_eff vs. Referenzkurve – als Widerstandsfaktor anzeigen
  const reffRef = d.analysis_reff_ref ?? 0;
  const reffCur = d.analysis_reff_cur ?? d.r_eff ?? 0;
  const reffDev = d.analysis_reff_deviation_pct ?? 0;
  const reffRefFactor = d.r_rel_factor != null && reffRef > 0 ? reffRef / reffRef : null; // Ref-Punkt = ×1.00
  const reffCurFactor = d.r_rel_factor != null && reffRef > 0 ? reffCur / reffRef : null;
  setText("an-reff-ref", reffRefFactor != null ? ("×" + reffRefFactor.toFixed(2)) : (fmt(reffRef * 1000, 1) + " mbar·min/l"));
  setText("an-reff-cur", reffCurFactor != null ? ("×" + reffCurFactor.toFixed(2)) : (fmt(reffCur * 1000, 1) + " mbar·min/l"));
  setAnalysisDev("an-reff-dev", reffDev, "%", _tolReff * 100, _tolReff * 200);

  // Durchfluss Q vs. Referenzkurve
  const flRef = d.analysis_flow_ref ?? 0;
  const flCur = d.flow_l_min        ?? 0;
  const flDev = d.analysis_flow_deviation_pct ?? 0;
  setText("an-fl-ref", fmt(flRef, 1) + " l/min");
  setText("an-fl-cur", fmt(flCur, 1) + " l/min");
  setAnalysisDev("an-fl-dev", flDev, "%", _tolFlow * 100, _tolFlow * 200);

  // Temperatur T vs. Referenzkurve
  const tRef = d.analysis_temp_ref      ?? 0;
  const tCur = d.temperature_c          ?? 0;
  const tDev = d.analysis_temp_deviation ?? 0;
  setText("an-tmp-ref", fmt(tRef, 1) + " °C");
  setText("an-tmp-cur", fmt(tCur, 1) + " °C");
  setAnalysisDev("an-tmp-dev", tDev, "°C", _tolTempC, _tolTempC * 2, true);

  setText("analysis-diagnosis", buildDiagnosis(dpDev, flDev, tDev));
}

function setAnalysisDev(id, val, unit, warnAt, critAt, isAbsolute = false) {
  const el = document.getElementById(id);
  if (!el) return;
  const sign = val > 0 ? "+" : "";
  const disp = isAbsolute ? Math.abs(val).toFixed(1) : Math.abs(Math.round(val));
  const prefix = val >= 0 ? sign : "−";
  el.textContent = `${prefix}${disp} ${unit}`;
  const absVal = Math.abs(val);
  el.className = "analysis-dev " + (
    absVal < warnAt ? "dev-ok" :
    absVal < critAt ? "dev-warn" : "dev-crit"
  );
}

function buildDiagnosis(dpDevPct, flowDevPct, tempDev) {
  const dpFast   = dpDevPct   >  40;
  const dpSlow   = dpDevPct   < -30;
  const flowLow  = flowDevPct < -20;
  const flowHigh = flowDevPct >  15;
  const tempHigh = tempDev    >  15;
  const tempLow  = tempDev    < -10;

  const hints = [];

  if (dpFast && flowLow) {
    hints.push("Schnelle Beladung + reduzierter Durchfluss → Verdacht auf Filterverstopfung oder erhöhten Verschmutzungseintrag.");
  } else if (dpFast) {
    hints.push("Δp steigt schneller als gelernt → erhöhte Partikelkonzentration oder beschädigtes Filterelement möglich.");
  } else if (dpSlow) {
    hints.push("Langsame Beladung → Prozess läuft mit reduzierter Last. Filterwechselintervall verlängert sich.");
  }

  if (flowLow && !dpFast) {
    hints.push("Durchfluss unter Referenz → Pumpenproblem, Leckage im Bypass oder Vorverstopfung möglich.");
  } else if (flowHigh) {
    hints.push("Erhöhter Durchfluss → Filterwechselintervall verkürzt sich entsprechend.");
  }

  if (tempHigh) {
    hints.push("Temperatur über Referenz → Filterkapazität kann reduziert sein, Materialbetändigkeit prüfen.");
  } else if (tempLow) {
    hints.push("Temperatur unter Referenz → Viskositätsänderung beeinflusst möglicherweise den Differenzdruck.");
  }

  if (hints.length === 0) {
    if (Math.abs(dpDevPct) < 15 && Math.abs(flowDevPct) < 15 && Math.abs(tempDev) < 8) {
      return "✔ Alle Parameter im gelernten Normalbereich – kein Handlungsbedarf.";
    }
    return "💡 Leichte Abweichungen vom gelernten Profil – Prozess beobachten.";
  }
  return "💡 " + hints.join(" ");
}

// ============================================================
// Simulations-Demo-Panel
// ============================================================

let _sliderDebounce = null;
let _rateValues = { dirt_rate_pct: 100.0, p1_trend_pct: 0.0, flow_drop_pct: 75.0, temp_trend: 0.0 };

const SIM_SCENARIOS = {
  normal:         { dirt_rate_pct: 100, p1_trend_pct:   0, flow_drop_pct: 75, temp_trend:  0 },
  high_dirt:      { dirt_rate_pct: 250, p1_trend_pct:   0, flow_drop_pct: 75, temp_trend:  0 },
  low_p1:         { dirt_rate_pct: 100, p1_trend_pct: -10, flow_drop_pct: 75, temp_trend:  0 },
  high_flow_drop: { dirt_rate_pct: 100, p1_trend_pct:   0, flow_drop_pct: 90, temp_trend:  0 },
  rising_temp:    { dirt_rate_pct: 100, p1_trend_pct:   0, flow_drop_pct: 75, temp_trend:  5 },
  atypical:       { dirt_rate_pct: 180, p1_trend_pct: -10, flow_drop_pct: 90, temp_trend:  3 },
};

function updateSimDemoPanel(d) {
  const panel = document.getElementById("sim-demo-panel");
  if (!panel) return;

  const simMode = !!d.simulation_mode;
  panel.classList.toggle("hidden", !simMode);
  if (!simMode) return;

  const profileValid = d.profile_status === "VALIDIERT" && d.heta_activated;
  const learnArea    = document.getElementById("sim-learn-area");
  const analysisArea = document.getElementById("sim-analysis-area");

  const needed   = Math.max(0, (d.required_cycles ?? 3) - (d.learned_cycles ?? 0));
  const totalReq = d.required_cycles ?? 3;
  setText("sim-learn-needed", needed > 0 ? needed : totalReq);

  const dotsEl = document.getElementById("sim-learn-dots");
  if (dotsEl) {
    const done = Math.min(d.learned_cycles ?? 0, totalReq);
    dotsEl.innerHTML = Array.from({length: totalReq}, (_, i) =>
      `<span class="sim-dot ${i < done ? "done" : ""}"></span>`
    ).join("");
  }

  const learnBtn = document.getElementById("btn-quick-learn");
  if (learnBtn) learnBtn.disabled = profileValid;

  if (profileValid) {
    if (learnArea)    learnArea.classList.add("hidden");
    if (analysisArea) analysisArea.classList.remove("hidden");
    const toggle = document.getElementById("sim-manual-toggle");
    if (toggle && !toggle.dataset.userSet) toggle.checked = !!d.sim_rates_active;
    updateComparison(d);
  } else {
    if (learnArea)    learnArea.classList.remove("hidden");
    if (analysisArea) analysisArea.classList.add("hidden");
  }
}

function updateComparison(d) {
  const cmpEl = document.getElementById("sim-comparison");
  if (!cmpEl) return;

  const active = !!d.sim_rates_active;
  cmpEl.classList.toggle("hidden", !active);
  if (!active) return;

  const s       = window._settings || {};
  const dp_clean = s.dp_clean_bar ?? 0.2;
  const dp_limit = s.dp_limit_bar ?? 2.5;
  const samp     = parseFloat(s.sampling_interval_seconds ?? 1);
  const cyc_steps = s.cycle_steps ?? 300;
  const ref_rate  = (dp_limit - dp_clean) / Math.max(samp * cyc_steps, 1);

  const dirt_pct     = d.sim_dirt_rate_pct      ?? 100.0;
  const dp_dev       = d.sim_dp_deviation_pct   ?? 0.0;
  const flow_drop    = d.sim_flow_drop_pct       ?? 75.0;
  const flow_dev     = d.sim_flow_deviation_pct  ?? 0.0;
  const temp_trend   = d.sim_temp_trend          ?? 0.0;
  const temp_dev     = d.sim_temp_deviation      ?? 0.0;

  const q_base   = s.sim_q_base_l_min ?? 145.0;
  const t_base   = s.sim_t_base_c     ?? 25.0;
  const ref_flow = d.analysis_ref_flow || (q_base * (1 - 0.4 * 0.75));
  const ref_temp = d.analysis_ref_temp || t_base;

  setText("cmp-dp-ref",   `${(ref_rate * 1000).toFixed(2)} mbar/s`);
  setText("cmp-dp-cur",   `${(ref_rate * dirt_pct / 100 * 1000).toFixed(2)} mbar/s`);
  setDev("cmp-dp-dev",    dp_dev, "%");

  setText("cmp-flow-ref", `${ref_flow.toFixed(1)} l/min`);
  setText("cmp-flow-cur", `${flow_drop.toFixed(0)} % Abfall`);
  setDev("cmp-flow-dev",  flow_dev, "%");

  const tSign = temp_trend >= 0 ? "+" : "";
  setText("cmp-temp-ref", `${ref_temp.toFixed(1)} °C`);
  setText("cmp-temp-cur", `${tSign}${temp_trend.toFixed(1)} °C/Zyklus`);
  setDev("cmp-temp-dev",  temp_dev, "°C", true);

  setText("sim-diagnosis", buildSimDiagnosis(dirt_pct / 100.0, flow_drop, temp_trend));
}

function setDev(id, val, unit, isAbsolute = false) {
  const el = document.getElementById(id);
  if (!el) return;
  const sign = val > 0 ? "+" : "";
  el.textContent = `${sign}${val.toFixed(isAbsolute ? 1 : 0)} ${unit}`;
  el.className = "sim-cmp-dev " + (
    Math.abs(val) < (isAbsolute ? 5 : 10)  ? "dev-ok"  :
    Math.abs(val) < (isAbsolute ? 15 : 30) ? "dev-warn" : "dev-crit"
  );
}

function buildSimDiagnosis(dirtF, flowDrop, tempTrend) {
  const parts = [];
  if (dirtF > 1.8)
    parts.push("Sehr hohe Verschmutzungsrate – Filterwechselintervall deutlich verkürzt. Erhöhte Partikelkonzentration oder Filterschaden möglich.");
  else if (dirtF > 1.2)
    parts.push("Erhöhte Verschmutzungsrate – Reststandzeit sinkt schneller als Referenz.");
  else if (dirtF < 0.6)
    parts.push("Geringe Verschmutzungsrate – verlängertes Filterwechselintervall.");
  if ((flowDrop ?? 75) > 85)
    parts.push("Starker Durchflussabfall – mögliche Verstopfung oder erhöhter Gegendruck.");
  else if ((flowDrop ?? 75) < 40)
    parts.push("Geringer Durchflussabfall – sehr stabile Prozessbedingungen.");
  if (Math.abs(tempTrend ?? 0) >= 3)
    parts.push(`Signifikanter Temperaturtrend (${(tempTrend ?? 0) > 0 ? "+" : ""}${(tempTrend ?? 0).toFixed(1)} °C/Zyklus) – Prozess oder Umgebung verändert sich.`);
  if (parts.length === 0)
    return "✔ Prozessparameter im gelernten Normalbereich – kein Handlungsbedarf.";
  return "💡 " + parts.join(" ");
}

async function quickLearn() {
  const btn = document.getElementById("btn-quick-learn");
  btn.disabled = true;
  btn.textContent = "… Lernzyklen werden simuliert";
  showMsg("sim-learn-msg", "", false);

  const res = await apiFetch("/api/simulation/quick-learn", "POST");
  btn.textContent = "▶ Lernzyklen simulieren";

  if (!res) {
    showMsg("sim-learn-msg", "Verbindungsfehler.", true);
    btn.disabled = false;
    return;
  }
  if (res.success) {
    showMsg("sim-learn-msg", res.message, false);
  } else {
    showMsg("sim-learn-msg", res.message, true);
    btn.disabled = false;
  }
}

function onSliderInput(which, rawVal) {
  const v = parseFloat(rawVal);
  if (which === "dirt_rate") {
    _rateValues.dirt_rate_pct = v;
    setText("sv-dirt-rate", Math.round(v) + " %");
  } else if (which === "p1_trend") {
    _rateValues.p1_trend_pct = v;
    const sign = v >= 0 ? "+" : "";
    setText("sv-p1-trend", sign + Math.round(v) + " %");
  } else if (which === "flow_drop") {
    _rateValues.flow_drop_pct = v;
    setText("sv-flow-drop", Math.round(v) + " %");
  } else if (which === "temp_trend") {
    _rateValues.temp_trend = v;
    const sign = v >= 0 ? "+" : "";
    setText("sv-temp-trend", sign + v.toFixed(1) + " °C");
  }
  // Szenario-Buttons: bei manueller Änderung deaktivieren
  document.querySelectorAll(".sim-scenario-btn").forEach(b => b.classList.remove("active"));
  scheduleSendValues();
}

function scheduleSendValues() {
  clearTimeout(_sliderDebounce);
  _sliderDebounce = setTimeout(() => sendSliderValues(), 150);
}

async function sendSliderValues(scenario) {
  await apiFetch("/api/simulation/set-rates", "POST", {
    active:         true,
    scenario:       scenario || "custom",
    dirt_rate_pct:  _rateValues.dirt_rate_pct,
    p1_trend_pct:   _rateValues.p1_trend_pct,
    flow_drop_pct:  _rateValues.flow_drop_pct,
    temp_trend:     _rateValues.temp_trend,
  });
}

function selectScenario(name) {
  const sc = SIM_SCENARIOS[name];
  if (!sc) return;
  _rateValues = { ...sc };

  const setSlider = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
  setSlider("sl-dirt-rate",  sc.dirt_rate_pct);
  setSlider("sl-p1-trend",   sc.p1_trend_pct);
  setSlider("sl-flow-drop",  sc.flow_drop_pct);
  setSlider("sl-temp-trend", sc.temp_trend);

  setText("sv-dirt-rate",  Math.round(sc.dirt_rate_pct) + " %");
  const ps = sc.p1_trend_pct >= 0 ? "+" : "";
  setText("sv-p1-trend",   ps + Math.round(sc.p1_trend_pct) + " %");
  setText("sv-flow-drop",  Math.round(sc.flow_drop_pct) + " %");
  const ts = sc.temp_trend >= 0 ? "+" : "";
  setText("sv-temp-trend", ts + sc.temp_trend.toFixed(1) + " °C");

  document.querySelectorAll(".sim-scenario-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.scenario === name);
  });
  sendSliderValues(name);
}

async function onManualToggle(checkbox) {
  checkbox.dataset.userSet = "1";
  if (checkbox.checked) {
    await sendSliderValues("custom");
  } else {
    clearTimeout(_sliderDebounce);
    await apiFetch("/api/simulation/set-rates", "POST", { active: false });
  }
  setTimeout(() => { checkbox.dataset.userSet = ""; }, 3000);
}

function resetSliders() {
  selectScenario("normal");
}

// ============================================================
// Simulationsmodus-Warnung in den Einstellungen
// ============================================================

function onSimModeToggle(checkbox) {
  const warnEl = document.getElementById("sim-mode-warning");
  if (!warnEl) return;
  warnEl.classList.toggle("hidden", !checkbox.checked);
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
  const token = sessionStorage.getItem(TOKEN_KEY);
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

// ============================================================
// Zyklen & Profil – Tab
// ============================================================

async function resetHetaCycles() {
  const d = window._lastStatus;
  const hetaCode = d?.heta_code;

  if (!hetaCode || !d?.heta_activated) {
    alert("Kein HETA-Code aktiv. Bitte zuerst einen HETA-Code aktivieren.");
    return;
  }

  const confirmed = confirm(
    `Alle Lernzyklen und das Profil für "${hetaCode}" wirklich zurücksetzen?\n\n` +
    `Das System muss danach erneut 3 Filterzyklen lernen.\n` +
    `Diese Aktion kann nicht rückgängig gemacht werden.`
  );
  if (!confirmed) return;

  const token = sessionStorage.getItem(TOKEN_KEY);
  if (!token) {
    alert("Sitzung abgelaufen. Bitte zuerst in den Einstellungen anmelden.");
    openSettings();
    return;
  }

  const btn = document.getElementById("btn-reset-cycles");
  if (btn) { btn.disabled = true; btn.textContent = "… wird zurückgesetzt"; }

  const result = await apiFetchAuth("/api/heta/reset-cycles", "POST", {}, token);

  if (btn) { btn.disabled = false; btn.textContent = "🗑 Lernzyklen zurücksetzen"; }

  if (result === null) {
    alert("Sitzung abgelaufen. Bitte erneut anmelden.");
    openSettings();
    return;
  }

  if (result?.success) {
    await loadCyclesOverview();
    alert(result.message);
  } else {
    alert("Fehler: " + (result?.message ?? "Unbekannter Fehler."));
  }
}

async function loadCyclesOverview() {
  const d = window._lastStatus;
  const hetaCode = d?.heta_code;
  const activated = !!d?.heta_activated;

  const noCodeEl      = document.getElementById("cycles-no-code");
  const profileContent = document.getElementById("profile-content");
  const tableWrap     = document.getElementById("cycles-table-wrap");
  const emptyEl       = document.getElementById("cycles-empty");

  if (!hetaCode || !activated) {
    if (noCodeEl)      noCodeEl.classList.remove("hidden");
    if (profileContent) profileContent.classList.add("hidden");
    if (tableWrap)     tableWrap.classList.add("hidden");
    if (emptyEl)       emptyEl.classList.add("hidden");
    return;
  }

  if (noCodeEl) noCodeEl.classList.add("hidden");

  const encoded = encodeURIComponent(hetaCode);
  const [cycles, profile] = await Promise.all([
    apiFetch(`/api/cycles?heta_code=${encoded}`),
    apiFetch(`/api/profile?heta_code=${encoded}`),
  ]);

  renderProfileStats(profile);
  renderCyclesTable(cycles || []);
}

function renderProfileStats(profile) {
  const badge = document.getElementById("profile-validity-badge");
  if (badge) {
    if (profile?.profile_valid) {
      badge.textContent = "VALIDIERT";
      badge.className = "badge badge-ok";
    } else if (profile) {
      badge.textContent = "LERNEND";
      badge.className = "badge badge-warn";
    } else {
      badge.textContent = "KEIN PROFIL";
      badge.className = "badge badge-observe";
    }
  }

  const profileContent = document.getElementById("profile-content");
  if (!profile) {
    if (profileContent) profileContent.classList.add("hidden");
    return;
  }
  if (profileContent) profileContent.classList.remove("hidden");

  const dpClean = profile.reference_dp_clean;
  setText("prof-dp-clean",     dpClean > 0 ? fmt(dpClean, 3) : "–");
  setText("prof-r-eff",        fmt(profile.reference_r_eff, 5));
  setText("prof-loading-rate", ((profile.reference_loading_rate ?? 0) * 1000).toFixed(3));
  setText("prof-avg-flow",     fmt(profile.reference_avg_flow, 1));
  setText("prof-avg-temp",     fmt(profile.reference_avg_temp, 1));
  // Berechneten dp_clean auch in der Einstellungs-Anzeige zeigen
  const dpCleanDisplay = document.getElementById("s-dp-clean-display");
  if (dpCleanDisplay) dpCleanDisplay.textContent = dpClean > 0 ? fmt(dpClean, 3) : "–";

  const count = profile.cycles_count ?? 0;
  const req   = window._lastStatus?.required_cycles ?? 3;
  setText("prof-cycles-count",  count);
  setText("prof-cycles-needed", `von ${req} erforderlich`);

  const bar = document.getElementById("prof-progress-bar");
  if (bar) {
    bar.style.width      = Math.min(100, (count / req) * 100) + "%";
    bar.style.background = profile.profile_valid ? "var(--ok-green)" : "var(--warn-yellow)";
  }
}

function renderCyclesTable(cycles) {
  const tbody    = document.getElementById("cycles-tbody");
  const emptyEl  = document.getElementById("cycles-empty");
  const tableWrap = document.getElementById("cycles-table-wrap");
  const countBadge = document.getElementById("cycles-count-badge");
  if (!tbody) return;

  if (!cycles || cycles.length === 0) {
    tbody.innerHTML = "";
    if (emptyEl)   emptyEl.classList.remove("hidden");
    if (tableWrap) tableWrap.classList.add("hidden");
    if (countBadge) countBadge.style.display = "none";
    return;
  }

  if (emptyEl)   emptyEl.classList.add("hidden");
  if (tableWrap) tableWrap.classList.remove("hidden");

  if (countBadge) {
    countBadge.textContent = `${cycles.length} Zyklen`;
    countBadge.style.display = "";
  }

  const hetaCode  = window._lastStatus?.heta_code || "";
  const reqCycles = window._lastStatus?.required_cycles ?? 3;
  const rows = cycles.slice().reverse().map((c, idx) => {
    const dt      = new Date((c.start_time ?? 0) * 1000);
    const dateStr = dt.toLocaleDateString("de-DE",  { day: "2-digit", month: "2-digit", year: "numeric" });
    const timeStr = dt.toLocaleTimeString("de-DE",  { hour: "2-digit", minute: "2-digit" });
    const durMin  = Math.round((c.duration_seconds ?? 0) / 60);
    const durStr  = durMin >= 60
      ? `${Math.floor(durMin / 60)}h ${durMin % 60}min`
      : `${durMin} min`;
    const rateMs  = ((c.loading_rate ?? 0) * 1000).toFixed(3);
    const ok      = c.confirmed_filter_change;
    const cycleNum = cycles.length - idx;
    const isLearning = cycleNum <= reqCycles;
    const rowCls  = ok ? "cycle-confirmed" : "";

    // Lernzyklus-Badge für die ersten reqCycles Zyklen
    const learningBadge = isLearning
      ? `<span class="badge badge-learn" title="Dieser Zyklus bildet die Referenz">Lernzyklus</span>`
      : "";

    // Problemmeldungen aus events_json
    let events = [];
    try { events = JSON.parse(c.events_json || "[]"); } catch (_) {}
    const hasProblems = events.length > 0;
    const problemsBadge = hasProblems
      ? `<span class="badge badge-warn" title="${events.map(e=>e.message).join('; ')}">&#9888; ${events.length}</span>`
      : `<span style="color:var(--text-muted)">–</span>`;

    // Diagramm-Button
    const cycleDataAttr = [
      `data-cycle-id="${c.id}"`,
      `data-cycle-num="${cycleNum}"`,
      `data-date="${dateStr} ${timeStr}"`,
      `data-heta="${hetaCode}"`,
      `data-duration="${c.duration_seconds ?? 0}"`,
      `data-events='${(c.events_json || "[]").replace(/'/g, "&apos;")}'`,
    ].join(" ");

    return `<tr class="${rowCls}${isLearning ? " cycle-learning" : ""}">
      <td>${cycleNum} ${learningBadge}</td>
      <td><span class="cycle-date">${dateStr}</span><span class="cycle-time">${timeStr}</span></td>
      <td>${durStr}</td>
      <td>${fmt(c.start_dp, 3)} bar</td>
      <td>${fmt(c.end_dp, 3)} bar</td>
      <td>${fmt(c.average_flow, 1)} l/min</td>
      <td>${fmt(c.average_temperature, 1)} °C</td>
      <td>${rateMs} mbar/s</td>
      <td class="${ok ? "cycle-check-ok" : ""}">${ok ? "✓" : "–"}</td>
      <td>${problemsBadge}</td>
      <td><button class="btn btn-ghost btn-sm cycle-chart-btn" ${cycleDataAttr}>&#128202;</button></td>
    </tr>`;
  });

  tbody.innerHTML = rows.join("");

  // Event-Listener für Diagramm-Buttons
  tbody.querySelectorAll(".cycle-chart-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      openCycleModal(
        Number(btn.dataset.cycleId),
        Number(btn.dataset.cycleNum),
        btn.dataset.date,
        btn.dataset.heta,
        Number(btn.dataset.duration),
        btn.dataset.events,
      );
    });
  });
}
