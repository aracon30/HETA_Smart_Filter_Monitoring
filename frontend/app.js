/**
 * HETA Smart Filter Monitoring – Frontend-Applikation
 * Pollt die REST-API, steuert Onboarding-Assistent und passwortgeschützten Einstellungsbereich.
 */

const API_BASE = "";
const POLL_INTERVAL_MS = 1500;

// Lernrelevante Parameter – Änderung löst Reset der Lernphasen aus
const LEARNING_SENSITIVE = ["dp_limit_bar", "dp_clean_bar", "flow_max_l_min", "pressure_range_bar"];

// Chart.js Instanz (kombiniert)
const MAX_CHART_POINTS = 300;
let combinedChart = null;

// Session-Token für Einstellungsbereich (wird im sessionStorage gehalten)
const TOKEN_KEY = "heta_settings_token";

// Tab-Navigation
let _activeTab = "dashboard";
let _cyclesPollTick = 0;

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
  updateSimDemoPanel(d);
  updateAnalysisSection(d);
}

// ============================================================
// Chart (kombiniert)
// ============================================================

function initCharts() {
  const ctx = document.getElementById("chart-combined");
  if (!ctx) return;

  const dpLimit = window._settings?.dp_limit_bar ?? 2.5;

  combinedChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "p1 [bar]",
          data: [],
          yAxisID: "yPressure",
          borderColor: "#7bafd4",
          backgroundColor: "transparent",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.3,
        },
        {
          label: "p2 [bar]",
          data: [],
          yAxisID: "yPressure",
          borderColor: "#a8c8e8",
          backgroundColor: "transparent",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.3,
        },
        {
          label: "Δp [bar]",
          data: [],
          yAxisID: "yPressure",
          borderColor: "#0077cc",
          backgroundColor: "rgba(0,119,204,0.07)",
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          fill: true,
        },
        {
          label: "Q [l/min]",
          data: [],
          yAxisID: "yFlow",
          borderColor: "#1a9e3c",
          backgroundColor: "transparent",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.3,
        },
        {
          label: "R_eff [bar·min/l]",
          data: [],
          yAxisID: "yReff",
          borderColor: "#7b1fa2",
          backgroundColor: "transparent",
          borderWidth: 1.5,
          borderDash: [4, 2],
          pointRadius: 0,
          tension: 0.3,
        },
        {
          label: "Reststandzeit [min]",
          data: [],
          yAxisID: "yTime",
          borderColor: "#d4820a",
          backgroundColor: "transparent",
          borderWidth: 1.5,
          borderDash: [4, 2],
          pointRadius: 0,
          tension: 0.3,
        },
      ],
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true,
          position: "top",
          labels: {
            usePointStyle: true,
            padding: 14,
            font: { size: 11 },
            color: "#1a1a2e",
          },
        },
        tooltip: {
          mode: "index",
          intersect: false,
          backgroundColor: "rgba(15, 25, 40, 0.93)",
          titleColor: "#a8c8f0",
          bodyColor: "#e0eaf5",
          borderColor: "#1c3a5c",
          borderWidth: 1,
          padding: 10,
          usePointStyle: true,
          callbacks: {
            label: (ctx) => {
              const v = ctx.parsed.y;
              if (v == null || isNaN(v)) return null;
              const decimals = {
                "p1 [bar]": 3, "p2 [bar]": 3, "Δp [bar]": 3,
                "Q [l/min]": 1, "R_eff [bar·min/l]": 5, "Reststandzeit [min]": 1,
              };
              return ` ${ctx.dataset.label}: ${v.toFixed(decimals[ctx.dataset.label] ?? 2)}`;
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
              borderColor: "rgba(192, 57, 43, 0.65)",
              borderWidth: 1.5,
              borderDash: [6, 3],
              label: {
                display: true,
                content: `dp-Limit (${Number(dpLimit).toFixed(2)} bar)`,
                position: "end",
                backgroundColor: "rgba(192, 57, 43, 0.08)",
                color: "#c0392b",
                font: { size: 10 },
                padding: { x: 5, y: 2 },
              },
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { maxTicksLimit: 8, maxRotation: 0, font: { size: 10 }, color: "#5f6878" },
          grid: { color: "rgba(100,130,160,0.12)" },
        },
        yPressure: {
          type: "linear",
          position: "left",
          min: 0,
          title: { display: true, text: "Druck [bar]", font: { size: 10 }, color: "#0077cc" },
          ticks: { font: { size: 10 }, color: "#0077cc" },
          grid: { color: "rgba(100,130,160,0.12)" },
        },
        yFlow: {
          type: "linear",
          position: "right",
          min: 0,
          title: { display: true, text: "Durchfluss [l/min]", font: { size: 10 }, color: "#1a9e3c" },
          ticks: { font: { size: 10 }, color: "#1a9e3c" },
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
}

function pushChartData(status) {
  if (!combinedChart) return;
  const label = new Date().toLocaleTimeString("de-DE");
  const remMin = status.remaining_seconds != null ? status.remaining_seconds / 60 : null;
  const datasets = combinedChart.data.datasets;
  combinedChart.data.labels.push(label);
  datasets[0].data.push(status.p1_bar ?? null);
  datasets[1].data.push(status.p2_bar ?? null);
  datasets[2].data.push(status.dp_bar ?? null);
  datasets[3].data.push(status.flow_l_min ?? null);
  datasets[4].data.push(status.r_eff ?? null);
  datasets[5].data.push(remMin);
  if (combinedChart.data.labels.length > MAX_CHART_POINTS) {
    combinedChart.data.labels.shift();
    datasets.forEach(ds => ds.data.shift());
  }
  combinedChart.update("none");
}

function resetChartZoom() {
  if (combinedChart) combinedChart.resetZoom();
}

function updateChartDpLimit(dpLimitBar) {
  if (!combinedChart) return;
  const ann = combinedChart.options.plugins.annotation.annotations.dpLimitLine;
  ann.value = dpLimitBar;
  ann.label.content = `dp-Limit (${Number(dpLimitBar).toFixed(2)} bar)`;
  combinedChart.update("none");
}

// ============================================================
// Steuerungs-Buttons
// ============================================================

async function startSimulation() {
  await apiFetch("/api/simulation/start", "POST");
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
  combinedChart.update("none");
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
  setAnalysisDev("an-dp-dev", dpDev, "%", 15, 40);

  // R_eff vs. Referenzkurve
  const reffRef = d.analysis_reff_ref ?? 0;
  const reffCur = d.analysis_reff_cur ?? d.r_eff ?? 0;
  const reffDev = d.analysis_reff_deviation_pct ?? 0;
  setText("an-reff-ref", fmt(reffRef, 5) + " bar·min/l");
  setText("an-reff-cur", fmt(reffCur, 5) + " bar·min/l");
  setAnalysisDev("an-reff-dev", reffDev, "%", 15, 40);

  // Durchfluss Q vs. Referenzkurve
  const flRef = d.analysis_flow_ref ?? 0;
  const flCur = d.flow_l_min        ?? 0;
  const flDev = d.analysis_flow_deviation_pct ?? 0;
  setText("an-fl-ref", fmt(flRef, 1) + " l/min");
  setText("an-fl-cur", fmt(flCur, 1) + " l/min");
  setAnalysisDev("an-fl-dev", flDev, "%", 15, 30);

  // Temperatur T vs. Referenzkurve
  const tRef = d.analysis_temp_ref      ?? 0;
  const tCur = d.temperature_c          ?? 0;
  const tDev = d.analysis_temp_deviation ?? 0;
  setText("an-tmp-ref", fmt(tRef, 1) + " °C");
  setText("an-tmp-cur", fmt(tCur, 1) + " °C");
  setAnalysisDev("an-tmp-dev", tDev, "°C", 8, 20, true);

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
let _rateValues = { dp_factor: 1.0, flow_factor: 1.0, temp_offset: 0.0, p1_bar: 3.5 };

function updateSimDemoPanel(d) {
  const panel = document.getElementById("sim-demo-panel");
  if (!panel) return;

  const simMode = !!d.simulation_mode;
  panel.classList.toggle("hidden", !simMode);
  if (!simMode) return;

  const profileValid = d.profile_status === "VALIDIERT" && d.heta_activated;
  const learnArea    = document.getElementById("sim-learn-area");
  const manualArea   = document.getElementById("sim-manual-area");

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
    if (learnArea)  learnArea.classList.add("hidden");
    if (manualArea) manualArea.classList.remove("hidden");
    const toggle = document.getElementById("sim-manual-toggle");
    if (toggle && !toggle.dataset.userSet) toggle.checked = !!d.sim_rates_active;
    updateComparison(d);
  } else {
    if (learnArea)  learnArea.classList.remove("hidden");
    if (manualArea) manualArea.classList.add("hidden");
  }
}

function updateComparison(d) {
  const cmpEl = document.getElementById("sim-comparison");
  if (!cmpEl) return;

  const active = !!d.sim_rates_active;
  cmpEl.classList.toggle("hidden", !active);
  if (!active) return;

  const s = window._settings || {};
  const dp_clean  = s.dp_clean_bar            ?? 0.2;
  const dp_limit  = s.dp_limit_bar            ?? 2.5;
  const samp      = parseFloat(s.sampling_interval_seconds ?? 1);
  const cyc_steps = s.cycle_steps             ?? 300;
  const ref_rate  = (dp_limit - dp_clean) / Math.max(samp * cyc_steps, 1);
  const ref_flow  = (s.flow_max_l_min ?? 150) * 0.53;
  const ref_temp  = 27.5;

  const dp_factor   = d.sim_dp_factor    ?? 1.0;
  const flow_factor = d.sim_flow_factor  ?? 1.0;
  const temp_offset = d.sim_temp_offset  ?? 0.0;
  const dp_dev      = d.sim_dp_deviation_pct   ?? 0.0;
  const flow_dev    = d.sim_flow_deviation_pct ?? 0.0;
  const temp_dev    = d.sim_temp_deviation     ?? 0.0;

  setText("cmp-dp-ref",   `${(ref_rate * 1000).toFixed(2)} mbar/s`);
  setText("cmp-dp-cur",   `${(ref_rate * dp_factor * 1000).toFixed(2)} mbar/s`);
  setDev("cmp-dp-dev",    dp_dev,   "%");

  setText("cmp-flow-ref", `${ref_flow.toFixed(0)} l/min`);
  setText("cmp-flow-cur", `${(ref_flow * flow_factor).toFixed(0)} l/min`);
  setDev("cmp-flow-dev",  flow_dev, "%");

  setText("cmp-temp-ref", `${ref_temp.toFixed(1)} °C`);
  setText("cmp-temp-cur", `${(ref_temp + temp_offset).toFixed(1)} °C`);
  setDev("cmp-temp-dev",  temp_dev, "°C", true);

  setText("sim-diagnosis", buildSimDiagnosis(dp_factor, flow_factor, temp_offset));
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

function buildSimDiagnosis(dpF, flowF, tempOff) {
  const hints = [];
  if (dpF > 1.5 && flowF < 0.8) {
    hints.push("💡 Schnelle Beladung + reduzierter Durchfluss → Verdacht auf Filterverstopfung oder erhöhten Verschmutzungseintrag.");
  } else if (dpF > 1.5) {
    hints.push("💡 Δp steigt deutlich schneller als gelernt → erhöhte Partikelkonzentration im Medium oder beschädigtes Filterelement möglich.");
  } else if (dpF < 0.6) {
    hints.push("💡 Sehr langsame Beladung → Prozess läuft mit deutlich reduzierter Last. Filterwechselintervall verlängert sich.");
  }
  if (flowF < 0.7) {
    hints.push("💡 Durchfluss stark reduziert → mögliche Ursache: Pumpenproblem, Leckage im Bypass oder Vorverstopfung.");
  } else if (flowF > 1.2) {
    hints.push("💡 Erhöhter Durchfluss → kürzere Filterstandzeit zu erwarten, Filterwechselintervall verkürzt sich.");
  }
  if (tempOff > 20) {
    hints.push("💡 Deutlich erhöhte Prozesstemperatur → Filterkapazität kann reduziert sein, Materialbeständigkeit prüfen.");
  } else if (tempOff < -15) {
    hints.push("💡 Deutlich niedrigere Temperatur → Viskositätsänderung kann den Differenzdruck beeinflussen.");
  }
  if (hints.length === 0) {
    if (Math.abs(dpF - 1.0) < 0.1 && Math.abs(flowF - 1.0) < 0.1 && Math.abs(tempOff) < 5) {
      return "✔ Alle Parameter im gelernten Normalbereich – kein Handlungsbedarf.";
    }
    hints.push("💡 Leichte Abweichungen vom gelernten Profil – Prozess und Filter im Auge behalten.");
  }
  return hints.join(" ");
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
  if (which === "p1") {
    _rateValues.p1_bar = v;
    setText("sv-p1", v.toFixed(1) + " bar");
  } else if (which === "dp_rate") {
    _rateValues.dp_factor = v / 100.0;
    setText("sv-dp-rate", Math.round(v) + " %");
  } else if (which === "flow_rate") {
    _rateValues.flow_factor = v / 100.0;
    setText("sv-flow-rate", Math.round(v) + " %");
  } else if (which === "temp_off") {
    _rateValues.temp_offset = v;
    const sign = v > 0 ? "+" : "";
    setText("sv-temp-off", sign + v.toFixed(0) + " °C");
  }
  const toggle = document.getElementById("sim-manual-toggle");
  if (toggle && toggle.checked) scheduleSendValues();
}

function scheduleSendValues() {
  clearTimeout(_sliderDebounce);
  _sliderDebounce = setTimeout(sendSliderValues, 150);
}

async function sendSliderValues() {
  await apiFetch("/api/simulation/set-rates", "POST", {
    active:      true,
    dp_factor:   _rateValues.dp_factor,
    flow_factor: _rateValues.flow_factor,
    temp_offset: _rateValues.temp_offset,
    p1_bar:      _rateValues.p1_bar,
  });
}

async function onManualToggle(checkbox) {
  checkbox.dataset.userSet = "1";
  if (checkbox.checked) {
    await sendSliderValues();
  } else {
    clearTimeout(_sliderDebounce);
    await apiFetch("/api/simulation/set-rates", "POST", { active: false });
  }
  setTimeout(() => { checkbox.dataset.userSet = ""; }, 3000);
}

function resetSliders() {
  _rateValues = { dp_factor: 1.0, flow_factor: 1.0, temp_offset: 0.0, p1_bar: 3.5 };
  document.getElementById("sl-p1").value        = 3.5;
  document.getElementById("sl-dp-rate").value   = 100;
  document.getElementById("sl-flow-rate").value = 100;
  document.getElementById("sl-temp-off").value  = 0;
  setText("sv-p1",        "3.5 bar");
  setText("sv-dp-rate",   "100 %");
  setText("sv-flow-rate", "100 %");
  setText("sv-temp-off",  "0 °C");
  const toggle = document.getElementById("sim-manual-toggle");
  if (toggle && toggle.checked) scheduleSendValues();
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

  setText("prof-r-eff",        fmt(profile.reference_r_eff, 5));
  setText("prof-loading-rate", ((profile.reference_loading_rate ?? 0) * 1000).toFixed(3));
  setText("prof-avg-flow",     fmt(profile.reference_avg_flow, 1));
  setText("prof-avg-temp",     fmt(profile.reference_avg_temp, 1));

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
    const rowCls  = ok ? "cycle-confirmed" : "";
    return `<tr class="${rowCls}">
      <td>${cycles.length - idx}</td>
      <td><span class="cycle-date">${dateStr}</span><span class="cycle-time">${timeStr}</span></td>
      <td>${durStr}</td>
      <td>${fmt(c.start_dp, 3)} bar</td>
      <td>${fmt(c.end_dp, 3)} bar</td>
      <td>${fmt(c.average_flow, 1)} l/min</td>
      <td>${fmt(c.average_temperature, 1)} °C</td>
      <td>${rateMs} mbar/s</td>
      <td class="${ok ? "cycle-check-ok" : ""}">${ok ? "✓" : "–"}</td>
    </tr>`;
  });

  tbody.innerHTML = rows.join("");
}
