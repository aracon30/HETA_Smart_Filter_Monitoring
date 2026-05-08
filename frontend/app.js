/**
 * HETA Smart Filter Monitoring – Frontend-Applikation
 * Pollt die REST-API und aktualisiert das Dashboard.
 */

const API_BASE = "";          // leer = gleicher Host
const POLL_INTERVAL_MS = 1500;

// Chart.js Instanzen
const MAX_CHART_POINTS = 120;
let charts = {};
const chartData = { dp: [], flow: [], reff: [], remaining: [] };

// ============================================================
// Init
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
  initCharts();
  startPolling();
});

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
  // Messwerte
  setText("val-p1",    fmt(d.p1_bar, 3));
  setText("val-p2",    fmt(d.p2_bar, 3));
  setText("val-dp",    fmt(d.dp_bar, 3));
  setText("val-flow",  fmt(d.flow_l_min, 1));
  setText("val-temp",  fmt(d.temperature_c, 1));
  setText("val-reff",  fmt(d.r_eff, 5));

  // Filterzustand
  const health = d.filter_health_percent ?? 100;
  setText("val-health", fmt(health, 1));
  const bar = document.getElementById("health-bar");
  if (bar) {
    bar.style.width = `${Math.max(0, Math.min(100, health))}%`;
    bar.style.background = healthColor(health);
  }

  // Reststandzeit
  setText("val-remaining", d.remaining_display ?? "–");
  setText("remaining-mode", d.prediction_mode ?? "BASIS");

  // HETA-Code
  setText("val-heta-code", d.heta_code || "(kein Code)");
  setText("val-heta-status", d.heta_activated ? "Aktiviert" : "nicht aktiviert");

  // Servicehinweis
  setText("val-service-msg", d.service_message || "–");
  setText("val-service-prio", d.service_priority || "–");
  styleServicePriority(d.service_priority);

  // Filterwechsel-Banner
  const banner = document.getElementById("filter-change-banner");
  if (banner) banner.classList.toggle("hidden", !d.awaiting_confirmation);

  // Status-Badge (Header)
  updateStatusBadge(d.filter_status);

  // Sensor-Modus-Badge
  updateSensorBadge(d.sensor_mode);

  // Letzte Aktualisierung
  setText("last-update", d.last_update ? new Date(d.last_update).toLocaleTimeString("de-DE") : "–");

  // Systeminfo
  setText("info-sensor-mode", d.sensor_mode ?? "–");
  setText("info-cycles", d.learned_cycles ?? "–");
  setText("info-profile", d.profile_status ?? "–");
  setText("info-anomaly", d.anomaly_active
    ? `Ja (${fmt(d.anomaly_percent, 1)} % Abweichung)` : "Nein");
  setText("info-pred-mode", d.prediction_mode ?? "–");
  setText("info-sensor-err", d.sensor_error ? "JA" : "Nein");

  // dp-Limit Hinweis
  const dpLimit = window._settings?.dp_limit_bar ?? 2.5;
  setText("dp-limit-hint", `Limit: ${dpLimit.toFixed(2)} bar`);

  // Karten-Farbe nach Status
  styleCardByStatus("card-dp", d.filter_status);

  // Charts befüllen
  pushChartData(d);
}

// ============================================================
// Charts
// ============================================================

function initCharts() {
  const opts = (label, color) => ({
    type: "line",
    data: {
      labels: [],
      datasets: [{
        label,
        data: [],
        borderColor: color,
        backgroundColor: color + "22",
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }]
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { ticks: { font: { size: 10 } } }
      }
    }
  });

  charts.dp        = new Chart(document.getElementById("chart-dp"),        opts("Δp [bar]", "#0077cc"));
  charts.flow      = new Chart(document.getElementById("chart-flow"),      opts("Q [l/min]", "#1a9e3c"));
  charts.reff      = new Chart(document.getElementById("chart-reff"),      opts("R_eff", "#7b1fa2"));
  charts.remaining = new Chart(document.getElementById("chart-remaining"), opts("Rest [min]", "#d4820a"));

  // Einstellungen laden für dp-Limit-Hinweis
  fetch(`${API_BASE}/api/settings`)
    .then(r => r.json())
    .then(s => { window._settings = s; })
    .catch(() => {});
}

function pushChartData(d) {
  const label = new Date().toLocaleTimeString("de-DE");
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
// Button-Aktionen
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
  if (result?.valid) {
    showMsg("heta-msg", `Aktivierung erfolgreich: ${result.heta_code}`, false);
  } else {
    showMsg("heta-msg", result?.message ?? "Fehler.", true);
  }
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
  if (result?.success) {
    showMsg("heta-msg", result.message, false);
    clearCharts();
  }
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
