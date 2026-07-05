/**
 * HETA Smart Filter Monitoring – Frontend-Applikation
 * Pollt die REST-API, steuert Onboarding-Assistent und passwortgeschützten Einstellungsbereich.
 *
 * Lädt nach utils.js, api.js und charts.js.
 * Konstanten API_BASE, POLL_INTERVAL_MS, TOKEN_KEY, MAX_CHART_POINTS, DS_COLORS
 * sowie Hilfsfunktionen fmt, fmtSeconds, setText, setInputVal, showMsg, healthColor
 * sind in utils.js definiert.
 * apiFetch / apiFetchAuth sind in api.js definiert.
 * Chart-Funktionen sind in charts.js definiert.
 */

// Lernrelevante Parameter – Änderung löst Reset der Lernphasen aus
const LEARNING_SENSITIVE = ["dp_limit_bar", "flow_max_l_min", "pressure_range_bar"];

// Aktuelle Toleranzwerte (als Fraktion; werden nach dem Laden der Einstellungen gesetzt)
let _tolDp   = 0.25;
let _tolReff = 0.25;
let _tolFlow = 0.25;
let _tolTempC = 10.0;

let _cyclesPollTick = 0;
let _prevAwaiting = false;

// ============================================================
// Init
// ============================================================

document.addEventListener("DOMContentLoaded", async () => {
  initCharts();
  const onboardingDone = await checkOnboarding();
  if (onboardingDone) startPolling();
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
// Onboarding
// ============================================================

let _wizardStep = 1;
const WIZARD_TOTAL = 8;
let _hetaActivatedInWizard = false;

async function checkOnboarding() {
  const banner   = document.getElementById("connection-error-banner");
  const bannerTx = document.getElementById("connection-error-text");
  let attempt = 0;
  while (true) {
    try {
      const data = await apiFetch("/api/onboarding/status");
      if (banner) banner.classList.add("hidden");   // Verbindung wieder OK
      if (data && !data.onboarding_complete) {
        showOnboarding();
        return false;
      }
      return true;
    } catch (e) {
      attempt++;
      console.warn(`Onboarding-Status nicht abrufbar (Versuch ${attempt}):`, e);
      if (banner) {
        if (bannerTx) bannerTx.textContent =
          `Server nicht erreichbar – neuer Versuch in 3 s… (Versuch ${attempt})`;
        banner.classList.remove("hidden");
      }
      await new Promise(r => setTimeout(r, 3000));
    }
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

  // Schritt 7: Zusammenfassung befüllen
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
  if (step === 2) {
    // HETA-Code-Schritt: asynchrone Validierung, daher hier sync-false zurückgeben
    // und wizardNext() nach erfolgreicher Aktivierung selbst weiterschalten
    _wizardActivateHeta();
    return false;
  }
  if (step === 7) {
    const pw  = document.getElementById("ob-password").value;
    const pw2 = document.getElementById("ob-password-confirm").value;
    if (pw.length < 4) { showMsg("ob-pw-msg", "Passwort muss mindestens 4 Zeichen haben.", true); return false; }
    if (pw !== pw2)     { showMsg("ob-pw-msg", "Passwörter stimmen nicht überein.", true); return false; }
    showMsg("ob-pw-msg", "", false);
  }
  return true;
}

async function _wizardActivateHeta() {
  const code = (document.getElementById("ob-heta-code")?.value ?? "").trim();
  const pin  = (document.getElementById("ob-heta-pin")?.value  ?? "").trim();
  if (!code || !pin) {
    showMsg("ob-heta-msg", "Bitte HETA-Code und PIN eingeben oder den Schritt überspringen.", true);
    return;
  }
  showMsg("ob-heta-msg", "Wird geprüft …", false);
  try {
    const result = await apiFetch("/api/heta/activate", "POST", { heta_code: code, pin });
    if (result?.valid) {
      _hetaActivatedInWizard = true;
      showMsg("ob-heta-msg", `✓ HETA-${result.heta_code} erfolgreich aktiviert.`, false);
      _wizardStep++;
      renderWizardStep();
    } else {
      showMsg("ob-heta-msg", result?.message ?? "Ungültiger Code oder PIN.", true);
    }
  } catch (e) {
    showMsg("ob-heta-msg", "Server nicht erreichbar – bitte erneut versuchen oder überspringen.", true);
  }
}

function wizardSkipHeta() {
  _hetaActivatedInWizard = false;
  showMsg("ob-heta-msg", "", false);
  _wizardStep++;
  renderWizardStep();
}

function buildSummary() {
  const mode = document.querySelector("input[name='op-mode']:checked")?.value === "hardware"
    ? "Hardwaremodus" : "Simulationsmodus";
  const cycleMode = document.querySelector("input[name='cycle-mode']:checked")?.value === "batch"
    ? "Intervallbetrieb (Batch)" : "Dauerbetrieb (kontinuierlich)";
  const hetaCode = (document.getElementById("ob-heta-code")?.value ?? "").trim();
  const hetaLine = _hetaActivatedInWizard && hetaCode
    ? `HETA-${hetaCode} ✓`
    : "Nicht aktiviert (kann später im System-Tab erfolgen)";
  const lines = [
    ["HETA-Code", hetaLine],
    ["Betriebsart", mode],
    ["Betriebsweise", cycleMode],
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
  const cycleMode = document.querySelector("input[name='cycle-mode']:checked")?.value ?? "continuous";
  const payload = {
    simulation_mode:    simMode,
    operation_mode:     cycleMode,
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
    startPolling();  // Polling jetzt erst starten
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
  document.getElementById("settings-tabs")?.classList.add("hidden");
  setTimeout(() => document.getElementById("settings-pw-input")?.focus(), 100);
}

function showSettingsForm() {
  document.getElementById("settings-login-area").classList.add("hidden");
  document.getElementById("settings-tabs")?.classList.remove("hidden");
  document.getElementById("settings-form-area").classList.remove("hidden");
  loadSettingsIntoForm();
  watchSettingsChanges();
  initSettingsTabs();
}

function initSettingsTabs() {
  const nav = document.getElementById("settings-tabs");
  if (!nav || nav.dataset.tabsInit) return;
  nav.dataset.tabsInit = "1";
  nav.addEventListener("click", e => {
    const btn = e.target.closest(".settings-tab");
    if (!btn) return;
    nav.querySelectorAll(".settings-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const target = btn.dataset.tab;
    document.querySelectorAll(".settings-tab-panel").forEach(p => {
      p.classList.toggle("active", p.id === target);
    });
  });
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

    // Betriebsweise & Durchflusserkennung
    const opModeEl = document.getElementById("s-operation-mode");
    if (opModeEl) opModeEl.value = s.operation_mode ?? "continuous";
    const thrEl = document.getElementById("s-flow-threshold");
    if (thrEl) thrEl.value = s.flow_start_threshold_l_min != null ? s.flow_start_threshold_l_min : "";
    const stabEl = document.getElementById("s-flow-stability");
    if (stabEl) stabEl.value = s.flow_stability_seconds != null ? s.flow_stability_seconds : "";
    const tolEl = document.getElementById("s-flow-pause-tol");
    if (tolEl) tolEl.value = s.flow_pause_tolerance_seconds != null ? s.flow_pause_tolerance_seconds : "";

    // MQTT
    const mqttCb = document.getElementById("s-mqtt-enabled");
    if (mqttCb) {
      mqttCb.checked = !!s.mqtt_enabled;
      document.getElementById("s-mqtt-fields")?.classList.toggle("hidden", !s.mqtt_enabled);
    }
    setInputVal("s-mqtt-broker",    s.mqtt_broker    ?? "localhost");
    setInputVal("s-mqtt-port",      s.mqtt_port      ?? 1883);
    setInputVal("s-mqtt-client-id", s.mqtt_client_id ?? "heta_monitor");

    // Modbus TCP
    const modbusCb = document.getElementById("s-modbus-enabled");
    if (modbusCb) {
      modbusCb.checked = !!s.modbus_enabled;
      document.getElementById("s-modbus-fields")?.classList.toggle("hidden", !s.modbus_enabled);
    }
    setInputVal("s-modbus-host", s.modbus_host ?? "0.0.0.0");
    setInputVal("s-modbus-port", s.modbus_port ?? 502);

    // dp_clean aus Profil laden (wird aus Lernzyklen berechnet)
    // Kein HETA-Code → Backend liefert DEMO-Profil als Fallback
    try {
      const hetaCode = window._lastStatus?.heta_code || "";
      const profile = await apiFetch(`/api/profile?heta_code=${encodeURIComponent(hetaCode)}`);
      const dpCleanEl = document.getElementById("s-dp-clean-display");
      if (dpCleanEl) {
        dpCleanEl.textContent = (profile?.reference_dp_clean > 0)
          ? fmt(profile.reference_dp_clean, 3) + " bar"
          : "–";
      }
    } catch (_) { /* Profil noch nicht vorhanden */ }
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
    operation_mode:            document.getElementById("s-operation-mode")?.value ?? "continuous",
    flow_start_threshold_l_min: document.getElementById("s-flow-threshold")?.value !== ""
      ? parseFloat(document.getElementById("s-flow-threshold").value) : null,
    flow_stability_seconds: document.getElementById("s-flow-stability")?.value !== ""
      ? parseInt(document.getElementById("s-flow-stability").value, 10) : null,
    flow_pause_tolerance_seconds: document.getElementById("s-flow-pause-tol")?.value !== ""
      ? parseInt(document.getElementById("s-flow-pause-tol").value, 10) : null,
    tolerance_dp_pct:   parseFloat(document.getElementById("s-tol-dp").value)   / 100,
    tolerance_reff_pct: parseFloat(document.getElementById("s-tol-reff").value) / 100,
    tolerance_flow_pct: parseFloat(document.getElementById("s-tol-flow").value) / 100,
    tolerance_temp_c:   parseFloat(document.getElementById("s-tol-temp").value),
    // MQTT
    mqtt_enabled:    document.getElementById("s-mqtt-enabled")?.checked ?? false,
    mqtt_broker:     document.getElementById("s-mqtt-broker")?.value.trim()    || "localhost",
    mqtt_port:       parseInt(document.getElementById("s-mqtt-port")?.value, 10) || 1883,
    mqtt_client_id:  document.getElementById("s-mqtt-client-id")?.value.trim() || "heta_monitor",
    // Modbus TCP
    modbus_enabled:  document.getElementById("s-modbus-enabled")?.checked ?? false,
    modbus_host:     document.getElementById("s-modbus-host")?.value.trim()    || "0.0.0.0",
    modbus_port:     parseInt(document.getElementById("s-modbus-port")?.value, 10) || 502,
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

let _pollingStarted = false;
function startPolling() {
  if (_pollingStarted) return;
  _pollingStarted = true;
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

  // Zyklen-Bereich alle ~15 s aktualisieren (alle 10 Poll-Zyklen)
  _cyclesPollTick++;
  if (_cyclesPollTick % 10 === 1) loadCyclesOverview();

  // Sensorfehler-Overlay (Hardwaremodus) hat Vorrang
  handleSensorFault(d);

  // Fluss-Warte- und Pause-Overlays
  updateFlowOverlays(d);

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

  updateHetaActivationSection(d);

  // Transport-Steuerung (Play/Pause/Reset) – nur im Simulationsmodus, im Realmodus steuert der Durchfluss
  updateHeaderTransport(d);

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
  updateDevRawPanel(d);
}

function updateDevRawPanel(d) {
  const panel = document.getElementById("dev-raw-panel");
  if (!panel) return;
  const raw = d.dev_raw;
  if (!raw) { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");

  const statusClass = s => s === "OK" ? "dev-status-ok" : "dev-status-error";

  setText("dev-p1-ma",      raw.p1_ma.toFixed(4) + " mA");
  setText("dev-p1-bar",     fmt(d.p1_bar, 3) + " bar");
  document.getElementById("dev-p1-status").className = statusClass(raw.p1_status);
  setText("dev-p1-status",  raw.p1_status);

  setText("dev-p2-ma",      raw.p2_ma.toFixed(4) + " mA");
  setText("dev-p2-bar",     fmt(d.p2_bar, 3) + " bar");
  document.getElementById("dev-p2-status").className = statusClass(raw.p2_status);
  setText("dev-p2-status",  raw.p2_status);

  setText("dev-temp-ma",    raw.temp_ma.toFixed(4) + " mA");
  setText("dev-temp-bar",   fmt(d.temperature_c, 1) + " °C");
  document.getElementById("dev-temp-status").className = statusClass(raw.temp_status);
  setText("dev-temp-status", raw.temp_status);

  setText("dev-flow-ma",    raw.flow_ma.toFixed(4) + " mA");
  setText("dev-flow-bar",   fmt(d.flow_l_min, 1) + " l/min");
  document.getElementById("dev-flow-status").className = statusClass(raw.flow_status);
  setText("dev-flow-status", raw.flow_status);
}

// ============================================================
// Fluss-Overlays (Durchflusserkennung aktiv / Zyklus pausiert)
// ============================================================

let _flowOverlayMinimized = false;
let _flowOverlayActiveType = null; // "wait" | "pause" | null

function minimizeFlowOverlay() {
  _flowOverlayMinimized = true;
  document.getElementById("flow-wait-overlay").classList.add("hidden");
  document.getElementById("flow-pause-overlay").classList.add("hidden");
  _applyFlowCardIndicator();
}


function expandFlowOverlay() {
  if (!_flowOverlayMinimized || !_flowOverlayActiveType) return;
  _flowOverlayMinimized = false;
  _applyFlowCardIndicator();
  if (_flowOverlayActiveType === "wait")
    document.getElementById("flow-wait-overlay").classList.remove("hidden");
  else if (_flowOverlayActiveType === "pause")
    document.getElementById("flow-pause-overlay").classList.remove("hidden");
}

function _applyFlowCardIndicator() {
  const cardEl     = document.getElementById("card-flow");
  const indicEl    = document.getElementById("flow-card-indicator");
  const waitIndEl  = document.getElementById("flow-card-wait");
  const pauseIndEl = document.getElementById("flow-card-pause");
  if (!cardEl || !indicEl) return;

  const show = _flowOverlayMinimized && !!_flowOverlayActiveType;
  indicEl.classList.toggle("hidden", !show);
  cardEl.classList.toggle("flow-card--interactive", show);
  cardEl.classList.toggle("pause-mode", show && _flowOverlayActiveType === "pause");

  if (waitIndEl)  waitIndEl.classList.toggle("hidden",  _flowOverlayActiveType !== "wait");
  if (pauseIndEl) pauseIndEl.classList.toggle("hidden", _flowOverlayActiveType !== "pause");
}

function updateFlowOverlays(d) {
  const waitEl  = document.getElementById("flow-wait-overlay");
  const pauseEl = document.getElementById("flow-pause-overlay");
  if (!waitEl || !pauseEl) return;

  // Sensor-Fault-Overlay hat Vorrang – Flow-Overlays nicht anzeigen
  if (d.sensor_fault) {
    waitEl.classList.add("hidden");
    pauseEl.classList.add("hidden");
    return;
  }

  const waiting = !!d.waiting_for_flow;
  const paused  = !!d.cycle_paused;
  const newType = waiting ? "wait" : paused ? "pause" : null;

  // Wenn der Zustand wegfällt → Minimierung aufheben
  if (!newType && _flowOverlayActiveType) {
    _flowOverlayMinimized  = false;
    _flowOverlayActiveType = null;
    _applyFlowCardIndicator();
  }
  // Wenn Zustand wechselt (wait→pause oder pause→wait) → Minimierung aufheben
  if (newType && _flowOverlayActiveType && newType !== _flowOverlayActiveType) {
    _flowOverlayMinimized = false;
  }
  _flowOverlayActiveType = newType;

  // Overlays ein-/ausblenden (nur wenn nicht minimiert)
  if (!_flowOverlayMinimized) {
    waitEl.classList.toggle("hidden",  !waiting);
    pauseEl.classList.toggle("hidden", !paused);
  }

  // Daten aktualisieren
  if (waiting) {
    const q   = d.flow_check_q   ?? 0;
    const thr = d.flow_threshold  ?? 0;
    const pct = d.flow_stable_pct ?? 0;

    document.getElementById("flow-wait-q").textContent   = `${q.toFixed(1)} l/min`;
    document.getElementById("flow-wait-thr").textContent = `${thr.toFixed(1)} l/min`;
    document.getElementById("flow-wait-pct").textContent = pct;
    document.getElementById("flow-wait-bar").style.width = `${Math.min(pct, 100)}%`;
    // Kachel-Kompaktanzeige
    const barEl = document.getElementById("flow-card-bar");
    const subEl = document.getElementById("flow-card-sub");
    if (barEl) barEl.style.width = `${Math.min(pct, 100)}%`;
    if (subEl) subEl.textContent = `Q: ${q.toFixed(1)} l/min | Schwelle: ${thr.toFixed(1)} l/min`;
  }

  if (paused) {
    const activeSecs = d.cycle_active_seconds ?? 0;
    const pauseStart = d.cycle_pause_start_time;
    const pauseSecs  = pauseStart ? (Date.now() / 1000 - pauseStart) : 0;
    document.getElementById("pause-active-time").textContent = fmtSeconds(activeSecs);
    document.getElementById("pause-elapsed").textContent     = fmtSeconds(Math.max(0, pauseSecs));
    // Kachel-Kompaktanzeige
    const ptEl = document.getElementById("flow-card-pause-time");
    if (ptEl) ptEl.textContent = `Pausiert seit ${fmtSeconds(Math.max(0, pauseSecs))}`;
  }

  _applyFlowCardIndicator();
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

function toggleSimulationRun() {
  const running = !!window._lastStatus?.running;
  if (running) stopSimulation();
  else startSimulation();
}

function updateHeaderTransport(d) {
  const wrap = document.getElementById("header-transport");
  if (!wrap) return;
  wrap.classList.toggle("hidden", !d.simulation_mode);
  const icon = document.getElementById("btn-transport-play-icon");
  if (icon) icon.innerHTML = d.running ? "&#9208;" : "&#9654;";
}

function _getHetaCode() {
  const num = document.getElementById("input-heta-code").value.trim();
  return num ? "HETA-" + num : "";
}

async function activateHetaCode() {
  const code = _getHetaCode();
  const pin  = document.getElementById("input-pin").value.trim();
  if (!code || !pin) { showMsg("heta-msg", "HETA-Code und PIN eingeben.", true); return; }

  // Ohne HETA-Code gelernte Zyklen (DEMO-Profil) werden beim Aktivieren NICHT
  // übernommen – der neue HETA-Code startet mit einem eigenen, leeren Profil.
  const d = window._lastStatus;
  const hasValidatedDemoProfile = !d?.heta_code && d?.profile_status === "VALIDIERT";
  if (hasValidatedDemoProfile) {
    const proceed = confirm(
      "Es sind bereits 3 Lernzyklen ohne HETA-Code gelernt (DEMO-Profil).\n\n" +
      "Diese werden bei der Aktivierung NICHT übernommen – für diesen HETA-Code " +
      "müssen erneut 3 Lernzyklen gefahren werden.\n\n" +
      "Trotzdem aktivieren?"
    );
    if (!proceed) return;
  }

  const result = await apiFetch("/api/heta/activate", "POST", { heta_code: code, pin });
  if (result?.valid) showMsg("heta-msg", `Aktivierung erfolgreich: ${result.heta_code}`, false);
  else showMsg("heta-msg", result?.message ?? "Fehler.", true);
}

async function deactivateHetaCode() {
  if (!confirm("HETA-Code wirklich deaktivieren?\nDie Lernzyklen bleiben gespeichert.")) return;
  const result = await apiFetch("/api/heta/deactivate", "POST");
  if (result?.success) {
    showMsg("heta-msg", result.message, false);
    clearCharts();
  } else {
    showMsg("heta-msg", result?.message ?? "Fehler.", true);
  }
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
// Hilfsfunktionen (Dashboard-Badges / Status)
// ============================================================

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

function updateHetaActivationSection(d) {
  const badge  = document.getElementById("heta-activation-badge");
  const active = document.getElementById("heta-activation-active");
  const form   = document.getElementById("heta-activation-form");
  const code   = document.getElementById("heta-activation-current-code");
  const btnDeact = document.getElementById("btn-heta-deactivate");

  const activated = !!d.heta_activated;
  if (badge) {
    badge.textContent = activated ? "aktiviert" : "nicht aktiviert";
    badge.className = "badge " + (activated ? "badge-ok" : "badge-warn");
  }
  if (active) active.classList.toggle("hidden", !activated);
  if (form)   form.classList.toggle("hidden", activated);
  if (code)   code.textContent = d.heta_code || "HETA-–";
  if (btnDeact) btnDeact.classList.toggle("hidden", !activated);
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

// Polling-Handle für Sensor-Diagnose
let _sfPollTimer = null;

function handleSensorFault(d) {
  const overlay = document.getElementById("sensor-fault-overlay");
  if (!overlay) return;

  if (!d.sensor_fault) {
    overlay.classList.add("hidden");
    _stopSfPoll();
    return;
  }

  // Flow-Wait-Overlay verstecken – Sensor-Fault-Overlay hat Vorrang
  document.getElementById("flow-wait-overlay")?.classList.add("hidden");

  // Titel je nach Zustand
  const titleEl = document.getElementById("sensor-fault-title");
  if (titleEl) {
    if (d.startup_sensor_check) {
      titleEl.textContent = "Startprüfung – Sensoren";
    } else if (d.waiting_for_flow) {
      titleEl.textContent = "Sensorfehler – Sensoren prüfen";
    } else {
      titleEl.textContent = "Sensorfehler – Messung gestoppt";
    }
  }

  setText("sensor-fault-message", "Sensorkanäle werden geprüft. Bitte alle 4 Sensoren anschließen.");
  overlay.classList.remove("hidden");

  // Diagnose-Polling starten (nur wenn noch nicht aktiv)
  _startSfPoll();
}

function _startSfPoll() {
  if (_sfPollTimer) return;
  _sfPollRound();
}

function _stopSfPoll() {
  if (_sfPollTimer) { clearTimeout(_sfPollTimer); _sfPollTimer = null; }
}

async function _sfPollRound() {
  const overlay = document.getElementById("sensor-fault-overlay");
  if (!overlay || overlay.classList.contains("hidden")) { _sfPollTimer = null; return; }

  try {
    const data = await apiFetch("/api/sensor/rawcheck");
    if (data) _updateSfDiagTable(data);
  } catch (_) {}

  _sfPollTimer = setTimeout(_sfPollRound, 1000);
}

function _updateSfDiagTable(data) {
  const channels = data.channels || [];
  const units    = ["bar", "bar", "°C", "l/min"];
  let allOk = true;

  channels.forEach(ch => {
    const i = ch.channel;
    const ok = ch.status === "OK";
    if (!ok) allOk = false;

    const maEl     = document.getElementById(`sf-ma-${i}`);
    const valEl    = document.getElementById(`sf-val-${i}`);
    const statusEl = document.getElementById(`sf-status-${i}`);
    const rowEl    = document.getElementById(`sf-row-${i}`);

    if (maEl)     maEl.textContent  = ch.ma != null ? ch.ma.toFixed(3) + " mA" : "–";
    if (valEl)    valEl.textContent = ch.value != null ? ch.value + " " + ch.unit : "–";
    if (statusEl) statusEl.innerHTML = ok
      ? `<span class="sf-dot sf-dot-ok"></span> OK`
      : `<span class="sf-dot sf-dot-err"></span> ${ch.status}`;
    if (rowEl) rowEl.className = ok ? "sf-row-ok" : "sf-row-err";
  });

  // "Messung starten"-Button nur freischalten wenn alle 4 OK
  const btn = document.getElementById("btn-sensor-recheck");
  if (btn) {
    btn.disabled = !allOk;
    btn.title = allOk ? "" : "Warte auf alle 4 Sensoren…";
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

async function startMeasurementFromCheck() {
  const btn    = document.getElementById("btn-sensor-recheck");
  const result = document.getElementById("sensor-fault-result");

  btn.disabled = true;
  btn.textContent = "Starte…";
  if (result) { result.classList.remove("hidden"); result.className = "sensor-fault-result checking"; result.textContent = "Messung wird gestartet…"; }

  const data = await apiFetch("/api/sensor/recheck", "POST");

  btn.textContent = "Messung starten";

  if (!data) {
    btn.disabled = false;
    if (result) { result.className = "sensor-fault-result error"; result.textContent = "Verbindungsfehler – Bitte erneut versuchen."; }
    return;
  }

  if (data.success) {
    _stopSfPoll();
    if (result) { result.className = "sensor-fault-result ok"; result.textContent = data.message; }
    // Overlay schließt sich beim nächsten Poll-Zyklus automatisch (sensor_fault = false)
  } else {
    btn.disabled = false;
    if (result) { result.className = "sensor-fault-result error"; result.textContent = data.message; }
  }
}

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

  // Zyklusfortschritt (dp-basiert) + Laufzeit
  const progressPct = d.analysis_cycle_progress_pct ?? 0;
  const progressBar = document.getElementById("analysis-progress-bar");
  if (progressBar) progressBar.style.width = Math.min(100, progressPct) + "%";
  setText("analysis-progress-pct", Math.round(progressPct) + " %");
  const elapsedSec = d.analysis_elapsed_seconds ?? 0;
  const elapsedMin = Math.floor(elapsedSec / 60);
  const elapsedS   = Math.floor(elapsedSec % 60);
  setText("analysis-elapsed", elapsedMin > 0
    ? `${elapsedMin} min ${String(elapsedS).padStart(2,"0")} s`
    : `${elapsedS} s`);

  // Δp-Steigung: 30-s-gefensterte Referenzsteigung vs. aktuelle 30-s-Regression
  const dpSlopeRef = d.analysis_dp_rate_ref     ?? 0;
  const dpSlopeCur = d.analysis_dp_rate_current ?? 0;
  const dpDev      = d.analysis_dp_deviation_pct ?? 0;
  setText("an-dp-ref", fmt(dpSlopeRef * 1000, 3) + " mbar/s");
  setText("an-dp-cur", fmt(dpSlopeCur * 1000, 3) + " mbar/s");
  setAnalysisDev("an-dp-dev", dpDev, "%", _tolDp * 100, _tolDp * 200);

  // R_eff-Steigung — rückwärts 30-s-Fenster
  const reffSlopeRef = d.analysis_reff_rate_ref     ?? 0;
  const reffSlopeCur = d.analysis_reff_rate_current ?? 0;
  const reffDev      = d.analysis_reff_deviation_pct ?? 0;
  setText("an-reff-ref", fmt(reffSlopeRef * 1e6, 3) + " µ(b·min/l)/s");
  setText("an-reff-cur", fmt(reffSlopeCur * 1e6, 3) + " µ(b·min/l)/s");
  setAnalysisDev("an-reff-dev", reffDev, "%", _tolReff * 100, _tolReff * 200);

  // Q-Steigung — rückwärts 30-s-Fenster
  const flSlopeRef = d.analysis_flow_rate_ref     ?? 0;
  const flSlopeCur = d.analysis_flow_rate_current ?? 0;
  const flDev      = d.analysis_flow_deviation_pct ?? 0;
  setText("an-fl-ref", fmt(flSlopeRef * 60, 3) + " l/min/min");
  setText("an-fl-cur", fmt(flSlopeCur * 60, 3) + " l/min/min");
  setAnalysisDev("an-fl-dev", flDev, "%", _tolFlow * 100, _tolFlow * 200);

  // T-Steigung — rückwärts 30-s-Fenster
  const tSlopeRef = d.analysis_temp_rate_ref     ?? 0;
  const tSlopeCur = d.analysis_temp_rate_current ?? 0;
  const tDev      = d.analysis_temp_deviation_pct ?? 0;
  setText("an-tmp-ref", fmt(tSlopeRef * 60, 4) + " °C/min");
  setText("an-tmp-cur", fmt(tSlopeCur * 60, 4) + " °C/min");
  setAnalysisDev("an-tmp-dev", tDev, "%", _tolTempC * 10, _tolTempC * 20);

  setText("analysis-diagnosis", buildDiagnosis(dpDev, flDev, tDev, true));
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

function buildDiagnosis(dpDevPct, flowDevPct, tempDev, isSlopeBase = false) {
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
    const label = isSlopeBase ? "Δp-Steigung höher als Referenz" : "Δp steigt schneller als gelernt";
    hints.push(label + " → erhöhte Partikelkonzentration oder beschädigtes Filterelement möglich.");
  } else if (dpSlow) {
    const label = isSlopeBase ? "Δp-Steigung niedriger als Referenz" : "Langsame Beladung";
    hints.push(label + " → Prozess läuft mit reduzierter Last. Filterwechselintervall verlängert sich.");
  }

  if (flowLow && !dpFast) {
    hints.push("Durchfluss unter Referenz → Pumpenproblem, Leckage im Bypass oder Vorverstopfung möglich.");
  } else if (flowHigh && !dpSlow) {
    // flowHigh + dpSlow ist konsistent: weniger Beladung → niedrigerer Δp UND höherer
    // Durchfluss (weniger Filterwiderstand). Kein Widerspruch – dpSlow-Hinweis reicht.
    hints.push("Erhöhter Durchfluss ohne Δp-Reduktion → mehr Partikelladung pro Zeiteinheit, Filterwechselintervall kann sich verkürzen.");
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
let _rateValues = { dirt_rate_pct: 100.0, p1_trend_pct: 0.0, p2_trend_pct: 0.0, flow_drop_pct: 75.0, temp_trend: 0.0 };

const SIM_SCENARIOS = {
  normal:         { dirt_rate_pct: 100, p1_trend_pct:   0, p2_trend_pct: 0, flow_drop_pct: 75, temp_trend:  0 },
  high_dirt:      { dirt_rate_pct: 150, p1_trend_pct:   0, p2_trend_pct: 0, flow_drop_pct: 75, temp_trend:  0 },
  low_p1:         { dirt_rate_pct: 100, p1_trend_pct:  -5, p2_trend_pct: 0, flow_drop_pct: 75, temp_trend:  0 },
  high_flow_drop: { dirt_rate_pct: 100, p1_trend_pct:   0, p2_trend_pct: 0, flow_drop_pct: 85, temp_trend:  0 },
  rising_temp:    { dirt_rate_pct: 100, p1_trend_pct:   0, p2_trend_pct: 0, flow_drop_pct: 75, temp_trend:  3 },
  atypical:       { dirt_rate_pct: 130, p1_trend_pct:  -5, p2_trend_pct: 0, flow_drop_pct: 85, temp_trend:  2 },
};

function toggleCardSimSliders(simMode) {
  document.querySelectorAll(".card-sim-slider").forEach(el => el.classList.toggle("hidden", !simMode));
  const presetsCard = document.getElementById("card-sim-presets");
  if (presetsCard) presetsCard.classList.toggle("hidden", !simMode);
}

function updateSimDemoPanel(d) {
  const simMode = !!d.simulation_mode;
  toggleCardSimSliders(simMode);
  if (!simMode) return;

  const profileValid = d.profile_status === "VALIDIERT";
  const learnBtn = document.getElementById("btn-quick-learn");
  if (learnBtn) learnBtn.disabled = profileValid;
}

async function quickLearn() {
  const btn = document.getElementById("btn-quick-learn");
  btn.disabled = true;
  btn.textContent = "… Lernzyklen werden simuliert";

  const res = await apiFetch("/api/simulation/quick-learn", "POST");
  btn.textContent = "▶ Lernzyklen simulieren";

  if (!res) {
    btn.disabled = false;
    return;
  }
  if (res.success) {
    // Cache invalidieren damit die neue Referenzkurve sofort geladen wird
    _refCurveCache = null;
    _refCurveCacheCode = null;
    _knownCycleStart = null;
    _knownLiveCycleStart = null;
  } else {
    btn.disabled = false;
  }
}

function _setSliderValue(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function onCardSliderInput(which, rawVal) {
  const v = parseFloat(rawVal);
  if (which === "dirt_rate") {
    _rateValues.dirt_rate_pct = v;
    const label = Math.round(v) + " %";
    setText("sv-card-dp-dirt", label);
    setText("sv-card-flow-dirt", label);
    _setSliderValue("sl-card-dp-dirt", v);
    _setSliderValue("sl-card-flow-dirt", v);
  } else if (which === "p1_trend") {
    _rateValues.p1_trend_pct = v;
    const sign = v >= 0 ? "+" : "";
    setText("sv-card-p1-trend", sign + Math.round(v) + " %");
  } else if (which === "p2_trend") {
    _rateValues.p2_trend_pct = v;
    const sign = v >= 0 ? "+" : "";
    setText("sv-card-p2-trend", sign + Math.round(v) + " %");
  } else if (which === "temp_trend") {
    _rateValues.temp_trend = v;
    const sign = v >= 0 ? "+" : "";
    setText("sv-card-temp-trend", sign + v.toFixed(1) + " °C");
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
    p2_trend_pct:   _rateValues.p2_trend_pct,
    flow_drop_pct:  _rateValues.flow_drop_pct,
    temp_trend:     _rateValues.temp_trend,
  });
}

function selectScenario(name) {
  const sc = SIM_SCENARIOS[name];
  if (!sc) return;
  _rateValues = { ...sc };

  _setSliderValue("sl-card-p1-trend",   sc.p1_trend_pct);
  _setSliderValue("sl-card-p2-trend",   sc.p2_trend_pct);
  _setSliderValue("sl-card-dp-dirt",    sc.dirt_rate_pct);
  _setSliderValue("sl-card-flow-dirt",  sc.dirt_rate_pct);
  _setSliderValue("sl-card-temp-trend", sc.temp_trend);

  const p1s = sc.p1_trend_pct >= 0 ? "+" : "";
  setText("sv-card-p1-trend", p1s + Math.round(sc.p1_trend_pct) + " %");
  const p2s = sc.p2_trend_pct >= 0 ? "+" : "";
  setText("sv-card-p2-trend", p2s + Math.round(sc.p2_trend_pct) + " %");
  setText("sv-card-dp-dirt",   Math.round(sc.dirt_rate_pct) + " %");
  setText("sv-card-flow-dirt", Math.round(sc.dirt_rate_pct) + " %");
  const ts = sc.temp_trend >= 0 ? "+" : "";
  setText("sv-card-temp-trend", ts + sc.temp_trend.toFixed(1) + " °C");

  document.querySelectorAll(".sim-scenario-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.scenario === name);
  });
  sendSliderValues(name);
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

function onMqttToggle(checkbox) {
  document.getElementById("s-mqtt-fields")?.classList.toggle("hidden", !checkbox.checked);
}

function onModbusToggle(checkbox) {
  document.getElementById("s-modbus-fields")?.classList.toggle("hidden", !checkbox.checked);
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

// ============================================================
// Zyklen & Profil – Tab
// ============================================================

async function resetHetaCycles() {
  const d = window._lastStatus;
  const hetaCode = d?.heta_code || "DEMO";

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
  const effectiveCode = d?.heta_code || "DEMO";

  const encoded = encodeURIComponent(effectiveCode);
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

  // dp_clean für Einstellungs-Anzeige
  const dpClean = profile?.reference_dp_clean;
  const dpCleanDisplay = document.getElementById("s-dp-clean-display");
  if (dpCleanDisplay) dpCleanDisplay.textContent = dpClean > 0 ? fmt(dpClean, 3) : "–";
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
  const reqCycles = Math.min(window._lastStatus?.required_cycles ?? 3, 3);
  const rows = cycles.slice().reverse().map((c, idx) => {
    const cycleNum  = cycles.length - idx;
    const isLearning = cycleNum <= reqCycles;

    // Start time
    const dtStart   = new Date((c.start_time ?? 0) * 1000);
    const startStr  = dtStart.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

    // End time (null when running)
    let endStr = "–";
    if (c.end_time) {
      const dtEnd = new Date(c.end_time * 1000);
      endStr = dtEnd.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
    }

    // Duration – für laufende Zyklen Echtzeit-Differenz verwenden,
    // damit _tsPct im Chart-Modal korrekt arbeitet.
    const durSec = c.end_time
      ? (c.duration_seconds ?? 0)
      : (Date.now() / 1000 - (c.start_time ?? 0));
    const durMin = Math.round(durSec / 60);
    const durStr = !c.end_time
      ? "läuft…"
      : (durMin >= 60 ? `${Math.floor(durMin / 60)}h ${durMin % 60}min` : `${durMin} min`);

    // Status
    const ok = c.confirmed_filter_change;
    let statusHtml;
    if (!c.end_time) {
      statusHtml = `<span class="cycle-status cycle-status-running">&#128260; Laufend</span>`;
    } else if (ok) {
      statusHtml = `<span class="cycle-status cycle-status-ok">&#10003; Filterwechsel</span>`;
    } else {
      statusHtml = `<span class="cycle-status cycle-status-done">&#9679; Beendet</span>`;
    }

    // Badge
    const badge = isLearning
      ? `<span class="badge badge-learn badge-sm" title="Lernzyklus">L</span>`
      : "";

    // Problem count
    let events = [];
    try { events = JSON.parse(c.events_json || "[]"); } catch (_) {}
    const problemCount = events.length;
    const problemLabel = problemCount > 0
      ? `&#128202; Diagramm &amp; <span class="cycle-problem-count">&#9888; ${problemCount} Problem${problemCount !== 1 ? "e" : ""}</span>`
      : `&#128202; Diagramm`;

    // Button attributes
    const dateLabel = dtStart.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" })
      + " " + dtStart.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    const cycleDataAttr = [
      `data-cycle-id="${c.id}"`,
      `data-cycle-num="${cycleNum}"`,
      `data-date="${dateLabel}"`,
      `data-heta="${hetaCode}"`,
      `data-duration="${durSec}"`,
      `data-events='${(c.events_json || "[]").replace(/'/g, "&apos;")}'`,
    ].join(" ");

    return `<tr class="${ok ? "cycle-confirmed" : ""}${isLearning ? " cycle-learning" : ""}">
      <td>${cycleNum} ${badge}</td>
      <td class="cycle-ts">${startStr}</td>
      <td class="cycle-ts">${endStr}</td>
      <td>${durStr}</td>
      <td>${statusHtml}</td>
      <td><button class="btn btn-ghost btn-sm cycle-chart-btn" ${cycleDataAttr}>${problemLabel}</button></td>
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
