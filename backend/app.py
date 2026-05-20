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
from collections import deque
from datetime import datetime
from typing import Optional

# Projektverzeichnis in sys.path eintragen damit relative Imports funktionieren
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE_DIR, "backend"))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from config import settings, save_settings, get_abs_path, hash_password, verify_password
from sensors import (read_sensors, reset_simulation, full_reset_simulation,
                     update_simulation_params, probe_hardware, check_hardware_sensors,
                     set_simulation_scenario_params, get_simulation_scenario_params,
                     clear_simulation_rates, get_simulation_rates_active,
                     get_simulation_cycle_steps)
from calculations import (calculate_filter_state, FilterState,
                          calculate_filter_health_from_r_eff,
                          STATUS_OK, STATUS_WARNUNG, STATUS_FEHLER,
                          STATUS_WECHSEL, STATUS_WECHSEL_BESTAETIGEN)
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
    "dp_limit_bar", "flow_max_l_min",
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

# Geglätteter Beladungsgrad mit Ratchet-Filter (in Prozent, None = nicht initialisiert)
_smoothed_health_pct: Optional[float] = None

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
    "r_rel_factor": None,        # r_eff / r_eff_reference_start, None während Lernphase
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

    # Simulations-Szenario-Parameter
    "sim_cycle_seconds":       settings.get("sim_cycle_seconds", 300),
    "sim_rates_active":        False,
    "sim_scenario":            "normal",
    "sim_dirt_rate_pct":       100.0,
    "sim_p1_trend_pct":        0.0,
    "sim_flow_drop_pct":       75.0,
    "sim_temp_trend":          0.0,
    "sim_dp_deviation_pct":    0.0,
    "sim_flow_deviation_pct":  0.0,
    "sim_temp_deviation":      0.0,

    # Modusneutrale Prozessanalyse (Sensor- UND Simulationsmodus)
    "analysis_active":             False,  # True wenn Profil valide + läuft
    "analysis_ready":              False,  # True wenn Kurvenvergleich verfügbar
    "analysis_dp_rate_ref":        0.0,
    "analysis_dp_rate_current":    0.0,
    "analysis_dp_deviation_pct":   0.0,    # Abweichung in %
    "analysis_flow_ref":           0.0,    # Referenz-Durchfluss (l/min)
    "analysis_flow_deviation_pct": 0.0,    # Abweichung in %
    "analysis_temp_ref":           0.0,    # Referenz-Temperatur (°C)
    "analysis_temp_deviation":     0.0,    # Abweichung in °C
    "analysis_cycle_progress_pct": 0.0,
    "analysis_dp_ref":             0.0,
    "analysis_reff_ref":           0.0,
    "analysis_reff_cur":           0.0,
    "analysis_reff_deviation_pct": 0.0,

    # Filterwechsel
    "awaiting_confirmation": False,
    "cycle_active": False,
    "cycle_start_time": None,
    "cycle_dp_reached_time": None,  # Zeitpunkt an dem dp-Limit erreicht wurde

    # Prognose
    "remaining_display": "Unbekannt",
    "remaining_seconds": None,
    "prediction_mode": "BASIS",

    # Lernmodul
    "learned_cycles": 0,
    "required_cycles": settings.get("required_cycles_for_profile", 3),
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
    tolerance_reff_pct=settings.get("tolerance_reff_pct",
                                    settings.get("clean_resistance_tolerance", 0.25)),
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
    cycle_seconds=settings.get("sim_cycle_seconds", 300),
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
            pin_enca=settings.get("encoder_pin_enca", 16),
            pin_encb=settings.get("encoder_pin_encb", 20),
            pin_sw1 =settings.get("encoder_pin_sw1",  21),
            pin_sw2 =settings.get("encoder_pin_sw2",  12),
            pin_sw3 =settings.get("encoder_pin_sw3",  13),
            pin_sw4 =settings.get("encoder_pin_sw4",  19),
            pin_sw5 =settings.get("encoder_pin_sw5",  26),
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

    logger.info("Messzyklus gestartet (Intervall: %ds).", interval)
    _dp_rate_buffer.clear()

    while _state["running"]:
        t_start = time.time()
        # dp_limit aus Einstellungen; dp_clean aus gemessenem Profil (Ø start_dp
        # der Lernzyklen), Fallback auf Einstellungswert solange kein Profil.
        dp_limit = settings.get("dp_limit_bar", 2.5)
        _loop_profile = learning.get_profile(_state.get("heta_code", ""))
        dp_clean = ((_loop_profile.get("reference_dp_clean") or 0.0)
                    if _loop_profile and (_loop_profile.get("reference_dp_clean") or 0.0) > 0
                    else settings.get("dp_clean_bar", 0.2))

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

        # Sensorfehler im Hardwaremodus: Messung sofort stoppen, Bediener informieren
        if sensor_mode == "sensor_fault":
            failed_ch = readings.get("failed_channels", [])
            failed_names = readings.get("failed_names", [])
            msg = f"Sensorfehler: {', '.join(failed_names)} – Messung gestoppt."
            logger.error("Messung gestoppt wegen Sensorfehler auf Kanal(en) %s.", failed_ch)
            learning.abort_cycle()
            with _state_lock:
                _state["running"]               = False
                _state["sensor_fault"]          = True
                _state["sensor_fault_channels"] = failed_ch
                _state["sensor_fault_message"]  = msg
                _state["filter_status"]         = "FEHLER"
                _state["sensor_error"]          = True
                _state["cycle_active"]          = False
                _state["cycle_start_time"]      = None
                _state["cycle_dp_reached_time"] = None
                _state["last_update"]           = time.strftime("%Y-%m-%dT%H:%M:%S")
            break

        sensor_error = not (p1.is_valid and p2.is_valid and temp.is_valid and flow.is_valid)

        # Plausibilitätsprüfung im Realbetrieb: p2 > p1 ist physikalisch nicht möglich
        if (sensor_mode == "hardware" and not sensor_error
                and p1.is_valid and p2.is_valid
                and p2.value > p1.value + 0.05):
            logger.warning(
                "Plausibilitätswarnung: p2 (%.3f bar) > p1 (%.3f bar) – "
                "Sensorkabel vertauscht oder Druckverhältnisse unplausibel.",
                p2.value, p1.value,
            )

        # Berechnungen
        # dp_direct: Simulationsmodus liefert dp als Primärwert – verhindert
        # Gleitkomma-Artefakte durch p1-p2-Subtraktion in calculate_filter_state.
        dp_direct = readings.get("dp_direct")
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
            dp_override=dp_direct,
        )

        # ── Profil laden (einmalig pro Loop-Iteration) ────────────────────
        profile       = learning.get_profile(heta_code) if heta_code else None
        profile_valid = bool(profile and profile.get("profile_valid")) and heta_activated
        cycles_count  = (profile.get("cycles_count", 0) if profile else 0) if heta_code else 0

        # ── Beladungsgrad via R_eff ──────────────────────────────────────
        # Bevorzugt R_eff-basiert (reagiert auf Δp UND Durchflussänderungen).
        # Ratchet: schnell steigen (Filter beladen), langsam fallen.
        global _smoothed_health_pct
        # R_eff-basierter Beladungsgrad nur wenn Profil VALIDE ist –
        # während der Lernphase bleibt die dp-Formel aktiv, damit
        # kein Methodenwechsel mitten im Lernzyklus auftritt.
        r_eff_clean_ref = r_eff_limit_ref = None
        if profile_valid and profile:
            r_eff_clean_ref = (profile.get("reference_r_eff_start")
                               or profile.get("reference_r_eff"))
            r_eff_limit_ref = profile.get("reference_r_eff_end") or 0.0
            if not r_eff_limit_ref:
                # Fallback für alte Profile ohne reference_r_eff_end
                ref_flow = profile.get("reference_avg_flow") or 0.0
                if ref_flow > 0.1:
                    r_eff_limit_ref = dp_limit / ref_flow

        if r_eff_clean_ref and r_eff_limit_ref and fs.r_eff > 0:
            raw_health, _ = calculate_filter_health_from_r_eff(
                fs.r_eff, r_eff_clean_ref, r_eff_limit_ref
            )
        else:
            raw_health = fs.filter_health_percent  # Fallback: dp-basiert

        if _smoothed_health_pct is None:
            _smoothed_health_pct = raw_health
        elif raw_health < _smoothed_health_pct:
            # Filter belädt sich → health sinkt → leicht geglättet (schnell)
            _smoothed_health_pct += 0.35 * (raw_health - _smoothed_health_pct)
        else:
            # Filter könnte sich scheinbar verbessern → sehr langsam (max 0.3 %/s)
            _smoothed_health_pct = min(raw_health, _smoothed_health_pct + 0.3)

        smoothed_health = round(_smoothed_health_pct, 1)

        # ── Zyklus starten falls nötig ────────────────────────────────────
        if not cycle_active and not sensor_error and heta_code:
            learning.start_cycle(heta_code, fs.r_eff, fs.dp_bar)
            with _state_lock:
                _state["cycle_active"] = True
                _state["cycle_start_time"] = time.time()
            logger.info("Neuer Filterzyklus gestartet.")

        # ── Kurvenbasierter Profilvergleich ───────────────────────────────
        with _state_lock:
            cycle_start_ts = _state.get("cycle_start_time")
        elapsed = (time.time() - cycle_start_ts) if cycle_start_ts else 0.0

        an_active = profile_valid and heta_activated and not sensor_error
        an_ready  = False
        analysis  = None
        cycle_progress_pct = 0.0
        dp_ref = dp_dev = 0.0
        reff_ref = reff_dev = 0.0
        flow_ref = flow_dev = 0.0
        temp_ref = temp_dev = 0.0

        if an_active and cycle_active:
            analysis = learning.get_curve_analysis(
                heta_code, elapsed,
                fs.dp_bar, fs.r_eff, fs.flow_l_min, fs.temperature_c,
            )
            if analysis:
                an_ready           = True
                cycle_progress_pct = analysis["cycle_progress_pct"]
                dp_ref             = analysis["ref_dp"]
                dp_dev             = analysis["dp_deviation_pct"]
                reff_ref           = analysis["ref_r_eff"]
                reff_dev           = analysis["r_eff_deviation_pct"]
                flow_ref           = analysis["ref_flow"]
                flow_dev           = analysis["flow_deviation_pct"]
                temp_ref           = analysis["ref_temp"]
                temp_dev           = analysis["temp_deviation"]

        # ── Reststandzeit berechnen ───────────────────────────────────────
        if profile_valid and heta_activated and profile:
            ref_duration = profile.get("reference_duration_seconds") or 0.0
            if ref_duration > 0:
                # Referenzkurve invertieren: dp → t_pct → lineare Restzeit.
                # Gleicht die nichtlineare dp-Kurve (clogging^1.8) heraus.
                curve_json = profile.get("reference_curve_json") or "[]"
                try:
                    ref_curve = json.loads(curve_json)
                except Exception:
                    ref_curve = []
                remaining_s = predictor.update_with_reference_curve(
                    fs.dp_bar, ref_duration, ref_curve
                )
            else:
                remaining_s = predictor.update(fs.dp_bar)
        else:
            # Lernphase: Beladungsrate aus aktuellen Messwerten schätzen
            remaining_s = predictor.update(fs.dp_bar)

        # ── Lernwert erfassen (mit Beladungsgrad und Reststandzeit) ───────
        if cycle_active and not sensor_error:
            learning.record_sample(
                fs.flow_l_min, fs.temperature_c, fs.dp_bar, fs.r_eff,
                p1=fs.p1_bar, p2=fs.p2_bar, timestamp=time.time(),
                filter_health_percent=smoothed_health,
                remaining_seconds=remaining_s,
            )

        # ── Startverhalten prüfen (erste 10 Sekunden) ────────────────────
        if (cycle_active and heta_activated and cycle_start_ts
                and (time.time() - cycle_start_ts) < 10):
            anomaly, anom_pct = learning.check_start_behavior(heta_code, fs.r_eff)
            if anomaly and not _state["anomaly_active"]:
                learning.add_event("WARNUNG",
                    f"Startverhalten-Anomalie: R_eff {anom_pct:+.1f}% zur Referenz")
            with _state_lock:
                _state["anomaly_active"] = anomaly
                _state["anomaly_percent"] = anom_pct

        # ── Statusänderungen als Ereignis im aktiven Zyklus speichern ────
        prev_status = _state.get("filter_status", STATUS_OK)
        if fs.status != prev_status and cycle_active:
            if fs.status == STATUS_FEHLER:
                learning.add_event("FEHLER", "Sensorfehler erkannt")
            elif fs.status == STATUS_WARNUNG:
                learning.add_event("WARNUNG", "Anomales Beladungsverhalten erkannt")
            elif fs.status in (STATUS_WECHSEL, STATUS_WECHSEL_BESTAETIGEN):
                learning.add_event("WECHSEL",
                    f"Filterwechsel erforderlich – Δp={fs.dp_bar:.3f} bar")

        # ── Prognosestatus ────────────────────────────────────────────────
        req_cycles  = settings.get("required_cycles_for_profile", 3)
        pred_status = predictor.get_status(
            remaining_seconds=remaining_s,
            heta_activated=heta_activated,
            profile_valid=profile_valid,
            learned_cycles=cycles_count,
            required_cycles=req_cycles,
        )

        # ── Filterwechsel erkennen ────────────────────────────────────────
        if fs.dp_bar >= dp_limit and not awaiting and cycle_active:
            logger.warning("Filterwechsel-Grenzwert überschritten! dp=%.3f >= %.2f",
                           fs.dp_bar, dp_limit)
            with _state_lock:
                _state["awaiting_confirmation"]  = True
                _state["cycle_dp_reached_time"]  = time.time()
            if _display_ctrl:
                _display_ctrl.navigate_to_filter_change()
                _display.show_filter_change(fs.dp_bar, dp_limit, armed=False, awaiting=True)
            elif _display:
                _display.show_filter_change(fs.dp_bar, dp_limit, armed=False, awaiting=True)
            if _mqtt:
                _mqtt.publish_alarm("WECHSEL", "Filterwechsel erforderlich!", heta_code)

        # ── Serviceempfehlung ─────────────────────────────────────────────
        rec = generate_service_recommendation(fs, pred_status, health_percent=smoothed_health)

        # ── Datenbank ─────────────────────────────────────────────────────
        db.insert_measurement({
            "timestamp": time.time(),
            "p1_bar": fs.p1_bar,
            "p2_bar": fs.p2_bar,
            "dp_bar": fs.dp_bar,
            "flow_l_min": fs.flow_l_min,
            "temperature_c": fs.temperature_c,
            "r_eff": fs.r_eff,
            "filter_health_percent": smoothed_health,
            "status": fs.status,
            "heta_code": heta_code,
            "sensor_mode": sensor_mode,
        })

        # ── dp-Puffer aktualisieren (Fallback-Prognose) ───────────────────
        _dp_rate_buffer.append((time.time(), fs.dp_bar))

        with _state_lock:
            _state.update({
                "analysis_active":             an_active,
                "analysis_ready":              an_ready,
                "analysis_cycle_progress_pct": cycle_progress_pct,
                "analysis_dp_ref":             dp_ref,
                "analysis_dp_deviation_pct":   dp_dev,
                "analysis_reff_ref":           reff_ref,
                "analysis_reff_cur":           fs.r_eff,
                "analysis_reff_deviation_pct": reff_dev,
                "analysis_flow_ref":           flow_ref,
                "analysis_flow_deviation_pct": flow_dev,
                "analysis_temp_ref":           temp_ref,
                "analysis_temp_deviation":     temp_dev,
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
                "r_rel_factor": round(fs.r_eff / r_eff_clean_ref, 4) if (r_eff_clean_ref and r_eff_clean_ref > 0) else None,
                "filter_health_percent": smoothed_health,
                "filter_status": fs.status,
                "sensor_error": fs.sensor_error,
                "remaining_display": pred_status["remaining_display"],
                "remaining_seconds": pred_status["remaining_seconds"],
                "prediction_mode": pred_status["prediction_mode"],
                "learned_cycles": cycles_count,
                "required_cycles": req_cycles,
                "profile_status": "VALIDIERT" if profile_valid else "LERNEND",
                "show_filter_health": heta_activated,
                "service_message": rec["message"],
                "service_priority": rec["priority"],
                "last_update": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "sim_rates_active": get_simulation_rates_active(),
            })

        loop_elapsed = time.time() - t_start
        sleep_time = max(0.0, interval - loop_elapsed)
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


