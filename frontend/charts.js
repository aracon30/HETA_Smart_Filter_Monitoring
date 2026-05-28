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

// Channel visibility state for cycle modal
const _cycleModalVisible = { dp: true, flow: true, temp: false, reff: false };

// ============================================================
// Dataset-Metadaten & Achsen-Optionen
// ============================================================

// Dataset metadata for toggle buttons and axis config
const DS_META = [
  { label: "p1",           color: DS_COLORS.p1,     live: true,  axisFixed: true,  unit: "bar",             axis: "yPressure" },
  { label: "p2",           color: DS_COLORS.p2,     live: true,  axisFixed: true,  unit: "bar",             axis: "yPressure" },
  { label: "Δp",           color: DS_COLORS.dp,     live: true,  axisFixed: true,  unit: "mbar/s",          axis: "yDpRate"   },
  { label: "Q",            color: DS_COLORS.flow,   live: true,  axisFixed: false, unit: "l/min/min",       axis: "yFlow"     },
  { label: "T",            color: DS_COLORS.temp,   live: true,  axisFixed: false, unit: "°C/min",          axis: "yTemp"     },
  { label: "Widerstandsfaktor", color: DS_COLORS.reff, live: true, axisFixed: false, unit: "µ(b·min/l)/s", axis: "yReff"     },
  { label: "Reststandzeit",color: DS_COLORS.remain, live: true,  axisFixed: false, unit: "min",             axis: "yTime"     },
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
  { id: "yDpRate",   label: "Links – Δp [mbar/s]"                },
  { id: "yFlow",     label: "Rechts 1 – ΔQ [l/min/min]"          },
  { id: "yTemp",     label: "Rechts 2 – ΔT [°C/min]"             },
  { id: "yReff",     label: "Rechts 3 – ΔR_eff [µ(b·min/l)/s]"  },
  { id: "yTime",     label: "Rechts 4 – Reststandzeit [min]"     },
  { id: "yPressure", label: "Links 2 – Druck [bar]"              },
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
        // ── Messwerte (Indizes 0–6) ──────────────────────────────────────
        mkDs("p1 [bar]",            DS_COLORS.p1,     "yPressure", { borderWidth: 1.5 }),
        mkDs("p2 [bar]",            DS_COLORS.p2,     "yPressure", { borderWidth: 1.5 }),
        mkDs("Δp [mbar/s]",           DS_COLORS.dp,     "yDpRate", {
          borderWidth: 2.5,
          backgroundColor: "rgba(56,189,248,0.07)",
          fill: "origin",
        }),
        mkDs("Q [l/min/min]",         DS_COLORS.flow,   "yFlow"),
        mkDs("T [°C/min]",            DS_COLORS.temp,   "yTemp"),
        mkDs("R_eff [µ(b·min/l)/s]",  DS_COLORS.reff,   "yReff",  { borderDash: [5, 3] }),
        mkDs("Reststandzeit [min]", DS_COLORS.remain, "yTime",   { borderDash: [5, 3] }),
        // ── Referenz & Toleranz Δp (Indizes 7–9) ────────────────────────────
        // 7 = Toleranz Δp-Rate obere Grenze → füllt bis Dataset 8
        {
          label: "±Tol Δp",
          yAxisID: "yDpRate", data: [], parsing: false,
          borderColor: DS_COLORS.tolEdge,
          backgroundColor: DS_COLORS.tolBand,
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: "+1",
        },
        // 8 = Toleranz Δp-Rate untere Grenze
        {
          label: "_tol_dp_lower",
          yAxisID: "yDpRate", data: [], parsing: false,
          borderColor: DS_COLORS.tolEdge,
          backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3, 4],
          pointRadius: 0, tension: 0.3, fill: false,
        },
        // 9 = Referenz Δp-Rate-Linie
        mkDs("Ref Δp", DS_COLORS.refLine, "yDpRate", {
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
              ? `Fortschritt: ${items[0].parsed.x.toFixed(1)} %`
              : "",
            label: ctx => {
              if (ctx.dataset.label.startsWith("_")) return null;
              const v = ctx.parsed.y;
              if (v == null || isNaN(v)) return null;
              const dec = {
                "p1 [bar]": 3, "p2 [bar]": 3,
                "Δp [mbar/s]": 3, "Q [l/min/min]": 3,
                "T [°C/min]": 3, "R_eff [µ(b·min/l)/s]": 3,
                "Reststandzeit [min]": 1,
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
          title: { display: true, text: "Druck [bar]", font: { size: 10 }, color: DS_COLORS.p1 },
          ticks: { font: { size: 10 }, color: DS_COLORS.p1 },
          grid: { color: "rgba(100,130,160,0.15)" },
        },
        yDpRate: {
          type: "linear",
          position: "left",
          min: 0,
          title: { display: true, text: "Δp [mbar/s]", font: { size: 10 }, color: DS_COLORS.dp },
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
      },
    },
  });

  _buildChartToggleButtons();
  _buildAxisPanel();
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
    for (let i = 0; i < 7; i++) ds[i].data = [];
    _knownLiveCycleStart = cycleStart;
  }

  const xPct   = status.analysis_cycle_progress_pct ?? 0;
  const remMin = status.remaining_seconds != null ? status.remaining_seconds / 60 : null;
  const dpRate   = status.analysis_dp_rate_current   != null ? status.analysis_dp_rate_current   * 1000 : null;
  const flRate   = status.analysis_flow_rate_current != null ? status.analysis_flow_rate_current * 60   : null;
  const tRate    = status.analysis_temp_rate_current != null ? status.analysis_temp_rate_current * 60   : null;
  const rfRate   = status.analysis_reff_rate_current != null ? status.analysis_reff_rate_current * 1e6  : null;
  ds[0].data.push({ x: xPct, y: status.p1_bar ?? null });
  ds[1].data.push({ x: xPct, y: status.p2_bar ?? null });
  ds[2].data.push({ x: xPct, y: dpRate });
  ds[3].data.push({ x: xPct, y: flRate });
  ds[4].data.push({ x: xPct, y: tRate });
  ds[5].data.push({ x: xPct, y: rfRate });
  ds[6].data.push({ x: xPct, y: remMin });
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
    _knownLiveCycleStart = null;
    return;
  }

  // Gleicher Zyklus + Referenz schon geladen → nichts tun
  if (startTime === _knownCycleStart && ds[9].data.length > 0) return;
  _knownCycleStart = startTime;

  const refCurve = await _getRefCurve(hetaCode);
  if (!refCurve?.curve?.length) return;

  const refDuration = refCurve.reference_duration_seconds || 300;
  const tolDp       = refCurve.tolerance_dp_pct   ?? refCurve.tolerance_pct ?? 0.25;
  const tolFlow     = refCurve.tolerance_flow_pct ?? 0.25;
  const tolReff     = refCurve.tolerance_reff_pct ?? 0.25;
  const tolTempAbs  = refCurve.tolerance_temp_c   ?? 10.0; // °C absolut → in Rate umrechnen

  // Dp datasets (7=upper, 8=lower, 9=center)   [mbar/s]
  const dpUpper = [], dpLower = [], dpCenter = [];
  // Flow datasets (10=upper, 11=lower, 12=center) [l/min/min]
  const flUpper = [], flLower = [], flCenter = [];
  // Temp datasets (13=upper, 14=lower, 15=center) [°C/min]
  const tpUpper = [], tpLower = [], tpCenter = [];
  // Reff datasets (16=upper, 17=lower, 18=center) [µ(b·min/l)/s]
  const rfUpper = [], rfLower = [], rfCenter = [];

  const curve = refCurve.curve;
  for (let i = 0; i < curve.length - 1; i++) {
    const p0 = curve[i], p1 = curve[i + 1];
    const dtS = (p1.t_pct - p0.t_pct) / 100 * refDuration; // Zeitdelta in s
    if (dtS <= 0) continue;
    const xMid = (p0.t_pct + p1.t_pct) / 2;

    if (p0.dp != null && p1.dp != null) {
      const r = (p1.dp - p0.dp) / dtS * 1000;          // mbar/s
      dpCenter.push({ x: xMid, y: r });
      dpUpper.push({  x: xMid, y: r * (1 + tolDp) });
      dpLower.push({  x: xMid, y: Math.max(0, r * (1 - tolDp)) });
    }
    if (p0.flow != null && p1.flow != null) {
      const r = (p1.flow - p0.flow) / dtS * 60;         // l/min/min
      flCenter.push({ x: xMid, y: r });
      flUpper.push({  x: xMid, y: r * (1 + tolFlow) });
      flLower.push({  x: xMid, y: r - r * tolFlow });
    }
    if (p0.temp != null && p1.temp != null) {
      const r = (p1.temp - p0.temp) / dtS * 60;         // °C/min
      const tol = tolTempAbs / (refDuration / 60);       // °C/min Toleranzbreite
      tpCenter.push({ x: xMid, y: r });
      tpUpper.push({  x: xMid, y: r + tol });
      tpLower.push({  x: xMid, y: r - tol });
    }
    if (p0.r_eff != null && p1.r_eff != null) {
      const r = (p1.r_eff - p0.r_eff) / dtS * 1e6;     // µ(b·min/l)/s
      rfCenter.push({ x: xMid, y: r });
      rfUpper.push({  x: xMid, y: r * (1 + tolReff) });
      rfLower.push({  x: xMid, y: r * (1 - tolReff) });
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

function _buildCycleChartConfig(samples, refCurve, events, durationSeconds) {
  const tolDp   = refCurve?.tolerance_dp_pct   ?? refCurve?.tolerance_pct ?? 0.25;
  const tolFlow = refCurve?.tolerance_flow_pct ?? 0.25;
  const tolTempC = refCurve?.tolerance_temp_c  ?? 10.0;
  const tolReff  = refCurve?.tolerance_reff_pct ?? 0.25;
  const reffStart = refCurve?.reference_r_eff_start || 0;

  const xOf = s => durationSeconds > 0 ? (s.cycle_second / durationSeconds) * 100 : s.cycle_second;

  // Measured channels
  const dpData   = samples.map(s => ({ x: xOf(s), y: s.dp_bar   ?? null })).filter(p => p.y != null);
  const flData   = samples.map(s => ({ x: xOf(s), y: s.flow_l_min ?? null })).filter(p => p.y != null);
  const tpData   = samples.map(s => ({ x: xOf(s), y: s.temp_c   ?? null })).filter(p => p.y != null);
  const rfData   = samples.map(s => {
    const rv = s.r_eff ?? null;
    if (rv == null) return null;
    const norm = reffStart > 0 ? rv / reffStart : rv;
    return { x: xOf(s), y: norm };
  }).filter(Boolean);

  // Reference channels
  const curve = refCurve?.curve || [];
  const dpRef = [], dpUp = [], dpLo = [];
  const flRef = [], flUp = [], flLo = [];
  const tpRef = [], tpUp = [], tpLo = [];
  const rfRef = [], rfUp = [], rfLo = [];
  for (const p of curve) {
    if (p.dp  != null) { dpRef.push({x:p.t_pct,y:p.dp}); dpUp.push({x:p.t_pct,y:p.dp*(1+tolDp)}); dpLo.push({x:p.t_pct,y:Math.max(0,p.dp*(1-tolDp))}); }
    if (p.flow != null) { flRef.push({x:p.t_pct,y:p.flow}); flUp.push({x:p.t_pct,y:p.flow*(1+tolFlow)}); flLo.push({x:p.t_pct,y:Math.max(0,p.flow*(1-tolFlow))}); }
    if (p.temp != null) { tpRef.push({x:p.t_pct,y:p.temp}); tpUp.push({x:p.t_pct,y:p.temp+tolTempC}); tpLo.push({x:p.t_pct,y:p.temp-tolTempC}); }
    if (p.r_eff != null) { const n = reffStart > 0 ? p.r_eff/reffStart : p.r_eff; rfRef.push({x:p.t_pct,y:n}); rfUp.push({x:p.t_pct,y:n*(1+tolReff)}); rfLo.push({x:p.t_pct,y:Math.max(0,n*(1-tolReff))}); }
  }

  // Annotations for events
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

  // Dataset visibility helpers
  const hidden = ch => !_cycleModalVisible[ch];

  return {
    type: "line",
    data: {
      datasets: [
        // 0 dp tol upper
        { label: `_dp_up`, data: dpUp, yAxisID: "yDp",
          borderColor: DS_COLORS.tolEdge, backgroundColor: DS_COLORS.tolBand,
          borderWidth: 1, borderDash: [3,4], pointRadius: 0, tension: 0.3, parsing: false, fill: "+1", hidden: hidden("dp") },
        // 1 dp tol lower
        { label: "_dp_lo", data: dpLo, yAxisID: "yDp",
          borderColor: DS_COLORS.tolEdge, backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3,4], pointRadius: 0, tension: 0.3, parsing: false, fill: false, hidden: hidden("dp") },
        // 2 dp ref
        { label: "Ref Δp", data: dpRef, yAxisID: "yDp",
          borderColor: DS_COLORS.refLine, backgroundColor: "transparent",
          borderWidth: 1.5, borderDash: [10,5], pointRadius: 0, tension: 0.3, parsing: false, hidden: hidden("dp") },
        // 3 dp measured
        { label: "Δp", data: dpData, yAxisID: "yDp",
          borderColor: DS_COLORS.dp, backgroundColor: "rgba(56,189,248,0.07)",
          borderWidth: 2.5, pointRadius: 0, tension: 0.3, parsing: false, fill: "origin", hidden: hidden("dp") },
        // 4 flow tol upper
        { label: "_fl_up", data: flUp, yAxisID: "yFlow",
          borderColor: "rgba(52,211,153,0.4)", backgroundColor: "rgba(52,211,153,0.08)",
          borderWidth: 1, borderDash: [3,4], pointRadius: 0, tension: 0.3, parsing: false, fill: "+1", hidden: hidden("flow") },
        // 5 flow tol lower
        { label: "_fl_lo", data: flLo, yAxisID: "yFlow",
          borderColor: "rgba(52,211,153,0.4)", backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3,4], pointRadius: 0, tension: 0.3, parsing: false, fill: false, hidden: hidden("flow") },
        // 6 flow ref
        { label: "Ref Q", data: flRef, yAxisID: "yFlow",
          borderColor: "rgba(52,211,153,0.7)", backgroundColor: "transparent",
          borderWidth: 1.5, borderDash: [10,5], pointRadius: 0, tension: 0.3, parsing: false, hidden: hidden("flow") },
        // 7 flow measured
        { label: "Q", data: flData, yAxisID: "yFlow",
          borderColor: DS_COLORS.flow, backgroundColor: "rgba(52,211,153,0.07)",
          borderWidth: 2, pointRadius: 0, tension: 0.3, parsing: false, hidden: hidden("flow") },
        // 8 temp tol upper
        { label: "_tp_up", data: tpUp, yAxisID: "yTemp",
          borderColor: "rgba(251,146,60,0.4)", backgroundColor: "rgba(251,146,60,0.08)",
          borderWidth: 1, borderDash: [3,4], pointRadius: 0, tension: 0.3, parsing: false, fill: "+1", hidden: hidden("temp") },
        // 9 temp tol lower
        { label: "_tp_lo", data: tpLo, yAxisID: "yTemp",
          borderColor: "rgba(251,146,60,0.4)", backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3,4], pointRadius: 0, tension: 0.3, parsing: false, fill: false, hidden: hidden("temp") },
        // 10 temp ref
        { label: "Ref T", data: tpRef, yAxisID: "yTemp",
          borderColor: "rgba(251,146,60,0.7)", backgroundColor: "transparent",
          borderWidth: 1.5, borderDash: [10,5], pointRadius: 0, tension: 0.3, parsing: false, hidden: hidden("temp") },
        // 11 temp measured
        { label: "T", data: tpData, yAxisID: "yTemp",
          borderColor: DS_COLORS.temp, backgroundColor: "rgba(251,146,60,0.07)",
          borderWidth: 2, pointRadius: 0, tension: 0.3, parsing: false, hidden: hidden("temp") },
        // 12 reff tol upper
        { label: "_rf_up", data: rfUp, yAxisID: "yReff",
          borderColor: "rgba(167,139,250,0.4)", backgroundColor: "rgba(167,139,250,0.08)",
          borderWidth: 1, borderDash: [3,4], pointRadius: 0, tension: 0.3, parsing: false, fill: "+1", hidden: hidden("reff") },
        // 13 reff tol lower
        { label: "_rf_lo", data: rfLo, yAxisID: "yReff",
          borderColor: "rgba(167,139,250,0.4)", backgroundColor: "transparent",
          borderWidth: 1, borderDash: [3,4], pointRadius: 0, tension: 0.3, parsing: false, fill: false, hidden: hidden("reff") },
        // 14 reff ref
        { label: "Ref Rₑₑₑ", data: rfRef, yAxisID: "yReff",
          borderColor: "rgba(167,139,250,0.7)", backgroundColor: "transparent",
          borderWidth: 1.5, borderDash: [10,5], pointRadius: 0, tension: 0.3, parsing: false, hidden: hidden("reff") },
        // 15 reff measured
        { label: "Rₑₑₑ", data: rfData, yAxisID: "yReff",
          borderColor: DS_COLORS.reff, backgroundColor: "rgba(167,139,250,0.07)",
          borderWidth: 2, pointRadius: 0, tension: 0.3, parsing: false, hidden: hidden("reff") },
      ],
    },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true, position: "top",
          labels: { usePointStyle: true, padding: 12, font: { size: 11 }, color: "#cbd5e1",
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
              const lbl = ctx.dataset.label;
              if (lbl.startsWith("Ref ") || lbl.startsWith("Rₑ") || lbl === "Δp" || lbl === "Q" || lbl === "T") {
                return ` ${lbl}: ${v.toFixed(3)}`;
              }
              return ` ${lbl}: ${v.toFixed(3)}`;
            },
          },
        },
        annotation: { annotations },
      },
      scales: {
        x: { type: "linear", min: 0,
          title: { display: true, text: "Zyklusfortschritt [%]", font: { size: 11 }, color: "#94a3b8" },
          ticks: { font: { size: 10 }, color: "#64748b" },
          grid: { color: "rgba(100,130,160,0.15)" } },
        yDp: { type: "linear", position: "left", min: 0,
          title: { display: true, text: "Δp [bar]", font: { size: 10 }, color: "#94a3b8" },
          ticks: { font: { size: 10 }, color: "#64748b" },
          grid: { color: "rgba(100,130,160,0.15)" },
          display: _cycleModalVisible.dp },
        yFlow: { type: "linear", position: "right", min: 0,
          title: { display: true, text: "Q [l/min]", font: { size: 10 }, color: "#94a3b8" },
          ticks: { font: { size: 10 }, color: "#64748b" },
          grid: { drawOnChartArea: false },
          display: _cycleModalVisible.flow },
        yTemp: { type: "linear", position: "right",
          title: { display: true, text: "T [°C]", font: { size: 10 }, color: "#94a3b8" },
          ticks: { font: { size: 10 }, color: "#64748b" },
          grid: { drawOnChartArea: false },
          display: _cycleModalVisible.temp },
        yReff: { type: "linear", position: "right", min: 0,
          title: { display: true, text: "Rₑff [×]", font: { size: 10 }, color: "#94a3b8" },
          ticks: { font: { size: 10 }, color: "#64748b" },
          grid: { drawOnChartArea: false },
          display: _cycleModalVisible.reff },
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
  const overlay   = document.getElementById("cycle-modal-overlay");
  const titleEl   = document.getElementById("cycle-modal-title");
  const eventsEl  = document.getElementById("cycle-modal-events");
  const togglesEl = document.getElementById("cycle-modal-toggles");
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

  // Render channel toggle chips
  if (togglesEl) {
    const channels = [
      { key: "dp",   label: "Δp",  color: DS_COLORS.dp },
      { key: "flow", label: "Q",   color: DS_COLORS.flow },
      { key: "temp", label: "T",   color: DS_COLORS.temp },
      { key: "reff", label: "Rₑff", color: DS_COLORS.reff },
    ];
    togglesEl.innerHTML = channels.map(ch =>
      `<button class="chart-chip${_cycleModalVisible[ch.key] ? " chip-active" : ""}"
        data-ch="${ch.key}"
        style="--chip-color:${ch.color}"
        onclick="_toggleCycleChannel('${ch.key}', this)">${ch.label}</button>`
    ).join("");
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
}

function _toggleCycleChannel(ch, btn) {
  _cycleModalVisible[ch] = !_cycleModalVisible[ch];
  btn.classList.toggle("chip-active", _cycleModalVisible[ch]);
  if (!cycleModalChart) return;
  const ds = cycleModalChart.data.datasets;
  const scales = cycleModalChart.options.scales;
  // indices per channel: dp=0-3, flow=4-7, temp=8-11, reff=12-15
  const ranges = { dp: [0,3], flow: [4,7], temp: [8,11], reff: [12,15] };
  const axisMap = { dp: "yDp", flow: "yFlow", temp: "yTemp", reff: "yReff" };
  const [lo, hi] = ranges[ch];
  const vis = _cycleModalVisible[ch];
  for (let i = lo; i <= hi; i++) ds[i].hidden = !vis;
  if (scales[axisMap[ch]]) scales[axisMap[ch]].display = vis;
  cycleModalChart.update("none");
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
    // yPressure only visible when p1/p2 are shown (ds[0], ds[1])
    if (axisId === "yPressure") {
      const anyP = [0, 1].some(i => combinedChart.getDatasetMeta(i).hidden !== true);
      scales[axisId].display = anyP;
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

function clearCharts() {
  if (!combinedChart) return;
  combinedChart.data.labels = [];
  combinedChart.data.datasets.forEach(ds => { ds.data = []; });
  _knownCycleStart = null;
  _knownLiveCycleStart = null;
  _refCurveCache = null;
  _refCurveCacheCode = null;
  combinedChart.update("none");
  _refreshRefChips();
}
