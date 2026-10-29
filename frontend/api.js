/**
 * HETA Smart Filter Monitoring – API-Funktionen
 * Wird nach utils.js und vor charts.js, app.js geladen.
 * Setzt API_BASE und TOKEN_KEY aus utils.js voraus.
 */

// ============================================================
// API-Basis-Wrapper
// ============================================================

/**
 * Standard-Aufruf. Ein vorhandenes Sitzungs-Token wird automatisch mitgesendet.
 * Antwortet der Server mit 401 (geschützter Endpunkt, nicht angemeldet), fragt
 * der Login-Dialog nach dem Passwort und die Anfrage wird einmal wiederholt.
 */
async function apiFetch(path, method = "GET", body = null) {
  try {
    let resp = await _apiRequest(path, method, body, sessionStorage.getItem(TOKEN_KEY));
    if (resp.status === 401 && path !== "/api/settings/login") {
      sessionStorage.removeItem(TOKEN_KEY);
      const token = await requestLogin();
      if (token) resp = await _apiRequest(path, method, body, token);
    }
    return await resp.json();
  } catch (e) {
    console.error("API-Fehler:", e);
    return null;
  }
}

async function apiFetchAuth(path, method, body, token) {
  try {
    const resp = await _apiRequest(path, method, body, token);
    if (resp.status === 401) return null;  // Token abgelaufen
    return await resp.json();
  } catch (e) {
    console.error("Auth-API-Fehler:", e);
    return null;
  }
}

function _apiRequest(path, method, body, token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-Auth-Token"] = token;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  return fetch(`${API_BASE}${path}`, opts);
}

// ============================================================
// Login-Dialog für geschützte Aktionen
// ============================================================

let _loginPromise = null;
let _loginResolve = null;

/**
 * Öffnet den Login-Dialog und liefert das neue Token (oder null bei Abbruch).
 * Mehrere gleichzeitige Anfragen (z. B. Slider-Updates) teilen sich einen Dialog.
 */
function requestLogin() {
  if (_loginPromise) return _loginPromise;
  _loginPromise = new Promise(resolve => { _loginResolve = resolve; });
  showMsg("auth-msg", "", false);
  document.getElementById("auth-overlay").classList.remove("hidden");
  setTimeout(() => document.getElementById("auth-pw-input")?.focus(), 100);
  return _loginPromise;
}

async function submitAuthLogin() {
  const input = document.getElementById("auth-pw-input");
  const resp = await _apiRequest("/api/settings/login", "POST", { password: input.value }, null);
  const result = await resp.json().catch(() => null);
  if (result?.success) {
    sessionStorage.setItem(TOKEN_KEY, result.token);
    _finishLogin(result.token);
  } else {
    showMsg("auth-msg", result?.message ?? "Fehler.", true);
  }
}

function cancelAuthLogin() {
  _finishLogin(null);
}

function _finishLogin(token) {
  document.getElementById("auth-pw-input").value = "";
  document.getElementById("auth-overlay").classList.add("hidden");
  const resolve = _loginResolve;
  _loginPromise = null;
  _loginResolve = null;
  if (resolve) resolve(token);
}
