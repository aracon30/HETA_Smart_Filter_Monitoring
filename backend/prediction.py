"""
Prognose-Modul – berechnet die Reststandzeit des Filters.

Zwei Modi:
  Basis-Modus       – Ausgabe als Bereich in 10-Minuten-Schritten (z.B. "80–90 min")
  Validierter Modus – konkreter geglätteter Wert (z.B. "112 min")
"""

import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PredictionEngine:
    """
    Glättet die Reststandzeit und begrenzt unplausible Sprünge.

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
        self._history_window: int = 30  # Anzahl Werte für Steigungsberechnung

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
            self._smoothed_remaining = raw_remaining
        else:
            self._smoothed_remaining = self._apply_smoothing(
                self._smoothed_remaining, raw_remaining
            )

        return self._smoothed_remaining

    def _calculate_slope(self) -> Optional[float]:
        """Berechnet die dp-Steigung als Differenz pro Sekunde über den Messfenster."""
        n = len(self._dp_history)
        if n < 5:
            return None
        # Einfache lineare Regression über die letzten N Werte
        # (Index als Zeiteinheit, 1 Einheit = 1 Sekunde)
        x_mean = (n - 1) / 2.0
        y_mean = sum(self._dp_history) / n
        numerator = sum((i - x_mean) * (self._dp_history[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return None
        slope = numerator / denominator
        return max(slope, 0.0)

    def _apply_smoothing(self, current: float, new_raw: float) -> float:
        """Wendet exponentielle Glättung mit Sprungbegrenzung an."""
        # Sprung nach oben begrenzen
        if new_raw > current:
            max_allowed = current * (1.0 + self.max_increase_pct)
            new_raw = min(new_raw, max_allowed)
        # Sprung nach unten begrenzen
        else:
            min_allowed = current * (1.0 - self.max_decrease_pct)
            new_raw = max(new_raw, min_allowed)
        return current + self.smoothing_factor * (new_raw - current)

    def reset(self):
        """Setzt die Prognose zurück (z.B. nach Filterwechsel)."""
        self._smoothed_remaining = None
        self._dp_history.clear()

    def update_limits(self, dp_limit: float, dp_clean: float):
        """Aktualisiert die Grenzwerte ohne Neustart."""
        self.dp_limit = dp_limit
        self.dp_clean = dp_clean

    # ------------------------------------------------------------------
    # Ausgabeformatierung
    # ------------------------------------------------------------------

    def format_remaining(self, remaining_seconds: Optional[float],
                          validated_mode: bool) -> str:
        """
        Formatiert die Reststandzeit abhängig vom Modus.

        Basis-Modus:     Bereich in 10-Minuten-Schritten (z.B. "80–90 min")
        Validiert-Modus: Konkreter Wert                  (z.B. "112 min")
        """
        if remaining_seconds is None or remaining_seconds < 0:
            return "Unbekannt"

        remaining_min = remaining_seconds / 60.0

        if validated_mode:
            return f"{int(remaining_min)} min"
        else:
            # Auf nächste 10 Minuten abrunden
            lower = int(remaining_min // 10) * 10
            upper = lower + 10
            return f"{lower}–{upper} min"

    def get_status(self, remaining_seconds: Optional[float],
                   validated_mode: bool) -> dict:
        """Gibt das vollständige Prognose-Statusobjekt zurück."""
        display = self.format_remaining(remaining_seconds, validated_mode)
        return {
            "remaining_seconds": round(remaining_seconds, 0) if remaining_seconds is not None else None,
            "remaining_display": display,
            "prediction_mode": "HETA_VALIDIERT" if validated_mode else "BASIS",
            "smoothed": self._smoothed_remaining is not None,
        }
