"""
Servicelogik – erzeugt Serviceempfehlungen, Ersatzteilbestellungen und Serviceberichte.
"""

import logging
import time

from calculations import (
    STATUS_BEOBACHTEN,
    STATUS_FEHLER,
    STATUS_OK,
    STATUS_WARNUNG,
    STATUS_WECHSEL,
    STATUS_WECHSEL_BESTAETIGEN,
)

logger = logging.getLogger(__name__)


def build_service_payload(
    filter_state,
    heta_code: str,
    activation_status: bool,
    prediction_status: dict,
    learned_cycles: int,
    profile_status: bool,
    anomaly_active: bool,
    anomaly_percent: float,
    action: str = "STATUS_UPDATE",
) -> dict:
    """
    Erstellt das standardisierte Service-Datenpaket.
    Alle Felder sind für spätere ERP/CRM-Integration vorgesehen.
    """
    return {
        "action": action,
        "timestamp": time.time(),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "heta_code": heta_code,
        "activation_status": activation_status,
        "prediction_mode": prediction_status.get("prediction_mode", "BASIS"),
        "p1_bar": filter_state.p1_bar,
        "p2_bar": filter_state.p2_bar,
        "dp_bar": filter_state.dp_bar,
        "flow_l_min": filter_state.flow_l_min,
        "temperature_c": filter_state.temperature_c,
        "r_eff": filter_state.r_eff,
        "filter_health_percent": filter_state.filter_health_percent,
        "remaining_life_display": prediction_status.get("remaining_display", "Unbekannt"),
        "remaining_seconds": prediction_status.get("remaining_seconds"),
        "learned_cycles": learned_cycles,
        "profile_status": "VALIDIERT" if profile_status else "LERNEND",
        "filter_status": filter_state.status,
        "loading_anomaly_active": anomaly_active,
        "loading_anomaly_percent": anomaly_percent,
    }


def generate_service_recommendation(filter_state, prediction_status: dict, health_percent: float = None) -> dict:
    """Leitet eine Serviceempfehlung aus dem Filterzustand ab."""
    status = filter_state.status
    health = health_percent if health_percent is not None else filter_state.filter_health_percent
    remaining = prediction_status.get("remaining_display", "Unbekannt")

    if status == STATUS_OK:
        priority = "NIEDRIG"
        message = f"Filter in Ordnung. Filterzustand: {health:.0f} %. Reststandzeit: {remaining}."
        action_required = False
    elif status == STATUS_BEOBACHTEN:
        priority = "MITTEL"
        message = f"Filter nähert sich dem Grenzwert. Filterzustand: {health:.0f} %. Reststandzeit: {remaining}. Ersatzfilter bereitstellen."
        action_required = False
    elif status in (STATUS_WECHSEL, STATUS_WECHSEL_BESTAETIGEN):
        priority = "HOCH"
        message = "Filterwechsel erforderlich! Grenzwert überschritten. Filter sofort tauschen und Wechsel bestätigen."
        action_required = True
    elif status == STATUS_WARNUNG:
        priority = "MITTEL"
        message = "Abweichendes Beladungsverhalten erkannt. Anlage und Filter prüfen."
        action_required = False
    elif status == STATUS_FEHLER:
        priority = "HOCH"
        message = "Sensorfehler erkannt. Sensor und Verkabelung prüfen."
        action_required = True
    else:
        priority = "UNBEKANNT"
        message = "Status unbekannt."
        action_required = False

    return {
        "priority": priority,
        "message": message,
        "action_required": action_required,
        "filter_status": status,
        "filter_health_percent": health,
    }


def generate_spare_parts_order(heta_code: str, filter_state) -> dict:
    """
    Erstellt ein Ersatzteilbestell-Datenpaket.
    Dient als Vorlage für spätere ERP-Integration.
    """
    return {
        "order_type": "ERSATZTEIL_ANFRAGE",
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "heta_code": heta_code,
        "article_description": "HETA Filterpatrone",
        "quantity": 1,
        "urgency": "HOCH" if filter_state.filter_health_percent < 15 else "NORMAL",
        "current_filter_health_percent": filter_state.filter_health_percent,
        "dp_at_order": filter_state.dp_bar,
        "note": "Automatisch generiert vom HETA Smart Filter Monitoring System",
    }


def generate_service_report(payload: dict, recommendation: dict, spare_parts: dict) -> str:
    """Erstellt einen lesbaren Servicebericht als Textblock."""
    lines = [
        "=" * 60,
        "  HETA SMART FILTER MONITORING – SERVICEBERICHT",
        "=" * 60,
        f"  Zeitpunkt:        {payload.get('timestamp_iso', '-')}",
        f"  HETA-Code:        {payload.get('heta_code', '-')}",
        f"  Aktivierung:      {'Aktiv' if payload.get('activation_status') else 'Nicht aktiv'}",
        f"  Prognose-Modus:   {payload.get('prediction_mode', '-')}",
        "-" * 60,
        "  MESSWERTE",
        f"  Eintrittsdruck p1:  {payload.get('p1_bar', 0):.3f} bar",
        f"  Austrittsdruck p2:  {payload.get('p2_bar', 0):.3f} bar",
        f"  Differenzdruck Δp:  {payload.get('dp_bar', 0):.3f} bar",
        f"  Durchfluss Q:       {payload.get('flow_l_min', 0):.1f} l/min",
        f"  Temperatur T:       {payload.get('temperature_c', 0):.1f} °C",
        f"  R_eff:              {payload.get('r_eff', 0):.5f}",
        "-" * 60,
        "  FILTERSTATUS",
        f"  Status:             {payload.get('filter_status', '-')}",
        f"  Filterzustand:      {payload.get('filter_health_percent', 0):.1f} %",
        f"  Reststandzeit:      {payload.get('remaining_life_display', '-')}",
        f"  Gelernte Zyklen:    {payload.get('learned_cycles', 0)}",
        f"  Profil:             {payload.get('profile_status', '-')}",
        "-" * 60,
        "  SERVICEEMPFEHLUNG",
        f"  Priorität:          {recommendation.get('priority', '-')}",
        f"  Maßnahme:           {recommendation.get('message', '-')}",
        "-" * 60,
        "  ERSATZTEILBESTELLUNG",
        f"  Artikel:            {spare_parts.get('article_description', '-')}",
        f"  Dringlichkeit:      {spare_parts.get('urgency', '-')}",
        "=" * 60,
    ]
    return "\n".join(lines)
