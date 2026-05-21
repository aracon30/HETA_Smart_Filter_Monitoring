"""
Prognose-Modul – berechnet die Reststandzeit des Filters.

Drei Anzeigemodi:
  BASIS          – Kein HETA-Code aktiv. Adaptive Bereiche in Tagen/Stunden,
                   keine Minutenangaben. Jede Filteranwendung hat eine andere
                   Standzeit – von Minuten bis Tage ist alles normal.
  HETA_LERNEND  – HETA-Code aktiv, aber Lernprofil noch nicht valide (< 3 Zyklen).
                   Breite Bereiche, Lernfortschritt wird angezeigt.
  HETA_VALIDIERT – HETA-Code aktiv, 3 vollständige Zyklen gelernt.
                   Minutengenaue, geglättete Reststandzeit.
"""

import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

# Anzeigemodi
MODE_BASIS      = "BASIS"
MODE_LERNEND    = "HETA_LERNEND"
MODE_VALIDIERT  = "HETA_VALIDIERT"


def _format_basis_range(seconds: float) -> str:
    """
    Wandelt Sekunden in einen adaptiven Bereich um.
    Keine Minutenangaben – nur Stunden und Tage.
    Die Bereiche sind bewusst breit, da Filterlaufzeiten je nach Anwendung
    von Minuten bis zu mehreren Tagen variieren können.
    """
    if seconds <= 0:
        return "< 1 Std."

    hours = seconds / 3600.0
    days  = hours / 24.0

    if days >= 5:
        return "> 5 Tage"
    if days >= 3:
        return "3–5 Tage"
    if days >= 2:
        return "2–3 Tage"
    if days >= 1:
        return "1–2 Tage"
    if hours >= 12:
        return "12–24 Std."
    if hours >= 6:
        return "6–12 Std."
    if hours >= 4:
        return "4–6 Std."
    if hours >= 2:
        return "2–4 Std."
    if hours >= 1:
        return "1–2 Std."
    return "< 1 Std."


def _format_validated(seconds: float) -> str:
    """Sekundengenaue Ausgabe für den validierten HETA-Modus."""
    total_s = max(0, int(seconds))
    if total_s == 0:
        return "< 1 s"
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    if h > 0:
        return f"{h} Std. {m:02d} min {s:02d} s"
    if m > 0:
        return f"{m} min {s:02d} s"
    return f"{s} s"


