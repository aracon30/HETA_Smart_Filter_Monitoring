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
    """
    Minutengenaue Ausgabe für den validierten HETA-Modus.
    Bei > 1 Stunde wird in Stunden und Minuten ausgegeben.
    """
    total_min = int(seconds / 60)
    if total_min <= 0:
        return "< 1 min"
    if total_min >= 60:
        h = total_min // 60
        m = total_min % 60
        return f"{h} Std. {m} min" if m > 0 else f"{h} Std."
    return f"{total_min} min"


class PredictionEngine:
    """
    Berechnet und glättet die Reststandzeit des Filters.

    Große Sprünge nach oben werden stark gedämpft (max. +2 %/Update),
    fallende Werte dürfen schneller reagieren (max. -8 %/Update).
    """

    def __init__(
        self,
        dp_limit: float,
        dp_clean: float,
        smoothing_factor: float = 0.15,
        max_increase_pct: float = 2.0,
        max_decrease_pct: float = 8.0,
        min_slope: float = 0.001,
    ):
        self.dp_limit = dp_limit
        self.dp_clean = dp_clean
        self.smoothing_factor = smoothing_factor
        self.max_increase_pct = max_increase_pct / 100.0
        self.max_decrease_pct = max_decrease_pct / 100.0
        self.min_slope = min_slope

        self._smoothed_remaining: Optional[float] = None
        self._dp_history: list[float] = []
        self._history_window: int = 30

    def update(self, dp_bar: float) -> Optional[float]:
        """
        Nimmt den aktuellen Differenzdruck entgegen und gibt die
        geglättete Reststandzeit in Sekunden zurück (oder None wenn nicht berechenbar).
        """
        self._dp_history.append(dp_bar)
        if len(self._dp_history) > self._history_window:
            self._dp_history.pop(0)

        slope = self._calculate_slope()
        if slope is None or slope <= 0:
            return self._smoothed_remaining

        raw_remaining = (self.dp_limit - dp_bar) / max(slope, self.min_slope)

        if self._smoothed_remaining is None:
            # Startwert nur übernehmen wenn plausibel (≥ 60 s),
            # um ein "Stuck near zero" nach Reset durch Rauschen zu vermeiden.
            if raw_remaining >= 60:
                self._smoothed_remaining = raw_remaining
            return self._smoothed_remaining
        else:
            self._smoothed_remaining = self._apply_smoothing(
                self._smoothed_remaining, raw_remaining
            )

        return self._smoothed_remaining

    def _calculate_slope(self) -> Optional[float]:
        """Lineare Regression über das dp-Messfenster (1 Index = 1 Sekunde)."""
        n = len(self._dp_history)
        if n < 5:
            return None
        x_mean = (n - 1) / 2.0
        y_mean = sum(self._dp_history) / n
        numerator   = sum((i - x_mean) * (self._dp_history[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return None
        return max(numerator / denominator, 0.0)

    def _apply_smoothing(self, current: float, new_raw: float) -> float:
        """Exponentielle Glättung mit asymmetrischer Sprungbegrenzung."""
        if new_raw > current:
            new_raw = min(new_raw, current * (1.0 + self.max_increase_pct))
        else:
            new_raw = max(new_raw, current * (1.0 - self.max_decrease_pct))
        return current + self.smoothing_factor * (new_raw - current)

    def reset(self):
        """Setzt die Prognose zurück (z.B. nach Filterwechsel oder Neukonfiguration)."""
        self._smoothed_remaining = None
        self._dp_history.clear()

    def seed(self, initial_seconds: float):
        """
        Setzt einen Startwert direkt nach dem Reset, wenn ein valides Lernprofil
        vorliegt. Verhindert 'Wird berechnet…' und ermöglicht sofortige Anzeige.
        """
        if initial_seconds > 60:
            self._smoothed_remaining = initial_seconds
            self._dp_history.clear()
            logger.info("Prognose-Startwert aus Profil: %.0f s", initial_seconds)

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
            "smoothed": self._smoothed_remaining is not None,
            "learned_cycles": learned_cycles,
            "required_cycles": required_cycles,
        }

    def _format_for_mode(self, seconds: Optional[float], mode: str) -> str:
        """Wählt die passende Formatierung je nach Anzeigemodus."""
        if seconds is None:
            return "Wird berechnet …"

        if mode == MODE_VALIDIERT:
            # Minutengenaue Angabe nur für validierte HETA-Elemente
            return _format_validated(seconds)

        if mode == MODE_LERNEND:
            # Breite Bereiche während der Lernphase
            return _format_basis_range(seconds)

        # BASIS – adaptive Bereiche, keine Minutenangaben
        return _format_basis_range(seconds)
