"""
Lernmodul – verwaltet Filterzyklen und erstellt Referenzprofile je HETA-Code.

Ein Referenzprofil gilt als valide nach 3 vollständig bestätigten Filterzyklen.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ActiveCycle:
    """Repräsentiert einen laufenden Filterzyklus."""
    heta_code: str
    start_time: float = field(default_factory=time.time)
    start_r_eff: float = 0.0
    start_dp: float = 0.0
    flow_samples: list = field(default_factory=list)
    temp_samples: list = field(default_factory=list)
    dp_samples: list = field(default_factory=list)
    r_eff_samples: list = field(default_factory=list)


class LearningManager:
    """
    Verwaltet Lernzyklen und Referenzprofile.
    Kommuniziert mit der Datenbank für persistente Speicherung.
    """

    def __init__(self, database, required_cycles: int = 3,
                 clean_resistance_tolerance: float = 0.25):
        self.db = database
        self.required_cycles = required_cycles
        self.clean_resistance_tolerance = clean_resistance_tolerance
        self._active_cycle: Optional[ActiveCycle] = None

    # ------------------------------------------------------------------
    # Zyklus-Verwaltung
    # ------------------------------------------------------------------

    def start_cycle(self, heta_code: str, r_eff: float, dp: float):
        """Startet einen neuen Filterzyklus."""
        self._active_cycle = ActiveCycle(
            heta_code=heta_code,
            start_r_eff=r_eff,
            start_dp=dp,
        )
        logger.info("Filterzyklus gestartet für %s (r_eff=%.4f)", heta_code, r_eff)

    def record_sample(self, flow: float, temperature: float, dp: float, r_eff: float):
        """Fügt dem aktiven Zyklus einen Messwert hinzu."""
        if self._active_cycle is None:
            return
        self._active_cycle.flow_samples.append(flow)
        self._active_cycle.temp_samples.append(temperature)
        self._active_cycle.dp_samples.append(dp)
        self._active_cycle.r_eff_samples.append(r_eff)

    def end_cycle(self, confirmed: bool, end_r_eff: float, end_dp: float) -> Optional[dict]:
        """
        Schließt den aktiven Zyklus ab und speichert ihn in der Datenbank.
        Gibt die Zyklus-Daten zurück oder None falls kein Zyklus aktiv war.
        """
        if self._active_cycle is None:
            logger.warning("Kein aktiver Zyklus beim Beenden.")
            return None

        cycle = self._active_cycle
        now = time.time()
        duration = now - cycle.start_time

        avg_flow = (sum(cycle.flow_samples) / len(cycle.flow_samples)
                    if cycle.flow_samples else 0.0)
        avg_temp = (sum(cycle.temp_samples) / len(cycle.temp_samples)
                    if cycle.temp_samples else 0.0)

        # Beladungsrate: dp-Anstieg pro Sekunde
        loading_rate = (end_dp - cycle.start_dp) / max(duration, 1.0)

        cycle_data = {
            "heta_code": cycle.heta_code,
            "start_time": cycle.start_time,
            "end_time": now,
            "duration_seconds": round(duration, 1),
            "start_r_eff": round(cycle.start_r_eff, 5),
            "end_r_eff": round(end_r_eff, 5),
            "start_dp": round(cycle.start_dp, 3),
            "end_dp": round(end_dp, 3),
            "average_flow": round(avg_flow, 1),
            "average_temperature": round(avg_temp, 1),
            "loading_rate": round(loading_rate, 6),
            "confirmed_filter_change": 1 if confirmed else 0,
        }

        self.db.insert_cycle(cycle_data)
        logger.info("Filterzyklus abgeschlossen: %s, Dauer=%.0f s, bestätigt=%s",
                    cycle.heta_code, duration, confirmed)
        self._active_cycle = None

        # Profil nach jedem abgeschlossenen Zyklus aktualisieren
        if confirmed:
            self._update_profile(cycle.heta_code)

        return cycle_data

    # ------------------------------------------------------------------
    # Referenzprofil
    # ------------------------------------------------------------------

    def _update_profile(self, heta_code: str):
        """Aktualisiert das Referenzprofil aus allen bestätigten Zyklen."""
        cycles = self.db.get_cycles_for_heta(heta_code)
        confirmed = [c for c in cycles if c["confirmed_filter_change"]]
        count = len(confirmed)

        if count == 0:
            return

        ref_r_eff        = sum(c["start_r_eff"]                  for c in confirmed) / count
        ref_loading_rate = sum(c["loading_rate"]                  for c in confirmed) / count
        ref_avg_flow     = sum(c.get("average_flow",       0.0)   for c in confirmed) / count
        ref_avg_temp     = sum(c.get("average_temperature", 20.0) for c in confirmed) / count
        profile_valid    = 1 if count >= self.required_cycles else 0

        self.db.upsert_profile(heta_code, {
            "reference_r_eff":        round(ref_r_eff, 5),
            "reference_loading_rate": round(ref_loading_rate, 6),
            "reference_avg_flow":     round(ref_avg_flow, 1),
            "reference_avg_temp":     round(ref_avg_temp, 2),
            "cycles_count":           count,
            "profile_valid":          profile_valid,
        })
        logger.info("Profil aktualisiert für %s: %d Zyklen, valide=%s",
                    heta_code, count, bool(profile_valid))

    def get_profile(self, heta_code: str) -> Optional[dict]:
        """Gibt das Referenzprofil zurück oder None."""
        return self.db.get_profile(heta_code)

    def is_profile_valid(self, heta_code: str) -> bool:
        """Prüft ob ein valides Referenzprofil existiert."""
        profile = self.get_profile(heta_code)
        return bool(profile and profile.get("profile_valid"))

    def get_cycles_count(self, heta_code: str) -> int:
        """Gibt die Anzahl bestätigter Zyklen zurück."""
        return self.db.count_confirmed_cycles(heta_code)

    # ------------------------------------------------------------------
    # Startverhalten-Prüfung
    # ------------------------------------------------------------------

    def check_start_behavior(self, heta_code: str, current_r_eff: float) -> tuple[bool, float]:
        """
        Vergleicht den aktuellen Startwiderstand mit dem Referenzprofil.

        Rückgabe:
            (anomalie: bool, abweichung_prozent: float)
        """
        profile = self.get_profile(heta_code)
        if not profile or not profile.get("profile_valid"):
            return False, 0.0

        ref = profile["reference_r_eff"]
        if ref <= 0:
            return False, 0.0

        deviation = abs(current_r_eff - ref) / ref
        anomaly = deviation > self.clean_resistance_tolerance
        return anomaly, round(deviation * 100, 1)

    @property
    def active_cycle(self) -> Optional[ActiveCycle]:
        return self._active_cycle