@app.route("/api/heta/reset-cycles", methods=["POST"])
def api_heta_reset_cycles():
    """
    Setzt alle Lernzyklen und das Profil für den aktuell aktiven HETA-Code zurück.
    Erfordert einen gültigen Auth-Token.
    """
    ok, err = _require_auth()
    if not ok:
        return err

    with _state_lock:
        heta_code = _state.get("heta_code", "")

    if not heta_code:
        return jsonify({"success": False, "message": "Kein HETA-Code aktiv."}), 400

    # Aktiven Lernzyklus abbrechen (ohne Speichern)
    learning._active_cycle = None

    # DB bereinigen
    db.reset_cycles_for_heta(heta_code)

    # Prognose-Modell zurücksetzen
    global _smoothed_health_pct
    _smoothed_health_pct = None
    predictor.reset()
    _dp_rate_buffer.clear()

    # Zustandsvariablen zurücksetzen
    with _state_lock:
        _state["cycle_active"]          = False
        _state["cycle_start_time"]      = None
        _state["cycle_dp_reached_time"] = None
        _state["awaiting_confirmation"] = False
        _state["anomaly_active"]        = False
        _state["anomaly_percent"]       = 0.0
        _state["analysis_active"]       = False
        _state["analysis_ready"]        = False

    db.insert_service_event("LERNZYKLEN_RESET", heta_code,
                            json.dumps({"timestamp": time.time()}))
    logger.info("Lernzyklen für %s zurückgesetzt.", heta_code)

    return jsonify({
        "success": True,
        "message": f"Lernzyklen für {heta_code} wurden zurückgesetzt. "
                   f"Das System startet die Lernphase neu.",
    })


