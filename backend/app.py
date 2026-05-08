"""
HETA Smart Filter Monitoring – Haupt-Backend-Applikation.

Startet den Flask-Webserver, den Messzyklus-Thread und koordiniert
alle Module (Sensoren, Berechnungen, Datenbank, Lernmodul, Prognose, Display).
"""

import os
import sys
import time
import json
import secrets
import logging
import threading
from datetime import datetime

# Projektverzeichnis in sys.path eintragen damit relative Imports funktionieren
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE_DIR, "backend"))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from config import settings, save_settings, get_abs_path, hash_password, verify_password
from sensors import read_sensors, reset_simulation, update_simulation_params
from calculations import calculate_filter_state, FilterState
from heta_code import verify_activation, validate_heta_format, get_demo_info
from database import Database
from learning import LearningManager
from prediction import PredictionEngine
from service_logic import (build_service_payload, generate_service_recommendation,
                            generate_spare_parts_order, generate_service_report)

# ---------------------------------------------------------------------------
# Logging konfigurieren
# ---------------------------------------------------------------------------
log_dir = get_abs_path(settings.get("log_path", "logs/"))
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, settings.get("log_level", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(log_dir, "heta_monitor.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask App initialisieren
# ---------------------------------------------------------------------------
app = Flask(
    __name__,
    static_folder=os.path.join(_BASE_DIR, "frontend"),
    static_url_path="",
)
CORS(app)

# ---------------------------------------------------------------------------
# Session-Token-Verwaltung (passwortgeschützter Einstellungsbereich)
# ---------------------------------------------------------------------------
# { token: last_access_timestamp }
_sessions: dict[str, float] = {}
_sessions_lock = threading.Lock()

# Kritische Parameter – bei Änderung muss der Lernprozess neu starten
_LEARNING_SENSITIVE_KEYS = {
    "dp_limit_bar", "dp_clean_bar", "flow_max_l_min",
    "pressure_range_bar", "temperature_min_c", "temperature_max_c",
}


def _create_session() -> str:
    """Erstellt einen neuen Session-Token und gibt ihn zurück."""
    token = secrets.token_hex(32)
    with _sessions_lock:
        _sessions[token] = time.time()
    return token


def _validate_session(token: str) -> bool:
    """Prüft ob ein Session-Token gültig und nicht abgelaufen ist."""
    if not token:
        return False
    timeout = settings.get("session_timeout_minutes", 30) * 60
    with _sessions_lock:
        last = _sessions.get(token)
        if last is None:
            return False
        if time.time() - last > timeout:
            del _sessions[token]
            return False
        # Zugriff erneuert die Sitzung
        _sessions[token] = time.time()
    return True


def _invalidate_session(token: str):
    """Löscht einen Session-Token."""
    with _sessions_lock:
        _sessions.pop(token, None)


def _require_auth():
    """
    Hilfsfunktion für geschützte Endpunkte.
    Gibt (True, None) zurück wenn authentifiziert, sonst (False, Response).
    """
    token = request.headers.get("X-Auth-Token", "") or request.args.get("token", "")
    if _validate_session(token):
        return True, None
    return False, (jsonify({"success": False, "message": "Nicht authentifiziert. Bitte anmelden."}), 401)


# ---------------------------------------------------------------------------
# Systemzustand
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()

_state = {
    # Betriebsmodus
    "simulation_mode": settings.get("simulation_mode", True),
    "sensor_mode": "simulation",
    "running": False,

    # Messwerte
    "p1_bar": 0.0,
    "p2_bar": 0.0,
    "dp_bar": 0.0,
    "flow_l_min": 0.0,
    "temperature_c": 0.0,
    "r_eff": 0.0,
    "filter_health_percent": 100.0,
    "filter_status": "OK",
    "sensor_error": False,

    # HETA-Code
    "heta_code": "",
    "heta_activated": False,
    "heta_number": "",

    # Filterwechsel
    "awaiting_confirmation": False,
    "cycle_active": False,
    "cycle_start_time": None,

    # Prognose
    "remaining_display": "Unbekannt",
    "remaining_seconds": None,
    "prediction_mode": "BASIS",

    # Lernmodul
    "learned_cycles": 0,
    "profile_status": "LERNEND",
    "anomaly_active": False,
    "anomaly_percent": 0.0,
    # Beladungsgrad nur anzeigen wenn HETA-Code aktiv
    "show_filter_health": False,

    # Servicehinweis
    "service_message": "",
    "service_priority": "NIEDRIG",

    "last_update": None,
}

# ---------------------------------------------------------------------------
# Module initialisieren
# ---------------------------------------------------------------------------
db = Database(get_abs_path(settings.get("db_path", "data/heta_monitor.db")))
learning = LearningManager(
    db,
    required_cycles=settings.get("required_cycles_for_profile", 3),
    clean_resistance_tolerance=settings.get("clean_resistance_tolerance", 0.25),
)
predictor = PredictionEngine(
    dp_limit=settings.get("dp_limit_bar", 2.5),
    dp_clean=settings.get("dp_clean_bar", 0.2),
    smoothing_factor=settings.get("smoothing_factor", 0.15),
    max_increase_pct=settings.get("max_increase_percent_per_update", 2.0),
    max_decrease_pct=settings.get("max_decrease_percent_per_update", 8.0),
    min_slope=settings.get("min_slope", 0.001),
)

# MQTT optional
_mqtt = None
if settings.get("mqtt_enabled", False):
    from mqtt_client import MQTTClient
    _mqtt = MQTTClient()
    _mqtt.connect()

# Display optional
_display = None
try:
    from display import OLEDDisplay
    _display = OLEDDisplay()
except Exception as e:
    logger.warning("Display-Init übersprungen: %s", e)

# Navigation optional
_navigation = None
try:
    from navigation import NavigationController
    _navigation = NavigationController()
    _navigation.start()
except Exception as e:
    logger.warning("Navigation-Init übersprungen: %s", e)

# ---------------------------------------------------------------------------
# Messzyklus-Thread
# ---------------------------------------------------------------------------

def _measurement_loop():
    """Haupt-Messzyklus – läuft in einem Hintergrund-Thread."""
    interval = settings.get("sampling_interval_seconds", 1)
    dp_limit = settings.get("dp_limit_bar", 2.5)
    dp_clean = settings.get("dp_clean_bar", 0.2)

    logger.info("Messzyklus gestartet (Intervall: %ds).", interval)

    while _state["running"]:
        t_start = time.time()

        with _state_lock:
            sim_mode = _state["simulation_mode"]
            awaiting = _state["awaiting_confirmation"]
            heta_code = _state["heta_code"]
            heta_activated = _state["heta_activated"]
            cycle_active = _state["cycle_active"]

        if awaiting:
            time.sleep(interval)
            continue

        # Sensoren lesen
        readings = read_sensors(
            simulation=sim_mode,
            pressure_range=settings.get("pressure_range_bar", 10.0),
            temperature_min=settings.get("temperature_min_c", -50.0),
            temperature_max=settings.get("temperature_max_c", 150.0),
            flow_max=settings.get("flow_max_l_min", 150.0),
        )

        p1 = readings["p1"]
        p2 = readings["p2"]
        temp = readings["temperature"]
        flow = readings["flow"]
        sensor_mode = readings["mode"]
        sensor_error = not (p1.is_valid and p2.is_valid and temp.is_valid and flow.is_valid)

        # Berechnungen
        fs: FilterState = calculate_filter_state(
            p1_bar=p1.value,
            p2_bar=p2.value,
            flow_l_min=flow.value,
            temperature_c=temp.value,
            dp_clean=dp_clean,
            dp_limit=dp_limit,
            awaiting_confirmation=awaiting,
            sensor_error=sensor_error,
            anomaly_active=_state["anomaly_active"],
            anomaly_percent=_state["anomaly_percent"],
        )

        # Zyklus starten falls nötig
        if not cycle_active and not sensor_error and heta_code:
            learning.start_cycle(heta_code, fs.r_eff, fs.dp_bar)
            with _state_lock:
                _state["cycle_active"] = True
                _state["cycle_start_time"] = time.time()
            logger.info("Neuer Filterzyklus gestartet.")

        # Lernwert erfassen
        if cycle_active and not sensor_error:
            learning.record_sample(fs.flow_l_min, fs.temperature_c,
                                   fs.dp_bar, fs.r_eff)

        # Startverhalten prüfen (nur am Zyklusanfang, erste 10 Sekunden)
        if (cycle_active and heta_activated
                and _state.get("cycle_start_time")
                and (time.time() - _state["cycle_start_time"]) < 10):
            anomaly, anom_pct = learning.check_start_behavior(heta_code, fs.r_eff)
            with _state_lock:
                _state["anomaly_active"] = anomaly
                _state["anomaly_percent"] = anom_pct

        # Prognose
        remaining_s = predictor.update(fs.dp_bar)
        profile_valid = learning.is_profile_valid(heta_code) and heta_activated
        cycles_count  = learning.get_cycles_count(heta_code) if heta_code else 0
        req_cycles    = settings.get("required_cycles_for_profile", 3)
        pred_status = predictor.get_status(
            remaining_seconds=remaining_s,
            heta_activated=heta_activated,
            profile_valid=profile_valid,
            learned_cycles=cycles_count,
            required_cycles=req_cycles,
        )

        # Filterwechsel erkennen
        if fs.dp_bar >= dp_limit and not awaiting and cycle_active:
            logger.warning("Filterwechsel-Grenzwert überschritten! dp=%.3f >= %.2f",
                           fs.dp_bar, dp_limit)
            with _state_lock:
                _state["awaiting_confirmation"] = True
            if _display:
                _display.show_filter_change(fs.dp_bar, dp_limit)
            if _mqtt:
                _mqtt.publish_alarm("WECHSEL", "Filterwechsel erforderlich!", heta_code)

        # Serviceempfehlung
        rec = generate_service_recommendation(fs, pred_status)

        # Datenbank
        db.insert_measurement({
            "timestamp": time.time(),
            "p1_bar": fs.p1_bar,
            "p2_bar": fs.p2_bar,
            "dp_bar": fs.dp_bar,
            "flow_l_min": fs.flow_l_min,
            "temperature_c": fs.temperature_c,
            "r_eff": fs.r_eff,
            "filter_health_percent": fs.filter_health_percent,
            "status": fs.status,
            "heta_code": heta_code,
            "sensor_mode": sensor_mode,
        })

        # MQTT
        if _mqtt and _mqtt.is_connected:
            _mqtt.publish_measurements(fs, heta_code)

        # Display aktualisieren
        if _display:
            _display.show_status({
                "heta_code": heta_code or "---",
                "mode": "SIM" if sim_mode else "HW",
                "p1": fs.p1_bar,
                "p2": fs.p2_bar,
                "dp": fs.dp_bar,
                "flow": fs.flow_l_min,
                "remaining": pred_status["remaining_display"],
                "status": fs.status,
            })

        # Systemzustand aktualisieren
        with _state_lock:
            _state.update({
                "sensor_mode": sensor_mode,
                "p1_bar": fs.p1_bar,
                "p2_bar": fs.p2_bar,
                "dp_bar": fs.dp_bar,
                "flow_l_min": fs.flow_l_min,
                "temperature_c": fs.temperature_c,
                "r_eff": fs.r_eff,
                "filter_health_percent": fs.filter_health_percent,
                "filter_status": fs.status,
                "sensor_error": fs.sensor_error,
                "remaining_display": pred_status["remaining_display"],
                "remaining_seconds": pred_status["remaining_seconds"],
                "prediction_mode": pred_status["prediction_mode"],
                "learned_cycles": cycles_count,
                "profile_status": "VALIDIERT" if profile_valid else "LERNEND",
                "show_filter_health": heta_activated,
                "service_message": rec["message"],
                "service_priority": rec["priority"],
                "last_update": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })

        elapsed = time.time() - t_start
        sleep_time = max(0.0, interval - elapsed)
        time.sleep(sleep_time)

    logger.info("Messzyklus beendet.")


_measure_thread: threading.Thread = None


def _start_measurement_thread():
    global _measure_thread
    if _measure_thread and _measure_thread.is_alive():
        return
    _state["running"] = True
    _measure_thread = threading.Thread(target=_measurement_loop, daemon=True)
    _measure_thread.start()


# ---------------------------------------------------------------------------
# REST API Endpunkte
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status")
def api_status():
    """Vollständiger Systemstatus."""
    with _state_lock:
        return jsonify(dict(_state))


@app.route("/api/measurements/latest")
def api_measurements_latest():
    """Letzte N Messwerte aus der Datenbank."""
    limit = min(int(request.args.get("limit", 100)), 1000)
    rows = db.get_latest_measurements(limit)
    return jsonify(rows)


@app.route("/api/measurements/history")
def api_measurements_history():
    """Messwerte seit einem Zeitstempel."""
    since = float(request.args.get("since", time.time() - 3600))
    rows = db.get_measurements_since(since)
    return jsonify(rows)


@app.route("/api/heta/activate", methods=["POST"])
def api_heta_activate():
    """Aktiviert einen HETA-Code mit dem zugehörigen PIN."""
    data = request.get_json(force=True, silent=True) or {}
    heta_code = data.get("heta_code", "").strip()
    pin = data.get("pin", "").strip()

    result = verify_activation(heta_code, pin)
    if result["valid"]:
        with _state_lock:
            _state["heta_code"] = result["heta_code"]
            _state["heta_activated"] = True
            _state["heta_number"] = result["heta_number"]
        db.insert_service_event("HETA_AKTIVIERT", result["heta_code"],
                                json.dumps(result, ensure_ascii=False))
        logger.info("HETA-Code %s aktiviert.", result["heta_code"])
    return jsonify(result)


@app.route("/api/heta/demo", methods=["GET"])
def api_heta_demo():
    """Demo: gibt Aktivierungscode für einen HETA-Code zurück (nur für Tests!)."""
    heta_code = request.args.get("heta_code", "")
    return jsonify(get_demo_info(heta_code))


@app.route("/api/filter/confirm-change", methods=["POST"])
def api_confirm_filter_change():
    """Bestätigt den Filterwechsel und startet einen neuen Zyklus."""
    with _state_lock:
        heta_code = _state["heta_code"]
        cycle_was_active = _state["cycle_active"]

    # Zyklus abschließen
    if cycle_was_active and learning.active_cycle:
        with _state_lock:
            current_r = _state["r_eff"]
            current_dp = _state["dp_bar"]
        learning.end_cycle(confirmed=True,
                           end_r_eff=current_r,
                           end_dp=current_dp)

    # Prognose und Simulation zurücksetzen
    predictor.reset()
    reset_simulation()

    with _state_lock:
        _state["awaiting_confirmation"] = False
        _state["cycle_active"] = False
        _state["cycle_start_time"] = None
        _state["anomaly_active"] = False
        _state["anomaly_percent"] = 0.0

    db.insert_service_event("FILTERWECHSEL_BESTAETIGT", heta_code,
                            json.dumps({"timestamp": time.time()}))
    logger.info("Filterwechsel bestätigt. Neuer Zyklus beginnt.")
    return jsonify({"success": True, "message": "Filterwechsel bestätigt. Neuer Zyklus startet."})


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    """Liest die Konfiguration (öffentlich, ohne sensible Felder)."""
    safe = {k: v for k, v in settings.items()
            if k not in ("settings_password_hash",)}
    return jsonify(safe)


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    """
    Aktualisiert die Konfiguration – nur mit gültigem Session-Token.
    Wenn lernrelevante Parameter geändert werden, werden alle Lerndaten
    gelöscht und der Lernprozess startet neu.
    """
    ok, err = _require_auth()
    if not ok:
        return err

    data = request.get_json(force=True, silent=True) or {}

    # Prüfen welche lernrelevanten Parameter sich ändern
    learning_reset_needed = any(
        k in _LEARNING_SENSITIVE_KEYS and data.get(k) != settings.get(k)
        for k in data
    )

    # Passwortänderung separat behandeln
    new_password = data.pop("new_password", None)
    old_password = data.pop("old_password", None)
    if new_password:
        if not verify_password(old_password or "", settings.get("settings_password_hash", "")):
            return jsonify({"success": False, "message": "Altes Passwort falsch."}), 403
        settings["settings_password_hash"] = hash_password(new_password)

    # Nur bekannte Felder übernehmen, interne Felder schützen
    protected = {"settings_password_hash", "db_path", "log_path", "export_path",
                 "webserver_host", "webserver_port", "onboarding_complete"}
    for k, v in data.items():
        if k in settings and k not in protected:
            settings[k] = v

    # Simulation-Parameter und Prognose aktualisieren
    update_simulation_params(
        dp_clean=settings["dp_clean_bar"],
        dp_limit=settings["dp_limit_bar"],
        flow_max=settings["flow_max_l_min"],
    )
    predictor.update_limits(settings["dp_limit_bar"], settings["dp_clean_bar"])
    save_settings(settings)

    with _state_lock:
        _state["simulation_mode"] = settings["simulation_mode"]

    # Lerndaten zurücksetzen wenn nötig
    if learning_reset_needed:
        db.reset_all_learning_data()
        predictor.reset()
        reset_simulation()
        with _state_lock:
            _state["cycle_active"] = False
            _state["cycle_start_time"] = None
            _state["anomaly_active"] = False
            _state["anomaly_percent"] = 0.0
        db.insert_service_event(
            "LERNDATEN_RESET",
            _state.get("heta_code", ""),
            json.dumps({"grund": "Konfigurationsänderung", "geaenderte_parameter":
                        [k for k in data if k in _LEARNING_SENSITIVE_KEYS]}),
        )
        logger.info("Lerndaten zurückgesetzt aufgrund Konfigurationsänderung: %s",
                    [k for k in data if k in _LEARNING_SENSITIVE_KEYS])

    safe = {k: v for k, v in settings.items() if k not in ("settings_password_hash",)}
    return jsonify({
        "success": True,
        "settings": safe,
        "learning_reset": learning_reset_needed,
        "message": ("Einstellungen gespeichert. Lernprozess wurde zurückgesetzt und muss neu durchlaufen werden."
                    if learning_reset_needed else "Einstellungen gespeichert."),
    })


# ---------------------------------------------------------------------------
# Authentifizierung (Einstellungsbereich)
# ---------------------------------------------------------------------------

@app.route("/api/settings/login", methods=["POST"])
def api_settings_login():
    """Meldet den Benutzer am Einstellungsbereich an."""
    data = request.get_json(force=True, silent=True) or {}
    password = data.get("password", "")
    stored_hash = settings.get("settings_password_hash", "")

    if not stored_hash:
        return jsonify({"success": False, "message": "Kein Passwort gesetzt. Onboarding abschließen."}), 403

    if verify_password(password, stored_hash):
        token = _create_session()
        logger.info("Einstellungsbereich: Anmeldung erfolgreich.")
        return jsonify({"success": True, "token": token,
                        "timeout_minutes": settings.get("session_timeout_minutes", 30)})
    else:
        logger.warning("Einstellungsbereich: Falsches Passwort.")
        return jsonify({"success": False, "message": "Falsches Passwort."}), 401


@app.route("/api/settings/logout", methods=["POST"])
def api_settings_logout():
    """Beendet die Sitzung."""
    token = request.headers.get("X-Auth-Token", "") or request.get_json(force=True, silent=True or {}).get("token", "")
    _invalidate_session(token)
    return jsonify({"success": True, "message": "Abgemeldet."})


@app.route("/api/settings/auth-check", methods=["GET"])
def api_settings_auth_check():
    """Prüft ob der aktuelle Token noch gültig ist."""
    token = request.headers.get("X-Auth-Token", "") or request.args.get("token", "")
    return jsonify({"authenticated": _validate_session(token)})


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

@app.route("/api/onboarding/status", methods=["GET"])
def api_onboarding_status():
    """Gibt zurück ob das Onboarding bereits abgeschlossen wurde."""
    return jsonify({
        "onboarding_complete": settings.get("onboarding_complete", False),
        "has_password": bool(settings.get("settings_password_hash", "")),
    })


@app.route("/api/onboarding/complete", methods=["POST"])
def api_onboarding_complete():
    """
    Schließt das Onboarding ab und speichert alle Einstellungen.
    Kann nur aufgerufen werden wenn onboarding_complete=false.
    """
    if settings.get("onboarding_complete", False):
        return jsonify({"success": False, "message": "Onboarding bereits abgeschlossen."}), 400

    data = request.get_json(force=True, silent=True) or {}

    # Passwort ist Pflichtfeld beim Onboarding
    password = data.get("password", "")
    if len(password) < 4:
        return jsonify({"success": False,
                        "message": "Passwort muss mindestens 4 Zeichen haben."}), 400

    # Konfigurierbare Felder aus dem Onboarding
    onboarding_fields = {
        "simulation_mode", "dp_limit_bar", "dp_clean_bar",
        "flow_max_l_min", "pressure_range_bar",
        "temperature_min_c", "temperature_max_c",
        "sampling_interval_seconds",
    }
    for k, v in data.items():
        if k in onboarding_fields:
            settings[k] = v

    settings["settings_password_hash"] = hash_password(password)
    settings["onboarding_complete"] = True
    save_settings(settings)

    # Simulation neu initialisieren mit den Onboarding-Werten
    update_simulation_params(
        dp_clean=settings["dp_clean_bar"],
        dp_limit=settings["dp_limit_bar"],
        flow_max=settings["flow_max_l_min"],
    )
    predictor.update_limits(settings["dp_limit_bar"], settings["dp_clean_bar"])

    with _state_lock:
        _state["simulation_mode"] = settings["simulation_mode"]

    db.insert_service_event("ONBOARDING_ABGESCHLOSSEN", "",
                            json.dumps({"timestamp": time.time()}))
    logger.info("Onboarding abgeschlossen.")

    # Messzyklus starten
    if not _state["running"]:
        _start_measurement_thread()

    return jsonify({"success": True, "message": "Einrichtung abgeschlossen. System startet."})


@app.route("/api/simulation/start", methods=["POST"])
def api_simulation_start():
    """Startet den Simulationsmodus und den Messzyklus."""
    with _state_lock:
        _state["simulation_mode"] = True
    reset_simulation()
    if not _state["running"]:
        _start_measurement_thread()
    return jsonify({"success": True, "message": "Simulation gestartet."})


@app.route("/api/simulation/stop", methods=["POST"])
def api_simulation_stop():
    """Stoppt den Messzyklus."""
    with _state_lock:
        _state["running"] = False
    return jsonify({"success": True, "message": "Simulation gestoppt."})


@app.route("/api/simulation/reset", methods=["POST"])
def api_simulation_reset():
    """Setzt Simulation und Prognose zurück."""
    reset_simulation()
    predictor.reset()
    with _state_lock:
        _state["awaiting_confirmation"] = False
        _state["cycle_active"] = False
        _state["anomaly_active"] = False
        _state["anomaly_percent"] = 0.0
        _state["heta_activated"] = False
        _state["heta_code"] = ""
        _state["heta_number"] = ""
    return jsonify({"success": True, "message": "System zurückgesetzt."})


@app.route("/api/service/request", methods=["POST"])
def api_service_request():
    """Erstellt ein Servicedatenpaket und einen Servicebericht."""
    with _state_lock:
        current = dict(_state)

    from calculations import FilterState
    fs = FilterState(
        p1_bar=current["p1_bar"],
        p2_bar=current["p2_bar"],
        dp_bar=current["dp_bar"],
        flow_l_min=current["flow_l_min"],
        temperature_c=current["temperature_c"],
        r_eff=current["r_eff"],
        filter_health_percent=current["filter_health_percent"],
        usage_ratio=0.0,
        status=current["filter_status"],
        sensor_error=current["sensor_error"],
        anomaly_active=current["anomaly_active"],
        anomaly_percent=current["anomaly_percent"],
    )

    pred_status = {
        "prediction_mode":  current["prediction_mode"],
        "remaining_display": current["remaining_display"],
        "remaining_seconds": current["remaining_seconds"],
        "learned_cycles":    current["learned_cycles"],
    }

    payload = build_service_payload(
        filter_state=fs,
        heta_code=current["heta_code"],
        activation_status=current["heta_activated"],
        prediction_status=pred_status,
        learned_cycles=current["learned_cycles"],
        profile_status=(current["profile_status"] == "VALIDIERT"),
        anomaly_active=current["anomaly_active"],
        anomaly_percent=current["anomaly_percent"],
        action="SERVICE_ANFRAGE",
    )
    rec = generate_service_recommendation(fs, pred_status)
    spare = generate_spare_parts_order(current["heta_code"], fs)
    report = generate_service_report(payload, rec, spare)

    db.insert_service_event("SERVICE_ANFRAGE", current["heta_code"],
                            json.dumps(payload, ensure_ascii=False))

    if _mqtt and _mqtt.is_connected:
        _mqtt.publish_service(payload)

    return jsonify({
        "payload": payload,
        "recommendation": rec,
        "spare_parts": spare,
        "report_text": report,
    })


@app.route("/api/export/csv")
def api_export_csv():
    """Exportiert Messwerte als CSV-Datei und gibt den Pfad zurück."""
    since = float(request.args.get("since", 0))
    export_dir = get_abs_path(settings.get("export_path", "exports/"))
    filename = f"heta_export_{int(time.time())}.csv"
    filepath = os.path.join(export_dir, filename)
    count = db.export_measurements_csv(filepath, since_timestamp=since)
    return jsonify({
        "success": count > 0,
        "filename": filename,
        "rows": count,
        "path": filepath,
    })


@app.route("/api/export/csv/download")
def api_export_csv_download():
    """Exportiert und lädt die CSV-Datei direkt herunter."""
    since = float(request.args.get("since", 0))
    export_dir = get_abs_path(settings.get("export_path", "exports/"))
    os.makedirs(export_dir, exist_ok=True)
    filename = f"heta_export_{int(time.time())}.csv"
    filepath = os.path.join(export_dir, filename)
    db.export_measurements_csv(filepath, since_timestamp=since)
    return send_from_directory(export_dir, filename,
                               as_attachment=True,
                               download_name="heta_messwerte.csv")


@app.route("/api/cycles")
def api_cycles():
    """Gibt die Filterzyklen für einen HETA-Code zurück."""
    heta_code = request.args.get("heta_code", _state.get("heta_code", ""))
    if not heta_code:
        return jsonify([])
    return jsonify(db.get_cycles_for_heta(heta_code))


@app.route("/api/profile")
def api_profile():
    """Gibt das Lernprofil für einen HETA-Code zurück."""
    heta_code = request.args.get("heta_code", _state.get("heta_code", ""))
    if not heta_code:
        return jsonify(None)
    return jsonify(db.get_profile(heta_code))


# ---------------------------------------------------------------------------
# Anwendungsstart
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = settings.get("webserver_host", "0.0.0.0")
    port = settings.get("webserver_port", 8080)

    logger.info("HETA Smart Filter Monitoring startet auf %s:%d", host, port)
    logger.info("Simulationsmodus: %s", settings.get("simulation_mode", True))
    logger.info("Onboarding abgeschlossen: %s", settings.get("onboarding_complete", False))

    # Messzyklus nur starten wenn Onboarding abgeschlossen
    if settings.get("onboarding_complete", False):
        _start_measurement_thread()
    else:
        logger.info("Onboarding ausstehend – Messzyklus wartet.")

    app.run(host=host, port=port, debug=False, threaded=True)
