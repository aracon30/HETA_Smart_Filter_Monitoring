"""
Konfigurationsmodul – lädt settings.json und stellt alle Parameter bereit.
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

# Pfad zur Konfigurationsdatei relativ zum Projektverzeichnis
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_BASE_DIR, "config", "settings.json")

# Standardwerte falls settings.json nicht vorhanden
_DEFAULTS = {
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
    "anomaly_threshold_percent": 25,
    "clean_resistance_tolerance": 0.25,
    "required_cycles_for_profile": 3,
    "smoothing_factor": 0.15,
    "max_increase_percent_per_update": 2,
    "max_decrease_percent_per_update": 8,
    "min_slope": 0.001,
}


def load_settings() -> dict:
    """Lädt die Konfiguration aus settings.json, füllt fehlende Felder mit Standardwerten."""
    settings = _DEFAULTS.copy()
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        settings.update(loaded)
        logger.info("Konfiguration aus %s geladen.", _CONFIG_PATH)
    except FileNotFoundError:
        logger.warning("settings.json nicht gefunden, verwende Standardwerte.")
    except json.JSONDecodeError as e:
        logger.error("Fehler beim Parsen von settings.json: %s – Standardwerte aktiv.", e)
    return settings


def save_settings(settings: dict) -> bool:
    """Speichert die Konfiguration in settings.json."""
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        logger.info("Konfiguration in %s gespeichert.", _CONFIG_PATH)
        return True
    except OSError as e:
        logger.error("Fehler beim Speichern der Konfiguration: %s", e)
        return False


def get_abs_path(relative_path: str) -> str:
    """Gibt den absoluten Pfad relativ zum Projektverzeichnis zurück."""
    return os.path.join(_BASE_DIR, relative_path)


# Modul-globale Instanz – einmalig beim Import laden
settings = load_settings()
