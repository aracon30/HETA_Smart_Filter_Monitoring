/**
 * HETA Smart Filter Monitoring – Chart-Funktionen
 * Wird nach utils.js, api.js und vor app.js geladen.
 * Setzt DS_COLORS, MAX_CHART_POINTS aus utils.js sowie apiFetch aus api.js voraus.
 */

// ============================================================
// Chart.js Instanzen
// ============================================================

let combinedChart = null;
let cycleModalChart = null;

// Cache für Referenzkurve; wird beim Zykluswechsel invalidiert
let _refCurveCache = null;
let _refCurveCacheCode = null;

// Zyklusverfolgung für das Referenz-Overlay im Live-Chart
let _knownCycleStart     = null;
let _knownLiveCycleStart = null;

// ============================================================
// Dataset-Metadaten & Achsen-Optionen
// ============================================================

// Anzahl der "live" Messwert-Datasets (Indizes 0..LIVE_COUNT-1) vor den Referenz-/Toleranzgruppen
const LIVE_COUNT = 12;

// Realwert-Datasets (Δp/p1/p2/Q/T aktuell) – sollen initial ausgeblendet sein.
const ABS_VALUE_INDICES = [7, 8, 9, 10, 11];

// Dataset metadata for toggle buttons and axis config
const DS_META = [
  { label: "p1",           color: DS_COLORS.p1,     live: true,  axisFixed: true,  unit: "mbar/s",          axis: "yDpRate"   },
  { label: "p2",           color: DS_COLORS.p2,     live: true,  axisFixed: true,  unit: "mbar/s",          axis: "yDpRate"   },
  { label: "Δp",           color: DS_COLORS.dp,     live: true,  axisFixed: true,  unit: "mbar/s",          axis: "yDpRate"   },
  { label: "Q",            color: DS_COLORS.flow,   live: true,  axisFixed: false, unit: "l/min/min",       axis: "yFlow"     },
  { label: "T",            color: DS_COLORS.temp,   live: true,  axisFixed: false, unit: "°C/min",          axis: "yTemp"     },
  { label: "Widerstandsfaktor", color: DS_COLORS.reff, live: true, axisFixed: false, unit: "µ(b·min/l)/s", axis: "yReff"     },
  { label: "Reststandzeit",color: DS_COLORS.remain, live: true,  axisFixed: false, unit: "min",             axis: "yTime"     },
  { label: "Δp aktuell",   color: DS_COLORS.dp,     live: true,  axisFixed: true,  unit: "bar",             axis: "yPressure" },
  { label: "p1 aktuell",   color: DS_COLORS.p1,     live: true,  axisFixed: true,  unit: "bar",             axis: "yPressure" },
  { label: "p2 aktuell",   color: DS_COLORS.p2,     live: true,  axisFixed: true,  unit: "bar",             axis: "yPressure" },
  { label: "Q aktuell",    color: DS_COLORS.flow,   live: true,  axisFixed: false, unit: "l/min",           axis: "yFlowAbs"  },
  { label: "T aktuell",    color: DS_COLORS.temp,   live: true,  axisFixed: false, unit: "°C",              axis: "yTempAbs"  },
  // Reference dp (indices 12,13,14)
  { label: "±Tol Δp",     color: "rgba(0,212,255,0.35)",  ref: true, refGroup: "dp",   groupLabel: "Δp",   isTolerancePair: [12,13], isTolUpper: true },
  { label: "_tol_dp_lo",  color: "rgba(0,212,255,0.35)",  ref: true, refGroup: "dp",   isToleranceLower: true },
  { label: "Ref Δp",      color: DS_COLORS.refLine,        ref: true, refGroup: "dp",   refLabel: "Ref Δp"  },
  // flow group (indices 15,16,17)
  { label: "±Tol Q",      color: "rgba(52,211,153,0.35)",  ref: true, refGroup: "flow", groupLabel: "Q",    isTolerancePair: [15,16], isTolUpper: true },
  { label: "_tol_fl_lo",  color: "rgba(52,211,153,0.35)",  ref: true, refGroup: "flow", isToleranceLower: true },
  { label: "Ref Q",       color: DS_COLORS.flow,           ref: true, refGroup: "flow", refLabel: "Ref Q"   },
  // temp group (indices 18,19,20)
  { label: "±Tol T",      color: "rgba(251,146,60,0.35)",  ref: true, refGroup: "temp", groupLabel: "T",    isTolerancePair: [18,19], isTolUpper: true },
  { label: "_tol_tp_lo",  color: "rgba(251,146,60,0.35)",  ref: true, refGroup: "temp", isToleranceLower: true },
  { label: "Ref T",       color: DS_COLORS.temp,           ref: true, refGroup: "temp", refLabel: "Ref T"   },
  // reff group (indices 21,22,23)
  { label: "±Tol R",      color: "rgba(192,132,252,0.35)", ref: true, refGroup: "reff", groupLabel: "Wid.faktor", isTolerancePair: [21,22], isTolUpper: true },
  { label: "_tol_rf_lo",  color: "rgba(192,132,252,0.35)", ref: true, refGroup: "reff", isToleranceLower: true },
  { label: "Ref R",       color: DS_COLORS.reff,           ref: true, refGroup: "reff", refLabel: "Ref Wid.faktor" },
];

const AXIS_OPTIONS = [
  { id: "yDpRate",   label: "Links – Druckraten p1/p2/Δp [mbar/s]" },
  { id: "yFlow",     label: "Rechts 1 – ΔQ [l/min/min]"          },
  { id: "yTemp",     label: "Rechts 2 – ΔT [°C/min]"             },
  { id: "yReff",     label: "Rechts 3 – ΔR_eff [µ(b·min/l)/s]"  },
  { id: "yTime",     label: "Rechts 4 – Reststandzeit [min]"     },
  { id: "yPressure", label: "Links 2 – Druck [bar]"              },
  { id: "yFlowAbs",  label: "Rechts 5 – Q [l/min]"                },
  { id: "yTempAbs",  label: "Rechts 6 – T [°C]"                   },
];

