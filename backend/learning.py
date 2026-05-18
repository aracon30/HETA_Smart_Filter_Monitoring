"""
Lernmodul – verwaltet Filterzyklen und erstellt zeitbasierte Referenzprofile je HETA-Code.

Ein Referenzprofil gilt als valide nach 3 vollständig bestätigten Filterzyklen.
Die Referenzkurve enthält den normierten zeitlichen Verlauf von Δp, R_eff, Durchfluss
und Temperatur (20 Stützpunkte von 0 % bis 100 % der Referenzzyklusdauer).
"""

import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

N_CURVE_BUCKETS = 20  # 20 Stützpunkte → je 5 % Zyklusfortschritt


@dataclass
class ActiveCycle:
    """Repräsentiert einen laufenden Filterzyklus."""
    heta_code: str
    start_time: float = field(default_factory=time.time)
    start_r_eff: float = 0.0
    start_dp: float = 0.0
    timestamps: list = field(default_factory=list)
    p1_samples: list = field(default_factory=list)
    p2_samples: list = field(default_factory=list)
    flow_samples: list = field(default_factory=list)
    temp_samples: list = field(default_factory=list)
    dp_samples: list = field(default_factory=list)
    r_eff_samples: list = field(default_factory=list)
    health_samples: list = field(default_factory=list)
    remaining_samples: list = field(default_factory=list)


