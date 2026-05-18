"""
Berechnungsmodul – Differenzdruck, Filterwiderstand, Filterzustand und Statuslogik.
"""

import math
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Filterstatus-Konstanten
STATUS_OK = "OK"
STATUS_BEOBACHTEN = "BEOBACHTEN"
STATUS_WECHSEL = "WECHSEL"
STATUS_WECHSEL_BESTAETIGEN = "WECHSEL_BESTAETIGEN"
STATUS_WARNUNG = "WARNUNG"
STATUS_FEHLER = "FEHLER"


@dataclass
class FilterState:
    """Vollständiger berechneter Filterzustand für einen Messzeitpunkt."""
    p1_bar: float
    p2_bar: float
    dp_bar: float
    flow_l_min: float
    temperature_c: float
    r_eff: float
    filter_health_percent: float
    usage_ratio: float
    status: str
    sensor_error: bool = False
    anomaly_active: bool = False
    anomaly_percent: float = 0.0


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def calculate_differential_pressure(p1: float, p2: float) -> float:
    """Differenzdruck dp = max(0, p1 - p2)."""
    return max(0.0, p1 - p2)


def calculate_r_eff(dp_bar: float, flow_l_min: float,
                    min_flow: float = 0.1) -> float:
    """Effektiver Filterwiderstand r_eff = dp / max(Q, min_flow)."""
    return dp_bar / max(flow_l_min, min_flow)


def calculate_usage(dp_bar: float, dp_clean: float, dp_limit: float) -> float:
    """
    Beladungsgrad als Zahl zwischen 0 (sauber) und 1 (Grenzwert erreicht).
    Verhindert Division durch Null wenn dp_limit == dp_clean.
    """
    denom = dp_limit - dp_clean
    if denom <= 0:
        return 1.0
    return (dp_bar - dp_clean) / denom


def calculate_filter_health(usage: float) -> float:
    """Filterzustand in Prozent (100 = sauber, 0 = verbraucht)."""
    return 100.0 * (1.0 - clamp(usage, 0.0, 1.0))


def calculate_filter_health_from_r_eff(
    r_eff_current: float,
    r_eff_clean: float,
    r_eff_limit: float,
) -> tuple:
    """
    R_eff-basierter Beladungsgrad:
      Beladungsgrad = (R_eff_aktuell - R_eff_clean) / (R_eff_limit - R_eff_clean)

    Reagiert direkt auf Prozessänderungen (Δp-Anstieg, Durchflussabfall).
    Gibt (filter_health_percent, usage_ratio) zurück.
    """
    denom = r_eff_limit - r_eff_clean
    if denom <= 0 or r_eff_limit <= 0 or r_eff_current <= 0:
        return 100.0, 0.0
    usage = clamp((r_eff_current - r_eff_clean) / denom, 0.0, 1.0)
    return round(100.0 * (1.0 - usage), 1), round(usage, 4)


def determine_status(dp_bar: float, dp_limit: float,
                     awaiting_confirmation: bool = False,
                     sensor_error: bool = False,
                     anomaly_active: bool = False) -> str:
    """Bestimmt den Filterstatus anhand der Statuslogik."""
    if sensor_error:
        return STATUS_FEHLER
    if awaiting_confirmation:
        return STATUS_WECHSEL_BESTAETIGEN
    if dp_bar >= dp_limit:
        return STATUS_WECHSEL
    if anomaly_active:
        return STATUS_WARNUNG
    if dp_bar >= 0.75 * dp_limit:
        return STATUS_BEOBACHTEN
    return STATUS_OK


def calculate_filter_state(
    p1_bar: float,
    p2_bar: float,
    flow_l_min: float,
    temperature_c: float,
    dp_clean: float,
    dp_limit: float,
    awaiting_confirmation: bool = False,
    sensor_error: bool = False,
    anomaly_active: bool = False,
    anomaly_percent: float = 0.0,
    min_flow: float = 0.1,
    dp_override: Optional[float] = None,
) -> FilterState:
    """
    Führt alle Berechnungen für einen Messzeitpunkt durch und liefert
    ein vollständiges FilterState-Objekt.

    dp_override: wenn gesetzt, wird dieser Wert als dp verwendet statt p1-p2
    zu subtrahieren (verhindert Gleitkomma-Artefakte im Simulationsmodus).
    """
    if sensor_error or math.isnan(p1_bar) or math.isnan(p2_bar):
        return FilterState(
            p1_bar=p1_bar if not math.isnan(p1_bar) else 0.0,
            p2_bar=p2_bar if not math.isnan(p2_bar) else 0.0,
            dp_bar=0.0,
            flow_l_min=flow_l_min if not math.isnan(flow_l_min) else 0.0,
            temperature_c=temperature_c if not math.isnan(temperature_c) else 0.0,
            r_eff=0.0,
            filter_health_percent=0.0,
            usage_ratio=0.0,
            status=STATUS_FEHLER,
            sensor_error=True,
        )

    dp = dp_override if dp_override is not None else calculate_differential_pressure(p1_bar, p2_bar)
    r_eff = calculate_r_eff(dp, flow_l_min, min_flow)
    usage = calculate_usage(dp, dp_clean, dp_limit)
    health = calculate_filter_health(usage)
    status = determine_status(dp, dp_limit, awaiting_confirmation,
                               sensor_error, anomaly_active)

    return FilterState(
        p1_bar=round(p1_bar, 3),
        p2_bar=round(p2_bar, 3),
        dp_bar=round(dp, 3),
        flow_l_min=round(flow_l_min, 1),
        temperature_c=round(temperature_c, 1),
        r_eff=round(r_eff, 5),
        filter_health_percent=round(health, 1),
        usage_ratio=round(clamp(usage, 0.0, 1.0), 4),
        status=status,
        sensor_error=sensor_error,
        anomaly_active=anomaly_active,
        anomaly_percent=round(anomaly_percent, 1),
    )
