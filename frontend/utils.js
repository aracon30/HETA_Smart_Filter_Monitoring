/**
 * HETA Smart Filter Monitoring – Hilfsfunktionen & Konstanten
 * Wird vor api.js, charts.js und app.js geladen.
 */

// ============================================================
// Konstanten
// ============================================================

const API_BASE = "";
const POLL_INTERVAL_MS = 1500;
const TOKEN_KEY = "heta_settings_token";
const MAX_CHART_POINTS = 300;

// Farben für Chart-Datasets
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

// ============================================================
// Reine Hilfsfunktionen
// ============================================================

function fmt(val, decimals) {
  if (val == null || isNaN(val)) return "–";
  return Number(val).toFixed(decimals);
}

function fmtSeconds(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m.toString().padStart(2,"0")}m`;
  if (m > 0) return `${m}m ${sec.toString().padStart(2,"0")}s`;
  return `${sec}s`;
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

function healthColor(pct) {
  if (pct > 50) return "var(--ok-green)";
  if (pct > 20) return "var(--warn-yellow)";
  return "var(--alert-red)";
}

// ============================================================
// Theme (Hell / Dunkel)
// ============================================================

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = theme === "light" ? "🌙" : "☀️";
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  localStorage.setItem("heta_theme", next);
  applyTheme(next);
}

// Beim Laden gespeichertes Theme anwenden
(function () {
  const saved = localStorage.getItem("heta_theme") || "dark";
  applyTheme(saved);
})();
