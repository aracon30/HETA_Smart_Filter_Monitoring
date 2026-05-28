/**
 * HETA Smart Filter Monitoring – API-Funktionen
 * Wird nach utils.js und vor charts.js, app.js geladen.
 * Setzt API_BASE und TOKEN_KEY aus utils.js voraus.
 */

// ============================================================
// API-Basis-Wrapper
// ============================================================

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
