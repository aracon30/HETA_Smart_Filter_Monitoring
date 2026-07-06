"""
HETA Smart Filter Monitoring – Haupt-Backend-Applikation.

Startet den Flask-Webserver, den Messzyklus-Thread und koordiniert
alle Module (Sensoren, Berechnungen, Datenbank, Lernmodul, Prognose, Display).
"""

import json
import logging
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque

# Projektverzeichnis in sys.path eintragen damit relative Imports funktionieren
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE_DIR, "backend"))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from calculations import (
    FilterState,
)
from config import get_abs_path, hash_password, save_settings, settings, verify_password
from database import Database
from diagnostics import run_diagnostics as _run_diagnostics
from heta_code import get_demo_info, verify_activation
from learning import LearningManager
from measurement import MeasurementLoop
from prediction import PredictionEngine
from sensors import (
    check_hardware_sensors,
    clear_simulation_rates,
    full_reset_simulation,
    get_simulation_estimated_cycle_secs,
    get_simulation_rates_active,
    pause_simulation,
    probe_hardware,
    read_sensors,
    reset_simulation,
    set_simulation_scenario_params,
    simulate_reference_cycle,
    update_simulation_params,
)
from service_logic import (
    build_service_payload,
    generate_service_recommendation,
    generate_service_report,
    generate_spare_parts_order,
)

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
    "dp_limit_bar",
    "flow_max_l_min",
    "pressure_range_bar",
    "temperature_min_c",
    "temperature_max_c",
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
# Hardware-Erkennung beim Programmstart
# ---------------------------------------------------------------------------
# Einmalige Probe beim Import: Hat das AnoPi Shield (SPI) eine Verbindung?
# Ergebnis wird im _state gespeichert und an die Weboberfläche übertragen.
_hw_available: bool = probe_hardware()

# ---------------------------------------------------------------------------
# Systemzustand
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()

# Rollierender Puffer für dp-Anstiegsschätzung: (timestamp, dp_bar)
_dp_rate_buffer: deque = deque(maxlen=60)

# Veränderliche Referenzen auf MQTT- und Modbus-Dienste (für MeasurementLoop)
_loop_services: dict = {"mqtt": None, "modbus": None}
# MeasurementLoop-Instanz (wird in _start_measurement_thread erstellt)
_loop: MeasurementLoop | None = None

_state = {
    # Betriebsmodus
    "simulation_mode": settings.get("simulation_mode", True),
    "sensor_mode": "simulation",
    "sensor_hw_available": _hw_available,  # Hardware beim Start erkannt?
    "running": False,
    # Messwerte
    "p1_bar": 0.0,
    "p2_bar": 0.0,
    "dp_bar": 0.0,
    "flow_l_min": 0.0,
    "temperature_c": 0.0,
    "r_eff": 0.0,
    "r_rel_factor": None,  # r_eff / r_eff_reference_start, None während Lernphase
    "filter_health_percent": 100.0,
    "filter_status": "OK",
    "sensor_error": False,
    # HETA-Code
    "heta_code": "",
    "heta_activated": False,
    "heta_number": "",
    # Sensorfehler (Hardwaremodus – Messung gestoppt)
    "sensor_fault": False,
    "sensor_fault_channels": [],
    "sensor_fault_message": "",
    # Startup-Sensorprüfung: True im Hardware-Modus bis alle Kanäle bestätigt sind
    "startup_sensor_check": not settings.get("simulation_mode", True),
    # Simulations-Szenario-Parameter
    "sim_estimated_cycle_secs": 300.0,
    "sim_rates_active": False,
    "sim_scenario": "normal",
    "sim_dirt_rate_pct": 100.0,
    "sim_p1_trend_pct": 0.0,
    "sim_p2_trend_pct": 0.0,
    "sim_flow_drop_pct": 75.0,
    "sim_temp_trend": 0.0,
    # Modusneutrale Prozessanalyse (Sensor- UND Simulationsmodus)
    "analysis_active": False,  # True wenn Profil valide + läuft
    "analysis_ready": False,  # True wenn Kurvenvergleich verfügbar
    "analysis_dp_rate_ref": 0.0,
    "analysis_dp_rate_current": 0.0,
    "analysis_dp_deviation_pct": 0.0,  # Abweichung in %
    "analysis_p1_rate_current": 0.0,  # Änderungsrate p1 (bar/s), kein Referenzvergleich
    "analysis_p2_rate_current": 0.0,  # Änderungsrate p2 (bar/s), kein Referenzvergleich
    "analysis_flow_ref": 0.0,  # Referenz-Durchfluss (l/min)
    "analysis_flow_deviation_pct": 0.0,  # Abweichung in %
    "analysis_temp_ref": 0.0,  # Referenz-Temperatur (°C)
    "analysis_temp_deviation": 0.0,  # Abweichung in °C
    "analysis_cycle_progress_pct": 0.0,
    "analysis_dp_ref": 0.0,
    "analysis_reff_ref": 0.0,
    "analysis_reff_cur": 0.0,
    "analysis_reff_deviation_pct": 0.0,
    # Filterwechsel
    "awaiting_confirmation": False,
    "cycle_active": False,
    "cycle_start_time": None,
    "cycle_dp_reached_time": None,  # Zeitpunkt an dem dp-Limit erreicht wurde
    # Zyklusstart-Logik (Durchflusserkennung)
    "waiting_for_flow": True,  # Wartet auf stabilen Durchfluss vor Zyklusstart
    "cycle_paused": False,  # Zyklus durch Durchflussausfall pausiert
    "cycle_active_seconds": 0.0,  # Kumulierte Betriebszeit (ohne Pausen)
    "cycle_pause_start_time": None,  # Zeitpunkt des letzten Pausenbeginns
    "flow_check_q": 0.0,  # Aktueller Q-Wert für Overlay-Anzeige
    "flow_check_dp": 0.0,  # Aktueller dp-Wert für Overlay-Anzeige
    "flow_threshold": 0.0,  # Effektiver Schwellwert (für Overlay)
    "flow_stable_pct": 0,  # Fortschritt Stabilitätsfenster 0–100 %
    "flow_check_sensor_error": False,  # True wenn Sensoren beim Durchfluss-Check fehlen
    # Prognose
    "remaining_display": "Unbekannt",
    "remaining_seconds": None,
    "prediction_mode": "BASIS",
    # Lernmodul
    "learned_cycles": 0,
    "required_cycles": settings.get("required_cycles_for_profile", 3),
    "profile_status": "LERNEND",
    "reference_dp_clean": 0.0,
    "anomaly_active": False,
    "anomaly_percent": 0.0,
    # Aktive Abweichungs-Perioden je Kanal (für ts_end-Tracking)
    "_dev_active": {"dp": False, "flow": False, "reff": False},
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
    tolerance_reff_pct=settings.get("tolerance_reff_pct", settings.get("clean_resistance_tolerance", 0.25)),
)
predictor = PredictionEngine(
    dp_limit=settings.get("dp_limit_bar", 2.5),
    dp_clean=settings.get("dp_clean_bar", 0.2),
    min_slope=settings.get("min_slope", 0.001),
)