def _do_confirm_filter_change():
    """Führt die Filterwechsel-Bestätigung durch (REST-API und Display-Controller)."""
    with _state_lock:
        heta_code = _state["heta_code"]
        cycle_was_active = _state["cycle_active"]

    if cycle_was_active and learning.active_cycle:
        with _state_lock:
            current_r        = _state["r_eff"]
            current_dp       = _state["dp_bar"]
            dp_reached_time  = _state.get("cycle_dp_reached_time")
        learning.end_cycle(confirmed=True,
                           end_r_eff=current_r,
                           end_dp=current_dp,
                           end_time=dp_reached_time)

    global _smoothed_health_pct
    _smoothed_health_pct = None
    predictor.reset()
    _dp_rate_buffer.clear()
    reset_simulation()

    with _state_lock:
        _state["awaiting_confirmation"]  = False
        _state["cycle_active"]           = False
        _state["cycle_start_time"]       = None
        _state["cycle_dp_reached_time"]  = None
        _state["anomaly_active"]         = False
        _state["anomaly_percent"]        = 0.0

    db.insert_service_event("FILTERWECHSEL_BESTAETIGT", heta_code,
                            json.dumps({"timestamp": time.time()}))
    logger.info("Filterwechsel bestätigt. Neuer Zyklus beginnt.")


