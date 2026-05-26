"""
Konfigurationsmodul – lädt settings.json und stellt alle Parameter bereit.

Konfigurationsprioritäten (höhere Nummer = höhere Priorität):
  1. _DEFAULTS          (Fallback-Werte im Code)
  2. config/settings.json       (git-versionierte Standardwerte, nie lokal editieren)
  3. config/settings.local.json (lokale Übersteuerungen, gitignored, git-pull-sicher)

Alle Einstellungsänderungen (Onboarding, Einstellungsbereich) werden in
settings.local.json gespeichert – git pull überschreibt sie nie.
"""

import json
import os
import hashlib
import logging

logger = logging.getLogger(__name__)

_BASE_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH     = os.path.join(_BASE_DIR, "config", "settings.json")
_CONFIG_LOCAL_PATH = os.path.join(_BASE_DIR, "config", "settings.local.json")

# Standardwerte falls settings.json nicht vorhanden
_DEFAULTS = {
    "onboarding_complete": False,
    "settings_password_hash": "",
    "session_timeout_minutes": 30,
    "dp_limit_bar": 2.5,
    "dp_clean_bar": 0.2,
    "pressure_range_bar": 10,
    "temperature_min_c": -50,
    "temperature_max_c": 150,
    "flow_max_l_min": 150,
    "sampling_interval_seconds": 1,
    "simulation_mode": True,
    "mqtt_enabled": False,
    "webserver_port": 8080,
    "webserver_host": "0.0.0.0",
    "log_level": "INFO",
    "db_path": "data/heta_monitor.db",
    "export_path": "exports/",
    "log_path": "logs/",
    "tolerance_dp_pct":   0.25,
    "tolerance_reff_pct": 0.25,
    "tolerance_flow_pct": 0.25,
    "tolerance_temp_c":   10.0,
    "required_cycles_for_profile": 3,
    # Simulation – feste Basiswerte
    "sim_p1_base_bar":   4.0,
    "sim_q_base_l_min":  145.0,
    "sim_t_base_c":      25.0,
    "smoothing_factor": 0.15,
    "max_increase_percent_per_update": 2,
    "max_decrease_percent_per_update": 8,
    "min_slope": 0.001,
    # Zyklusstart-Verhalten (Durchflusserkennung)
    "operation_mode": "continuous",          # "continuous" | "batch"
    "flow_start_threshold_l_min": None,      # None = automatisch berechnet
    "flow_stability_seconds": None,          # None = automatisch (Standard: 10 s)
    "flow_pause_tolerance_seconds": None,    # None = automatisch (30/60 s)
    "flow_max_pause_days": 7,               # Zyklus-Abbruch nach X Tagen ohne Durchfluss
    # Auto-berechnete Schwellwerte (werden nach jedem Zyklus aktualisiert):
    "flow_start_threshold_auto": 0.0,
    "flow_stability_seconds_auto": 10,
    "flow_pause_tolerance_auto": 30,
    # MQTT
    "mqtt_broker": "localhost",
    "mqtt_port": 1883,
    "mqtt_client_id": "heta_monitor",
    # Modbus TCP
    "modbus_enabled": False,
    "modbus_host": "0.0.0.0",
    "modbus_port": 502,
    # OLED-Display (Waveshare 2.42" SSD1309)
    "display_enabled": True,
    "display_use_spi": True,
    "display_spi_port": 0,
    "display_spi_device": 0,
    "display_gpio_dc": 25,
    "display_gpio_rst": 27,
    "display_i2c_address": 60,
    # ANO-Rotary-Encoder (direktes GPIO, kein I2C)
    "navigation_enabled": True,
    "encoder_pin_enca": 16,
    "encoder_pin_encb": 20,
    "encoder_pin_sw1":  21,   # Mitte / OK
    "encoder_pin_sw2":  12,   # Unten
    "encoder_pin_sw3":  13,   # Rechts
    "encoder_pin_sw4":  19,   # Oben
    "encoder_pin_sw5":  26,   # Links
}


def load_settings() -> dict:
    """
    Lädt die Konfiguration in drei Schichten:
      1. _DEFAULTS (Code-Fallback)
      2. settings.json (git-versionierte Standardwerte)
      3. settings.local.json (lokale Übersteuerungen, gitignored)

    Automatische Migration: Falls settings.json bereits Benutzerdaten enthält
    (onboarding_complete=true oder Passwort-Hash gesetzt) und settings.local.json
    noch nicht existiert, wird settings.local.json automatisch erstellt – danach
    ist git pull ohne Konflikte möglich.
    """
    settings = _DEFAULTS.copy()

    # Schicht 2: git-versionierte Standardwerte
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        settings.update(loaded)
        logger.info("Basiskonfiguration aus %s geladen.", _CONFIG_PATH)
    except FileNotFoundError:
        logger.warning("settings.json nicht gefunden, verwende Standardwerte.")
    except json.JSONDecodeError as e:
        logger.error("Fehler beim Parsen von settings.json: %s – Standardwerte aktiv.", e)

    # Schicht 3: lokale Übersteuerungen (gitignored, git-pull-sicher)
    local_exists = False
    try:
        with open(_CONFIG_LOCAL_PATH, "r", encoding="utf-8") as f:
            local = json.load(f)
        settings.update(local)
        local_exists = True
        logger.info("Lokale Konfiguration aus %s geladen.", _CONFIG_LOCAL_PATH)
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as e:
        logger.error("Fehler beim Parsen von settings.local.json: %s – lokale Werte ignoriert.", e)

    # Automatische Migration: Benutzerdaten aus settings.json nach settings.local.json
    # übertragen, damit künftige git pulls keine Konflikte erzeugen.
    if not local_exists and (settings.get("onboarding_complete") or settings.get("settings_password_hash")):
        logger.info(
            "Migration: Erstelle %s aus bestehenden Benutzerdaten in settings.json. "
            "Danach kann settings.json mit 'git checkout config/settings.json' "
            "auf die Standardwerte zurückgesetzt werden.",
            _CONFIG_LOCAL_PATH,
        )
        save_settings(settings)

    return settings


def save_settings(settings: dict) -> bool:
    """
    Speichert die Konfiguration in settings.local.json (gitignored).
    settings.json bleibt unverändert – git pull erzeugt keine Konflikte.
    """
    try:
        os.makedirs(os.path.dirname(_CONFIG_LOCAL_PATH), exist_ok=True)
        with open(_CONFIG_LOCAL_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        logger.info("Konfiguration in %s gespeichert.", _CONFIG_LOCAL_PATH)
        return True
    except OSError as e:
        logger.error("Fehler beim Speichern der Konfiguration: %s", e)
        return False


def get_abs_path(relative_path: str) -> str:
    """Gibt den absoluten Pfad relativ zum Projektverzeichnis zurück."""
    return os.path.join(_BASE_DIR, relative_path)


def hash_password(password: str) -> str:
    """Gibt den SHA-256-Hash eines Passworts als Hex-String zurück."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    """Prüft ob ein Passwort mit dem gespeicherten Hash übereinstimmt."""
    if not stored_hash:
        return False
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored_hash


# Modul-globale Instanz – einmalig beim Import laden
settings = load_settings()