# Simulator mit gespeicherten Einstellungen synchronisieren.
# reset_clogging=False: App-Start soll laufende Simulation nicht zurückwerfen.
update_simulation_params(
    dp_clean=settings.get("dp_clean_bar", 0.2),
    dp_limit=settings.get("dp_limit_bar", 2.5),
    flow_max=settings.get("flow_max_l_min", 150.0),
    p1_base=settings.get("sim_p1_base_bar", 4.0),
    q_base=settings.get("sim_q_base_l_min", 145.0),
    t_base=settings.get("sim_t_base_c", 25.0),
    reset_clogging=False,
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

# Modbus TCP optional
_modbus: "ModbusTCPServer | None" = None  # type: ignore[name-defined]
if settings.get("modbus_enabled", False):
    from modbus_server import ModbusTCPServer

    _modbus = ModbusTCPServer(
        host=settings.get("modbus_host", "0.0.0.0"),
        port=settings.get("modbus_port", 502),
    )
    _modbus.start()

_loop_services["mqtt"] = _mqtt
_loop_services["modbus"] = _modbus

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
            gpio_rst=settings.get("display_gpio_rst", 24),
            i2c_address=settings.get("display_i2c_address", 60),
        )
        _display.show_boot_animation()
    except Exception as e:
        logger.warning("Display-Init übersprungen: %s", e)


def _handle_sigterm(signum, frame):
    """
    Python fängt SIGTERM standardmäßig nicht ab (SIG_DFL beendet den Prozess
    sofort, ohne atexit-Hooks) – systemctl stop/Shutdown senden aber SIGTERM.
    Ohne diesen Handler bleibt das OLED auf dem letzten Bild stehen, obwohl
    die 3.3V-Schiene nach dem Shutdown weiter versorgt wird.
    """
    if _display is not None:
        try:
            _display.clear()
        except Exception:
            pass
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_sigterm)

# Navigation optional
_navigation = None
if settings.get("navigation_enabled", True):
    try:
        from navigation import NavigationController

        _navigation = NavigationController(
            pin_enca=settings.get("encoder_pin_enca", 16),
            pin_encb=settings.get("encoder_pin_encb", 20),
            pin_sw1=settings.get("encoder_pin_sw1", 21),
            pin_sw2=settings.get("encoder_pin_sw2", 12),
            pin_sw3=settings.get("encoder_pin_sw3", 13),
            pin_sw4=settings.get("encoder_pin_sw4", 19),
            pin_sw5=settings.get("encoder_pin_sw5", 26),
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
        self._screens = SCREENS  # list of screen name constants
        self._screen_idx = 0  # 0 = Status
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

        # Sensor-Fehler-Modus: normale Navigation sperren, nur OK = Sensor-Check
        with _state_lock:
            sensor_fault_waiting = _state.get("flow_check_sensor_error", False)
        if sensor_fault_waiting:
            if event == NavigationEvent.PRESS:
                self._retry_sensor_check()
            return  # alle anderen Tasten ignorieren

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

    def _retry_sensor_check(self):
        """Sofortige Sensor-Prüfung per OK-Taste im Sensor-Fault-Zustand."""
        import threading

        from sensors import check_hardware_sensors

        def _check():
            self._display.show_sensor_fault([], checking=True)
            result = check_hardware_sensors()
            if result["all_ok"]:
                with _state_lock:
                    _state["flow_check_sensor_error"] = False
                    _state["sensor_fault"] = False
                    _state["sensor_fault_channels"] = []
                    _state["sensor_fault_message"] = ""
                    _state["filter_status"] = "OK"
                logger.info("Sensor-Prüfung erfolgreich – alle Sensoren verfügbar.")
            else:
                with _state_lock:
                    _state["sensor_fault_channels"] = result["failed_channels"]
                    _state["sensor_fault_message"] = (
                        f"Sensorfehler: {', '.join(result['failed_names'])} – Sensoren anschließen."
                    )
                self._display.show_sensor_fault(
                    result["failed_names"],
                    channel_ma=result.get("channel_ma"),
                    failed_channels=result["failed_channels"],
                )
                logger.warning("Sensor-Prüfung: Kanäle %s fehlen.", result["failed_channels"])

        threading.Thread(target=_check, daemon=True, name="sensor-check").start()

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
                dp,
                settings.get("dp_limit_bar", 2.5),
                armed=True,
                awaiting=True,
            )
        else:
            self._confirm_armed = False
            if _loop:
                _loop.confirm_filter_change()
            # Zurück zum Status-Bildschirm
            self._screen_idx = 0
            self._display.show_status(self._last_status_data)

    # ------------------------------------------------------------------
    # Display-Refresh
    # ------------------------------------------------------------------

    def _refresh_display(self):
        from display import (
            SCREEN_FILTER_CHANGE,
            SCREEN_HETA,
            SCREEN_HISTORY,
            SCREEN_NETWORK,
            SCREEN_SERVICE,
            SCREEN_STATUS,
        )

        screen = self._screens[self._screen_idx]

        if screen == SCREEN_STATUS:
            self._display.show_status(self._last_status_data)

        elif screen == SCREEN_HETA:
            with _state_lock:
                code = _state["heta_code"]
                activated = _state["heta_activated"]
                learned = _state["learned_cycles"]
                pred_mode = _state["prediction_mode"]
            req = settings.get("required_cycles_for_profile", 3)
            self._display.show_heta_code(
                code,
                activated,
                learned_cycles=learned,
                required_cycles=req,
                prediction_mode=pred_mode,
            )

        elif screen == SCREEN_FILTER_CHANGE:
            with _state_lock:
                dp = _state["dp_bar"]
                awaiting = _state["awaiting_confirmation"]
            self._display.show_filter_change(
                dp,
                settings.get("dp_limit_bar", 2.5),
                armed=self._confirm_armed,
                awaiting=awaiting,
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


def _seed_predictor_from_profile(heta_code: str):
    """Setzt Reststandzeit-Startwert aus der Referenzdauer der Lernzyklen."""
    if not heta_code:
        return
    profile = learning.get_profile(heta_code)
    if profile and profile.get("profile_valid"):
        ref_dur = profile.get("reference_duration_seconds", 0.0)
        if ref_dur > 0:
            predictor.seed(ref_dur)


def _get_flow_thresholds() -> tuple:
    """
    Gibt (flow_threshold, stability_secs, pause_tolerance) zurück.
    Manuelle Einstellungswerte haben Vorrang vor auto-berechneten Werten.
    """
    flow_max = settings.get("flow_max_l_min", 150.0)
    # Durchfluss-Startschwellwert
    manual_thr = settings.get("flow_start_threshold_l_min")
    auto_thr = settings.get("flow_start_threshold_auto") or 0.0
    threshold = float(manual_thr) if manual_thr else (auto_thr if auto_thr > 0 else flow_max * 0.10)
    threshold = max(threshold, 0.1)

    # Stabilitätsfenster
    manual_stab = settings.get("flow_stability_seconds")
    auto_stab = settings.get("flow_stability_seconds_auto") or 10
    stability = float(manual_stab) if manual_stab else float(auto_stab)
    stability = max(stability, 3.0)

    # Pause-Toleranz (Batch: 60 s, Kontinuierlich: 30 s)
    manual_pause = settings.get("flow_pause_tolerance_seconds")
    auto_pause = settings.get("flow_pause_tolerance_auto") or 0
    if manual_pause:
        pause_tol = float(manual_pause)
    elif auto_pause > 0:
        pause_tol = float(auto_pause)
    else:
        pause_tol = 60.0 if settings.get("operation_mode") == "batch" else 30.0
    pause_tol = max(pause_tol, 5.0)

    return threshold, stability, pause_tol


def _update_auto_thresholds(active_cycle_samples: list):
    """
    Berechnet auto-Schwellwerte aus den Samples des abgeschlossenen Zyklus
    und speichert sie in settings (werden in settings.local.json persistiert).
    Läuft nach jedem bestätigten Filterwechsel.
    """
    if len(active_cycle_samples) < 10:
        return

    dp_clean = settings.get("dp_clean_bar", 0.2)
    # Minimaler Durchfluss in Phasen mit dp > dp_clean (Filter beladen = Anlage läuft)
    active_flows = [
        s for s in active_cycle_samples if s.get("dp_bar", 0) > dp_clean * 0.5 and s.get("flow_l_min", 0) > 0.1
    ]
    if len(active_flows) < 5:
        return

    min_flow = min(s["flow_l_min"] for s in active_flows)
    new_threshold = round(max(min_flow * 0.4, 0.5), 1)

    changed = False
    if abs(new_threshold - (settings.get("flow_start_threshold_auto") or 0)) > 0.5:
        settings["flow_start_threshold_auto"] = new_threshold
        changed = True

    if changed:
        save_settings(settings)
        logger.info("Auto-Durchflussschwellwert aktualisiert: %.1f l/min", new_threshold)


_loop_thread: threading.Thread = None


def _start_measurement_thread():
    global _loop_thread, _loop
    if _loop_thread and _loop_thread.is_alive():
        # Alter Thread lebt noch; running wurde vom Aufrufer bereits auf True gesetzt,
        # sodass der Thread nach seinem sleep() einfach weiterläuft — kein neuer Thread.
        return
    _state["running"] = True
    _loop = MeasurementLoop(
        state=_state,
        state_lock=_state_lock,
        settings=settings,
        db=db,
        learning=learning,
        predictor=predictor,
        dp_rate_buffer=_dp_rate_buffer,
        sensor_manager=None,
        sim_manager=None,
        display=_display,
        display_ctrl=_display_ctrl,
        services=_loop_services,
        fn_read_sensors=read_sensors,
        fn_update_auto_thresholds=_update_auto_thresholds,
        fn_seed_predictor=_seed_predictor_from_profile,
        fn_get_flow_thresholds=_get_flow_thresholds,
        fn_get_sim_rates=get_simulation_rates_active,
        fn_get_sim_cycle_secs=get_simulation_estimated_cycle_secs,
        fn_generate_service_rec=generate_service_recommendation,
        fn_reset_simulation=reset_simulation,
        fn_get_status_display_data=None,
    )
    _loop_thread = threading.Thread(target=_loop.run, daemon=True, name="measurement")
    _loop_thread.start()


# ---------------------------------------------------------------------------
# REST API Endpunkte
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/help")
def help_page():
    """Rendert das Benutzerhandbuch (Markdown → HTML)."""
    try:
        import markdown as _md
    except ImportError:
        return (
            "<html><body><h1>Benutzerhandbuch</h1>"
            "<p>Bitte <code>pip install markdown</code> ausführen, "
            "um das Handbuch anzuzeigen.</p></body></html>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    doc_path = os.path.join(_BASE_DIR, "docs", "benutzerhandbuch.md")
    try:
        with open(doc_path, encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        raw = "# Benutzerhandbuch\n\nDie Datei `docs/benutzerhandbuch.md` wurde nicht gefunden."

    content_html = _md.markdown(
        raw,
        extensions=["tables", "toc", "fenced_code"],
        extension_configs={"toc": {"title": "Inhalt"}},
    )

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bedienungsanleitung – HETA Smart Filter Monitoring</title>
  <style>
    :root {{
      --blue: #0d6efd;
      --dark: #1a1f2e;
      --surface: #242938;
      --border: #2e3550;
      --text: #e8eaf0;
      --muted: #8892b0;
      --code-bg: #1a1f2e;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--dark);
      color: var(--text);
      line-height: 1.7;
    }}
    .page-header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 1rem 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    .page-header h1 {{
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--blue);
    }}
    .back-btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      background: var(--blue);
      color: #fff;
      border: none;
      border-radius: 6px;
      padding: 0.45rem 0.9rem;
      font-size: 0.85rem;
      cursor: pointer;
      text-decoration: none;
      white-space: nowrap;
    }}
    .back-btn:hover {{ background: #0b5ed7; }}
    .toc-box {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1rem 1.5rem;
      margin-bottom: 2rem;
    }}
    .toc-box .toctitle {{ font-weight: 700; margin-bottom: 0.5rem; color: var(--blue); }}
    .toc-box ul {{ padding-left: 1.2rem; }}
    .toc-box a {{ color: var(--muted); text-decoration: none; }}
    .toc-box a:hover {{ color: var(--text); }}
    main {{
      max-width: 860px;
      margin: 0 auto;
      padding: 2rem 1.5rem 4rem;
    }}
    h1, h2, h3, h4 {{ color: var(--text); margin-top: 2rem; margin-bottom: 0.5rem; }}
    h1 {{ font-size: 1.8rem; border-bottom: 2px solid var(--blue); padding-bottom: 0.4rem; }}
    h2 {{ font-size: 1.3rem; border-bottom: 1px solid var(--border); padding-bottom: 0.3rem; }}
    h3 {{ font-size: 1.1rem; color: var(--blue); }}
    p {{ margin-bottom: 0.9rem; }}
    a {{ color: var(--blue); }}
    ul, ol {{ padding-left: 1.5rem; margin-bottom: 0.9rem; }}
    li {{ margin-bottom: 0.25rem; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1rem 0 1.4rem;
      font-size: 0.9rem;
    }}
    th {{
      background: var(--surface);
      border: 1px solid var(--border);
      padding: 0.55rem 0.75rem;
      text-align: left;
      color: var(--blue);
    }}
    td {{
      border: 1px solid var(--border);
      padding: 0.5rem 0.75rem;
    }}
    tr:nth-child(even) td {{ background: rgba(255,255,255,0.02); }}
    code {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 0.15em 0.4em;
      font-size: 0.88em;
      font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
      color: #a8d8a8;
    }}
    pre {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1rem;
      overflow-x: auto;
      margin: 0.8rem 0 1.2rem;
    }}
    pre code {{
      background: none;
      border: none;
      padding: 0;
      font-size: 0.87em;
    }}
    blockquote {{
      border-left: 3px solid var(--blue);
      margin: 0.8rem 0;
      padding: 0.5rem 1rem;
      background: rgba(13,110,253,0.07);
      border-radius: 0 6px 6px 0;
      color: var(--muted);
    }}
    hr {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 2rem 0;
    }}
  </style>