@app.route("/api/diagnostics", methods=["GET"])
def api_diagnostics():
    """Selbstcheck aller Komponenten basierend auf tatsächlichem Laufzeitzustand."""
    import platform

    checks = []

    # ── System ──────────────────────────────────────────────────────────────
    checks.append({
        "id": "system",
        "label": "System",
        "status": "ok",
        "detail": (f"Python {sys.version.split()[0]}  ·  "
                   f"{platform.machine()}  ·  "
                   f"{platform.system()} {platform.release()}"),
        "hints": [],
    })

    # ── Software-Version ────────────────────────────────────────────────────
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

    # ── Betriebsmodus ───────────────────────────────────────────────────────
    with _state_lock:
        sim_mode    = _state["simulation_mode"]
        hw_avail    = _state.get("sensor_hw_available", False)
        meas_running = _state["running"]
        awaiting     = _state["awaiting_confirmation"]
        cycle_active = _state["cycle_active"]
        sensor_fault = _state.get("sensor_fault", False)
        sensor_err   = _state.get("sensor_error", False)
        heta_code    = _state.get("heta_code", "")

    if sim_mode:
        mode_status = "info"
        mode_detail = "Simulationsmodus aktiv"
        if hw_avail:
            mode_detail += " (Hardware erkannt – Echtbetrieb verfügbar)"
        else:
            mode_detail += " – kein AnoPi Shield gefunden"
        mode_hints = (["Für Echtbetrieb: simulation_mode=false in den Einstellungen"]
                      if hw_avail else [])
    else:
        if sensor_fault:
            mode_status = "error"
            mode_detail = f"Hardware-Modus – Sensorfehler: {_state.get('sensor_fault_message', '')}"
            mode_hints  = ["Verkabelung aller 4 Kanäle prüfen", "Sensorneuprüfung über den Button starten"]
        elif sensor_err:
            mode_status = "warning"
            mode_detail = "Hardware-Modus – Sensorlesefehler (Messung läuft)"
            mode_hints  = ["Sensor-Kabelverbindungen prüfen"]
        else:
            mode_status = "ok"
            mode_detail = "Hardware-Modus – AnoPi Shield aktiv"
            mode_hints  = []
    checks.append({
        "id": "mode",
        "label": "Betriebsmodus",
        "status": mode_status,
        "detail": mode_detail,
        "hints": mode_hints,
    })

    # ── Messzyklus ──────────────────────────────────────────────────────────
    if not meas_running and not awaiting:
        cyc_status = "warning"
        cyc_detail = "Messung gestoppt"
        cyc_hints  = ["Messung über den Start-Button starten"]
    elif awaiting:
        cyc_status = "warning"
        cyc_detail = "Messung pausiert – Filterwechsel bestätigen"
        cyc_hints  = ["Filterwechsel durchführen und bestätigen um fortzufahren"]
    elif cycle_active:
        cyc_status = "ok"
        cyc_detail = f"Messung läuft – Zyklus aktiv{(' · ' + heta_code) if heta_code else ''}"
        cyc_hints  = []
    else:
        cyc_status = "ok"
        cyc_detail = "Messung läuft – warte auf Zyklusstart (dp unterhalb Startschwelle)"
        cyc_hints  = []
    checks.append({
        "id": "measurement",
        "label": "Messzyklus",
        "status": cyc_status,
        "detail": cyc_detail,
        "hints": cyc_hints,
    })

    # ── Datenbank ─────────────────────────────────────────────────────────────
    try:
        with db._conn() as _dbcon:
            meas_count  = _dbcon.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
            cycle_count = _dbcon.execute("SELECT COUNT(*) FROM filter_cycles").fetchone()[0]
        checks.append({
            "id": "database",
            "label": "Datenbank (SQLite)",
            "status": "ok",
            "detail": (f"{meas_count} Messwerte  ·  {cycle_count} Filterzyklen  ·  "
                       f"Pfad: {db.db_path}"),
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

    # ── MQTT ────────────────────────────────────────────────────────────────
    mqtt_enabled = settings.get("mqtt_enabled", False)
    if not mqtt_enabled:
        checks.append({
            "id": "mqtt",
            "label": "MQTT",
            "status": "info",
            "detail": "MQTT deaktiviert (mqtt_enabled=false in den Einstellungen)",
            "hints": [],
        })
    elif _mqtt is None:
        checks.append({
            "id": "mqtt",
            "label": "MQTT",
            "status": "error",
            "detail": "MQTT-Client konnte nicht initialisiert werden",
            "hints": [
                "pip install paho-mqtt",
                f"Broker-Adresse prüfen: {settings.get('mqtt_broker','localhost')}:{settings.get('mqtt_port',1883)}",
            ],
        })
    elif _mqtt.is_connected:
        checks.append({
            "id": "mqtt",
            "label": "MQTT",
            "status": "ok",
            "detail": (f"Verbunden mit {settings.get('mqtt_broker','localhost')}:"
                       f"{settings.get('mqtt_port',1883)}  ·  "
                       f"Client-ID: {settings.get('mqtt_client_id','heta_monitor')}"),
            "hints": [],
        })
    else:
        checks.append({
            "id": "mqtt",
            "label": "MQTT",
            "status": "warning",
            "detail": (f"Nicht verbunden mit "
                       f"{settings.get('mqtt_broker','localhost')}:{settings.get('mqtt_port',1883)}"),
            "hints": [
                "MQTT-Broker erreichbar?  ping " + settings.get("mqtt_broker", "localhost"),
                "Broker-Port und Zugangsdaten in den Einstellungen prüfen",
            ],
        })

    # ── OLED-Display ─────────────────────────────────────────────────────────
    if not settings.get("display_enabled", True):
        checks.append({
            "id": "display",
            "label": "OLED-Display (SSD1309)",
            "status": "info",
            "detail": "Display deaktiviert (display_enabled=false in den Einstellungen)",
            "hints": [],
        })
    elif _display is None:
        checks.append({
            "id": "display",
            "label": "OLED-Display (SSD1309)",
            "status": "error",
            "detail": "Display-Modul konnte beim Start nicht geladen werden",
            "hints": [
                "pip install luma.oled",
                "Logs prüfen: journalctl -u heta-monitor | grep -i display",
            ],
        })
    elif _display.is_simulated:
        use_spi = settings.get("display_use_spi", True)
        if use_spi:
            spi_port   = settings.get("display_spi_port", 0)
            spi_device = settings.get("display_spi_device", 0)
            dc  = settings.get("display_gpio_dc", 25)
            rst = settings.get("display_gpio_rst", 27)
            hw_hints = [
                f"SPI-Verbindung: DC→GPIO{dc}, RST→GPIO{rst}, DIN→GPIO10, CLK→GPIO11, CS→GPIO8",
                f"SPI-Bus prüfen: ls /dev/spidev{spi_port}.{spi_device}",
                "SPI aktivieren: sudo raspi-config → Interface Options → SPI",
                "pip install luma.oled",
            ]
        else:
            addr = settings.get("display_i2c_address", 60)
            hw_hints = [
                f"I2C-Adresse: 0x{addr:02X}  ·  I2C-Bus prüfen: ls /dev/i2c*",
                "I2C aktivieren: sudo raspi-config → Interface Options → I2C",
                "i2c-Gerät scannen: sudo i2cdetect -y 1",
            ]
        checks.append({
            "id": "display",
            "label": "OLED-Display (SSD1309)",
            "status": "warning",
            "detail": "Kein Hardware-Display erkannt – läuft im Simulationsmodus (kein Ausgabegerät)",
            "hints": hw_hints,
        })
    else:
        try:
            _display.show_network(_get_local_ip(), settings.get("webserver_port", 8080), "DIAGNOSE")
            checks.append({
                "id": "display",
                "label": "OLED-Display (SSD1309)",
                "status": "ok",
                "detail": "Display aktiv – Testbild erfolgreich gerendert",
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

    # ── SPI-Bus (nur relevant wenn Display SPI nutzt oder Hardware-Modus aktiv)
    display_uses_spi = settings.get("display_enabled", True) and settings.get("display_use_spi", True)
    if display_uses_spi or not sim_mode:
        spi_port   = settings.get("display_spi_port", 0)
        spi_device = settings.get("display_spi_device", 0)
        spi_dev    = f"/dev/spidev{spi_port}.{spi_device}"
        spi_exists = os.path.exists(spi_dev)
        checks.append({
            "id": "spi",
            "label": f"SPI-Bus ({spi_dev})",
            "status": "ok" if spi_exists else "error",
            "detail": f"{spi_dev} {'gefunden' if spi_exists else 'nicht gefunden – SPI nicht aktiviert'}",
            "hints": [] if spi_exists else [
                "SPI aktivieren: sudo raspi-config → Interface Options → SPI",
                "Neustart: sudo reboot",
                "Prüfen: ls /dev/spidev*",
            ],
        })

    # ── I2C-Bus (nur relevant wenn Display I2C nutzt) ────────────────────────
    display_uses_i2c = settings.get("display_enabled", True) and not settings.get("display_use_spi", True)
    if display_uses_i2c:
        i2c_dev    = "/dev/i2c-1"
        i2c_exists = os.path.exists(i2c_dev)
        checks.append({
            "id": "i2c_bus",
            "label": f"I2C-Bus ({i2c_dev})",
            "status": "ok" if i2c_exists else "error",
            "detail": f"{i2c_dev} {'gefunden' if i2c_exists else 'nicht gefunden – I2C nicht aktiviert'}",
            "hints": [] if i2c_exists else [
                "I2C aktivieren: sudo raspi-config → Interface Options → I2C",
                "Neustart: sudo reboot",
                "Prüfen: ls /dev/i2c*",
            ],
        })

    # ── ANO-Encoder ──────────────────────────────────────────────────────────
    if not settings.get("navigation_enabled", True):
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (GPIO)",
            "status": "info",
            "detail": "Encoder deaktiviert (navigation_enabled=false in den Einstellungen)",
            "hints": [],
        })
    elif _navigation is None:
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (GPIO)",
            "status": "error",
            "detail": "Encoder-Modul konnte beim Start nicht geladen werden",
            "hints": [
                "pip install gpiozero lgpio",
                "Logs prüfen: journalctl -u heta-monitor | grep -i encoder",
            ],
        })
    elif _navigation.is_simulated:
        enc_pins = {
            "ENCA": settings.get("encoder_pin_enca", 16),
            "ENCB": settings.get("encoder_pin_encb", 20),
            "SW1":  settings.get("encoder_pin_sw1", 21),
            "SW2":  settings.get("encoder_pin_sw2", 12),
            "SW3":  settings.get("encoder_pin_sw3", 13),
            "SW4":  settings.get("encoder_pin_sw4", 19),
            "SW5":  settings.get("encoder_pin_sw5", 26),
        }
        pin_summary = "  ·  ".join(f"{n}=GPIO{p}" for n, p in enc_pins.items())
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (GPIO)",
            "status": "warning",
            "detail": f"Kein Hardware-Encoder erkannt – läuft im Simulationsmodus  ·  {pin_summary}",
            "hints": [
                "Encoder anschließen: ENCA, ENCB, SW1–SW5, COMA→GND, COMB→GND",
                "GPIO-Pins in den Einstellungen prüfen",
                "pip install gpiozero lgpio",
            ],
        })
    else:
        steps = _navigation.get_encoder_steps()
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (GPIO)",
            "status": "ok",
            "detail": f"Encoder aktiv – Schrittposition: {steps}",
            "hints": [],
        })

    # ── Sensoren / AnoPi Shield ───────────────────────────────────────────────
    if sim_mode:
        checks.append({
            "id": "sensors",
            "label": "Sensoren (4–20 mA / AnoPi Shield)",
            "status": "info",
            "detail": (f"Simulationsmodus – Sensor-Hardware nicht geprüft"
                       + ("  ·  AnoPi Shield erreichbar" if hw_avail else "  ·  kein AnoPi Shield erkannt")),
            "hints": (["Für Echtbetrieb: simulation_mode=false in den Einstellungen"]
                      if hw_avail else []),
        })
    elif not hw_avail:
        checks.append({
            "id": "sensors",
            "label": "Sensoren (4–20 mA / AnoPi Shield)",
            "status": "error",
            "detail": "AnoPi Shield nicht erreichbar – SPI-Kommunikation fehlgeschlagen",
            "hints": [
                "AnoPi Shield korrekt aufgesteckt?",
                "SPI-Bus aktiv? (ls /dev/spidev*)",
                "pip install spidev",
            ],
        })
    else:
        try:
            import spidev  # type: ignore
            _spi = spidev.SpiDev()
            _spi.open(0, 0)
            _spi.max_speed_hz = 1_350_000
            raw = _spi.xfer2([1, (8 + 0) << 4, 0])
            _spi.close()
            adc_raw = ((raw[1] & 3) << 8) + raw[2]
            checks.append({
                "id": "sensors",
                "label": "Sensoren (4–20 mA / AnoPi Shield)",
                "status": "ok",
                "detail": f"AnoPi Shield antwortet – ADC Kanal 0 Rohwert: {adc_raw} / 4095",
                "hints": [],
            })
        except ImportError:
            checks.append({
                "id": "sensors",
                "label": "Sensoren (4–20 mA / AnoPi Shield)",
                "status": "error",
                "detail": "spidev-Bibliothek nicht installiert",
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
                    "SPI-Gerätekonflikte? (Display und Shield auf unterschiedlichen CE)",
                ],
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


@app.route("/api/sensor/recheck", methods=["POST"])
def api_sensor_recheck():
    """
    Bediener hat bestätigt, alle Sensoren angeschlossen zu haben.
    System prüft alle 4 Kanäle und startet die Messung neu wenn alles OK ist.
    """
    with _state_lock:
        sim_mode = _state["simulation_mode"]

    if sim_mode:
        return jsonify({"success": False,
                        "message": "Sensorprüfung nur im Hardwaremodus verfügbar."})

    result = check_hardware_sensors()

    if result["all_ok"]:
        with _state_lock:
            _state["sensor_fault"] = False
            _state["sensor_fault_channels"] = []
            _state["sensor_fault_message"] = ""
            _state["sensor_error"] = False
        _start_measurement_thread()
        logger.info("Sensorprüfung erfolgreich – alle Kanäle lesbar, Messung neu gestartet.")
        return jsonify({"success": True,
                        "message": "Alle Sensoren erkannt. Messung wird neu gestartet."})

    msg = f"Sensorfehler: {', '.join(result['failed_names'])} weiterhin nicht lesbar."
    with _state_lock:
        _state["sensor_fault_channels"] = result["failed_channels"]
        _state["sensor_fault_message"] = msg
    logger.error("Sensorprüfung fehlgeschlagen: Kanal(e) %s.", result["failed_channels"])
    return jsonify({"success": False,
                    "message": msg,
                    "failed_channels": result["failed_channels"],
                    "failed_names": result["failed_names"]})


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

    # Simulationsparameter vor der Übernahme merken um Clogging-Reset zu steuern
    _SIM_PARAMS = {"dp_clean_bar", "dp_limit_bar", "flow_max_l_min",
                   "sim_p1_base_bar", "sim_q_base_l_min", "sim_t_base_c"}
    sim_params_changed = any(
        k in _SIM_PARAMS and data.get(k) != settings.get(k)
        for k in data
    )

    for k, v in data.items():
        if k in settings and k not in protected:
            settings[k] = v

    # Simulator aktualisieren; Clogging nur zurücksetzen wenn physikalisch
    # relevante Simulationsparameter geändert wurden.
    update_simulation_params(
        dp_clean=settings["dp_clean_bar"],
        dp_limit=settings["dp_limit_bar"],
        flow_max=settings["flow_max_l_min"],
        cycle_seconds=settings.get("sim_cycle_seconds", 300),
        p1_base=settings.get("sim_p1_base_bar", 4.0),
        q_base=settings.get("sim_q_base_l_min", 145.0),
        t_base=settings.get("sim_t_base_c", 25.0),
        reset_clogging=sim_params_changed,
    )
    predictor.update_limits(settings["dp_limit_bar"], settings["dp_clean_bar"])
    learning.tolerance_reff_pct = settings.get("tolerance_reff_pct", 0.25)
    save_settings(settings)

    with _state_lock:
        _state["simulation_mode"] = settings["simulation_mode"]

    # Lerndaten zurücksetzen wenn nötig
    if learning_reset_needed:
        global _smoothed_health_pct
        _smoothed_health_pct = None
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
    token = request.headers.get("X-Auth-Token", "") or (request.get_json(force=True, silent=True) or {}).get("token", "")
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
    global _smoothed_health_pct
    _smoothed_health_pct = None
    predictor.reset()
    reset_simulation()
    learning.tolerance_reff_pct = settings.get("tolerance_reff_pct", 0.25)

    with _state_lock:
        _state["heta_code"]        = ""
        _state["activation_status"] = False
        _state["cycle_active"]     = False
        _state["cycle_start_time"] = None
        _state["anomaly_active"]   = False
        _state["anomaly_percent"]  = 0.0
        _state["filter_status"]    = "OK"
        _state["simulation_mode"]  = settings.get("simulation_mode", True)

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
        "tolerance_dp_pct", "tolerance_reff_pct",
        "tolerance_flow_pct", "tolerance_temp_c",
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
        cycle_seconds=settings.get("sim_cycle_seconds", 300),
        p1_base=settings.get("sim_p1_base_bar", 4.0),
        q_base=settings.get("sim_q_base_l_min", 145.0),
        t_base=settings.get("sim_t_base_c", 25.0),
    )
    predictor.update_limits(settings["dp_limit_bar"], settings["dp_clean_bar"])
    learning.tolerance_reff_pct = settings.get("tolerance_reff_pct", 0.25)

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
    """Startet den Simulationsmodus und den Messzyklus. Setzt immer am Zyklusanfang an."""
    global _smoothed_health_pct
    learning.abort_cycle()
    reset_simulation()
    predictor.reset()
    _smoothed_health_pct = None
    with _state_lock:
        _state["simulation_mode"]       = True
        _state["sensor_fault"]          = False
        _state["sensor_fault_channels"] = []
        _state["sensor_fault_message"]  = ""
        _state["sensor_error"]          = False
        _state["cycle_active"]           = False
        _state["cycle_start_time"]       = None
        _state["cycle_dp_reached_time"]  = None
        _state["awaiting_confirmation"]  = False
        _state["anomaly_active"]         = False
        _state["anomaly_percent"]        = 0.0
    if not _state["running"]:
        _start_measurement_thread()
    return jsonify({"success": True, "message": "Simulation gestartet."})