// ============================================================
// initCharts – kombiniertes Live-Chart
// ============================================================

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
        // ── Messwerte (Indizes 0–11) ──────────────────────────────────────
        mkDs("p1 [mbar/s]",          DS_COLORS.p1,     "yDpRate",  { borderWidth: 1.5 }),
        mkDs("p2 [mbar/s]",          DS_COLORS.p2,     "yDpRate",  { borderWidth: 1.5 }),
        mkDs("Δp [mbar/s]",           DS_COLORS.dp,     "yDpRate", {
          borderWidth: 2.5,
          backgroundColor: "rgba(56,189,248,0.07)",
          fill: "origin",
        }),
        mkDs("Q [l/min/min]",         DS_COLORS.flow,   "yFlow"),
        mkDs("T [°C/min]",            DS_COLORS.temp,   "yTemp"),
        mkDs("R_eff [µ(b·min/l)/s]",  DS_COLORS.reff,   "yReff",  { borderDash: [5, 3] }),
        mkDs("Reststandzeit [min]", DS_COLORS.remain, "yTime",   { borderDash: [5, 3] }),
        // Realwerte (7–11): standardmäßig ausgeblendet (hidden: true) – nur Steigungen
        // sollen initial sichtbar sein, Realwerte muss der Benutzer bei Bedarf über die
        // Chips einblenden, damit das Diagramm nicht überladen wirkt.
        mkDs("Δp aktuell [bar]",   DS_COLORS.dp,     "yPressure", { borderWidth: 2, hidden: true }),
        mkDs("p1 aktuell [bar]",  DS_COLORS.p1,     "yPressure", { borderWidth: 1.5, hidden: true }),
        mkDs("p2 aktuell [bar]",  DS_COLORS.p2,     "yPressure", { borderWidth: 1.5, hidden: true }),
        mkDs("Q aktuell [l/min]", DS_COLORS.flow,   "yFlowAbs",  { borderWidth: 1.5, hidden: true }),
        mkDs("T aktuell [°C]",    DS_COLORS.temp,   "yTempAbs",  { borderWidth: 1.5, hidden: true }),
        // ── Referenz & Toleranz Δp (Indizes 12–14) ────────────────────────────
        // 12 = Toleranz Δp-Rate obere Grenze → füllt bis Dataset 13
        {
          label: "±Tol Δp",
          yAxisID: "yDpRate", data: [], parsing: false,
          borderColor: DS_COLORS.tolEdge,
          backgroundColor: DS_COLORS.tolBand,
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: "+1",
        },
        // 13 = Toleranz Δp-Rate untere Grenze
        {
          label: "_tol_dp_lower",
          yAxisID: "yDpRate", data: [], parsing: false,
          borderColor: DS_COLORS.tolEdge,
          backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: false,
        },
        // 14 = Referenz Δp-Rate-Linie
        mkDs("Ref Δp", DS_COLORS.refLine, "yDpRate", {
          borderWidth: 1.5, borderDash: [10, 5],
        }),
        // ── Referenz & Toleranz Q (Indizes 15–17) ───────────────────────────
        // 15 = Toleranz Q obere Grenze → füllt bis Dataset 16
        {
          label: "±Tol Q",
          yAxisID: "yFlow", data: [], parsing: false,
          borderColor: "rgba(52,211,153,0.35)",
          backgroundColor: "rgba(52,211,153,0.08)",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: "+1",
        },
        // 16 = Toleranz Q untere Grenze
        {
          label: "_tol_flow_lower",
          yAxisID: "yFlow", data: [], parsing: false,
          borderColor: "rgba(52,211,153,0.35)",
          backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: false,
        },
        // 17 = Referenz Q-Linie
        mkDs("Ref Q", DS_COLORS.flow, "yFlow", {
          borderWidth: 1.5, borderDash: [10, 5],
        }),
        // ── Referenz & Toleranz Temp (Indizes 18–20) ────────────────────────
        // 18 = Toleranz T obere Grenze → füllt bis Dataset 19
        {
          label: "±Tol T",
          yAxisID: "yTemp", data: [], parsing: false,
          borderColor: "rgba(251,146,60,0.35)",
          backgroundColor: "rgba(251,146,60,0.08)",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: "+1",
        },
        // 19 = Toleranz T untere Grenze
        {
          label: "_tol_temp_lower",
          yAxisID: "yTemp", data: [], parsing: false,
          borderColor: "rgba(251,146,60,0.35)",
          backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: false,
        },
        // 20 = Referenz T-Linie
        mkDs("Ref T", DS_COLORS.temp, "yTemp", {
          borderWidth: 1.5, borderDash: [10, 5],
        }),
        // ── Referenz & Toleranz R_eff (Indizes 21–23) ───────────────────────
        // 21 = Toleranz R_eff obere Grenze → füllt bis Dataset 22
        {
          label: "±Tol R_eff",
          yAxisID: "yReff", data: [], parsing: false,
          borderColor: "rgba(192,132,252,0.35)",
          backgroundColor: "rgba(192,132,252,0.08)",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: "+1",
        },
        // 22 = Toleranz R_eff untere Grenze
        {
          label: "_tol_reff_lower",
          yAxisID: "yReff", data: [], parsing: false,
          borderColor: "rgba(192,132,252,0.35)",
          backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: false,
        },
        // 23 = Referenz R_eff-Linie
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
              ? `Fortschritt: ${items[0].parsed.x.toFixed(1)} %`
              : "",
            label: ctx => {
              if (ctx.dataset.label.startsWith("_")) return null;
              const v = ctx.parsed.y;
              if (v == null || isNaN(v)) return null;
              const dec = {
                "p1 [mbar/s]": 3, "p2 [mbar/s]": 3,
                "Δp [mbar/s]": 3, "Q [l/min/min]": 3,
                "T [°C/min]": 3, "R_eff [µ(b·min/l)/s]": 3,
                "Reststandzeit [min]": 1,
                "Δp aktuell [bar]": 3,
                "p1 aktuell [bar]": 3, "p2 aktuell [bar]": 3,
                "Q aktuell [l/min]": 1, "T aktuell [°C]": 2,
                "Ref Δp": 3, "Ref Q": 3, "Ref T": 3, "Ref R_eff": 3,
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
          min: 0,
          max: 100,
          title: {
            display: true,
            text: "Zyklusfortschritt [%]",
            font: { size: 10 },
            color: "#64748b",
          },
          ticks: {
            maxTicksLimit: 11,
            maxRotation: 0,
            font: { size: 10 },
            color: "#64748b",
            callback: val => val + " %",
          },
          grid: { color: "rgba(100,130,160,0.15)" },
        },
        yPressure: {
          type: "linear",
          position: "left",
          display: false,
          min: 0,
          title: { display: true, text: "Δp [bar]", font: { size: 10 }, color: DS_COLORS.dp },
          ticks: { font: { size: 10 }, color: DS_COLORS.dp },
          grid: { color: "rgba(100,130,160,0.15)" },
        },
        yDpRate: {
          type: "linear",
          position: "left",
          title: { display: true, text: "Druckraten [mbar/s]", font: { size: 10 }, color: DS_COLORS.dp },
          ticks: { font: { size: 10 }, color: DS_COLORS.dp },
          grid: { color: "rgba(100,130,160,0.15)" },
        },
        yFlow: {
          type: "linear",
          position: "right",
          title: { display: true, text: "ΔQ [l/min/min]", font: { size: 10 }, color: DS_COLORS.flow },
          ticks: { font: { size: 10 }, color: DS_COLORS.flow },
          grid: { drawOnChartArea: false },
          display: false,
        },
        yTemp: {
          type: "linear",
          position: "right",
          display: false,
          title: { display: true, text: "ΔT [°C/min]", font: { size: 10 }, color: DS_COLORS.temp },
          ticks: { font: { size: 10 }, color: DS_COLORS.temp },
          grid: { drawOnChartArea: false },
        },
        yReff: {
          type: "linear",
          position: "right",
          display: false,
          title: { display: true, text: "ΔR_eff [µ(b·min/l)/s]", font: { size: 10 }, color: DS_COLORS.reff },
          ticks: { font: { size: 10 }, color: DS_COLORS.reff },
          grid: { drawOnChartArea: false },
        },
        yTime: {
          type: "linear",
          position: "right",
          display: false,
          min: 0,
          grid: { drawOnChartArea: false },
        },
        yFlowAbs: {
          type: "linear",
          position: "right",
          display: false,
          min: 0,
          title: { display: true, text: "Q aktuell [l/min]", font: { size: 10 }, color: DS_COLORS.flow },
          ticks: { font: { size: 10 }, color: DS_COLORS.flow },
          grid: { drawOnChartArea: false },
        },
        yTempAbs: {
          type: "linear",
          position: "right",
          display: false,
          title: { display: true, text: "T aktuell [°C]", font: { size: 10 }, color: DS_COLORS.temp },
          ticks: { font: { size: 10 }, color: DS_COLORS.temp },
          grid: { drawOnChartArea: false },
        },
      },
    },
  });

  // dataset.hidden:true allein reicht nicht – Chart.js löst getDatasetMeta(i).hidden
  // erst bei einem Render-/Update-Zyklus aus dataset.hidden auf; bis dahin liest es
  // sich als null (= "sichtbar") und die Chips/Achsen-Logik unten würde es als aktiv
  // einstufen. Deshalb hier explizit erzwingen, bevor Chips/Achsen gebaut werden.
  for (const idx of ABS_VALUE_INDICES) combinedChart.getDatasetMeta(idx).hidden = true;

  _registerChartUI("live", combinedChart, "chart-live-chips", "chart-ref-chips");
  _buildChartToggleButtons("live");
  _buildAxisPanel();
  // Achsen der initial ausgeblendeten Realwert-Reihen (hidden:true) müssen selbst
  // auch verborgen bleiben, statt durch die statische Scale-Konfiguration allein.
  updateAxisVisibility("live");
}