class PredictionEngine:
    """
    Berechnet die Reststandzeit des Filters direkt aus dem aktuellen
    Differenzdruck und der gemessenen Beladungsrate.

    Formel: remaining = (dp_limit − dp_bar) / slope
    → nähert sich natürlich 0 wenn dp → dp_limit, kein Sprung.

    Sprünge nach OBEN werden gedämpft (max. +5 %/Tick),
    Abfall folgt sofort den tatsächlichen Messwerten.
    """

    def __init__(
        self,
        dp_limit: float,
        dp_clean: float,
        min_slope: float = 0.001,
    ):
        self.dp_limit = dp_limit
        self.dp_clean = dp_clean
        self.min_slope = min_slope

        self._last_remaining: Optional[float] = None
        self._seeded_ceiling: Optional[float] = None  # verhindert Sprünge nach dem Seed
        self._dp_history: list[float] = []
        self._history_window: int = 30

        # Multi-Kanal-Verlauf für Q, T, R_eff
        self._flow_history:  list[float] = []
        self._temp_history:  list[float] = []
        self._reff_history:  list[float] = []

    def update(self, dp_bar: float) -> Optional[float]:
        """
        Berechnet Reststandzeit aus der gemessenen dp-Steigung.

        Wenn ein Seed-Wert gesetzt wurde (aus Referenzdauer):
          - Zählt sekündlich herunter bis die echte Steigung einen
            niedrigeren Wert liefert → dann übernimmt slope-Berechnung.
          - Verhindert dadurch den Sprung nach oben in den ersten ~30 s.
        """
        self._dp_history.append(dp_bar)
        if len(self._dp_history) > self._history_window:
            self._dp_history.pop(0)

        slope = self._calculate_slope()

        # Seeded phase: tick-weise herunterzählen, kein Sprung nach oben
        if self._seeded_ceiling is not None:
            if self._last_remaining is None:
                self._last_remaining = self._seeded_ceiling
            if slope is not None and slope > 0:
                # Echte Steigung verwenden (ohne min_slope-Clamp) für den Vergleich
                raw_true = (self.dp_limit - dp_bar) / slope
                if raw_true < self._last_remaining:
                    # Slope-basierter Wert liegt unter dem Countdown → übergeben
                    self._last_remaining = max(0.0, raw_true)
                    self._seeded_ceiling = None
                    return self._last_remaining
            # Noch nicht übergeben: einfach 1 Sekunde herunterzählen
            self._last_remaining = max(0.0, self._last_remaining - 1.0)
            return self._last_remaining

        # Normale Phase (kein Seed mehr aktiv)
        if slope is None or slope <= 0:
            return self._last_remaining

        raw_remaining = max(0.0, (self.dp_limit - dp_bar) / max(slope, self.min_slope))

        if self._last_remaining is None:
            self._last_remaining = raw_remaining
        elif raw_remaining < self._last_remaining:
            self._last_remaining = raw_remaining
        else:
            if raw_remaining > self._last_remaining * 1.05:
                self._last_remaining = raw_remaining
            else:
                self._last_remaining += 0.4 * (raw_remaining - self._last_remaining)

        return self._last_remaining

    def update_with_reference_curve(
        self,
        dp_bar: float,
        ref_duration: float,
        ref_curve: list,
        elapsed_seconds: float = 0.0,
    ) -> float:
        """
        Berechnet Reststandzeit durch Invertierung der gelernten Referenzkurve.

        Funktionsprinzip:
          1. Finde t_pct in der Referenzkurve wo dp_ref ≈ dp_bar
          2. Schätze die tatsächliche Zyklusdauer aus der bisherigen Laufzeit:
               actual_duration ≈ elapsed / (t_pct / 100)
             Damit passt sich die Restzeit automatisch an langsamere/schnellere
             Beladung an: reduzierte Last → dp niedrig → t_pct klein →
             actual_duration groß → Restzeit springt sofort nach oben.
          3. Fallback auf ref_duration wenn elapsed zu klein für eine
             zuverlässige Schätzung (erste 5 Sekunden).
        """
        t_pct = self._invert_curve_dp_to_tpct(dp_bar, ref_curve)

        # Tatsächliche Zyklusdauer aus Laufzeit ableiten (ab 5 s zuverlässig)
        if elapsed_seconds >= 5.0 and t_pct > 0.5:
            actual_duration = elapsed_seconds / (t_pct / 100.0)
        else:
            actual_duration = ref_duration

        remaining = max(0.0, actual_duration * (1.0 - t_pct / 100.0))

        if self._last_remaining is None or remaining <= self._last_remaining:
            self._last_remaining = remaining
        else:
            # Anstiege durch echte Lastreduktion sofort übernehmen;
            # kleines Rauschen (<5 %) sanft glätten.
            ratio = remaining / max(self._last_remaining, 0.1)
            if ratio > 1.05:
                self._last_remaining = remaining
            else:
                self._last_remaining += 0.4 * (remaining - self._last_remaining)

        return self._last_remaining

    def _invert_curve_dp_to_tpct(self, dp_bar: float, curve: list) -> float:
        """
        Lineare Interpolation der Referenzkurve: dp → t_pct.
        Die Kurve ist nach t_pct sortiert; dp steigt mit t_pct.
        Nicht-monotone Stellen (Rauschen) werden durch Forward-Scan überbrückt.
        """
        if not curve:
            return 0.0

        # Sammle (t_pct, dp) – nur gültige Punkte
        pts = [(p["t_pct"], p["dp"]) for p in curve
               if p.get("t_pct") is not None and p.get("dp") is not None]
        if not pts:
            return 0.0

        pts.sort(key=lambda x: x[0])   # nach t_pct (aufsteigend)

        # Rand-Clamps
        if dp_bar <= pts[0][1]:
            return pts[0][0]
        if dp_bar >= pts[-1][1]:
            return pts[-1][0]

        # Vorwärts-Scan: suche ersten Übergang dp_lo ≤ dp_bar ≤ dp_hi
        for i in range(len(pts) - 1):
            t_lo, dp_lo = pts[i]
            t_hi, dp_hi = pts[i + 1]
            if dp_hi <= dp_lo:          # nicht-monotone Stelle überspringen
                continue
            if dp_lo <= dp_bar <= dp_hi:
                frac = (dp_bar - dp_lo) / (dp_hi - dp_lo)
                return t_lo + frac * (t_hi - t_lo)

        # Alle Abschnitte nicht-monoton – nächsten dp-Punkt suchen
        closest = min(pts, key=lambda p: abs(p[1] - dp_bar))
        return closest[0]

    def _calculate_slope(self) -> Optional[float]:
        """Lineare Regression über das dp-Messfenster."""
        return self._linear_slope(self._dp_history, clamp_positive=True)

    @staticmethod
    def _linear_slope(history: list, clamp_positive: bool = False) -> Optional[float]:
        """Lineare Regression über einen beliebigen Messverlauf (1 Index = 1 Sekunde)."""
        n = len(history)
        if n < 5:
            return None
        x_mean = (n - 1) / 2.0
        y_mean = sum(history) / n
        numerator   = sum((i - x_mean) * (history[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return None
        slope = numerator / denominator
        return max(slope, 0.0) if clamp_positive else slope

    def update_channels(self, flow: float, temp: float, r_eff: float) -> None:
        """Aktualisiert den Verlaufspuffer für Q, T und R_eff (je 1 Eintrag/s)."""
        for hist, val in (
            (self._flow_history, flow),
            (self._temp_history, temp),
            (self._reff_history, r_eff),
        ):
            hist.append(val)
            if len(hist) > self._history_window:
                hist.pop(0)

    def get_current_slope(self) -> Optional[float]:
        """Gibt die aktuelle dp-Steigung (bar/s) zurück, oder None wenn zu wenig Daten."""
        return self._calculate_slope()

    def get_channel_slopes(self) -> dict:
        """Gibt Steigungen für Q (l/min/s), T (°C/s) und R_eff (bar·min/l/s) zurück."""
        return {
            "flow": self._linear_slope(self._flow_history),
            "temp": self._linear_slope(self._temp_history),
            "r_eff": self._linear_slope(self._reff_history),
        }

    def reset(self):
        """Setzt die Prognose zurück (z.B. nach Filterwechsel oder Neukonfiguration)."""
        self._last_remaining = None
        self._seeded_ceiling  = None
        self._dp_history.clear()
        self._flow_history.clear()
        self._temp_history.clear()
        self._reff_history.clear()

    def seed(self, initial_seconds: float):
        """Setzt den Startwert der Reststandzeit aus der Referenzdauer."""
        if initial_seconds > 0:
            self._last_remaining  = float(initial_seconds)
            self._seeded_ceiling  = float(initial_seconds)  # kein Sprung über diesen Wert

    def update_limits(self, dp_limit: float, dp_clean: float):
        """Aktualisiert die Grenzwerte ohne Neustart."""
        self.dp_limit = dp_limit
        self.dp_clean = dp_clean

    # ------------------------------------------------------------------
    # Ausgabe
    # ------------------------------------------------------------------

    def get_status(self, remaining_seconds: Optional[float],
                   heta_activated: bool,
                   profile_valid: bool,
                   learned_cycles: int,
                   required_cycles: int = 3) -> dict:
        """
        Gibt das vollständige Prognose-Statusobjekt zurück.

        Modus-Logik:
          HETA_VALIDIERT  → heta_activated + profile_valid
          HETA_LERNEND    → heta_activated, aber noch nicht genug Zyklen
          BASIS           → kein HETA-Code aktiv
        """
        if heta_activated and profile_valid:
            mode = MODE_VALIDIERT
        elif heta_activated:
            mode = MODE_LERNEND
        else:
            mode = MODE_BASIS

        display = self._format_for_mode(remaining_seconds, mode)

        return {
            "remaining_seconds": round(remaining_seconds, 0) if remaining_seconds is not None else None,
            "remaining_display": display,
            "prediction_mode": mode,
            "smoothed": self._last_remaining is not None,
            "learned_cycles": learned_cycles,
            "required_cycles": required_cycles,
        }

    def _format_for_mode(self, seconds: Optional[float], mode: str) -> str:
        """Wählt die passende Formatierung je nach Anzeigemodus."""
        if seconds is None:
            return "Wird berechnet …"
        if mode == MODE_VALIDIERT:
            return _format_validated(seconds)
        return _format_basis_range(seconds)