@app.route("/api/simulation/stop", methods=["POST"])
def api_simulation_stop():
    """Stoppt den Messzyklus und verwirft einen eventuell laufenden Zyklus."""
    global _smoothed_health_pct
    clear_simulation_rates()
    learning.abort_cycle()
    with _state_lock:
        _state["running"]                = False
        _state["sim_rates_active"]       = False
        _state["cycle_active"]           = False
        _state["cycle_start_time"]       = None
        _state["cycle_dp_reached_time"]  = None
        _state["awaiting_confirmation"]  = False
        _state["anomaly_active"]         = False
        _state["anomaly_percent"]        = 0.0
    _smoothed_health_pct = None
    return jsonify({"success": True, "message": "Simulation gestoppt."})


@app.route("/api/simulation/reset", methods=["POST"])
def api_simulation_reset():
    """Setzt Simulation und Prognose zurück."""
    global _smoothed_health_pct
    clear_simulation_rates()
    full_reset_simulation()
    predictor.reset()
    _smoothed_health_pct = None
    with _state_lock:
        _state["cycle_active"]           = False
        _state["sim_rates_active"]       = False
        _state["sim_scenario"]           = "normal"
        _state["sim_dirt_rate_pct"]      = 100.0
        _state["sim_p1_trend_pct"]       = 0.0
        _state["sim_flow_drop_pct"]      = 75.0
        _state["sim_temp_trend"]         = 0.0
        _state["sim_dp_deviation_pct"]   = 0.0
        _state["sim_flow_deviation_pct"] = 0.0
        _state["sim_temp_deviation"]     = 0.0
    return jsonify({"success": True, "message": "System zurückgesetzt."})


