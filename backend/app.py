"""
HETA Smart Filter Monitoring – Haupt-Backend-Applikation.

Startet den Flask-Webserver, den Messzyklus-Thread und koordiniert
alle Module (Sensoren, Berechnungen, Datenbank, Lernmodul, Prognose, Display).
"""

import os
import sys
import subprocess
import time
import json
import socket
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


def _get_local_ip() -> str:
    """Ermittelt die lokale IP-Adresse des Geräts."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _parse_i2cdetect(output: str) -> list:
    """Parst die Ausgabe von 'i2cdetect -y 1' und gibt gefundene Adressen als int-Liste zurück."""
    addresses = []
    for line in output.splitlines():
        parts = line.split()
        if not parts or ":" not in parts[0]:
            continue
        for p in parts[1:]:
            if p not in ("--", "UU"):
                try:
                    addresses.append(int(p, 16))
                except ValueError:
                    pass
    return addresses


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
    _mqtt = MQTTClient(
        broker=settings.get("mqtt_broker", "localhost"),
        port=settings.get("mqtt_port", 1883),
        client_id=settings.get("mqtt_client_id", "heta_monitor"),
    )
    _mqtt.connect()

# Display optional
_display = None
if settings.get("display_enabled", True):
    try:
        from display import OLEDDisplay
        _display = OLEDDisplay(
            use_spi=settings.get("display_use_spi", True),
            spi_port=settings.get("display_spi_port", 0),
            spi_device=settings.get("display_spi_device", 0),
            gpio_dc=settings.get("display_gpio_dc", 25),
            gpio_rst=settings.get("display_gpio_rst", 27),
            i2c_address=settings.get("display_i2c_address", 60),
        )
    except Exception as e:
        logger.warning("Display-Init übersprungen: %s", e)

# Navigation optional
_navigation = None
if settings.get("navigation_enabled", True):
    try:
        from navigation import NavigationController
        _navigation = NavigationController(
            i2c_address=settings.get("encoder_i2c_address", 73),
        )
        _navigation.start()
    except Exception as e:
        logger.warning("Navigation-Init übersprungen: %s", e)


# ---------------------------------------------------------------------------
# Display-Controller (verbindet Encoder mit Display)
# ---------------------------------------------------------------------------

class _DisplayController:
    """
    Verbindet den ANO Rotary Encoder mit dem OLED-Display.

    Bildschirme (per Encoder-Drehung navigierbar):
      0 Status · 1 HETA-Code · 2 Filterwechsel · 3 Service · 4 Historie · 5 Netzwerk

    Filterwechsel-Bestätigung am Gerät:
      1. Encoder auf Bildschirm 2 drehen (oder automatisch, wenn dp >= limit)
      2. OK-Taste (PRESS) → Bestätigung vormerken (armed)
      3. Nochmals OK-Taste → Filterwechsel bestätigen
      LINKS-Taste während armed → Abbruch
    """

    def __init__(self, disp, nav):
        from display import SCREENS
        self._display = disp
        self._nav = nav
        self._screens = SCREENS          # list of screen name constants
        self._screen_idx = 0             # 0 = Status
        self._confirm_armed = False
        self._last_status_data: dict = {}
        self._lock = threading.Lock()
        disp.set_nav_index(0)
        nav.register_handler(self._on_event)

    # ------------------------------------------------------------------
    # Öffentliche Schnittstelle
    # ------------------------------------------------------------------

    def update_status(self, data: dict):
        """Vom Messzyklus aufgerufen – aktualisiert nur wenn Status-Bildschirm aktiv."""
        with self._lock:
            self._last_status_data = data
            if self._screen_idx == 0:
                self._display.show_status(data)

    def navigate_to_filter_change(self):
        """Wechselt automatisch zum Filterwechsel-Bildschirm (bei dp >= limit)."""
        from display import SCREEN_FILTER_CHANGE
        with self._lock:
            self._screen_idx = self._screens.index(SCREEN_FILTER_CHANGE)
            self._confirm_armed = False

    # ------------------------------------------------------------------
    # Ereignis-Handler
    # ------------------------------------------------------------------

    def _on_event(self, event: str):
        with self._lock:
            self._handle(event)

    def _handle(self, event: str):
        from navigation import NavigationEvent
        from display import SCREEN_FILTER_CHANGE

        if event in (NavigationEvent.ROTATE_RIGHT, NavigationEvent.RIGHT):
            self._screen_idx = (self._screen_idx + 1) % len(self._screens)
            self._confirm_armed = False
            self._display.set_nav_index(self._screen_idx)
            self._refresh_display()

        elif event in (NavigationEvent.ROTATE_LEFT, NavigationEvent.LEFT):
            if self._confirm_armed:
                # Abbruch der Bestätigung
                self._confirm_armed = False
                self._refresh_display()
            else:
                self._screen_idx = (self._screen_idx - 1) % len(self._screens)
                self._display.set_nav_index(self._screen_idx)
                self._refresh_display()

        elif event == NavigationEvent.PRESS:
            self._handle_press()

    def _handle_press(self):
        from display import SCREEN_FILTER_CHANGE
        screen = self._screens[self._screen_idx]

        if screen != SCREEN_FILTER_CHANGE:
            return

        with _state_lock:
            awaiting = _state["awaiting_confirmation"]
            dp = _state["dp_bar"]

        if not awaiting:
            return

        if not self._confirm_armed:
            self._confirm_armed = True
            self._display.show_filter_change(
                dp, settings.get("dp_limit_bar", 2.5),
                armed=True, awaiting=True,
            )
        else:
            self._confirm_armed = False
            _do_confirm_filter_change()
            # Zurück zum Status-Bildschirm
            self._screen_idx = 0
            self._display.show_status(self._last_status_data)

    # ------------------------------------------------------------------
    # Display-Refresh
    # ------------------------------------------------------------------

    def _refresh_display(self):
        from display import (SCREEN_STATUS, SCREEN_HETA, SCREEN_FILTER_CHANGE,
                              SCREEN_SERVICE, SCREEN_HISTORY, SCREEN_NETWORK)

        screen = self._screens[self._screen_idx]

        if screen == SCREEN_STATUS:
            self._display.show_status(self._last_status_data)

        elif screen == SCREEN_HETA:
            with _state_lock:
                code           = _state["heta_code"]
                activated      = _state["heta_activated"]
                learned        = _state["learned_cycles"]
                pred_mode      = _state["prediction_mode"]
            req = settings.get("required_cycles_for_profile", 3)
            self._display.show_heta_code(
                code, activated,
                learned_cycles=learned,
                required_cycles=req,
                prediction_mode=pred_mode,
            )

        elif screen == SCREEN_FILTER_CHANGE:
            with _state_lock:
                dp = _state["dp_bar"]
                awaiting = _state["awaiting_confirmation"]
            self._display.show_filter_change(
                dp, settings.get("dp_limit_bar", 2.5),
                armed=self._confirm_armed, awaiting=awaiting,
            )

        elif screen == SCREEN_SERVICE:
            with _state_lock:
                msg = _state["service_message"]
                prio = _state["service_priority"]
            self._display.show_service(msg or "Kein Hinweis", prio or "NIEDRIG")

        elif screen == SCREEN_HISTORY:
            cycles = db.get_recent_cycles(4)
            self._display.show_history(cycles)

        elif screen == SCREEN_NETWORK:
            ip = _get_local_ip()
            self._display.show_network(
                ip,
                settings.get("webserver_port", 8080),
                "SIM" if settings.get("simulation_mode", True) else "HW",
            )


# Display-Controller instanziieren wenn beide Module verfügbar
_display_ctrl: _DisplayController = None
if _display and _navigation:
    try:
        _display_ctrl = _DisplayController(_display, _navigation)
        logger.info("Display-Controller initialisiert.")
    except Exception as e:
        logger.warning("Display-Controller-Init fehlgeschlagen: %s", e)


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
            if _display_ctrl:
                _display_ctrl.navigate_to_filter_change()
                _display.show_filter_change(fs.dp_bar, dp_limit, armed=False, awaiting=True)
            elif _display:
                _display.show_filter_change(fs.dp_bar, dp_limit, armed=False, awaiting=True)
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
        _status_display_data = {
            "heta_code":   heta_code or "---",
            "mode":        "SIM" if sim_mode else "HW",
            "p1":          fs.p1_bar,
            "p2":          fs.p2_bar,
            "dp":          fs.dp_bar,
            "dp_limit":    dp_limit,
            "flow":        fs.flow_l_min,
            "temperature": fs.temperature_c,
            "remaining":   pred_status["remaining_display"],
            "status":      fs.status,
        }
        if _display_ctrl:
            _display_ctrl.update_status(_status_display_data)
        elif _display:
            _display.show_status(_status_display_data)

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


def _do_confirm_filter_change():
    """Führt die Filterwechsel-Bestätigung durch (REST-API und Display-Controller)."""
    with _state_lock:
        heta_code = _state["heta_code"]
        cycle_was_active = _state["cycle_active"]

    if cycle_was_active and learning.active_cycle:
        with _state_lock:
            current_r = _state["r_eff"]
            current_dp = _state["dp_bar"]
        learning.end_cycle(confirmed=True,
                           end_r_eff=current_r,
                           end_dp=current_dp)

    predictor.reset()
    reset_simulation()

    # Startwert aus dem validierten Lernprofil setzen, damit die Reststandzeit
    # nach dem Filterwechsel sofort einen sinnvollen Wert zeigt.
    if heta_code:
        profile = learning.get_profile(heta_code)
        if (profile and profile.get("profile_valid")
                and profile.get("reference_loading_rate", 0) > 0):
            dp_start = settings.get("dp_clean_bar", 0.2)
            dp_lim   = settings.get("dp_limit_bar", 2.5)
            seed_secs = (dp_lim - dp_start) / profile["reference_loading_rate"]
            predictor.seed(seed_secs)

    with _state_lock:
        _state["awaiting_confirmation"] = False
        _state["cycle_active"] = False
        _state["cycle_start_time"] = None
        _state["anomaly_active"] = False
        _state["anomaly_percent"] = 0.0

    db.insert_service_event("FILTERWECHSEL_BESTAETIGT", heta_code,
                            json.dumps({"timestamp": time.time()}))
    logger.info("Filterwechsel bestätigt. Neuer Zyklus beginnt.")


@app.route("/api/diagnostics", methods=["GET"])
def api_diagnostics():
    """Selbstcheck aller Hardware-Komponenten. Öffentlich (kein Auth erforderlich)."""
    import platform

    checks = []

    # ── System ──────────────────────────────────────────────────────────────
    checks.append({
        "id": "system",
        "label": "System",
        "status": "ok",
        "detail": f"Python {sys.version.split()[0]}  ·  {platform.machine()}  ·  {platform.system()} {platform.release()}",
        "hints": [],
    })

    # ── Git-Version ──────────────────────────────────────────────────────────
    try:
        gres = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=5, cwd=_BASE_DIR,
        )
        git_info = gres.stdout.strip() if gres.returncode == 0 else "unbekannt"
    except Exception:
        git_info = "git nicht verfügbar"
    checks.append({
        "id": "git",
        "label": "Software-Version (Git)",
        "status": "ok",
        "detail": git_info,
        "hints": [],
    })

    # ── SPI-Bus ──────────────────────────────────────────────────────────────
    spi_port   = settings.get("display_spi_port", 0)
    spi_device = settings.get("display_spi_device", 0)
    spi_dev    = f"/dev/spidev{spi_port}.{spi_device}"
    spi_exists = os.path.exists(spi_dev)
    checks.append({
        "id": "spi",
        "label": f"SPI-Bus ({spi_dev})",
        "status": "ok" if spi_exists else "error",
        "detail": f"{spi_dev} {'gefunden' if spi_exists else 'nicht gefunden'}",
        "hints": [] if spi_exists else [
            "SPI aktivieren: sudo raspi-config → Interface Options → SPI",
            "Danach Neustart erforderlich: sudo reboot",
            f"Prüfen mit: ls /dev/spidev*",
        ],
    })

    # ── I2C-Bus ──────────────────────────────────────────────────────────────
    i2c_dev    = "/dev/i2c-1"
    i2c_exists = os.path.exists(i2c_dev)
    checks.append({
        "id": "i2c_bus",
        "label": f"I2C-Bus ({i2c_dev})",
        "status": "ok" if i2c_exists else "error",
        "detail": f"{i2c_dev} {'gefunden' if i2c_exists else 'nicht gefunden'}",
        "hints": [] if i2c_exists else [
            "I2C aktivieren: sudo raspi-config → Interface Options → I2C",
            "Danach Neustart erforderlich: sudo reboot",
            "Prüfen mit: ls /dev/i2c*",
        ],
    })

    # ── I2C-Scan (Encoder-Adresse 0x49) ──────────────────────────────────────
    enc_addr     = settings.get("encoder_i2c_address", 73)
    enc_addr_hex = f"0x{enc_addr:02x}"
    if i2c_exists:
        try:
            ires = subprocess.run(
                ["i2cdetect", "-y", "1"],
                capture_output=True, text=True, timeout=5,
            )
            found_addrs = _parse_i2cdetect(ires.stdout)
            enc_found   = enc_addr in found_addrs
            addr_list   = ", ".join(f"0x{a:02x}" for a in sorted(found_addrs)) or "–"
            checks.append({
                "id": "i2c_scan",
                "label": f"I2C-Scan (Encoder erwartet bei {enc_addr_hex})",
                "status": "ok" if enc_found else "error",
                "detail": (f"Encoder bei {enc_addr_hex} erkannt  ·  Alle Geräte: {addr_list}"
                           if enc_found else
                           f"Encoder NICHT gefunden  ·  Gefundene Adressen: {addr_list}"),
                "hints": [] if enc_found else [
                    f"Kabel prüfen: SDA→Pin 3 (GPIO2), SCL→Pin 5 (GPIO3), VCC→3,3V, GND→Pin 6",
                    f"I2C-Adresse in settings.json: encoder_i2c_address={enc_addr} (={enc_addr_hex})",
                    "Direkttest: sudo i2cdetect -y 1",
                ],
            })
        except FileNotFoundError:
            checks.append({
                "id": "i2c_scan",
                "label": f"I2C-Scan (Encoder {enc_addr_hex})",
                "status": "warning",
                "detail": "i2cdetect nicht installiert",
                "hints": ["sudo apt install i2c-tools"],
            })
        except Exception as exc:
            checks.append({
                "id": "i2c_scan",
                "label": f"I2C-Scan (Encoder {enc_addr_hex})",
                "status": "error",
                "detail": f"Scan fehlgeschlagen: {exc}",
                "hints": [],
            })
    else:
        checks.append({
            "id": "i2c_scan",
            "label": f"I2C-Scan (Encoder {enc_addr_hex})",
            "status": "error",
            "detail": "I2C-Bus nicht verfügbar – Scan übersprungen",
            "hints": [],
        })

    # ── OLED-Display ─────────────────────────────────────────────────────────
    if not settings.get("display_enabled", True):
        checks.append({
            "id": "display",
            "label": "OLED-Display (SSD1309)",
            "status": "info",
            "detail": "Display deaktiviert (display_enabled=false in settings.json)",
            "hints": [],
        })
    elif _display is None:
        dc  = settings.get("display_gpio_dc", 25)
        rst = settings.get("display_gpio_rst", 27)
        checks.append({
            "id": "display",
            "label": "OLED-Display (SSD1309)",
            "status": "error",
            "detail": "Display konnte beim Start nicht initialisiert werden",
            "hints": [
                f"SPI-Verbindung: DC→GPIO{dc} (Pin 22), RST→GPIO{rst} (Pin 13), DIN→GPIO10, CLK→GPIO11, CS→GPIO8",
                "SPI-Bus aktiv? (ls /dev/spidev*)",
                "Bibliothek installiert? (pip show luma.oled)",
                "Logs: journalctl -u heta-monitor | grep -i display",
            ],
        })
    else:
        try:
            _display.show_network(_get_local_ip(), settings.get("webserver_port", 8080), "DIAGNOSE")
            checks.append({
                "id": "display",
                "label": "OLED-Display (SSD1309)",
                "status": "ok",
                "detail": "Display antwortet – Testbild 'DIAGNOSE' gerendert (Bildschirm 5 aktiv)",
                "hints": [],
            })
        except Exception as exc:
            checks.append({
                "id": "display",
                "label": "OLED-Display (SSD1309)",
                "status": "error",
                "detail": f"Render-Fehler: {exc}",
                "hints": ["Verkabelung prüfen", "sudo pip install --upgrade luma.oled"],
            })

    # ── ANO-Encoder ──────────────────────────────────────────────────────────
    if not settings.get("navigation_enabled", True):
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (Adafruit Seesaw I2C)",
            "status": "info",
            "detail": "Encoder deaktiviert (navigation_enabled=false in settings.json)",
            "hints": [],
        })
    elif _navigation is None:
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (Adafruit Seesaw I2C)",
            "status": "error",
            "detail": "Encoder konnte beim Start nicht initialisiert werden",
            "hints": [
                f"I2C-Adresse {enc_addr_hex} mit i2cdetect prüfen",
                "Kabel: SDA→Pin 3, SCL→Pin 5, VCC→3,3V, GND→Pin 6",
                "Bibliothek: pip show adafruit-circuitpython-seesaw adafruit-blinka",
            ],
        })
    elif _navigation.is_simulated:
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (Adafruit Seesaw I2C)",
            "status": "warning",
            "detail": "Encoder läuft im Simulationsmodus – keine Hardware erkannt",
            "hints": [
                "Encoder anschließen (SDA/SCL/VCC/GND)",
                f"I2C-Adresse {enc_addr_hex} mit i2cdetect -y 1 prüfen",
            ],
        })
    else:
        try:
            pos = _navigation._seesaw.encoder_position()
            checks.append({
                "id": "encoder",
                "label": "ANO-Encoder (Adafruit Seesaw I2C)",
                "status": "ok",
                "detail": f"Encoder antwortet – aktuelle Position: {pos}",
                "hints": [],
            })
        except Exception as exc:
            checks.append({
                "id": "encoder",
                "label": "ANO-Encoder (Adafruit Seesaw I2C)",
                "status": "error",
                "detail": f"Lesefehler: {exc}",
                "hints": ["I2C-Verbindung und Kabel prüfen", "Encoder neu anschließen"],
            })

    # ── Sensoren / AnoPi Shield ───────────────────────────────────────────────
    sim_mode = settings.get("simulation_mode", True)
    if sim_mode:
        checks.append({
            "id": "sensors",
            "label": "Sensoren (4–20 mA / AnoPi Shield)",
            "status": "info",
            "detail": "Simulationsmodus aktiv – echte Sensor-Hardware nicht geprüft",
            "hints": ["Für Echtbetrieb: simulation_mode=false in den Einstellungen"],
        })
    elif not spi_exists:
        checks.append({
            "id": "sensors",
            "label": "Sensoren (4–20 mA / AnoPi Shield)",
            "status": "error",
            "detail": f"SPI-Bus {spi_dev} nicht verfügbar – AnoPi Shield nicht erreichbar",
            "hints": ["SPI aktivieren und neu starten"],
        })
    else:
        try:
            import spidev  # type: ignore
            _spi = spidev.SpiDev()
            _spi.open(0, 0)
            _spi.max_speed_hz = 1350000
            raw = _spi.xfer2([1, (8 + 0) << 4, 0])
            _spi.close()
            adc_raw = ((raw[1] & 3) << 8) + raw[2]
            checks.append({
                "id": "sensors",
                "label": "Sensoren (4–20 mA / AnoPi Shield)",
                "status": "ok",
                "detail": f"SPI-Testlesung erfolgreich (ADC Kanal 0 Rohwert: {adc_raw} / 4095)",
                "hints": [],
            })
        except ImportError:
            checks.append({
                "id": "sensors",
                "label": "Sensoren (4–20 mA / AnoPi Shield)",
                "status": "error",
                "detail": "spidev nicht installiert",
                "hints": ["pip install spidev"],
            })
        except Exception as exc:
            checks.append({
                "id": "sensors",
                "label": "Sensoren (4–20 mA / AnoPi Shield)",
                "status": "error",
                "detail": f"SPI-Lesefehler: {exc}",
                "hints": [
                    "AnoPi Shield korrekt aufgesteckt?",
                    "SPI-Gerätekonflikte prüfen (Display und Shield auf unterschiedlichen CE?)",
                ],
            })

    # ── Datenbank ─────────────────────────────────────────────────────────────
    try:
        with db._conn() as _dbcon:
            row_count = _dbcon.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
        checks.append({
            "id": "database",
            "label": "Datenbank (SQLite)",
            "status": "ok",
            "detail": f"{row_count} Messwerte gespeichert  ·  Pfad: {db.db_path}",
            "hints": [],
        })
    except Exception as exc:
        checks.append({
            "id": "database",
            "label": "Datenbank (SQLite)",
            "status": "error",
            "detail": f"Datenbankfehler: {exc}",
            "hints": ["data/-Verzeichnis vorhanden?", "Schreibrechte prüfen"],
        })

    # ── Gesamtstatus ──────────────────────────────────────────────────────────
    statuses = [c["status"] for c in checks]
    if "error" in statuses:
        overall = "error"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "ok"

    return jsonify({
        "overall": overall,
        "timestamp": time.time(),
        "checks": checks,
    })


@app.route("/api/filter/confirm-change", methods=["POST"])
def api_confirm_filter_change():
    """Bestätigt den Filterwechsel und startet einen neuen Zyklus."""
    _do_confirm_filter_change()
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


@app.route("/api/navigation/event", methods=["POST"])
def api_navigation_event():
    """Simuliert ein Navigationsereignis (für Tests ohne Hardware)."""
    data = request.get_json(force=True, silent=True) or {}
    event = data.get("event", "")
    if not event:
        return jsonify({"success": False, "message": "Kein Ereignis angegeben."}), 400
    if _navigation:
        _navigation.simulate_event(event)
        return jsonify({"success": True, "event": event})
    return jsonify({"success": False, "message": "Navigation nicht verfügbar."}), 503


@app.route("/api/display/screen", methods=["GET"])
def api_display_screen():
    """Gibt den aktuell angezeigten Bildschirm zurück."""
    if _display_ctrl:
        screen = _display_ctrl._screens[_display_ctrl._screen_idx]
        return jsonify({"screen": screen, "screen_index": _display_ctrl._screen_idx,
                        "confirm_armed": _display_ctrl._confirm_armed})
    if _display:
        return jsonify({"screen": _display.current_screen, "screen_index": None,
                        "confirm_armed": False})
    return jsonify({"screen": None, "screen_index": None, "confirm_armed": False})


# ---------------------------------------------------------------------------
# Software-Update via Git
# ---------------------------------------------------------------------------

@app.route("/api/update/pull", methods=["POST"])
def api_update_pull():
    """
    Führt 'git pull --ff-only' im Projektverzeichnis aus und startet den
    Dienst danach neu (nur wenn es tatsächlich Änderungen gab).
    Erfordert einen gültigen Auth-Token.
    """
    ok, err = _require_auth()
    if not ok:
        return err

    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True,
            text=True,
            cwd=_BASE_DIR,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "changed": False, "restarting": False,
                        "output": "Timeout – git pull hat zu lange gebraucht."})
    except FileNotFoundError:
        return jsonify({"success": False, "changed": False, "restarting": False,
                        "output": "git nicht gefunden. Ist Git installiert?"})

    output  = (result.stdout + result.stderr).strip()
    success = result.returncode == 0
    changed = success and "Already up to date." not in result.stdout

    logger.info("Git pull: rc=%d changed=%s output=%r", result.returncode, changed, output)

    if changed:
        def _restart():
            time.sleep(1.5)
            logger.info("Neustart nach Git-Update.")
            try:
                r = subprocess.run(
                    ["sudo", "systemctl", "restart", "heta-monitor"],
                    timeout=10, capture_output=True,
                )
                if r.returncode == 0:
                    return
            except Exception:
                pass
            # Fallback: Prozess sauber beenden, systemd (Restart=always) startet neu.
            # os.execv() wird NICHT verwendet, da es den offenen Flask-Socket
            # an den neuen Prozess vererbt, der dann den Port nicht binden kann.
            logger.info("Fallback: Prozess wird beendet, systemd übernimmt den Neustart.")
            os._exit(0)

        threading.Thread(target=_restart, daemon=True).start()

    return jsonify({
        "success":   success,
        "changed":   changed,
        "restarting": changed,
        "output":    output,
    })


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