// ============================================================
// pushChartData – Live-Daten eintragen
// ============================================================

function pushChartData(status) {
  if (!combinedChart) return;
  const ds = combinedChart.data.datasets;

  // Neuen Zyklus erkennen: live-Datasets leeren damit die Kurve von 0 % startet
  const cycleStart = status.cycle_start_time ?? null;
  if (cycleStart !== _knownLiveCycleStart) {
    for (let i = 0; i < LIVE_COUNT; i++) ds[i].data = [];
    _knownLiveCycleStart = cycleStart;
  }

  // Vor dem 4. Zyklus existiert noch kein gelerntes Profil – analysis_cycle_progress_pct
  // kommt ausschließlich aus der Referenzkurven-Invertierung (get_curve_analysis) und bleibt
  // ohne Profil bei 0 hängen. Fallback auf eine Δp-basierte Fortschrittsschätzung
  // (100 − filter_health_percent), die schon ab der ersten Sekunde verfügbar ist –
  // sonst kleben alle Live-Punkte während der Lernzyklen bei x=0.
  const xPct = status.analysis_ready
    ? (status.analysis_cycle_progress_pct ?? 0)
    : (status.filter_health_percent != null ? 100 - status.filter_health_percent : 0);
  const remMin = status.remaining_seconds != null ? status.remaining_seconds / 60 : null;
  const p1Rate   = status.analysis_p1_rate_current   != null ? status.analysis_p1_rate_current   * 1000 : null;
  const p2Rate   = status.analysis_p2_rate_current   != null ? status.analysis_p2_rate_current   * 1000 : null;
  const dpRate   = status.analysis_dp_rate_current   != null ? status.analysis_dp_rate_current   * 1000 : null;
  const flRate   = status.analysis_flow_rate_current != null ? status.analysis_flow_rate_current * 60   : null;
  const tRate    = status.analysis_temp_rate_current != null ? status.analysis_temp_rate_current * 60   : null;
  const rfRate   = status.analysis_reff_rate_current != null ? status.analysis_reff_rate_current * 1e6  : null;
  ds[0].data.push({ x: xPct, y: p1Rate });
  ds[1].data.push({ x: xPct, y: p2Rate });
  ds[2].data.push({ x: xPct, y: dpRate });
  ds[3].data.push({ x: xPct, y: flRate });
  ds[4].data.push({ x: xPct, y: tRate });
  ds[5].data.push({ x: xPct, y: rfRate });
  ds[6].data.push({ x: xPct, y: remMin });
  ds[7].data.push({ x: xPct, y: status.dp_bar ?? null });
  ds[8].data.push({ x: xPct, y: status.p1_bar ?? null });
  ds[9].data.push({ x: xPct, y: status.p2_bar ?? null });
  ds[10].data.push({ x: xPct, y: status.flow_l_min ?? null });
  ds[11].data.push({ x: xPct, y: status.temperature_c ?? null });
  for (let i = 0; i < LIVE_COUNT; i++) {
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

// Berechnet die Referenz-Steigungsbänder (Δp/Q/T/R_eff, je Ober-/Unter-/Mittellinie)
// aus der gelernten Referenzkurve. Gemeinsam genutzt von Live-Chart-Overlay und
// Filterzyklus-Diagramm, damit beide identisch aussehen.
function _computeRateRefBands(refCurve) {
  const empty = () => ({ upper: [], lower: [], center: [] });
  const bands = { dp: empty(), flow: empty(), temp: empty(), reff: empty() };
  const curve = refCurve?.curve;
  if (!curve?.length) return bands;

  const refDuration = refCurve.reference_duration_seconds || 300;
  const tolDp       = refCurve.tolerance_dp_pct   ?? refCurve.tolerance_pct ?? 0.25;
  const tolFlow     = refCurve.tolerance_flow_pct ?? 0.25;
  const tolReff     = refCurve.tolerance_reff_pct ?? 0.25;
  const tolTempAbs  = refCurve.tolerance_temp_c   ?? 10.0; // °C absolut → in Rate umrechnen

  // Toleranzbandbreite aus der DURCHSCHNITTLICHEN Referenzrate über den ganzen
  // Zyklus ableiten (konstante Breite), nicht aus der lokalen Rate an jedem
  // Punkt – sonst würde das Band zum Zyklusende hin (wo Δp/Q/R_eff progressiv
  // am steilsten verlaufen) immer breiter, obwohl Abweichungen dort am
  // kritischsten sind (identische Überlegung wie learning.py::get_curve_analysis).
  const first = curve[0], last = curve[curve.length - 1];
  const avgRate = (field, scale) =>
    first?.[field] != null && last?.[field] != null ? ((last[field] - first[field]) / refDuration) * scale : 0;
  const dpTolWidth   = Math.abs(avgRate("dp", 1000)) * tolDp;      // mbar/s
  const flowTolWidth = Math.abs(avgRate("flow", 60)) * tolFlow;    // l/min/min
  const reffTolWidth = Math.abs(avgRate("r_eff", 1e6)) * tolReff;  // µ(b·min/l)/s

  // Wert eines Kurvenfelds an einer beliebigen t_pct-Position interpolieren
  // (identisch zur Backend-Logik in learning.py::_slope_windowed/interp_val).
  const interpVal = (t, field) => {
    if (t <= curve[0].t_pct) return curve[0][field] ?? null;
    if (t >= curve[curve.length - 1].t_pct) return curve[curve.length - 1][field] ?? null;
    for (let i = 0; i < curve.length - 1; i++) {
      const t0 = curve[i].t_pct, t1 = curve[i + 1].t_pct;
      if (t0 <= t && t <= t1 && (t1 - t0) > 1e-6) {
        const v0 = curve[i][field], v1 = curve[i + 1][field];
        if (v0 == null || v1 == null) return null;
        return v0 + (t - t0) / (t1 - t0) * (v1 - v0);
      }
    }
    return null;
  };

  // Steigung über ein rückwärtsgerichtetes 30-s-Fenster statt reiner
  // Nachbarpunkt-Differenz – glättet Rundungs-Quantisierungsrauschen bei
  // eng benachbarten Kurvenpunkten (siehe Backend-Pendant _slope_windowed).
  const WINDOW_S = 30;
  const windowPct = (WINDOW_S / refDuration) * 100;

  for (const point of curve) {
    const tHi = point.t_pct;
    const tLo = Math.max(0, tHi - windowPct);
    const dtS = (tHi - tLo) / 100 * refDuration;
    if (dtS <= 0) continue;
    const xMid = tHi;

    const dpLo = interpVal(tLo, "dp"), dpHi = interpVal(tHi, "dp");
    if (dpLo != null && dpHi != null) {
      const r = (dpHi - dpLo) / dtS * 1000;            // mbar/s
      bands.dp.center.push({ x: xMid, y: r });
      bands.dp.upper.push({  x: xMid, y: r + dpTolWidth });
      bands.dp.lower.push({  x: xMid, y: Math.max(0, r - dpTolWidth) });
    }
    const flLo = interpVal(tLo, "flow"), flHi = interpVal(tHi, "flow");
    if (flLo != null && flHi != null) {
      const r = (flHi - flLo) / dtS * 60;               // l/min/min
      bands.flow.center.push({ x: xMid, y: r });
      bands.flow.upper.push({  x: xMid, y: r + flowTolWidth });
      bands.flow.lower.push({  x: xMid, y: r - flowTolWidth });
    }
    const tpLo = interpVal(tLo, "temp"), tpHi = interpVal(tHi, "temp");
    if (tpLo != null && tpHi != null) {
      const r = (tpHi - tpLo) / dtS * 60;               // °C/min
      const tol = tolTempAbs / (refDuration / 60);       // °C/min Toleranzbreite
      bands.temp.center.push({ x: xMid, y: r });
      bands.temp.upper.push({  x: xMid, y: r + tol });
      bands.temp.lower.push({  x: xMid, y: r - tol });
    }
    const rfLo = interpVal(tLo, "r_eff"), rfHi = interpVal(tHi, "r_eff");
    if (rfLo != null && rfHi != null) {
      const r = (rfHi - rfLo) / dtS * 1e6;              // µ(b·min/l)/s
      bands.reff.center.push({ x: xMid, y: r });
      bands.reff.upper.push({  x: xMid, y: r + reffTolWidth });
      bands.reff.lower.push({  x: xMid, y: Math.max(0, r - reffTolWidth) });
    }
  }

  return bands;
}

// Rollierende Steigung (kleinste Quadrate) über ein window_s-Sekundenfenster
// entlang der echten cycle_second-Zeitachse eines historischen Zyklus –
// dieselbe Methodik wie PredictionEngine._linear_slope im Backend, mit der
// tatsächlichen Zeitachse statt Sample-Index (robust ggü. Abtastlücken).
function _rollingSlopeSeries(samples, field, durationSeconds, windowS = 30, scale = 1, minPoints = 5) {
  const out = [];
  let lo = 0;
  for (let i = 0; i < samples.length; i++) {
    const tHi = samples[i].cycle_second;
    while (samples[lo].cycle_second < tHi - windowS) lo++;
    let n = 0, sumT = 0, sumV = 0, sumTT = 0, sumTV = 0;
    for (let j = lo; j <= i; j++) {
      const v = samples[j][field];
      if (v == null) continue;
      const t = samples[j].cycle_second;
      n++; sumT += t; sumV += v; sumTT += t * t; sumTV += t * v;
    }
    if (n < minPoints) continue;
    const denom = n * sumTT - sumT * sumT;
    if (denom === 0) continue;
    const slope = (n * sumTV - sumT * sumV) / denom;
    const x = durationSeconds > 0 ? (tHi / durationSeconds) * 100 : tHi;
    out.push({ x, y: slope * scale });
  }
  return out;
}

async function updateReferenceOverlay(status) {
  if (!combinedChart) return;
  const hetaCode    = status?.heta_code;
  const cycleActive = !!status?.cycle_active;
  const startTime   = status?.cycle_start_time;
  const ds = combinedChart.data.datasets;

  if (!cycleActive || !hetaCode || !startTime) {
    const anyData = ds[14].data.length > 0 || ds[17].data.length > 0 ||
                    ds[20].data.length > 0 || ds[23].data.length > 0;
    if (anyData) {
      // Clear all reference datasets 12-23
      for (let i = 12; i <= 23; i++) ds[i].data = [];
      combinedChart.update("none");
      _refreshRefChips("live");
    }
    _knownCycleStart = null;
    _knownLiveCycleStart = null;
    return;
  }

  // Gleicher Zyklus + Referenz schon geladen → nichts tun
  if (startTime === _knownCycleStart && ds[14].data.length > 0) return;
  _knownCycleStart = startTime;

  const refCurve = await _getRefCurve(hetaCode);
  if (!refCurve?.curve?.length) return;

  const bands = _computeRateRefBands(refCurve);
  ds[12].data = bands.dp.upper;    ds[13].data = bands.dp.lower;    ds[14].data = bands.dp.center;
  ds[15].data = bands.flow.upper;  ds[16].data = bands.flow.lower;  ds[17].data = bands.flow.center;
  ds[18].data = bands.temp.upper;  ds[19].data = bands.temp.lower;  ds[20].data = bands.temp.center;
  ds[21].data = bands.reff.upper;  ds[22].data = bands.reff.lower;  ds[23].data = bands.reff.center;

  combinedChart.update("none");
  _refreshRefChips("live");
}

// ============================================================
// Zyklus-Diagramm Modal (vergangene Zyklen)
// ============================================================

// Baut die Event-Annotationen (Fehler/Warnungen/Abweichungen) für das
// Filterzyklus-Diagramm – unverändert gegenüber der Vorgängerversion.
function _buildCycleEventAnnotations(events, samples, durationSeconds) {
  const annotations = {};
  const cycleStartTs = samples.length > 0 ? (samples[0].timestamp - samples[0].cycle_second) : 0;

  const _tsPct = ts => {
    if (!ts || !cycleStartTs || !durationSeconds) return null;
    return Math.max(0, Math.min(100, ((ts - cycleStartTs) / durationSeconds) * 100));
  };

  const _sevColors = sev => {
    if (sev === "FEHLER")      return { line: "rgba(239,68,68,0.9)",    box: "rgba(239,68,68,0.10)",  border: "rgba(239,68,68,0.4)"  };
    if (sev === "ABWEICHUNG")  return { line: "rgba(251,146,60,0.9)",   box: "rgba(251,146,60,0.09)", border: "rgba(251,146,60,0.4)"  };
    return                            { line: "rgba(251,191,36,0.9)",   box: "rgba(251,191,36,0.08)", border: "rgba(251,191,36,0.35)" };
  };

  (events || []).forEach((e, i) => {
    const tsStart = e.ts_start ?? e.ts;
    const tsEnd   = e.ts_end ?? null;
    const xStart  = _tsPct(tsStart);
    if (xStart === null) return;

    const col   = _sevColors(e.severity);
    const label = e.severity + (e.message ? `: ${e.message}` : "");

    if (tsEnd && durationSeconds) {
      // Shaded region — problem period with known end
      const xEnd = _tsPct(tsEnd);
      annotations[`ev${i}`] = {
        type: "box",
        xMin: xStart, xMax: xEnd,
        yMin: "0%",   yMax: "100%",
        backgroundColor: col.box,
        borderColor: col.border,
        borderWidth: 1,
        label: {
          content: label, display: true, position: { x: "start", y: "start" },
          backgroundColor: col.line, color: "#fff",
          font: { size: 9, weight: "600" }, padding: { x: 5, y: 3 },
          textAlign: "left",
        },
      };
    } else {
      // Single vertical line — point event
      annotations[`ev${i}`] = {
        type: "line", scaleID: "x", value: xStart,
        borderColor: col.line, borderWidth: 1.5, borderDash: [4, 3],
        label: {
          content: e.severity, display: true, position: "start",
          backgroundColor: col.line, color: "#fff",
          font: { size: 9 }, padding: { x: 4, y: 2 },
        },
      };
    }
  });

  return annotations;
}

// Baut die Chart.js-Konfiguration für ein vergangenes Filterzyklus-Diagramm.
// Identische Dataset-/Achsenstruktur wie das Live-Diagramm (initCharts):
// Steigungen (p1/p2/Δp/Q/T/R_eff) statt Absolutwerte, plus Δp aktuell und
// Reststandzeit, plus Referenz-/Toleranzbänder – berechnet aus den
// gespeicherten Samples nach derselben 30-s-Fenster-Methodik wie live.
function _buildCycleChartConfig(samples, refCurve, events, durationSeconds) {
  const mkDs = (label, color, yAxis, data, extra = {}) => ({
    label, yAxisID: yAxis, data, parsing: false,
    borderColor: color, backgroundColor: "transparent",
    borderWidth: 2, pointRadius: 0, tension: 0.3,
    ...extra,
  });

  const WINDOW_S = 30;
  const p1Rate = _rollingSlopeSeries(samples, "p1_bar",     durationSeconds, WINDOW_S, 1000);
  const p2Rate = _rollingSlopeSeries(samples, "p2_bar",     durationSeconds, WINDOW_S, 1000);
  const dpRate = _rollingSlopeSeries(samples, "dp_bar",     durationSeconds, WINDOW_S, 1000);
  const flRate = _rollingSlopeSeries(samples, "flow_l_min", durationSeconds, WINDOW_S, 60);
  const tpRate = _rollingSlopeSeries(samples, "temp_c",     durationSeconds, WINDOW_S, 60);
  const rfRate = _rollingSlopeSeries(samples, "r_eff",      durationSeconds, WINDOW_S, 1e6);

  const xOf = s => durationSeconds > 0 ? (s.cycle_second / durationSeconds) * 100 : s.cycle_second;
  const remainData = samples
    .filter(s => s.remaining_seconds != null)
    .map(s => ({ x: xOf(s), y: s.remaining_seconds / 60 }));
  const absData = field => samples.filter(s => s[field] != null).map(s => ({ x: xOf(s), y: s[field] }));
  const dpAbsData   = absData("dp_bar");
  const p1AbsData    = absData("p1_bar");
  const p2AbsData    = absData("p2_bar");
  const flowAbsData  = absData("flow_l_min");
  const tempAbsData  = absData("temp_c");

  const bands = _computeRateRefBands(refCurve);
  const annotations = _buildCycleEventAnnotations(events, samples, durationSeconds);

  return {
    type: "line",
    data: {
      datasets: [
        // ── Messwerte (Indizes 0–11) – identisch zum Live-Chart ──────────
        mkDs("p1 [mbar/s]", DS_COLORS.p1, "yDpRate", p1Rate, { borderWidth: 1.5 }),
        mkDs("p2 [mbar/s]", DS_COLORS.p2, "yDpRate", p2Rate, { borderWidth: 1.5 }),
        mkDs("Δp [mbar/s]", DS_COLORS.dp, "yDpRate", dpRate, {
          borderWidth: 2.5, backgroundColor: "rgba(56,189,248,0.07)", fill: "origin",
        }),
        mkDs("Q [l/min/min]",        DS_COLORS.flow,   "yFlow", flRate),
        mkDs("T [°C/min]",           DS_COLORS.temp,   "yTemp", tpRate),
        mkDs("R_eff [µ(b·min/l)/s]", DS_COLORS.reff,   "yReff", rfRate, { borderDash: [5, 3] }),
        mkDs("Reststandzeit [min]",  DS_COLORS.remain, "yTime", remainData, { borderDash: [5, 3] }),
        // Realwerte (7–11): standardmäßig ausgeblendet – siehe initCharts() für Begründung.
        mkDs("Δp aktuell [bar]",     DS_COLORS.dp,     "yPressure", dpAbsData, { borderWidth: 2, hidden: true }),
        mkDs("p1 aktuell [bar]",  DS_COLORS.p1,   "yPressure", p1AbsData,   { borderWidth: 1.5, hidden: true }),
        mkDs("p2 aktuell [bar]", DS_COLORS.p2,   "yPressure", p2AbsData,   { borderWidth: 1.5, hidden: true }),
        mkDs("Q aktuell [l/min]", DS_COLORS.flow, "yFlowAbs",  flowAbsData, { borderWidth: 1.5, hidden: true }),
        mkDs("T aktuell [°C]",    DS_COLORS.temp, "yTempAbs",  tempAbsData, { borderWidth: 1.5, hidden: true }),
        // ── Referenz & Toleranz Δp (Indizes 12–14) ────────────────────────
        { label: "±Tol Δp", yAxisID: "yDpRate", data: bands.dp.upper, parsing: false,
          borderColor: DS_COLORS.tolEdge, backgroundColor: DS_COLORS.tolBand,
          borderWidth: 1, borderDash: [3, 4], pointRadius: 0, tension: 0.3, fill: "+1" },
        { label: "_tol_dp_lower", yAxisID: "yDpRate", data: bands.dp.lower, parsing: false,
          borderColor: DS_COLORS.tolEdge, backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4], pointRadius: 0, tension: 0.3, fill: false },
        mkDs("Ref Δp", DS_COLORS.refLine, "yDpRate", bands.dp.center, { borderWidth: 1.5, borderDash: [10, 5] }),
        // ── Referenz & Toleranz Q (Indizes 15–17) ───────────────────────
        { label: "±Tol Q", yAxisID: "yFlow", data: bands.flow.upper, parsing: false,
          borderColor: "rgba(52,211,153,0.35)", backgroundColor: "rgba(52,211,153,0.08)",
          borderWidth: 1, borderDash: [3, 4], pointRadius: 0, tension: 0.3, fill: "+1" },
        { label: "_tol_flow_lower", yAxisID: "yFlow", data: bands.flow.lower, parsing: false,
          borderColor: "rgba(52,211,153,0.35)", backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4], pointRadius: 0, tension: 0.3, fill: false },
        mkDs("Ref Q", DS_COLORS.flow, "yFlow", bands.flow.center, { borderWidth: 1.5, borderDash: [10, 5] }),
        // ── Referenz & Toleranz Temp (Indizes 18–20) ────────────────────
        { label: "±Tol T", yAxisID: "yTemp", data: bands.temp.upper, parsing: false,
          borderColor: "rgba(251,146,60,0.35)", backgroundColor: "rgba(251,146,60,0.08)",
          borderWidth: 1, borderDash: [3, 4], pointRadius: 0, tension: 0.3, fill: "+1" },
        { label: "_tol_temp_lower", yAxisID: "yTemp", data: bands.temp.lower, parsing: false,
          borderColor: "rgba(251,146,60,0.35)", backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4], pointRadius: 0, tension: 0.3, fill: false },
        mkDs("Ref T", DS_COLORS.temp, "yTemp", bands.temp.center, { borderWidth: 1.5, borderDash: [10, 5] }),
        // ── Referenz & Toleranz R_eff (Indizes 21–23) ───────────────────
        { label: "±Tol R_eff", yAxisID: "yReff", data: bands.reff.upper, parsing: false,
          borderColor: "rgba(192,132,252,0.35)", backgroundColor: "rgba(192,132,252,0.08)",
          borderWidth: 1, borderDash: [3, 4], pointRadius: 0, tension: 0.3, fill: "+1" },
        { label: "_tol_reff_lower", yAxisID: "yReff", data: bands.reff.lower, parsing: false,
          borderColor: "rgba(192,132,252,0.35)", backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4], pointRadius: 0, tension: 0.3, fill: false },
        mkDs("Ref R_eff", DS_COLORS.reff, "yReff", bands.reff.center, { borderWidth: 1.5, borderDash: [10, 5] }),
      ],
    },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: "index", intersect: false,
          backgroundColor: "rgba(12,22,38,0.95)",
          titleColor: "#a8c8f0", bodyColor: "#dde8f5",
          borderColor: "#1c3a5c", borderWidth: 1, padding: 10,
          usePointStyle: true,
          callbacks: {
            title: items => items[0] ? `Fortschritt: ${items[0].parsed.x.toFixed(1)} %` : "",
            label: ctx => {
              if (ctx.dataset.label.startsWith("_")) return null;
              const v = ctx.parsed.y;
              if (v == null || isNaN(v)) return null;
              const dec = {
                "p1 [mbar/s]": 3, "p2 [mbar/s]": 3,
                "Δp [mbar/s]": 3, "Q [l/min/min]": 3,
                "T [°C/min]": 3, "R_eff [µ(b·min/l)/s]": 3,
                "Reststandzeit [min]": 1,
                "Δp aktuell [bar]": 3,
                "p1 aktuell [bar]": 3, "p2 aktuell [bar]": 3,
                "Q aktuell [l/min]": 1, "T aktuell [°C]": 2,
                "Ref Δp": 3, "Ref Q": 3, "Ref T": 3, "Ref R_eff": 3,
              };
              return ` ${ctx.dataset.label}: ${v.toFixed(dec[ctx.dataset.label] ?? 2)}`;
            },
          },
        },
        annotation: { annotations },
      },
      scales: {
        x: { type: "linear", min: 0, max: 100,
          title: { display: true, text: "Zyklusfortschritt [%]", font: { size: 10 }, color: "#64748b" },
          ticks: { maxTicksLimit: 11, maxRotation: 0, font: { size: 10 }, color: "#64748b", callback: val => val + " %" },
          grid: { color: "rgba(100,130,160,0.15)" } },
        yPressure: { type: "linear", position: "left", display: false, min: 0,
          title: { display: true, text: "Δp [bar]", font: { size: 10 }, color: DS_COLORS.dp },
          ticks: { font: { size: 10 }, color: DS_COLORS.dp },
          grid: { color: "rgba(100,130,160,0.15)" } },
        yDpRate: { type: "linear", position: "left",
          title: { display: true, text: "Druckraten [mbar/s]", font: { size: 10 }, color: DS_COLORS.dp },
          ticks: { font: { size: 10 }, color: DS_COLORS.dp },
          grid: { color: "rgba(100,130,160,0.15)" } },
        yFlow: { type: "linear", position: "right", display: false,
          title: { display: true, text: "ΔQ [l/min/min]", font: { size: 10 }, color: DS_COLORS.flow },
          ticks: { font: { size: 10 }, color: DS_COLORS.flow },
          grid: { drawOnChartArea: false } },
        yTemp: { type: "linear", position: "right", display: false,
          title: { display: true, text: "ΔT [°C/min]", font: { size: 10 }, color: DS_COLORS.temp },
          ticks: { font: { size: 10 }, color: DS_COLORS.temp },
          grid: { drawOnChartArea: false } },
        yReff: { type: "linear", position: "right", display: false,
          title: { display: true, text: "ΔR_eff [µ(b·min/l)/s]", font: { size: 10 }, color: DS_COLORS.reff },
          ticks: { font: { size: 10 }, color: DS_COLORS.reff },
          grid: { drawOnChartArea: false } },
        yTime: { type: "linear", position: "right", display: false, min: 0,
          grid: { drawOnChartArea: false } },
        yFlowAbs: { type: "linear", position: "right", display: false, min: 0,
          title: { display: true, text: "Q aktuell [l/min]", font: { size: 10 }, color: DS_COLORS.flow },
          ticks: { font: { size: 10 }, color: DS_COLORS.flow },
          grid: { drawOnChartArea: false } },
        yTempAbs: { type: "linear", position: "right", display: false,
          title: { display: true, text: "T aktuell [°C]", font: { size: 10 }, color: DS_COLORS.temp },
          ticks: { font: { size: 10 }, color: DS_COLORS.temp },
          grid: { drawOnChartArea: false } },
      },
    },
  };
}