@app.route("/api/simulation/quick-learn", methods=["POST"])
def api_simulation_quick_learn():
    """Simuliert die erforderlichen Lernzyklen für den aktuellen HETA-Code."""
    with _state_lock:
        sim_mode = _state["simulation_mode"]
        heta_code = _state["heta_code"]
        heta_activated = _state["heta_activated"]

    if not sim_mode:
        return jsonify({"success": False, "message": "Nur im Simulationsmodus verfügbar."})
    if not heta_code or not heta_activated:
        return jsonify({"success": False, "message": "Kein aktiver HETA-Code. Bitte zuerst HETA-Code aktivieren."})
    if learning.is_profile_valid(heta_code):
        return jsonify({"success": False, "message": "Profil ist bereits valide – Lernphase abgeschlossen."})

    dp_clean          = settings.get("dp_clean_bar", 0.2)
    dp_limit          = settings.get("dp_limit_bar", 2.5)
    flow_max          = settings.get("flow_max_l_min", 150.0)
    sampling_interval = settings.get("sampling_interval_seconds", 1)
    cycle_steps       = get_simulation_cycle_steps()        # Schritte pro Zyklus
    cycle_secs        = float(cycle_steps) * sampling_interval
    required_cycles   = settings.get("required_cycles_for_profile", 3)

    # Aktuelle Szenario-Parameter für konsistente Simulation
    sc = get_simulation_scenario_params()
    sim_p1_base      = sc.get("p1_base",              4.0)
    sim_q_base       = sc.get("q_base",               145.0)
    sim_t_base       = sc.get("t_base",               25.0)
    sim_p1_trend     = sc.get("p1_trend_factor",      0.0)
    sim_flow_drop    = sc.get("flow_drop_factor",     0.75)
    sim_temp_trend   = sc.get("temp_trend_per_cycle", 0.0)
    q_min_sim        = max(1.0, sim_q_base * 0.10)

    # ── Physikalische Werte identisch mit FilterSimulator.get_readings() ────
    def _sim_step(s: int) -> dict:
        clogging = min(s / max(cycle_steps, 1), 1.0)
        p1  = round(sim_p1_base * (1.0 + sim_p1_trend * clogging), 4)
        p1  = max(0.1, p1)
        dp  = dp_clean + (dp_limit - dp_clean) * clogging ** 1.8
        dp  = round(max(dp_clean, min(dp, dp_limit)), 5)
        p2  = round(max(0.0, p1 - dp), 4)
        fl  = round(max(q_min_sim, sim_q_base * (1.0 - sim_flow_drop * clogging ** 1.5)), 2)
        tmp = round(sim_t_base + sim_temp_trend * clogging, 1)
        return {"dp": dp, "p1": p1, "p2": p2, "flow": fl, "temp": tmp,
                "r_eff": dp / max(fl, 0.1)}

    start_vals = _sim_step(0)
    end_vals   = _sim_step(cycle_steps)

    # Analytisch: ∫₀¹ (1 - flow_drop * c^1.5) dc = 1 - flow_drop * 2/5 = 1 - 0.4*flow_drop
    avg_flow = round(sim_q_base * (1.0 - 0.4 * sim_flow_drop), 2)
    avg_temp = round(sim_t_base + sim_temp_trend * 0.5, 1)
    loading_rate = round((end_vals["dp"] - dp_clean) / max(cycle_secs, 1.0), 6)

    existing = db.count_confirmed_cycles(heta_code)
    needed   = max(0, required_cycles - existing)
    now      = time.time()

    for i in range(needed):
        t_start  = now - (needed - i) * (cycle_secs + 60)
        cycle_id = db.insert_cycle({
            "heta_code":              heta_code,
            "start_time":             t_start,
            "end_time":               t_start + cycle_secs,
            "duration_seconds":       round(cycle_secs, 1),
            "start_r_eff":            round(start_vals["r_eff"], 6),
            "end_r_eff":              round(end_vals["r_eff"],   6),
            "start_dp":               round(dp_clean, 3),
            "end_dp":                 round(end_vals["dp"], 3),
            "average_flow":           avg_flow,
            "average_temperature":    avg_temp,
            "loading_rate":           loading_rate,
            "confirmed_filter_change": 1,
        })

        # Zeitreihe exakt nach Simulator-Formel generieren.
        # Stride damit maximal ~100 Samples pro Zyklus gespeichert werden.
        stride  = max(1, cycle_steps // 100)
        samples = []
        for s in range(0, cycle_steps + 1, stride):
            sv = _sim_step(s)
            t  = t_start + s * sampling_interval
            samples.append({
                "cycle_id":             cycle_id,
                "heta_code":            heta_code,
                "timestamp":            t,
                "cycle_second":         round(s * sampling_interval, 1),
                "p1_bar":               sv["p1"],
                "p2_bar":               sv["p2"],
                "dp_bar":               sv["dp"],
                "flow_l_min":           round(sv["flow"], 2),
                "temp_c":               round(sv["temp"], 1),
                "r_eff":                round(sv["r_eff"], 6),
                "filter_health_percent": None,
                "remaining_seconds":    None,
            })
        db.insert_cycle_samples(samples)

    learning._update_profile(heta_code)
    remaining_secs = (dp_limit - dp_clean) / max(loading_rate, 1e-9)
    predictor.update_limits(dp_limit, dp_clean)
    predictor.seed(remaining_secs)

    with _state_lock:
        _state["learned_cycles"]  = required_cycles
        _state["profile_status"]  = "VALIDIERT"
        _state["show_filter_health"] = True

    # Simulation auf Schritt 0 zurücksetzen damit der nächste Zyklus
    # mit sauberem Startwert beginnt (kein dp-Offset aus alten Schritten).
    global _smoothed_health_pct
    _smoothed_health_pct = None
    reset_simulation()
    learning._active_cycle = None   # laufenden Zyklus verwerfen (Daten vor Quick-Learn)
    with _state_lock:
        _state["cycle_active"]     = False   # Messzyklus neu starten
        _state["cycle_start_time"] = None

    db.insert_service_event("SIM_SCHNELLLERN", heta_code,
                            json.dumps({"simulated_cycles": needed, "loading_rate": loading_rate}))
    logger.info("Schnell-Lernphase: %d Zyklen für %s simuliert (je %d Samples).",
                needed, heta_code, len(samples) if needed else 0)
    return jsonify({
        "success": True,
        "message": f"{needed} Lernzyklus/-zyklen für «{heta_code}» simuliert. Profil ist jetzt valide.",
        "loading_rate": loading_rate,
    })


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
            _state["sim_rates_active"]       = False
            _state["sim_scenario"]           = "normal"
            _state["sim_dirt_rate_pct"]      = 100.0
            _state["sim_p1_trend_pct"]       = 0.0
            _state["sim_flow_drop_pct"]      = 75.0
            _state["sim_temp_trend"]         = 0.0
            _state["sim_dp_deviation_pct"]   = 0.0
            _state["sim_flow_deviation_pct"] = 0.0
            _state["sim_temp_deviation"]     = 0.0
        return jsonify({"success": True, "active": False})

    dirt_rate_pct  = max(10.0,  min(float(data.get("dirt_rate_pct",  100.0)), 400.0))
    p1_trend_pct   = max(-20.0, min(float(data.get("p1_trend_pct",   0.0)),   20.0))
    flow_drop_pct  = max(10.0,  min(float(data.get("flow_drop_pct",  75.0)),  99.0))
    temp_trend     = max(-5.0,  min(float(data.get("temp_trend",     0.0)),   5.0))
    scenario       = str(data.get("scenario", "custom"))
    cycle_secs     = max(10.0, min(float(data.get("cycle_seconds", settings.get("sim_cycle_seconds", 300))), 86400.0))

    settings["sim_cycle_seconds"] = round(cycle_secs)
    save_settings(settings)

    update_simulation_params(
        dp_clean=settings["dp_clean_bar"],
        dp_limit=settings["dp_limit_bar"],
        flow_max=settings["flow_max_l_min"],
        cycle_seconds=cycle_secs,
        p1_base=settings.get("sim_p1_base_bar", 4.0),
        q_base=settings.get("sim_q_base_l_min", 145.0),
        t_base=settings.get("sim_t_base_c", 25.0),
        reset_clogging=False,
    )

    set_simulation_scenario_params(
        dirt_rate_factor    = dirt_rate_pct / 100.0,
        p1_trend_factor     = p1_trend_pct  / 100.0,
        flow_drop_factor    = flow_drop_pct / 100.0,
        temp_trend_per_cycle = temp_trend,
    )

    dp_dev_pct   = round(dirt_rate_pct - 100.0, 1)
    flow_dev_pct = round((flow_drop_pct / 75.0 - 1.0) * 100.0, 1)
    temp_dev     = round(temp_trend, 1)

    with _state_lock:
        _state["sim_cycle_seconds"]      = round(cycle_secs)
        _state["sim_rates_active"]       = True
        _state["sim_scenario"]           = scenario
        _state["sim_dirt_rate_pct"]      = round(dirt_rate_pct, 1)
        _state["sim_p1_trend_pct"]       = round(p1_trend_pct,  1)
        _state["sim_flow_drop_pct"]      = round(flow_drop_pct, 1)
        _state["sim_temp_trend"]         = round(temp_trend,     1)
        _state["sim_dp_deviation_pct"]   = dp_dev_pct
        _state["sim_flow_deviation_pct"] = flow_dev_pct
        _state["sim_temp_deviation"]     = temp_dev

    return jsonify({
        "success": True, "active": True,
        "scenario": scenario,
        "dirt_rate_pct": dirt_rate_pct,
        "p1_trend_pct": p1_trend_pct,
        "flow_drop_pct": flow_drop_pct,
        "temp_trend": temp_trend,
    })


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
    rec = generate_service_recommendation(fs, pred_status,
                                          health_percent=current["filter_health_percent"])
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


@app.route("/api/reference-curve")
def api_reference_curve():
    """Gibt die zeitbasierte Referenzkurve für einen HETA-Code zurück."""
    heta_code = request.args.get("heta_code", _state.get("heta_code", ""))
    if not heta_code:
        return jsonify(None)
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
    return jsonify({
        "heta_code":                  heta_code,
        "curve":                      curve,
        "reference_duration_seconds": profile.get("reference_duration_seconds", 0),
        "reference_r_eff_start":      profile.get("reference_r_eff_start") or profile.get("reference_r_eff") or 0.0,
        "reference_dp_clean":         profile.get("reference_dp_clean") or 0.0,
        "cycles_count":               profile.get("cycles_count", 0),
        "profile_valid":              bool(profile.get("profile_valid")),
        "tolerance_dp_pct":   settings.get("tolerance_dp_pct",   0.25),
        "tolerance_reff_pct": settings.get("tolerance_reff_pct", 0.25),
        "tolerance_flow_pct": settings.get("tolerance_flow_pct", 0.25),
        "tolerance_temp_c":   settings.get("tolerance_temp_c",   10.0),
    })


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
        return jsonify({
            "heta_code": heta_code,
            "start_time": cycle.start_time,
            "elapsed_seconds": 0.0,
            "ref_duration_seconds": ref_duration,
            "samples": [],
        })
    step = max(1, n // 300)
    samples = []
    for i in range(0, n, step):
        t_off = cycle.timestamps[i] - cycle.start_time
        t_pct = (t_off / ref_duration * 100.0) if ref_duration > 0 else None
        samples.append({
            "cycle_second": round(t_off, 1),
            "t_pct": round(t_pct, 2) if t_pct is not None else None,
            "dp_bar": round(cycle.dp_samples[i], 4),
            "r_eff": round(cycle.r_eff_samples[i], 5) if i < len(cycle.r_eff_samples) else None,
        })
    return jsonify({
        "heta_code": heta_code,
        "start_time": cycle.start_time,
        "elapsed_seconds": round(time.time() - cycle.start_time, 1),
        "ref_duration_seconds": ref_duration,
        "samples": samples,
    })


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
            time.sleep(2.0)
            logger.info("Neustart nach Git-Update – versuche systemctl…")

            # Versuch 1: systemd (Produktion – Pi läuft als Service)
            try:
                r = subprocess.run(
                    ["sudo", "systemctl", "restart", "heta-monitor"],
                    timeout=10, capture_output=True,
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
            logger.info(
                "Fallback: Starte neuen Prozess und beende mich – "
                "Port wird nach ~3 s wieder erreichbar sein."
            )
            try:
                restart_cmd = (
                    f"sleep 3 && exec {sys.executable} "
                    f"{os.path.join(_BASE_DIR, 'backend', 'app.py')}"
                )
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

    logger.info("=" * 60)
    logger.info("HETA Smart Filter Monitoring – Start auf %s:%d", host, port)
    sim = settings.get("simulation_mode", True)
    if sim:
        logger.info("Betriebsart : Simulationsmodus")
    elif _hw_available:
        logger.info("Betriebsart : Realbetrieb – AnoPi Shield erkannt")
    else:
        logger.warning("Betriebsart : Realbetrieb konfiguriert, "
                       "aber AnoPi Shield NICHT erkannt – Fallback zur Simulation aktiv!")
    logger.info("Onboarding  : %s", "abgeschlossen" if settings.get("onboarding_complete") else "ausstehend")
    logger.info("=" * 60)

    # Messzyklus nur starten wenn Onboarding abgeschlossen
    if settings.get("onboarding_complete", False):
        _start_measurement_thread()
    else:
        logger.info("Onboarding ausstehend – Messzyklus wartet.")

    app.run(host=host, port=port, debug=False, threaded=True)
