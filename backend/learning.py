"""
Lernmodul – verwaltet Filterzyklen und erstellt zeitbasierte Referenzprofile je HETA-Code.

Ein Referenzprofil gilt als valide nach 3 vollständig bestätigten Filterzyklen.
Die Referenzkurve enthält den normierten zeitlichen Verlauf von Δp, R_eff, Durchfluss
und Temperatur (20 Stützpunkte von 0 % bis 100 % der Referenzzyklusdauer).
"""

import json
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

N_CURVE_BUCKETS = 40  # 40 Stützpunkte → je 2,5 % Zyklusfortschritt (feinere Auflösung für die stark nichtlineare dp-Kurve)


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
    events: list = field(default_factory=list)


class LearningManager:
    """
    Verwaltet Lernzyklen und zeitbasierte Referenzprofile.
    Kommuniziert mit der Datenbank für persistente Speicherung.
    """

    def __init__(self, database, required_cycles: int = 3, tolerance_reff_pct: float = 0.25):
        self.db = database
        self.required_cycles = required_cycles
        self.tolerance_reff_pct = tolerance_reff_pct
        self._active_cycle: ActiveCycle | None = None

    # ------------------------------------------------------------------
    # Zyklus-Verwaltung
    # ------------------------------------------------------------------

    def abort_cycle(self):
        """Verwirft den aktiven Zyklus ohne Speicherung (z. B. nach Stopp)."""
        if self._active_cycle is not None:
            logger.info("Aktiver Zyklus für %s verworfen (Messung gestoppt).", self._active_cycle.heta_code)
            self._active_cycle = None

    def start_cycle(self, heta_code: str, r_eff: float, dp: float):
        """Startet einen neuen Filterzyklus."""
        self._active_cycle = ActiveCycle(
            heta_code=heta_code,
            start_r_eff=r_eff,
            start_dp=dp,
        )
        logger.info("Filterzyklus gestartet für %s (r_eff=%.4f)", heta_code, r_eff)

    def record_sample(
        self,
        flow: float,
        temperature: float,
        dp: float,
        r_eff: float,
        p1: float = 0.0,
        p2: float = 0.0,
        timestamp: float = None,
        filter_health_percent: float = None,
        remaining_seconds: float = None,
    ):
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

    def end_cycle(
        self, confirmed: bool, end_r_eff: float, end_dp: float, end_time: float = None, active_seconds: float = None
    ) -> dict | None:
        """
        Schließt den aktiven Zyklus ab und speichert ihn in der Datenbank.
        end_time: Zeitpunkt an dem dp-Limit erreicht wurde (exkl. Wartezeit auf Bestätigung).
                  Wenn None, wird time.time() verwendet.
        active_seconds: Kumulierte Betriebszeit (ohne Pausen). Wenn None, wird
                        duration_seconds (Wanduhrzeit) verwendet – korrekt für Dauerbetrieb.
        Gibt die Zyklus-Daten zurück oder None falls kein Zyklus aktiv war.
        """
        if self._active_cycle is None:
            logger.warning("Kein aktiver Zyklus beim Beenden.")
            return None

        cycle = self._active_cycle
        now = end_time if end_time is not None else time.time()
        self.close_all_events(ts_end=now)
        duration = now - cycle.start_time
        active_secs = active_seconds if active_seconds is not None else duration

        avg_flow = sum(cycle.flow_samples) / len(cycle.flow_samples) if cycle.flow_samples else 0.0
        avg_temp = sum(cycle.temp_samples) / len(cycle.temp_samples) if cycle.temp_samples else 0.0

        # Beladungsrate: dp-Anstieg pro aktiver Sekunde
        loading_rate = (end_dp - cycle.start_dp) / max(active_secs, 1.0)

        cycle_data = {
            "heta_code": cycle.heta_code,
            "start_time": cycle.start_time,
            "end_time": now,
            "duration_seconds": round(duration, 1),
            "active_seconds": round(active_secs, 1),
            "start_r_eff": round(cycle.start_r_eff, 5),
            "end_r_eff": round(end_r_eff, 5),
            "start_dp": round(cycle.start_dp, 3),
            "end_dp": round(end_dp, 3),
            "average_flow": round(avg_flow, 1),
            "average_temperature": round(avg_temp, 1),
            "loading_rate": round(loading_rate, 6),
            "confirmed_filter_change": 1 if confirmed else 0,
            "events_json": json.dumps(cycle.events),
        }

        cycle_id = self.db.insert_cycle(cycle_data)
        cycle_data["id"] = cycle_id

        logger.info("Filterzyklus abgeschlossen: %s, Dauer=%.0f s, bestätigt=%s", cycle.heta_code, duration, confirmed)

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
        samples = [
            {
                "cycle_id": cycle_id,
                "heta_code": cycle.heta_code,
                "timestamp": ts,
                "cycle_second": round(ts - t0, 2),
                "p1_bar": p1,
                "p2_bar": p2,
                "dp_bar": dp,
                "flow_l_min": fl,
                "temp_c": tmp,
                "r_eff": r,
                "filter_health_percent": hp,
                "remaining_seconds": rem,
            }
            for ts, p1, p2, dp, fl, tmp, r, hp, rem in zip(
                cycle.timestamps,
                cycle.p1_samples,
                cycle.p2_samples,
                cycle.dp_samples,
                cycle.flow_samples,
                cycle.temp_samples,
                cycle.r_eff_samples,
                cycle.health_samples,
                cycle.remaining_samples,
            )
        ]
        self.db.insert_cycle_samples(samples)
        logger.info("Zyklus %d: %d Samples gespeichert.", cycle_id, len(samples))

    # ------------------------------------------------------------------
    # Referenzprofil
    # ------------------------------------------------------------------

    def _update_profile(self, heta_code: str):
        """
        Aktualisiert das Referenzprofil.
        Die Referenzwerte werden NUR aus den ersten required_cycles Zyklen berechnet
        und danach eingefroren. Spätere Zyklen erhöhen nur noch cycles_count.
        """
        cycles = self.db.get_cycles_for_heta(heta_code)
        confirmed = [c for c in cycles if c["confirmed_filter_change"]]
        count = len(confirmed)

        if count == 0:
            return

        # Referenzprofil ist eingefroren sobald genug Lernzyklen vorliegen
        profile_valid = 1 if count >= self.required_cycles else 0

        if count > self.required_cycles:
            # Nur cycles_count aktualisieren, Referenzwerte bleiben unverändert
            existing = self.db.get_profile(heta_code)
            if existing and existing.get("profile_valid"):
                self.db.upsert_profile(
                    heta_code,
                    {
                        "reference_r_eff": existing["reference_r_eff"],
                        "reference_r_eff_end": existing.get("reference_r_eff_end", 0.0),
                        "reference_loading_rate": existing["reference_loading_rate"],
                        "reference_avg_flow": existing.get("reference_avg_flow", 0.0),
                        "reference_avg_temp": existing.get("reference_avg_temp", 20.0),
                        "reference_duration_seconds": existing.get("reference_duration_seconds", 0.0),
                        "reference_r_eff_start": existing.get("reference_r_eff_start", 0.0),
                        "reference_curve_json": existing.get("reference_curve_json"),
                        "reference_dp_clean": existing.get("reference_dp_clean", 0.0),
                        "cycles_count": count,
                        "profile_valid": 1,
                    },
                )
                logger.info(
                    "Profil eingefroren für %s – Zyklus %d wird nicht in Referenz aufgenommen.", heta_code, count
                )
                return

        # Nur die ersten required_cycles Zyklen für die Referenzberechnung verwenden
        learning_cycles = confirmed[: self.required_cycles]
        n = len(learning_cycles)

        ref_r_eff = sum(c["start_r_eff"] for c in learning_cycles) / n
        ref_r_eff_end = sum(c["end_r_eff"] for c in learning_cycles) / n
        ref_loading_rate = sum(c["loading_rate"] for c in learning_cycles) / n
        ref_avg_flow = sum(c.get("average_flow", 0.0) for c in learning_cycles) / n
        ref_avg_temp = sum(c.get("average_temperature", 20.0) for c in learning_cycles) / n
        # Betriebszeit bevorzugen (Batch-Modus: exkl. Pausen); Fallback auf Wanduhrzeit.
        ref_duration = (
            sum(c["active_seconds"] if c.get("active_seconds") else c["duration_seconds"] for c in learning_cycles) / n
        )
        # dp_clean = Ø der start_dp-Werte der Lernzyklen (gemessener Sauberdruckabfall)
        ref_dp_clean = sum(c.get("start_dp", 0.0) for c in learning_cycles) / n

        # Zeitbasierte Referenzkurve nur aus Lernzyklen berechnen
        curve = self._compute_reference_curve(learning_cycles)

        self.db.upsert_profile(
            heta_code,
            {
                "reference_r_eff": round(ref_r_eff, 6),
                "reference_r_eff_end": round(ref_r_eff_end, 6),
                "reference_loading_rate": round(ref_loading_rate, 6),
                "reference_avg_flow": round(ref_avg_flow, 1),
                "reference_avg_temp": round(ref_avg_temp, 2),
                "reference_duration_seconds": round(ref_duration, 1),
                "reference_r_eff_start": round(ref_r_eff, 6),
                "reference_curve_json": json.dumps(curve),
                "reference_dp_clean": round(ref_dp_clean, 4),
                "cycles_count": count,
                "profile_valid": profile_valid,
            },
        )
        logger.info(
            "Profil aktualisiert für %s: %d/%d Lernzyklen, valide=%s, dp_clean_gemessen=%.4f bar, Kurve=%d Stützpunkte",
            heta_code,
            n,
            self.required_cycles,
            bool(profile_valid),
            ref_dp_clean,
            len(curve),
        )

    def _compute_reference_curve(self, confirmed_cycles: list) -> list:
        """
        Berechnet eine zeitnormierte Referenzkurve aus allen bestätigten Zyklen.
        Jeder Zyklus wird auf 0–100 % normiert; die Werte werden in N_CURVE_BUCKETS
        gemittelt. Zyklen ohne Sample-Daten werden linear interpoliert.

        Kurvenstruktur (N+2 Punkte):
          [0]      – expliziter Ankerpunkt t_pct=0   aus gemittelten Zyklusstartwerten
          [1..N]   – N Bucket-Mittelwerte, beschriftet an der Bucket-Mitte (i+0.5)/N*100
          [N+1]    – expliziter Ankerpunkt t_pct=100 aus gemittelten Zyklusenddaten

        Durch die Bucket-Mitten-Beschriftung stimmt die Interpolation auch bei
        nichtlinearem dp/R_eff-Verlauf; die Endpunkt-Anker verhindern die
        bisherige systematische Abweichung am Zyklusanfang und -ende.
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
                    progress = t**1.5  # simuliert konvexen dp-Anstieg
                    buckets[i]["dp"].append(cycle["start_dp"] + (cycle["end_dp"] - cycle["start_dp"]) * progress)
                    buckets[i]["r_eff"].append(cycle["start_r_eff"] + (cycle["end_r_eff"] - cycle["start_r_eff"]) * t)
                    buckets[i]["flow"].append(cycle.get("average_flow", 0))
                    buckets[i]["temp"].append(cycle.get("average_temperature", 20))

        # Innere Kurve: Bucket-Mittelpunkte als t_pct-Beschriftung.
        # Bucket i deckt t_frac ∈ [i/n, (i+1)/n) ab → Mittelpunkt (i+0.5)/n.
        curve = []
        for i in range(n):
            t_pct = round((i + 0.5) / n * 100.0, 1)
            b = buckets[i]
            point = {"t_pct": t_pct}
            for key in ("dp", "r_eff", "flow", "temp"):
                point[key] = round(sum(b[key]) / len(b[key]), 6) if b[key] else None
            curve.append(point)

        self._fill_none_in_curve(curve)

        # Explizite Endpunkt-Anker aus gemittelten Zyklusdaten berechnen.
        # Verhindert systematische Abweichung wenn dp/R_eff am Ende steil ansteigt.
        count = len(confirmed_cycles)
        if count > 0:
            avg_start_dp = sum(c.get("start_dp", 0.0) for c in confirmed_cycles) / count
            avg_end_dp = sum(c.get("end_dp", 0.0) for c in confirmed_cycles) / count
            avg_start_reff = sum(c.get("start_r_eff", 0.0) for c in confirmed_cycles) / count
            avg_end_reff = sum(c.get("end_r_eff", 0.0) for c in confirmed_cycles) / count
            avg_temp = sum(c.get("average_temperature", 20.0) for c in confirmed_cycles) / count
            # Durchfluss aus dp/R_eff ableiten (R_eff = dp/flow → flow = dp/R_eff)
            start_flow = avg_start_dp / avg_start_reff if avg_start_reff > 1e-9 else 0.0
            end_flow = avg_end_dp / avg_end_reff if avg_end_reff > 1e-9 else 0.0

            curve.insert(
                0,
                {
                    "t_pct": 0.0,
                    "dp": round(avg_start_dp, 6),
                    "r_eff": round(avg_start_reff, 6),
                    "flow": round(start_flow, 2),
                    "temp": round(avg_temp, 2),
                },
            )
            curve.append(
                {
                    "t_pct": 100.0,
                    "dp": round(avg_end_dp, 6),
                    "r_eff": round(avg_end_reff, 6),
                    "flow": round(end_flow, 2),
                    "temp": round(avg_temp, 2),
                }
            )

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
                    next_i = next((j for j in range(i + 1, n) if vals[j] is not None), None)
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

    def get_curve_analysis(
        self,
        heta_code: str,
        elapsed_seconds: float,
        current_dp: float,
        current_r_eff: float,
        current_flow: float,
        current_temp: float,
        current_dp_slope: float | None = None,
        current_flow_slope: float | None = None,
        current_temp_slope: float | None = None,
        current_reff_slope: float | None = None,
    ) -> dict | None:
        """
        Vergleicht aktuelle Messwerte mit der gelernten Referenzkurve.

        Fortschritt & Ankerpunkt: dp-basiert (Referenzkurve invertieren).
        - Δp-Steigung: Vergleich mbar/s — zeigt Beladungsgeschwindigkeit
        - Q, T, R_eff: Absolutwertvergleich am gleichen dp-Punkt — aktualisiert
          sich sekündlich mit dp und zeigt echte Prozessabweichungen.
        """
        profile = self.get_profile(heta_code)
        if not profile or not profile.get("profile_valid"):
            logger.debug("get_curve_analysis: kein valides Profil für %s", heta_code)
            return None

        curve_json = profile.get("reference_curve_json")
        ref_dur = profile.get("reference_duration_seconds", 0)
        if not curve_json or ref_dur <= 0:
            logger.debug("get_curve_analysis: curve_json leer oder ref_dur=%s für %s", ref_dur, heta_code)
            return None

        try:
            curve = json.loads(curve_json)
        except Exception as e:
            logger.warning("get_curve_analysis: JSON-Fehler für %s: %s", heta_code, e)
            return None

        if not curve:
            logger.debug("get_curve_analysis: leere Kurve nach JSON-Parse für %s", heta_code)
            return None

        # dp-basierter Zyklusfortschritt
        t_pct = self._invert_dp_to_tpct(curve, current_dp)
        cycle_progress_pct = round(t_pct, 1)
        ref = self._interpolate_curve(curve, t_pct)
        if not ref:
            return None

        def pct_dev(cur, ref_val):
            if ref_val and abs(ref_val) > 1e-9:
                return round((cur / ref_val - 1.0) * 100.0, 1)
            return 0.0

        # dp-Steigung: Referenz über dasselbe 30-s-Fenster wie die aktuelle Regression.
        # Beide Steigungen nutzen denselben Mittelungshorizont → kein Versatz.
        # Referenzfenster: 30 s um aktuelle t_pct-Position in der Referenzkurve.
        ref_dp_slope = self._slope_windowed(curve, t_pct, ref_dur, field="dp", window_s=30)
        dp_slope_dev = (
            pct_dev(current_dp_slope, ref_dp_slope)
            if current_dp_slope is not None and abs(ref_dp_slope) > 1e-9
            else 0.0
        )

        # Rückwärts-Steigungen für Q, T, R_eff — identische Methodik wie dp
        def slope_dev(cur_slope, field):
            ref_s = self._slope_windowed(curve, t_pct, ref_dur, field=field, window_s=30)
            if cur_slope is None or abs(ref_s) < 1e-12:
                return 0.0, ref_s
            return pct_dev(cur_slope, ref_s), ref_s

        flow_dev_pct, ref_flow_slope = slope_dev(current_flow_slope, "flow")
        temp_dev_pct, ref_temp_slope = slope_dev(current_temp_slope, "temp")
        reff_dev_pct, ref_reff_slope = slope_dev(current_reff_slope, "r_eff")

        return {
            "cycle_progress_pct": cycle_progress_pct,
            "elapsed_seconds": round(elapsed_seconds, 1),
            # dp-Steigung
            "ref_dp_slope": round(ref_dp_slope, 6),
            "cur_dp_slope": round(current_dp_slope, 6) if current_dp_slope is not None else None,
            "dp_deviation_pct": dp_slope_dev,
            # Q-Steigung (l/min/s)
            "ref_flow_slope": round(ref_flow_slope, 6),
            "cur_flow_slope": round(current_flow_slope, 6) if current_flow_slope is not None else None,
            "flow_deviation_pct": flow_dev_pct,
            # T-Steigung (°C/s)
            "ref_temp_slope": round(ref_temp_slope, 6),
            "cur_temp_slope": round(current_temp_slope, 6) if current_temp_slope is not None else None,
            "temp_deviation_pct": temp_dev_pct,
            # R_eff-Steigung
            "ref_reff_slope": round(ref_reff_slope, 9),
            "cur_reff_slope": round(current_reff_slope, 9) if current_reff_slope is not None else None,
            "r_eff_deviation_pct": reff_dev_pct,
        }

    @staticmethod
    def _interpolate_curve(curve: list, t_pct: float) -> dict | None:
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

    @staticmethod
    def _invert_dp_to_tpct(curve: list, dp_bar: float) -> float:
        """
        Invertiert die Referenzkurve: dp → t_pct.
        Gibt zurück wo dp_bar in der Kurve liegt (0–100 %).
        Nicht-monotone Stellen (Messrauschen) werden überbrückt.
        """
        pts = [(p["t_pct"], p.get("dp") or 0.0) for p in curve if p.get("t_pct") is not None]
        if not pts:
            return 0.0
        pts.sort(key=lambda x: x[0])

        if dp_bar <= pts[0][1]:
            return pts[0][0]
        if dp_bar >= pts[-1][1]:
            return pts[-1][0]

        for i in range(len(pts) - 1):
            t_lo, dp_lo = pts[i]
            t_hi, dp_hi = pts[i + 1]
            if dp_hi <= dp_lo:
                continue
            if dp_lo <= dp_bar <= dp_hi:
                frac = (dp_bar - dp_lo) / (dp_hi - dp_lo)
                return t_lo + frac * (t_hi - t_lo)

        closest = min(pts, key=lambda p: abs(p[1] - dp_bar))
        return closest[0]

    @staticmethod
    def _slope_windowed(
        curve: list, t_pct: float, ref_duration: float, field: str = "dp", window_s: float = 30.0
    ) -> float:
        """
        Referenzsteigung über ein window_s-Fenster VOR t_pct (rückwärts).
        Gleiche Richtung wie die lineare Regression der aktuellen Messwerte
        (beide schauen 30s zurück) → kein systematischer Versatz bei
        beschleunigender dp-Kurve.
        """
        if not curve or ref_duration <= 0:
            return 0.0
        window_pct = (window_s / ref_duration) * 100.0  # Fenstergröße in t_pct
        t_lo = max(0.0, t_pct - window_pct)
        t_hi = min(100.0, t_pct)

        def interp_val(t):
            if t <= curve[0].get("t_pct", 0):
                return curve[0].get(field) or 0.0
            if t >= curve[-1].get("t_pct", 100):
                return curve[-1].get(field) or 0.0
            for i in range(len(curve) - 1):
                t0 = curve[i].get("t_pct", 0)
                t1 = curve[i + 1].get("t_pct", 0)
                if t0 <= t <= t1 and (t1 - t0) > 1e-6:
                    alpha = (t - t0) / (t1 - t0)
                    v0 = curve[i].get(field) or 0.0
                    v1 = curve[i + 1].get(field) or 0.0
                    return v0 + alpha * (v1 - v0)
            return curve[-1].get(field) or 0.0

        v_lo = interp_val(t_lo)
        v_hi = interp_val(t_hi)
        actual_window_s = (t_hi - t_lo) / 100.0 * ref_duration
        return (v_hi - v_lo) / actual_window_s if actual_window_s > 0 else 0.0

    @staticmethod
    def _slope_at_tpct(curve: list, t_pct: float, ref_duration: float, field: str = "dp") -> float:
        """
        Berechnet die Referenzsteigung für ein beliebiges Kurvenfeld (bar/s, l/min/s, …)
        an der Position t_pct. Ableitung: d(field)/d(t_pct) × (100 / ref_duration).
        """
        if not curve or ref_duration <= 0:
            return 0.0
        for i in range(len(curve) - 1):
            t0 = curve[i].get("t_pct", 0)
            t1 = curve[i + 1].get("t_pct", 0)
            if t0 <= t_pct <= t1 and (t1 - t0) > 0.001:
                v0 = curve[i].get(field) or 0.0
                v1 = curve[i + 1].get(field) or 0.0
                t_delta_s = (t1 - t0) / 100.0 * ref_duration
                return (v1 - v0) / t_delta_s if t_delta_s > 0 else 0.0
        # Fallback: mittlere Gesamtsteigung
        v_total = (curve[-1].get(field) or 0.0) - (curve[0].get(field) or 0.0)
        return v_total / ref_duration

    def get_profile(self, heta_code: str) -> dict | None:
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
        anomaly = deviation > self.tolerance_reff_pct
        return anomaly, round(deviation * 100, 1)

    @property
    def active_cycle(self) -> ActiveCycle | None:
        return self._active_cycle

    def add_event(self, severity: str, message: str, category: str = ""):
        """Fügt ein Ereignis zum aktiven Zyklus hinzu (z.B. Anomalie, Sensorfehler)."""
        if self._active_cycle is not None:
            now = round(time.time())
            self._active_cycle.events.append(
                {
                    "ts": now,
                    "ts_start": now,
                    "ts_end": None,
                    "severity": severity,
                    "category": category,
                    "message": message,
                }
            )

    def close_event(self, category: str = "", severity: str = "", ts_end: float = None):
        """Schließt das letzte offene Ereignis (optional nach Kategorie/Schwere filtern)."""
        if not category and not severity:
            logger.warning(
                "close_event() ohne category/severity – schließt erstes offenes Event, "
                "egal welcher Typ. Bitte category angeben."
            )
        if self._active_cycle is None:
            return
        now = round(ts_end or time.time())
        for ev in reversed(self._active_cycle.events):
            if ev.get("ts_end") is not None:
                continue
            if category and ev.get("category") != category:
                continue
            if severity and ev.get("severity") != severity:
                continue
            ev["ts_end"] = now
            return

    def close_all_events(self, ts_end: float = None):
        """Schließt alle noch offenen Ereignisse (z.B. am Zyklusende)."""
        if self._active_cycle is None:
            return
        now = round(ts_end or time.time())
        for ev in self._active_cycle.events:
            if ev.get("ts_end") is None:
                ev["ts_end"] = now