class LearningManager:
    """
    Verwaltet Lernzyklen und zeitbasierte Referenzprofile.
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

    def record_sample(self, flow: float, temperature: float, dp: float, r_eff: float,
                      p1: float = 0.0, p2: float = 0.0, timestamp: float = None,
                      filter_health_percent: float = None, remaining_seconds: float = None):
        """Fügt dem aktiven Zyklus einen Messwert inkl. Zeitstempel und Beladungsgrad hinzu."""
        if self._active_cycle is None:
            return
        t = timestamp if timestamp is not None else time.time()
        c = self._active_cycle
        c.timestamps.append(t)
        c.p1_samples.append(p1)
        c.p2_samples.append(p2)
        c.flow_samples.append(flow)
        c.temp_samples.append(temperature)
        c.dp_samples.append(dp)
        c.r_eff_samples.append(r_eff)
        c.health_samples.append(filter_health_percent)
        c.remaining_samples.append(remaining_seconds)

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
            "heta_code":              cycle.heta_code,
            "start_time":             cycle.start_time,
            "end_time":               now,
            "duration_seconds":       round(duration, 1),
            "start_r_eff":            round(cycle.start_r_eff, 5),
            "end_r_eff":              round(end_r_eff, 5),
            "start_dp":               round(cycle.start_dp, 3),
            "end_dp":                 round(end_dp, 3),
            "average_flow":           round(avg_flow, 1),
            "average_temperature":    round(avg_temp, 1),
            "loading_rate":           round(loading_rate, 6),
            "confirmed_filter_change": 1 if confirmed else 0,
        }

        cycle_id = self.db.insert_cycle(cycle_data)
        cycle_data["id"] = cycle_id

        logger.info("Filterzyklus abgeschlossen: %s, Dauer=%.0f s, bestätigt=%s",
                    cycle.heta_code, duration, confirmed)

        # Zeitreihen-Messwerte persistieren
        self._persist_samples(cycle_id, cycle)

        self._active_cycle = None

        # Profil nach jedem bestätigten Zyklus aktualisieren
        if confirmed:
            self._update_profile(cycle.heta_code)

        return cycle_data

    # ------------------------------------------------------------------
    # Sample-Persistierung
    # ------------------------------------------------------------------

    def _persist_samples(self, cycle_id: int, cycle: ActiveCycle):
        """Speichert alle Zeitreihen-Samples des Zyklus in die DB."""
        if not cycle.timestamps:
            return
        t0 = cycle.timestamps[0]
        n = len(cycle.timestamps)
        samples = []
        for i in range(n):
            samples.append({
                "cycle_id":             cycle_id,
                "heta_code":            cycle.heta_code,
                "timestamp":            cycle.timestamps[i],
                "cycle_second":         round(cycle.timestamps[i] - t0, 2),
                "p1_bar":               cycle.p1_samples[i]       if i < len(cycle.p1_samples)       else None,
                "p2_bar":               cycle.p2_samples[i]       if i < len(cycle.p2_samples)       else None,
                "dp_bar":               cycle.dp_samples[i]       if i < len(cycle.dp_samples)       else None,
                "flow_l_min":           cycle.flow_samples[i]     if i < len(cycle.flow_samples)     else None,
                "temp_c":               cycle.temp_samples[i]     if i < len(cycle.temp_samples)     else None,
                "r_eff":                cycle.r_eff_samples[i]    if i < len(cycle.r_eff_samples)    else None,
                "filter_health_percent":cycle.health_samples[i]   if i < len(cycle.health_samples)   else None,
                "remaining_seconds":    cycle.remaining_samples[i] if i < len(cycle.remaining_samples) else None,
            })
        self.db.insert_cycle_samples(samples)
        logger.info("Zyklus %d: %d Samples gespeichert.", cycle_id, len(samples))

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
        ref_r_eff_end    = sum(c["end_r_eff"]                    for c in confirmed) / count
        ref_loading_rate = sum(c["loading_rate"]                  for c in confirmed) / count
        ref_avg_flow     = sum(c.get("average_flow",       0.0)   for c in confirmed) / count
        ref_avg_temp     = sum(c.get("average_temperature", 20.0) for c in confirmed) / count
        ref_duration     = sum(c["duration_seconds"]              for c in confirmed) / count
        profile_valid    = 1 if count >= self.required_cycles else 0

        # Zeitbasierte Referenzkurve berechnen
        curve = self._compute_reference_curve(confirmed)

        self.db.upsert_profile(heta_code, {
            "reference_r_eff":              round(ref_r_eff, 6),
            "reference_r_eff_end":          round(ref_r_eff_end, 6),
            "reference_loading_rate":       round(ref_loading_rate, 6),
            "reference_avg_flow":           round(ref_avg_flow, 1),
            "reference_avg_temp":           round(ref_avg_temp, 2),
            "reference_duration_seconds":   round(ref_duration, 1),
            "reference_r_eff_start":        round(ref_r_eff, 6),
            "reference_curve_json":         json.dumps(curve),
            "cycles_count":                 count,
            "profile_valid":                profile_valid,
        })
        logger.info("Profil aktualisiert für %s: %d Zyklen, valide=%s, Kurve=%d Stützpunkte",
                    heta_code, count, bool(profile_valid), len(curve))

    def _compute_reference_curve(self, confirmed_cycles: list) -> list:
        """
        Berechnet eine zeitnormierte Referenzkurve aus allen bestätigten Zyklen.
        Jeder Zyklus wird auf 0–100 % normiert; die Werte werden in N_CURVE_BUCKETS
        gemittelt. Zyklen ohne Sample-Daten werden linear interpoliert.
        """
        n = N_CURVE_BUCKETS
        buckets = [{"dp": [], "r_eff": [], "flow": [], "temp": []} for _ in range(n)]

        for cycle in confirmed_cycles:
            cycle_id = cycle.get("id")
            dur = cycle.get("duration_seconds", 0)
            if dur <= 0:
                continue

            samples = self.db.get_cycle_samples(cycle_id) if cycle_id else []

            if samples:
                for s in samples:
                    t_frac = s["cycle_second"] / dur
                    idx = min(int(t_frac * n), n - 1)
                    if s.get("dp_bar") is not None:
                        buckets[idx]["dp"].append(s["dp_bar"])
                    if s.get("r_eff") is not None:
                        buckets[idx]["r_eff"].append(s["r_eff"])
                    if s.get("flow_l_min") is not None:
                        buckets[idx]["flow"].append(s["flow_l_min"])
                    if s.get("temp_c") is not None:
                        buckets[idx]["temp"].append(s["temp_c"])
            else:
                # Fallback: lineare Interpolation aus Zyklusdaten
                for i in range(n):
                    t = i / max(n - 1, 1)
                    progress = t ** 1.5  # simuliert konvexen dp-Anstieg
                    buckets[i]["dp"].append(
                        cycle["start_dp"] + (cycle["end_dp"] - cycle["start_dp"]) * progress
                    )
                    buckets[i]["r_eff"].append(
                        cycle["start_r_eff"] + (cycle["end_r_eff"] - cycle["start_r_eff"]) * t
                    )
                    buckets[i]["flow"].append(cycle.get("average_flow", 0))
                    buckets[i]["temp"].append(cycle.get("average_temperature", 20))

        curve = []
        for i in range(n):
            t_pct = round(i / max(n - 1, 1) * 100.0, 1)
            b = buckets[i]
            point = {"t_pct": t_pct}
            for key in ("dp", "r_eff", "flow", "temp"):
                point[key] = (round(sum(b[key]) / len(b[key]), 6) if b[key] else None)
            curve.append(point)

        self._fill_none_in_curve(curve)
        return curve

    @staticmethod
    def _fill_none_in_curve(curve: list):
        """Füllt None-Werte in der Kurve durch lineare Interpolation auf."""
        for key in ("dp", "r_eff", "flow", "temp"):
            vals = [p.get(key) for p in curve]
            n = len(vals)
            for i in range(n):
                if vals[i] is None:
                    prev_i = next((j for j in range(i - 1, -1, -1) if vals[j] is not None), None)
                    next_i = next((j for j in range(i + 1, n)     if vals[j] is not None), None)
                    if prev_i is not None and next_i is not None:
                        alpha = (i - prev_i) / (next_i - prev_i)
                        vals[i] = vals[prev_i] + alpha * (vals[next_i] - vals[prev_i])
                    elif prev_i is not None:
                        vals[i] = vals[prev_i]
                    elif next_i is not None:
                        vals[i] = vals[next_i]
                    else:
                        vals[i] = 0.0
            for i, p in enumerate(curve):
                p[key] = round(vals[i], 6) if vals[i] is not None else 0.0

    # ------------------------------------------------------------------
    # Kurvenbasierte Analyse
    # ------------------------------------------------------------------

    def get_curve_analysis(self, heta_code: str, elapsed_seconds: float,
                           current_dp: float, current_r_eff: float,
                           current_flow: float, current_temp: float) -> Optional[dict]:
        """
        Vergleicht aktuelle Messwerte mit der gelernten Referenzkurve am
        entsprechenden Zeitpunkt im Zyklus.

        Rückgabe: dict mit Referenzwerten und Abweichungen, oder None.
        """
        profile = self.get_profile(heta_code)
        if not profile or not profile.get("profile_valid"):
            return None

        curve_json = profile.get("reference_curve_json")
        ref_dur    = profile.get("reference_duration_seconds", 0)
        if not curve_json or ref_dur <= 0:
            return None

        try:
            curve = json.loads(curve_json)
        except Exception:
            return None

        if not curve:
            return None

        # Aktueller Fortschritt in % der Referenzdauer
        t_pct = max(0.0, min(100.0, elapsed_seconds / ref_dur * 100.0))
        ref   = self._interpolate_curve(curve, t_pct)
        if not ref:
            return None

        ref_dp   = ref.get("dp")   or 0.0
        ref_reff = ref.get("r_eff") or 0.0
        ref_flow = ref.get("flow") or 0.0
        ref_temp = ref.get("temp") or 0.0

        def pct_dev(cur, ref_val):
            if ref_val and abs(ref_val) > 1e-9:
                return round((cur / ref_val - 1.0) * 100.0, 1)
            return 0.0

        return {
            "cycle_progress_pct":  round(t_pct, 1),
            "ref_dp":              round(ref_dp,   4),
            "ref_r_eff":           round(ref_reff, 6),
            "ref_flow":            round(ref_flow, 1),
            "ref_temp":            round(ref_temp, 1),
            "dp_deviation_pct":    pct_dev(current_dp,    ref_dp),
            "r_eff_deviation_pct": pct_dev(current_r_eff, ref_reff),
            "flow_deviation_pct":  pct_dev(current_flow,  ref_flow),
            "temp_deviation":      round(current_temp - ref_temp, 1),
        }

    @staticmethod
    def _interpolate_curve(curve: list, t_pct: float) -> Optional[dict]:
        """Lineare Interpolation zwischen zwei Stützpunkten der Referenzkurve."""
        if not curve:
            return None
        if t_pct <= curve[0]["t_pct"]:
            return dict(curve[0])
        if t_pct >= curve[-1]["t_pct"]:
            return dict(curve[-1])
        for i in range(len(curve) - 1):
            t0, t1 = curve[i]["t_pct"], curve[i + 1]["t_pct"]
            if t0 <= t_pct <= t1:
                if t1 - t0 < 0.001:
                    return dict(curve[i])
                alpha = (t_pct - t0) / (t1 - t0)
                return {
                    k: (curve[i].get(k) or 0.0) + alpha * ((curve[i + 1].get(k) or 0.0) - (curve[i].get(k) or 0.0))
                    for k in ("dp", "r_eff", "flow", "temp")
                }
        return dict(curve[-1])

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

    def check_start_behavior(self, heta_code: str, current_r_eff: float) -> tuple:
        """
        Vergleicht den aktuellen Startwiderstand mit dem Referenzprofil.

        Rückgabe:
            (anomalie: bool, abweichung_prozent: float)
        """
        profile = self.get_profile(heta_code)
        if not profile or not profile.get("profile_valid"):
            return False, 0.0

        ref = profile.get("reference_r_eff_start") or profile.get("reference_r_eff", 0)
        if ref <= 0:
            return False, 0.0

        deviation = abs(current_r_eff - ref) / ref
        anomaly = deviation > self.clean_resistance_tolerance
        return anomaly, round(deviation * 100, 1)

    @property
    def active_cycle(self) -> Optional[ActiveCycle]:
        return self._active_cycle