</head>
<body>
  <div class="page-header">
    <h1>Bedienungsanleitung – HETA Smart Filter Monitoring</h1>
    <a href="/" class="back-btn">&#8592; Zurück zum Dashboard</a>
  </div>
  <main>
    {content_html}
  </main>
</body>
</html>"""

    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


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
        db.insert_service_event("HETA_AKTIVIERT", result["heta_code"], json.dumps(result, ensure_ascii=False))
        logger.info("HETA-Code %s aktiviert.", result["heta_code"])
    return jsonify(result)


@app.route("/api/heta/deactivate", methods=["POST"])
def api_heta_deactivate():
    """Deaktiviert den aktiven HETA-Code (ohne Lernzyklen zu löschen)."""
    with _state_lock:
        heta_code = _state.get("heta_code", "")
        _state["heta_code"] = ""
        _state["heta_activated"] = False
        _state["heta_number"] = ""
    predictor.reset()
    _dp_rate_buffer.clear()
    if heta_code:
        db.insert_service_event("HETA_DEAKTIVIERT", heta_code, json.dumps({"timestamp": time.time()}))
        logger.info("HETA-Code %s deaktiviert.", heta_code)
    return jsonify({"success": True, "message": f"HETA-Code {heta_code} deaktiviert."})


@app.route("/api/heta/demo", methods=["GET"])
def api_heta_demo():
    """Demo: gibt Aktivierungscode für einen HETA-Code zurück (nur für Tests!)."""
    heta_code = request.args.get("heta_code", "")
    return jsonify(get_demo_info(heta_code))


@app.route("/api/heta/reset-cycles", methods=["POST"])
def api_heta_reset_cycles():
    """
    Setzt alle Lernzyklen und das Profil zurück – für den aktiven HETA-Code, oder
    ohne aktiven Code für das DEMO-Profil (Simulationsmodus ohne HETA-Code).
    Erfordert einen gültigen Auth-Token.
    """
    ok, err = _require_auth()
    if not ok:
        return err

    with _state_lock:
        heta_code = _state.get("heta_code", "") or "DEMO"

    # Aktiven Lernzyklus abbrechen (ohne Speichern)
    learning._active_cycle = None

    # DB bereinigen
    db.reset_cycles_for_heta(heta_code)

    # Prognose-Modell zurücksetzen
    if _loop:
        _loop.mstate.smoothed_health_pct = None
    predictor.reset()
    _dp_rate_buffer.clear()

    # Zustandsvariablen zurücksetzen
    with _state_lock:
        _state["cycle_active"] = False
        _state["cycle_start_time"] = None
        _state["cycle_dp_reached_time"] = None
        _state["awaiting_confirmation"] = False
        _state["anomaly_active"] = False
        _state["_dev_active"] = {"dp": False, "flow": False, "reff": False}
        _state["anomaly_percent"] = 0.0
        _state["analysis_active"] = False
        _state["analysis_ready"] = False

    db.insert_service_event("LERNZYKLEN_RESET", heta_code, json.dumps({"timestamp": time.time()}))
    logger.info("Lernzyklen für %s zurückgesetzt.", heta_code)

    return jsonify(
        {
            "success": True,
            "message": f"Lernzyklen für {heta_code} wurden zurückgesetzt. Das System startet die Lernphase neu.",
        }
    )


@app.route("/api/diagnostics", methods=["GET"])
def api_diagnostics():
    """Selbstcheck aller Komponenten basierend auf tatsächlichem Laufzeitzustand."""
    return jsonify(
        _run_diagnostics(
            state=_state,
            state_lock=_state_lock,
            settings=settings,
            db=db,
            base_dir=_BASE_DIR,
            get_local_ip=_get_local_ip,
            mqtt=_mqtt,
            modbus=_modbus,
            display=_display,
            navigation=_navigation,
        )
    )


@app.route("/api/filter/confirm-change", methods=["POST"])
def api_confirm_filter_change():
    """Bestätigt den Filterwechsel und startet einen neuen Zyklus."""
    if _loop:
        _loop.confirm_filter_change()
    return jsonify({"success": True, "message": "Filterwechsel bestätigt. Neuer Zyklus startet."})


@app.route("/api/sensor/recheck", methods=["POST"])
def api_sensor_recheck():
    """
    Bediener hat bestätigt, alle Sensoren angeschlossen zu haben.
    System prüft alle 4 Kanäle und startet die Messung neu wenn alles OK ist.
    """
    with _state_lock:
        sim_mode = _state["simulation_mode"]

    if sim_mode:
        return jsonify({"success": False, "message": "Sensorprüfung nur im Hardwaremodus verfügbar."})

    result = check_hardware_sensors()

    if result["all_ok"]:
        with _state_lock:
            thread_running = _state.get("running", False)
            _state["sensor_fault"] = False
            _state["sensor_fault_channels"] = []
            _state["sensor_fault_message"] = ""
            _state["sensor_error"] = False
            _state["flow_check_sensor_error"] = False
            _state["startup_sensor_check"] = False
        if thread_running:
            # Messzyklus läuft noch (waiting_for_flow) – kein Neustart nötig
            logger.info("Sensorprüfung erfolgreich – Messzyklus läuft weiter.")
            return jsonify({"success": True, "message": "Alle Sensoren erkannt. Durchflussprüfung läuft."})
        _start_measurement_thread()
        logger.info("Sensorprüfung erfolgreich – alle Kanäle lesbar, Messung neu gestartet.")
        return jsonify({"success": True, "message": "Alle Sensoren erkannt. Messung wird neu gestartet."})

    msg = f"Sensorfehler: {', '.join(result['failed_names'])} weiterhin nicht lesbar."
    with _state_lock:
        _state["sensor_fault_channels"] = result["failed_channels"]
        _state["sensor_fault_message"] = msg
    logger.error("Sensorprüfung fehlgeschlagen: Kanal(e) %s.", result["failed_channels"])
    return jsonify(
        {
            "success": False,
            "message": msg,
            "failed_channels": result["failed_channels"],
            "failed_names": result["failed_names"],
        }
    )


@app.route("/api/sensor/rawcheck", methods=["GET"])
def api_sensor_rawcheck():
    """
    Liest alle 4 Sensorkanäle direkt und gibt Raw-mA sowie skalierten Wert zurück.
    Für die Startprüfungs-Diagnoseansicht im Frontend (sekündliches Polling).
    """
    from sensors import (
        _check_status,
        _read_anopi_channel,
        _scale_flow,
        _scale_pressure,
        _scale_temperature,
    )

    pressure_range = settings.get("pressure_range_bar", 10.0)
    temp_min = settings.get("temperature_min_c", -50.0)
    temp_max = settings.get("temperature_max_c", 150.0)
    flow_max = settings.get("flow_max_l_min", 150.0)

    channels = []
    all_ok = True
    for ch in range(1, 5):
        ma = _read_anopi_channel(ch)
        if ma is None:
            channels.append({"channel": ch, "ma": None, "value": None, "unit": "–", "status": "FEHLER"})
            all_ok = False
            continue
        status = _check_status(ma)
        if status != "OK":
            all_ok = False
        if ch in (1, 2):
            val = round(_scale_pressure(ma, pressure_range), 3) if status == "OK" else None
            unit = "bar"
        elif ch == 3:
            val = round(_scale_temperature(ma, temp_min, temp_max), 1) if status == "OK" else None
            unit = "°C"
        else:
            val = round(_scale_flow(ma, flow_max), 1) if status == "OK" else None
            unit = "l/min"
        channels.append({"channel": ch, "ma": round(ma, 4), "value": val, "unit": unit, "status": status})

    return jsonify({"channels": channels, "all_ok": all_ok})


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    """Liest die Konfiguration (öffentlich, ohne sensible Felder)."""
    safe = {k: v for k, v in settings.items() if k not in ("settings_password_hash",)}
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
    learning_reset_needed = any(k in _LEARNING_SENSITIVE_KEYS and data.get(k) != settings.get(k) for k in data)

    # Passwortänderung separat behandeln
    new_password = data.pop("new_password", None)
    old_password = data.pop("old_password", None)
    if new_password:
        if not verify_password(old_password or "", settings.get("settings_password_hash", "")):
            return jsonify({"success": False, "message": "Altes Passwort falsch."}), 403
        settings["settings_password_hash"] = hash_password(new_password)

    # Nur bekannte Felder übernehmen, interne Felder schützen
    protected = {
        "settings_password_hash",
        "db_path",
        "log_path",
        "export_path",
        "webserver_host",
        "webserver_port",
        "onboarding_complete",
    }

    # Simulationsparameter vor der Übernahme merken um Clogging-Reset zu steuern
    _SIM_PARAMS = {
        "dp_clean_bar",
        "dp_limit_bar",
        "flow_max_l_min",
        "sim_p1_base_bar",
        "sim_q_base_l_min",
        "sim_t_base_c",
    }
    sim_params_changed = any(k in _SIM_PARAMS and data.get(k) != settings.get(k) for k in data)

    for k, v in data.items():
        if k in settings and k not in protected:
            settings[k] = v

    # Simulator aktualisieren; Clogging nur zurücksetzen wenn physikalisch
    # relevante Simulationsparameter geändert wurden.
    update_simulation_params(
        dp_clean=settings["dp_clean_bar"],
        dp_limit=settings["dp_limit_bar"],
        flow_max=settings["flow_max_l_min"],
        p1_base=settings.get("sim_p1_base_bar", 4.0),
        q_base=settings.get("sim_q_base_l_min", 145.0),
        t_base=settings.get("sim_t_base_c", 25.0),
        reset_clogging=sim_params_changed,
    )
    predictor.update_limits(settings["dp_limit_bar"], settings["dp_clean_bar"])
    learning.tolerance_reff_pct = settings.get("tolerance_reff_pct", 0.25)
    save_settings(settings)

    with _state_lock:
        prev_sim = _state["simulation_mode"]
        _state["simulation_mode"] = settings["simulation_mode"]
        mode_changed = prev_sim != settings["simulation_mode"]
        if mode_changed:
            # Zustand für Moduswechsel zurücksetzen
            _state["sensor_fault"] = False
            _state["sensor_fault_channels"] = []
            _state["sensor_fault_message"] = ""
            _state["sensor_error"] = False
            _state["cycle_active"] = False
            _state["cycle_start_time"] = None
            _state["cycle_dp_reached_time"] = None
            _state["awaiting_confirmation"] = False
            _state["waiting_for_flow"] = True
            _state["anomaly_active"] = False
            _state["anomaly_percent"] = 0.0
            _state["_dev_active"] = {"dp": False, "flow": False, "reff": False}
            # Wechsel Simulation → Hardware: Startprüfung aktivieren
            _state["startup_sensor_check"] = not settings["simulation_mode"]
            _state["running"] = True

    # Messzyklus neu starten wenn Modus gewechselt wurde
    if mode_changed:
        reset_simulation()
        predictor.reset()
        if _loop:
            _loop.mstate.smoothed_health_pct = None
        _start_measurement_thread()

    # MQTT neu starten wenn sich relevante Parameter geändert haben
    _mqtt_keys = {"mqtt_enabled", "mqtt_broker", "mqtt_port", "mqtt_client_id"}
    if _mqtt_keys & set(data.keys()):
        global _mqtt
        if _mqtt:
            try:
                _mqtt.disconnect()
            except Exception:
                pass
            _mqtt = None
        if settings.get("mqtt_enabled", False):
            from mqtt_client import MQTTClient

            _mqtt = MQTTClient(
                broker=settings.get("mqtt_broker", "localhost"),
                port=settings.get("mqtt_port", 1883),
                client_id=settings.get("mqtt_client_id", "heta_monitor"),
            )
            _mqtt.connect()

    # Modbus TCP neu starten wenn sich relevante Parameter geändert haben
    _modbus_keys = {"modbus_enabled", "modbus_host", "modbus_port"}
    if _modbus_keys & set(data.keys()):
        global _modbus
        if _modbus:
            try:
                _modbus.stop()
            except Exception:
                pass
            _modbus = None
        if settings.get("modbus_enabled", False):
            from modbus_server import ModbusTCPServer

            _modbus = ModbusTCPServer(
                host=settings.get("modbus_host", "0.0.0.0"),
                port=settings.get("modbus_port", 502),
            )
            _modbus.start()
        _loop_services["mqtt"] = _mqtt
        _loop_services["modbus"] = _modbus

    # Lerndaten zurücksetzen wenn nötig
    if learning_reset_needed:
        if _loop:
            _loop.mstate.smoothed_health_pct = None
        db.reset_all_learning_data()
        predictor.reset()
        reset_simulation()
        with _state_lock:
            _state["cycle_active"] = False
            _state["cycle_start_time"] = None
            _state["anomaly_active"] = False
            _state["_dev_active"] = {"dp": False, "flow": False, "reff": False}
            _state["anomaly_percent"] = 0.0
        db.insert_service_event(
            "LERNDATEN_RESET",
            _state.get("heta_code", ""),
            json.dumps(
                {
                    "grund": "Konfigurationsänderung",
                    "geaenderte_parameter": [k for k in data if k in _LEARNING_SENSITIVE_KEYS],
                }
            ),
        )
        logger.info(
            "Lerndaten zurückgesetzt aufgrund Konfigurationsänderung: %s",
            [k for k in data if k in _LEARNING_SENSITIVE_KEYS],
        )

    safe = {k: v for k, v in settings.items() if k not in ("settings_password_hash",)}
    return jsonify(
        {
            "success": True,
            "settings": safe,
            "learning_reset": learning_reset_needed,
            "message": (
                "Einstellungen gespeichert. Lernprozess wurde zurückgesetzt und muss neu durchlaufen werden."
                if learning_reset_needed
                else "Einstellungen gespeichert."
            ),
        }
    )


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
        return jsonify(
            {"success": True, "token": token, "timeout_minutes": settings.get("session_timeout_minutes", 30)}
        )
    else:
        logger.warning("Einstellungsbereich: Falsches Passwort.")
        return jsonify({"success": False, "message": "Falsches Passwort."}), 401


@app.route("/api/settings/logout", methods=["POST"])
def api_settings_logout():
    """Beendet die Sitzung."""
    token = request.headers.get("X-Auth-Token", "") or (request.get_json(force=True, silent=True) or {}).get(
        "token", ""
    )
    _invalidate_session(token)
    return jsonify({"success": True, "message": "Abgemeldet."})


@app.route("/api/settings/auth-check", methods=["GET"])
def api_settings_auth_check():
    """Prüft ob der aktuelle Token noch gültig ist."""
    token = request.headers.get("X-Auth-Token", "") or request.args.get("token", "")
    return jsonify({"authenticated": _validate_session(token)})


@app.route("/api/factory-reset", methods=["POST"])
def api_factory_reset():
    """
    Werksreset: löscht alle Messdaten, Profile und Zyklen, entfernt die lokale
    Konfigurationsdatei und setzt den gesamten Laufzeitstatus zurück.
    Das System startet danach im Onboarding-Modus.

    Erfordert gültigen Session-Token UND Passwort-Bestätigung.
    """
    ok, err = _require_auth()
    if not ok:
        return err

    data = request.get_json(force=True, silent=True) or {}
    password = data.get("password", "")
    if not verify_password(password, settings.get("settings_password_hash", "")):
        return jsonify({"success": False, "message": "Passwort falsch."}), 403

    logger.warning("WERKSRESET ausgeführt.")

    # 1. Alle Datenbankdaten löschen
    db.wipe_all_data()

    # 2. Lokale Konfigurationsdatei entfernen (setzt auf settings.json-Defaults zurück)
    local_cfg = get_abs_path("config/settings.local.json")
    try:
        import os as _os

        _os.remove(local_cfg)
        logger.info("settings.local.json gelöscht.")
    except FileNotFoundError:
        pass

    # 3. Laufzeit-Settings auf Defaults zurücksetzen (onboarding_complete=False, kein Passwort)
    from config import load_settings as _load_settings

    settings.clear()
    settings.update(_load_settings())

    # 4. Laufzeitstatus zurücksetzen
    if _loop:
        _loop.mstate.smoothed_health_pct = None
    predictor.reset()
    reset_simulation()
    learning.tolerance_reff_pct = settings.get("tolerance_reff_pct", 0.25)

    with _state_lock:
        _state["heta_code"] = ""
        _state["activation_status"] = False
        _state["cycle_active"] = False
        _state["cycle_start_time"] = None
        _state["anomaly_active"] = False
        _state["_dev_active"] = {"dp": False, "flow": False, "reff": False}
        _state["anomaly_percent"] = 0.0
        _state["filter_status"] = "OK"
        _state["simulation_mode"] = settings.get("simulation_mode", True)

    # 5. Alle Sessions invalidieren
    with _sessions_lock:
        _sessions.clear()

    return jsonify({"success": True, "message": "Werksreset abgeschlossen. Bitte Seite neu laden."})


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


@app.route("/api/onboarding/status", methods=["GET"])
def api_onboarding_status():
    """Gibt zurück ob das Onboarding bereits abgeschlossen wurde."""
    return jsonify(
        {
            "onboarding_complete": settings.get("onboarding_complete", False),
            "has_password": bool(settings.get("settings_password_hash", "")),
        }
    )


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
        return jsonify({"success": False, "message": "Passwort muss mindestens 4 Zeichen haben."}), 400

    # Konfigurierbare Felder aus dem Onboarding
    onboarding_fields = {
        "simulation_mode",
        "dp_limit_bar",
        "dp_clean_bar",
        "flow_max_l_min",
        "pressure_range_bar",
        "temperature_min_c",
        "temperature_max_c",
        "sampling_interval_seconds",
        "tolerance_dp_pct",
        "tolerance_reff_pct",
        "tolerance_flow_pct",
        "tolerance_temp_c",
        "operation_mode",
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
        p1_base=settings.get("sim_p1_base_bar", 4.0),
        q_base=settings.get("sim_q_base_l_min", 145.0),
        t_base=settings.get("sim_t_base_c", 25.0),
    )
    predictor.update_limits(settings["dp_limit_bar"], settings["dp_clean_bar"])
    learning.tolerance_reff_pct = settings.get("tolerance_reff_pct", 0.25)

    with _state_lock:
        _state["simulation_mode"] = settings["simulation_mode"]
        # Im Hardware-Modus muss die Startup-Sensorprüfung durchlaufen werden
        _state["startup_sensor_check"] = not settings["simulation_mode"]

    db.insert_service_event("ONBOARDING_ABGESCHLOSSEN", "", json.dumps({"timestamp": time.time()}))
    logger.info("Onboarding abgeschlossen.")

    # Messzyklus starten
    if not _state["running"]:
        _start_measurement_thread()

    return jsonify({"success": True, "message": "Einrichtung abgeschlossen. System startet."})


@app.route("/api/simulation/start", methods=["POST"])
def api_simulation_start():
    """Startet die Messung (Play) bzw. setzt einen pausierten Zyklus fort – ohne ihn zu verwerfen."""
    if not settings.get("onboarding_complete", False):
        return jsonify({"success": False, "message": "Onboarding nicht abgeschlossen."}), 403
    with _state_lock:
        # running=True muss VOR _start_measurement_thread gesetzt werden: läuft der alte
        # Thread nach einem Stop noch im sleep(), sieht er running=True und macht weiter
        # statt zu beenden — Race Condition beim schnellen Stop→Start vermieden.
        _state["running"] = True
        _state["simulation_mode"] = True
        _state["sensor_fault"] = False
        _state["sensor_fault_channels"] = []
        _state["sensor_fault_message"] = ""
        _state["sensor_error"] = False
        _state["startup_sensor_check"] = False
    _start_measurement_thread()
    return jsonify({"success": True, "message": "Simulation gestartet."})


@app.route("/api/simulation/stop", methods=["POST"])
def api_simulation_stop():
    """Pausiert die Messung (Pause) – der laufende Zyklus und die Szenario-Einstellungen bleiben erhalten."""
    pause_simulation()
    with _state_lock:
        _state["running"] = False
    return jsonify({"success": True, "message": "Simulation pausiert."})


@app.route("/api/simulation/reset", methods=["POST"])
def api_simulation_reset():
    """Setzt Simulation, Zyklus und Prognose vollständig zurück. Startet NICHT automatisch neu (Play erforderlich)."""
    learning.abort_cycle()
    clear_simulation_rates()
    full_reset_simulation()
    predictor.reset()
    if _loop:
        _loop.mstate.smoothed_health_pct = None
    with _state_lock:
        _state["running"] = False
        _state["cycle_active"] = False
        _state["cycle_start_time"] = None
        _state["cycle_dp_reached_time"] = None
        _state["cycle_active_seconds"] = 0.0
        _state["awaiting_confirmation"] = False
        _state["waiting_for_flow"] = True
        _state["anomaly_active"] = False
        _state["_dev_active"] = {"dp": False, "flow": False, "reff": False}
        _state["anomaly_percent"] = 0.0
        _state["sim_rates_active"] = False
        _state["sim_scenario"] = "normal"
        _state["sim_dirt_rate_pct"] = 100.0
        _state["sim_p1_trend_pct"] = 0.0
        _state["sim_p2_trend_pct"] = 0.0
        _state["sim_flow_drop_pct"] = 75.0
        _state["sim_temp_trend"] = 0.0
    return jsonify({"success": True, "message": "System zurückgesetzt."})


@app.route("/api/simulation/quick-learn", methods=["POST"])
def api_simulation_quick_learn():
    """Simuliert die erforderlichen Lernzyklen für den aktuellen HETA-Code."""
    with _state_lock:
        sim_mode = _state["simulation_mode"]
        heta_code = _state["heta_code"]

    if not sim_mode:
        return jsonify({"success": False, "message": "Nur im Simulationsmodus verfügbar."})
    effective_code = heta_code or "DEMO"
    if learning.is_profile_valid(effective_code):
        return jsonify({"success": False, "message": "Profil ist bereits valide – Lernphase abgeschlossen."})

    dp_clean = settings.get("dp_clean_bar", 0.2)
    dp_limit = settings.get("dp_limit_bar", 2.5)
    sampling_interval = settings.get("sampling_interval_seconds", 1)
    # Zyklusdauer aus Simulator ableiten (dirt_rate_factor bestimmt die Dauer)
    cycle_secs = get_simulation_estimated_cycle_secs()
    cycle_steps = max(10, int(cycle_secs / max(sampling_interval, 1)))
    required_cycles = settings.get("required_cycles_for_profile", 3)

    # Sample-Schritte: ~200 Stützpunkte für ausreichende Füllung der 40-Bucket-Referenzkurve.
    stride = max(1, cycle_steps // 200)
    sample_steps = list(range(0, cycle_steps + 1, stride))

    existing = db.count_confirmed_cycles(effective_code)
    needed = max(0, required_cycles - existing)
    now = time.time()
    loading_rate = 0.0  # Fallback falls needed == 0 (Schleife läuft dann nicht)

    for i in range(needed):
        t_start = now - (needed - i) * (cycle_secs + 60)

        # ── Physik identisch mit FilterSimulator.get_readings() (inkl. Temperatur-
        # Drift) – jeder gelernte Zyklus bekommt seinen eigenen t_start und damit
        # eine eigene Drift-Phase, genau wie echte, zeitlich versetzte Zyklen. ──
        boundary_vals = simulate_reference_cycle([0, cycle_steps], cycle_steps, sampling_interval, t_start)
        start_vals, end_vals = boundary_vals[0], boundary_vals[1]
        start_vals["r_eff"] = start_vals["dp"] / max(start_vals["flow"], 0.1)
        end_vals["r_eff"] = end_vals["dp"] / max(end_vals["flow"], 0.1)

        # Mittelwerte aus tatsächlichen Samples berechnen (nicht analytisch).
        # Wichtig bei hohem flow_drop: analytische Formel ignoriert den q_min-Clamp.
        sample_vals = simulate_reference_cycle(sample_steps, cycle_steps, sampling_interval, t_start)
        for sv in sample_vals:
            sv["r_eff"] = sv["dp"] / max(sv["flow"], 0.1)
        avg_flow = round(sum(sv["flow"] for sv in sample_vals) / len(sample_vals), 2)
        avg_temp = round(sum(sv["temp"] for sv in sample_vals) / len(sample_vals), 1)

        # Beladungsrate: (dp_ende - dp_start) / Zyklusdauer [bar/s]
        loading_rate = round((end_vals["dp"] - start_vals["dp"]) / max(cycle_secs, 1.0), 6)

        cycle_id = db.insert_cycle(
            {
                "heta_code": effective_code,
                "start_time": t_start,
                "end_time": t_start + cycle_secs,
                "duration_seconds": round(cycle_secs, 1),
                "start_r_eff": round(start_vals["r_eff"], 6),
                "end_r_eff": round(end_vals["r_eff"], 6),
                "start_dp": round(start_vals["dp"], 4),
                "end_dp": round(end_vals["dp"], 3),
                "average_flow": avg_flow,
                "average_temperature": avg_temp,
                "loading_rate": loading_rate,
                "confirmed_filter_change": 1,
            }
        )

        # Zeitreihe aus den bereits berechneten Samples übernehmen.
        samples = []
        for s, sv in zip(sample_steps, sample_vals):
            t = t_start + s * sampling_interval
            samples.append(
                {
                    "cycle_id": cycle_id,
                    "heta_code": effective_code,
                    "timestamp": t,
                    "cycle_second": round(s * sampling_interval, 1),
                    "p1_bar": sv["p1"],
                    "p2_bar": sv["p2"],
                    "dp_bar": sv["dp"],
                    "flow_l_min": round(sv["flow"], 2),
                    "temp_c": round(sv["temp"], 1),
                    "r_eff": round(sv["r_eff"], 6),
                    "filter_health_percent": None,
                    "remaining_seconds": None,
                }
            )
        db.insert_cycle_samples(samples)

    learning._update_profile(effective_code)
    remaining_secs = (dp_limit - dp_clean) / max(loading_rate, 1e-9)
    predictor.update_limits(dp_limit, dp_clean)
    predictor.seed(remaining_secs)

    with _state_lock:
        _state["learned_cycles"] = required_cycles
        _state["profile_status"] = "VALIDIERT"
        _state["show_filter_health"] = True

    # Simulation auf Schritt 0 zurücksetzen damit der nächste Zyklus
    # mit sauberem Startwert beginnt (kein dp-Offset aus alten Schritten).
    if _loop:
        _loop.mstate.smoothed_health_pct = None
    reset_simulation()
    learning._active_cycle = None  # laufenden Zyklus verwerfen (Daten vor Quick-Learn)
    with _state_lock:
        # awaiting_confirmation MUSS zurückgesetzt werden: war es True als Quick-Learn
        # aufgerufen wurde, schläft der Messzyklus-Thread sonst dauerhaft und die
        # Prozessanalyse startet nie (analysis_ready bleibt False).
        _state["awaiting_confirmation"] = False
        _state["cycle_active"] = False
        _state["cycle_start_time"] = None
        _state["cycle_dp_reached_time"] = None
        _state["cycle_active_seconds"] = 0.0
        _state["waiting_for_flow"] = True  # Zyklus sauber neu starten

    db.insert_service_event(
        "SIM_SCHNELLLERN", effective_code, json.dumps({"simulated_cycles": needed, "loading_rate": loading_rate})
    )
    logger.info(
        "Schnell-Lernphase: %d Zyklen für %s simuliert (je %d Samples).",
        needed,
        effective_code,
        len(samples) if needed else 0,
    )
    return jsonify(
        {
            "success": True,
            "message": f"{needed} Lernzyklus/-zyklen für «{effective_code}» simuliert. Profil ist jetzt valide.",
            "loading_rate": loading_rate,
        }
    )


@app.route("/api/simulation/set-rates", methods=["POST"])
def api_simulation_set_rates():
    """Setzt Simulations-Szenario-Parameter."""
    with _state_lock:
        sim_mode = _state["simulation_mode"]
    if not sim_mode:
        return jsonify({"success": False, "message": "Nur im Simulationsmodus verfügbar."})

    data = request.get_json(force=True, silent=True) or {}

    if not data.get("active", True):
        clear_simulation_rates()
        with _state_lock:
            _state["sim_rates_active"] = False
            _state["sim_scenario"] = "normal"
            _state["sim_dirt_rate_pct"] = 100.0
            _state["sim_p1_trend_pct"] = 0.0
            _state["sim_p2_trend_pct"] = 0.0
            _state["sim_flow_drop_pct"] = 75.0
            _state["sim_temp_trend"] = 0.0
        return jsonify({"success": True, "active": False})

    dirt_rate_pct = max(10.0, min(float(data.get("dirt_rate_pct", 100.0)), 400.0))
    p1_trend_pct = max(-100.0, min(float(data.get("p1_trend_pct", 0.0)), 100.0))
    p2_trend_pct = max(-100.0, min(float(data.get("p2_trend_pct", 0.0)), 100.0))
    flow_drop_pct = max(10.0, min(float(data.get("flow_drop_pct", 75.0)), 99.0))
    temp_trend = max(-5.0, min(float(data.get("temp_trend", 0.0)), 5.0))
    scenario = str(data.get("scenario", "custom"))

    set_simulation_scenario_params(
        dirt_rate_factor=dirt_rate_pct / 100.0,
        p1_trend_factor=p1_trend_pct / 100.0,
        flow_drop_factor=flow_drop_pct / 100.0,
        temp_trend_per_cycle=temp_trend,
        p2_trend_factor=p2_trend_pct / 100.0,
    )

    estimated_secs = get_simulation_estimated_cycle_secs()

    with _state_lock:
        _state["sim_estimated_cycle_secs"] = round(estimated_secs, 1)
        _state["sim_rates_active"] = True
        _state["sim_scenario"] = scenario
        _state["sim_dirt_rate_pct"] = round(dirt_rate_pct, 1)
        _state["sim_p1_trend_pct"] = round(p1_trend_pct, 1)
        _state["sim_p2_trend_pct"] = round(p2_trend_pct, 1)
        _state["sim_flow_drop_pct"] = round(flow_drop_pct, 1)
        _state["sim_temp_trend"] = round(temp_trend, 1)

    return jsonify(
        {
            "success": True,
            "active": True,
            "scenario": scenario,
            "dirt_rate_pct": dirt_rate_pct,
            "p1_trend_pct": p1_trend_pct,
            "p2_trend_pct": p2_trend_pct,
            "flow_drop_pct": flow_drop_pct,
            "temp_trend": temp_trend,
            "estimated_cycle_secs": round(estimated_secs, 1),
        }
    )


@app.route("/api/service/request", methods=["POST"])
def api_service_request():
    """Erstellt ein Servicedatenpaket und einen Servicebericht."""
    with _state_lock:
        current = dict(_state)

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
        "prediction_mode": current["prediction_mode"],
        "remaining_display": current["remaining_display"],
        "remaining_seconds": current["remaining_seconds"],
        "learned_cycles": current["learned_cycles"],
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
    rec = generate_service_recommendation(fs, pred_status, health_percent=current["filter_health_percent"])
    spare = generate_spare_parts_order(current["heta_code"], fs)
    report = generate_service_report(payload, rec, spare)

    db.insert_service_event("SERVICE_ANFRAGE", current["heta_code"], json.dumps(payload, ensure_ascii=False))

    if _mqtt and _mqtt.is_connected:
        _mqtt.publish_service(payload)

    return jsonify(
        {
            "payload": payload,
            "recommendation": rec,
            "spare_parts": spare,
            "report_text": report,
        }
    )


@app.route("/api/export/csv")
def api_export_csv():
    """Exportiert Messwerte als CSV-Datei und gibt den Pfad zurück."""
    since = float(request.args.get("since", 0))
    export_dir = get_abs_path(settings.get("export_path", "exports/"))
    filename = f"heta_export_{int(time.time())}.csv"
    filepath = os.path.join(export_dir, filename)
    count = db.export_measurements_csv(filepath, since_timestamp=since)
    return jsonify(
        {
            "success": count > 0,
            "filename": filename,
            "rows": count,
            "path": filepath,
        }
    )


@app.route("/api/export/csv/download")
def api_export_csv_download():
    """Exportiert und lädt die CSV-Datei direkt herunter."""
    since = float(request.args.get("since", 0))
    export_dir = get_abs_path(settings.get("export_path", "exports/"))
    os.makedirs(export_dir, exist_ok=True)
    filename = f"heta_export_{int(time.time())}.csv"
    filepath = os.path.join(export_dir, filename)
    db.export_measurements_csv(filepath, since_timestamp=since)
    return send_from_directory(export_dir, filename, as_attachment=True, download_name="heta_messwerte.csv")


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
    heta_code = request.args.get("heta_code", _state.get("heta_code", "")) or "DEMO"
    return jsonify(db.get_profile(heta_code))


@app.route("/api/reference-curve")
def api_reference_curve():
    """Gibt die zeitbasierte Referenzkurve für einen HETA-Code zurück."""
    heta_code = request.args.get("heta_code", _state.get("heta_code", "")) or "DEMO"
    profile = learning.get_profile(heta_code)
    if not profile:
        return jsonify(None)
    curve_json = profile.get("reference_curve_json")
    curve = []
    if curve_json:
        try:
            curve = json.loads(curve_json)
        except Exception:
            pass
    return jsonify(
        {
            "heta_code": heta_code,
            "curve": curve,
            "reference_duration_seconds": profile.get("reference_duration_seconds", 0),
            "reference_r_eff_start": profile.get("reference_r_eff_start") or profile.get("reference_r_eff") or 0.0,
            "reference_dp_clean": profile.get("reference_dp_clean") or 0.0,
            "cycles_count": profile.get("cycles_count", 0),
            "profile_valid": bool(profile.get("profile_valid")),
            "tolerance_dp_pct": settings.get("tolerance_dp_pct", 0.25),
            "tolerance_reff_pct": settings.get("tolerance_reff_pct", 0.25),
            "tolerance_flow_pct": settings.get("tolerance_flow_pct", 0.25),
            "tolerance_temp_c": settings.get("tolerance_temp_c", 10.0),
        }
    )


@app.route("/api/cycle-samples/<int:cycle_id>")
def api_cycle_samples(cycle_id):
    """Gibt die Zeitreihen-Messwerte eines abgeschlossenen Filterzyklus zurück (max. 300 Punkte)."""
    samples = db.get_cycle_samples(cycle_id)
    if len(samples) > 300:
        step = max(1, len(samples) // 300)
        samples = samples[::step]
    return jsonify(samples)


@app.route("/api/active-cycle")
def api_active_cycle():
    """Gibt den aktuellen laufenden Filterzyklus mit Zeitreihen zurück (max. 300 Punkte)."""
    cycle = learning.active_cycle
    if cycle is None:
        return jsonify(None)
    heta_code = cycle.heta_code
    profile = learning.get_profile(heta_code) or {}
    ref_duration = profile.get("reference_duration_seconds", 0.0)
    n = len(cycle.dp_samples)
    if n == 0:
        return jsonify(
            {
                "heta_code": heta_code,
                "start_time": cycle.start_time,
                "elapsed_seconds": 0.0,
                "ref_duration_seconds": ref_duration,
                "samples": [],
            }
        )
    step = max(1, n // 300)
    samples = []
    for i in range(0, n, step):
        t_off = cycle.timestamps[i] - cycle.start_time
        t_pct = (t_off / ref_duration * 100.0) if ref_duration > 0 else None
        samples.append(
            {
                "cycle_second": round(t_off, 1),
                "t_pct": round(t_pct, 2) if t_pct is not None else None,
                "dp_bar": round(cycle.dp_samples[i], 4),
                "r_eff": round(cycle.r_eff_samples[i], 5) if i < len(cycle.r_eff_samples) else None,
            }
        )
    return jsonify(
        {
            "heta_code": heta_code,
            "start_time": cycle.start_time,
            "elapsed_seconds": round(time.time() - cycle.start_time, 1),
            "ref_duration_seconds": ref_duration,
            "samples": samples,
        }
    )


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
        return jsonify(
            {"screen": screen, "screen_index": _display_ctrl._screen_idx, "confirm_armed": _display_ctrl._confirm_armed}
        )
    if _display:
        return jsonify({"screen": _display.current_screen, "screen_index": None, "confirm_armed": False})
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
        return jsonify(
            {
                "success": False,
                "changed": False,
                "restarting": False,
                "output": "Timeout – git pull hat zu lange gebraucht.",
            }
        )
    except FileNotFoundError:
        return jsonify(
            {
                "success": False,
                "changed": False,
                "restarting": False,
                "output": "git nicht gefunden. Ist Git installiert?",
            }
        )

    output = (result.stdout + result.stderr).strip()
    success = result.returncode == 0
    changed = success and "Already up to date." not in result.stdout

    logger.info("Git pull: rc=%d changed=%s output=%r", result.returncode, changed, output)

    if changed:

        def _restart():
            time.sleep(2.0)
            logger.info("Neustart nach Git-Update – versuche systemctl…")

            # Versuch 1: systemd (Produktion – Pi läuft als Service)
            try:
                r = subprocess.run(
                    ["sudo", "systemctl", "restart", "heta-monitor"],
                    timeout=10,
                    capture_output=True,
                )
                if r.returncode == 0:
                    logger.info("systemctl restart erfolgreich.")
                    return
                logger.warning(
                    "systemctl restart fehlgeschlagen (rc=%d): %s",
                    r.returncode,
                    (r.stdout + r.stderr).decode(errors="replace").strip(),
                )
            except Exception as exc:
                logger.warning("systemctl nicht ausführbar: %s", exc)

            # Fallback: neuen Python-Prozess vollständig losgelöst starten,
            # dann diesen Prozess beenden.  close_fds=True verhindert, dass
            # der neue Prozess den offenen Flask-Socket erbt und "Port belegt"
            # meldet.  start_new_session=True schützt vor SIGHUP beim Exit.
            # sleep 3 gibt dem Betriebssystem Zeit, den Port freizugeben.
            logger.info("Fallback: Starte neuen Prozess und beende mich – Port wird nach ~3 s wieder erreichbar sein.")
            try:
                restart_cmd = f"sleep 3 && exec {sys.executable} {os.path.join(_BASE_DIR, 'backend', 'app.py')}"
                subprocess.Popen(
                    ["bash", "-c", restart_cmd],
                    cwd=_BASE_DIR,
                    close_fds=True,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                logger.error("Fallback-Neustart konnte nicht gestartet werden: %s", exc)
            finally:
                os._exit(0)

        threading.Thread(target=_restart, daemon=True).start()

    return jsonify(
        {
            "success": success,
            "changed": changed,
            "restarting": changed,
            "output": output,
        }
    )


# ---------------------------------------------------------------------------
# Anwendungsstart
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = settings.get("webserver_host", "0.0.0.0")
    port = settings.get("webserver_port", 8080)

    logger.info("=" * 60)
    logger.info("HETA Smart Filter Monitoring – Start auf %s:%d", host, port)
    sim = settings.get("simulation_mode", True)
    if sim:
        logger.info("Betriebsart : Simulationsmodus")
    elif _hw_available:
        logger.info("Betriebsart : Realbetrieb – AnoPi Shield erkannt")
    else:
        logger.warning(
            "Betriebsart : Realbetrieb konfiguriert, aber AnoPi Shield NICHT erkannt – Fallback zur Simulation aktiv!"
        )
    logger.info("Onboarding  : %s", "abgeschlossen" if settings.get("onboarding_complete") else "ausstehend")
    logger.info("=" * 60)

    # Messzyklus nur starten wenn Onboarding abgeschlossen
    if settings.get("onboarding_complete", False):
        _start_measurement_thread()
    else:
        logger.info("Onboarding ausstehend – Messzyklus wartet.")

    app.run(host=host, port=port, debug=False, threaded=True)