async function openCycleModal(cycleId, cycleNum, dateStr, hetaCode, durationSeconds, eventsJson) {
  const overlay  = document.getElementById("cycle-modal-overlay");
  const titleEl  = document.getElementById("cycle-modal-title");
  const eventsEl = document.getElementById("cycle-modal-events");
  if (!overlay) return;

  if (titleEl) titleEl.textContent = `Filterzyklus #${cycleNum} – ${dateStr}`;

  // Show overlay immediately
  overlay.classList.remove("hidden");

  let events = [];
  try { events = JSON.parse(eventsJson || "[]"); } catch (_) {}

  // Render events list
  if (eventsEl) {
    if (!events.length) {
      eventsEl.innerHTML = '<p class="cycle-events-ok">&#10003; Keine Probleme in diesem Zyklus.</p>';
    } else {
      const sevColor = s => {
        if (s === "FEHLER")     return "var(--alert-red)";
        if (s === "ABWEICHUNG") return "#fb923c";
        return "var(--warn-yellow)";
      };
      const fmtTs = ts => ts ? new Date(ts * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "–";
      const rows = events.map(e => {
        const tsStart = e.ts_start ?? e.ts;
        const tsEnd   = e.ts_end ?? null;
        let timeStr;
        if (tsEnd) {
          const durSec = tsEnd - tsStart;
          const durFmt = durSec >= 60
            ? `${Math.floor(durSec / 60)} min ${durSec % 60} s`
            : `${durSec} s`;
          timeStr = `${fmtTs(tsStart)} – ${fmtTs(tsEnd)} (${durFmt})`;
        } else {
          timeStr = fmtTs(tsStart);
        }
        const icon = e.severity === "ABWEICHUNG" ? "⬆" : "⚠";
        return `<div class="cycle-event-row">
          <span class="cycle-event-sev" style="color:${sevColor(e.severity)}">${icon} ${e.severity}</span>
          <span class="cycle-event-ts">${timeStr}</span>
          <span class="cycle-event-msg">${e.message}</span>
        </div>`;
      }).join("");
      eventsEl.innerHTML = `<div class="cycle-events-header">&#9888; Ereignisse &amp; Abweichungen</div>${rows}`;
    }
  }

  const [samples, refCurve] = await Promise.all([
    apiFetch(`/api/cycle-samples/${cycleId}`),
    hetaCode ? _getRefCurve(hetaCode) : Promise.resolve(null),
  ]);

  const ctx = document.getElementById("chart-cycle-modal");
  if (!ctx) return;
  if (cycleModalChart) { cycleModalChart.destroy(); cycleModalChart = null; }
  cycleModalChart = new Chart(ctx,
    _buildCycleChartConfig(samples || [], refCurve, events, durationSeconds));

  // Meta-Zustand explizit erzwingen – siehe initCharts() für die Begründung
  // (dataset.hidden allein wird erst bei einem Render-Zyklus in getDatasetMeta().hidden übernommen).
  for (const idx of ABS_VALUE_INDICES) cycleModalChart.getDatasetMeta(idx).hidden = true;

  // Toggle-Chips wie beim Live-Chart aufbauen (Messwerte + Referenz/Toleranz),
  // Referenzdaten sind hier von Anfang an vollständig geladen.
  _registerChartUI("cycle", cycleModalChart, "cycle-live-chips", "cycle-ref-chips");
  _buildChartToggleButtons("cycle");
  _refreshRefChips("cycle");
  updateAxisVisibility("cycle");
}

function closeCycleModal() {
  const overlay = document.getElementById("cycle-modal-overlay");
  if (overlay) overlay.classList.add("hidden");
  if (cycleModalChart) { cycleModalChart.destroy(); cycleModalChart = null; }
  delete _chartUI.cycle;
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
//
// Beide Diagramme (Live-Chart & Filterzyklus-Modal) haben dieselbe
// 20-Dataset-Struktur (siehe DS_META) und teilen sich deshalb dieselbe
// Toggle-/Referenz-Logik. _chartUI registriert pro Chart-Instanz die
// Container-IDs, damit Chip-Klicks nur die eigenen Chips betreffen.

const _chartUI = {};

function _registerChartUI(key, chart, liveContainerId, refContainerId) {
  _chartUI[key] = { chart, liveContainerId, refContainerId };
}

function _buildChartToggleButtons(key) {
  const ui = _chartUI[key];
  if (!ui?.chart) return;
  const chart = ui.chart;

  // ── Live chips (indices 0..LIVE_COUNT-1) ─────────────────────
  // Zwei Zeilen: Steigungen (aktiv) oben, Realwerte (ausgeblendet) unten –
  // getrennt, damit die unterschiedlichen Größenarten nicht durcheinander wirken.
  const liveContainer = document.getElementById(ui.liveContainerId);
  if (liveContainer) {
    liveContainer.innerHTML = "";

    const rowSlopes = document.createElement("div");
    rowSlopes.className = "chart-toggle-chips-row";
    const slopesLabel = document.createElement("span");
    slopesLabel.className = "chart-toggle-row-label";
    slopesLabel.textContent = "Steigungen";
    rowSlopes.appendChild(slopesLabel);

    const rowAbs = document.createElement("div");
    rowAbs.className = "chart-toggle-chips-row";
    const absLabel = document.createElement("span");
    absLabel.className = "chart-toggle-row-label";
    absLabel.textContent = "Realwerte";
    rowAbs.appendChild(absLabel);

    for (let i = 0; i < LIVE_COUNT; i++) {
      const meta = DS_META[i];
      const btn = document.createElement("button");
      btn.className = "chart-chip";
      btn.dataset.dsIndex = i;
      btn.style.setProperty("--chip-color", meta.color);
      btn.textContent = meta.label;
      // Initially active unless the dataset meta says hidden
      const hidden = chart.getDatasetMeta(i).hidden;
      if (!hidden) btn.classList.add("active");
      btn.addEventListener("click", () => toggleChartDs(key, i));
      (ABS_VALUE_INDICES.includes(i) ? rowAbs : rowSlopes).appendChild(btn);
    }

    liveContainer.appendChild(rowSlopes);
    liveContainer.appendChild(rowAbs);
  }

  // ── Reference chips (grouped) ────────────────────────────────
  const refContainer = document.getElementById(ui.refContainerId);
  if (refContainer) {
    refContainer.innerHTML = "";

    // Groups: dp(12,13,14), flow(15,16,17), temp(18,19,20), reff(21,22,23)
    const groups = [
      { name: "dp",   label: "Δp",     refIdx: 14, tolIdx: [12,13], color: DS_COLORS.refLine,  tolColor: "rgba(0,212,255,0.35)"  },
      { name: "flow", label: "Q",      refIdx: 17, tolIdx: [15,16], color: DS_COLORS.flow,     tolColor: "rgba(52,211,153,0.35)" },
      { name: "temp", label: "T",      refIdx: 20, tolIdx: [18,19], color: DS_COLORS.temp,     tolColor: "rgba(251,146,60,0.35)" },
      { name: "reff", label: "R_eff",  refIdx: 23, tolIdx: [21,22], color: DS_COLORS.reff,     tolColor: "rgba(192,132,252,0.35)"},
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
      refBtn.addEventListener("click", () => toggleChartDs(key, grp.refIdx));
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
        toggleChartDs(key, indices[0], indices);
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

  const addSectionHeader = text => {
    const h = document.createElement("div");
    h.className = "chart-axis-section-header";
    h.textContent = text;
    panel.appendChild(h);
  };

  for (let i = 0; i < LIVE_COUNT; i++) {
    if (i === 0) addSectionHeader("Steigungen");
    if (ABS_VALUE_INDICES[0] === i) addSectionHeader("Realwerte");

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
      const axisLbl = AXIS_OPTIONS.find(o => o.id === meta.axis);
      fixedLabel.textContent = axisLbl ? axisLbl.label : meta.axis;
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

function toggleChartDs(key, primaryIndex, allIndices) {
  const ui = _chartUI[key];
  if (!ui?.chart) return;
  const chart = ui.chart;
  const indices = allIndices || [primaryIndex];

  // Determine new state based on primary dataset
  const primaryMeta = chart.getDatasetMeta(primaryIndex);
  const newHidden = !primaryMeta.hidden;

  for (const idx of indices) {
    chart.getDatasetMeta(idx).hidden = newHidden;
  }

  // Update chip button active state – scoped to this chart's own containers
  // (both charts use the same dataset indices, so a global query would hit
  // the wrong chart's chips too).
  [ui.liveContainerId, ui.refContainerId].forEach(containerId => {
    document.querySelectorAll(`#${containerId} .chart-chip[data-ds-index="${primaryIndex}"]`).forEach(btn => {
      btn.classList.toggle("active", !newHidden);
    });
  });

  updateAxisVisibility(key);
  chart.update();
}

function setDatasetAxis(index, axisId) {
  if (!combinedChart) return;
  combinedChart.data.datasets[index].yAxisID = axisId;
  if (DS_META[index]) DS_META[index].axis = axisId;
  updateAxisVisibility("live");
  combinedChart.update();
}

function updateAxisVisibility(key) {
  const ui = _chartUI[key];
  if (!ui?.chart) return;
  const chart = ui.chart;
  const scales = chart.options.scales;
  const datasets = chart.data.datasets;

  for (const axisId of Object.keys(scales)) {
    if (axisId === "x") continue;
    // Check if any dataset assigned to this axis is visible
    let hasVisible = false;
    datasets.forEach((ds, idx) => {
      if (ds.yAxisID === axisId) {
        const m = chart.getDatasetMeta(idx);
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

function _refreshRefChips(key) {
  const ui = _chartUI[key];
  if (!ui?.chart) return;
  const chart = ui.chart;
  const ds = chart.data.datasets;
  const hasData = ds[14].data.length > 0;

  // Groups and their indices
  const groupInfo = [
    { refIdx: 14, tolIdx: [12,13] },
    { refIdx: 17, tolIdx: [15,16] },
    { refIdx: 20, tolIdx: [18,19] },
    { refIdx: 23, tolIdx: [21,22] },
  ];

  for (const grp of groupInfo) {
    const grpHasData = ds[grp.refIdx].data.length > 0;

    // Find chips for this ref index and tol indices
    const refChip = document.querySelector(`#${ui.refContainerId} .chart-chip[data-ds-index="${grp.refIdx}"]`);
    const tolChip = document.querySelector(`#${ui.refContainerId} .chart-chip[data-ds-index="${grp.tolIdx[0]}"]`);

    if (refChip) {
      refChip.disabled = !grpHasData;
      refChip.classList.toggle("disabled", !grpHasData);
      if (grpHasData && !chart.getDatasetMeta(grp.refIdx).hidden) {
        refChip.classList.add("active");
      } else if (!grpHasData) {
        refChip.classList.remove("active");
      }
    }
    if (tolChip) {
      tolChip.disabled = !grpHasData;
      tolChip.classList.toggle("disabled", !grpHasData);
      if (grpHasData && !chart.getDatasetMeta(grp.tolIdx[0]).hidden) {
        tolChip.classList.add("active");
      } else if (!grpHasData) {
        tolChip.classList.remove("active");
      }
    }
  }

  // Also update the hint text (live chart only)
  const hintEl = document.getElementById("chart-ref-hint");
  if (hintEl) {
    hintEl.textContent = hasData ? "" : "Kein aktiver Zyklus mit HETA-Code";
  }
}

function clearCharts() {
  if (!combinedChart) return;
  combinedChart.data.labels = [];
  combinedChart.data.datasets.forEach(ds => { ds.data = []; });
  _knownCycleStart = null;
  _knownLiveCycleStart = null;
  _refCurveCache = null;
  _refCurveCacheCode = null;
  combinedChart.update("none");
  _refreshRefChips("live");
}
