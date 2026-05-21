"""
Sensormodul – liest analoge Kanäle vom AnoPi Shield oder simuliert Werte.

Kanalbelegung:
  Kanal 1 → Eintrittsdruck p1  (ifm PL5423, 0–10 bar)
  Kanal 2 → Austrittsdruck p2  (ifm PL5423, 0–10 bar)
  Kanal 3 → Temperatur T        (ifm TA2405, -50–150 °C)
  Kanal 4 → Durchfluss Q        (Keyence FD-X, 0–150 l/min)

Alle Sensoren liefern 4–20 mA Signale.
"""

import math
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Fehlerzustands-Konstanten
SENSOR_OK = "OK"
SENSOR_WIRE_BREAK = "KABELBRUCH"      # mA < 3.6  → Unterschreitung Unterbereich
SENSOR_UNDERRANGE = "UNTERBEREICH"    # mA < 4.0  → unterhalb Messbereich
SENSOR_OVERRANGE = "UEBERBEREICH"     # mA > 20.5 → oberhalb Messbereich

# Gültigkeitsgrenzen in mA
MA_WIRE_BREAK_LIMIT = 3.6
MA_UNDERRANGE_LIMIT = 4.0
MA_OVERRANGE_LIMIT = 20.5
MA_MIN = 4.0
MA_MAX = 20.0


@dataclass
class SensorReading:
    """Enthält den skalierten Messwert eines einzelnen Kanals."""
    channel: int
    raw_ma: float
    value: float
    unit: str
    status: str = SENSOR_OK
    timestamp: float = field(default_factory=time.time)

    @property
    def is_valid(self) -> bool:
        return self.status == SENSOR_OK


def _check_status(ma: float) -> str:
    """Prüft den mA-Wert auf Sensorfehler."""
    if ma < MA_WIRE_BREAK_LIMIT:
        return SENSOR_WIRE_BREAK
    if ma < MA_UNDERRANGE_LIMIT:
        return SENSOR_UNDERRANGE
    if ma > MA_OVERRANGE_LIMIT:
        return SENSOR_OVERRANGE
    return SENSOR_OK


def _scale_pressure(ma: float, range_bar: float = 10.0) -> float:
    """Skaliert 4–20 mA auf 0–range_bar."""
    return ((ma - MA_MIN) / (MA_MAX - MA_MIN)) * range_bar


def _scale_temperature(ma: float, t_min: float = -50.0, t_max: float = 150.0) -> float:
    """Skaliert 4–20 mA auf t_min–t_max °C."""
    return t_min + ((ma - MA_MIN) / (MA_MAX - MA_MIN)) * (t_max - t_min)


def _scale_flow(ma: float, flow_max: float = 150.0) -> float:
    """Skaliert 4–20 mA auf 0–flow_max l/min."""
    return ((ma - MA_MIN) / (MA_MAX - MA_MIN)) * flow_max


# ---------------------------------------------------------------------------
# Hardware-Lesefunktion (AnoPi Shield via SPI/ADC)
# ---------------------------------------------------------------------------

def _read_anopi_channel(channel: int) -> Optional[float]:
    """
    Liest einen analogen Kanal vom AnoPi Shield via SPI-ADC (MCP3208, 12 Bit).
    Gibt den skalierten mA-Wert (4–20 mA) zurück oder None bei Hardwarefehler.

    Skalierung: ADC 0–4095 → 0–3,3 V → 0–20 mA (Shunt 165 Ω, 3,3 V Referenz).
    Kanal-Nummerierung: 1-basiert (wird intern auf 0-basiert umgerechnet).
    """
    try:
        import spidev  # type: ignore
        spi = spidev.SpiDev()
        spi.open(0, 0)
        spi.max_speed_hz = 1_350_000
        ch0 = channel - 1  # AnoPi-Kanäle sind 0-basiert im SPI-Protokoll
        adc_val = spi.xfer2([1, (8 + ch0) << 4, 0])
        spi.close()
        raw = ((adc_val[1] & 3) << 8) + adc_val[2]
        voltage = (raw / 4095.0) * 3.3
        ma = (voltage / 3.3) * 20.0  # 0–3,3 V → 0–20 mA
        return max(0.0, min(25.0, ma))
    except Exception as e:
        logger.debug("AnoPi Kanal %d Lesefehler: %s", channel, e)
        return None


def probe_hardware() -> bool:
    """
    Prüft beim Programmstart ob das AnoPi Shield (SPI) erreichbar ist.
    Gibt True zurück wenn Hardware erkannt wurde, sonst False.
    Löst keine Exception aus – immer sicher aufrufbar.
    """
    try:
        import spidev  # type: ignore
        spi = spidev.SpiDev()
        spi.open(0, 0)
        spi.close()
        logger.info("Hardware-Probe: AnoPi Shield auf SPI(0,0) erkannt – Realbetrieb möglich.")
        return True
    except Exception as e:
        logger.info("Hardware-Probe: AnoPi Shield nicht erreichbar (%s) – Simulation verfügbar.",
                    type(e).__name__)
        return False


# Sensorkanalbezeichnungen für Fehlermeldungen
_CHANNEL_NAMES = {
    1: "p1 (Eintrittsdruck)",
    2: "p2 (Austrittsdruck)",
    3: "T (Temperatur)",
    4: "Q (Durchfluss)",
}


def check_hardware_sensors() -> dict:
    """
    Prüft alle 4 Sensorkanäle auf Erreichbarkeit (z. B. nach Bediener-Bestätigung).
    Gibt zurück: {'all_ok': bool, 'failed_channels': list, 'failed_names': list}.
    """
    failed = []
    for ch in range(1, 5):
        if _read_anopi_channel(ch) is None:
            failed.append(ch)
    return {
        "all_ok": len(failed) == 0,
        "failed_channels": failed,
        "failed_names": [_CHANNEL_NAMES.get(ch, f"Kanal {ch}") for ch in failed],
    }


class FilterSimulator:
    """
    Szenariobasierter Filterbeladungs-Simulator.

    Feste Basiswerte: p1_base, q_base, t_base (aus Konfiguration).
    Einstellbare Szenarien: dirt_rate_factor, p1_trend_factor,
                            flow_drop_factor, temp_trend_per_cycle.

    clogging ∈ [0, 1] wächst zeitbasiert:
        clogging += dirt_rate_factor * _BASE_CLOGGING_RATE * delta_t

    _BASE_CLOGGING_RATE = 1/300 → Bei dirt_rate_factor=1.0 dauert ein Zyklus ~300 s.
    Die Zyklusdauer ergibt sich ausschließlich aus Beladungsintensität und Filterphysik.
    """

    _BASE_CLOGGING_RATE = 1.0 / 300.0  # 1.0 = normaler Schmutzeintrag → ~300 s / Zyklus

    def __init__(self, dp_clean: float = 0.2, dp_limit: float = 2.5,
                 flow_max: float = 150.0):
        self.dp_clean      = dp_clean
        self.dp_limit      = dp_limit
        self.flow_max      = flow_max   # Sensor-Maximalbereich (nicht Q_base)
        self._lock         = threading.Lock()
        # Feste Basiswerte (aus Konfiguration gesetzt)
        self._p1_base = 4.0
        self._q_base  = 145.0
        self._t_base  = 25.0
        # Szenario-Parameter (einstellbar)
        self._dirt_rate_factor    = 1.0   # 1.0 = Referenzrate
        self._p1_trend_factor     = 0.0   # 0.0 = stabil, +0.1 = steigt 10 % über Zyklus
        self._flow_drop_factor    = 0.75  # 0.75 = normaler Abfall
        self._temp_trend_per_cycle = 0.0  # °C-Änderung über Zyklus
        # Interner Zustand
        self._clogging    = 0.0
        self._last_time   = None
        self._rates_active = False

    def estimated_cycle_secs(self) -> float:
        """Geschätzte Zyklusdauer in Sekunden (abhängig vom aktuellen dirt_rate_factor)."""
        with self._lock:
            return 1.0 / (max(self._dirt_rate_factor, 0.01) * self._BASE_CLOGGING_RATE)

    def reset(self):
        """Setzt nur Beladungszustand zurück – Szenarien bleiben."""
        with self._lock:
            self._clogging  = 0.0
            self._last_time = None

    def full_reset(self):
        """Vollständiger Reset inkl. Szenario-Parameter."""
        with self._lock:
            self._clogging             = 0.0
            self._last_time            = None
            self._dirt_rate_factor     = 1.0
            self._p1_trend_factor      = 0.0
            self._flow_drop_factor     = 0.75
            self._temp_trend_per_cycle = 0.0
            self._rates_active         = False

    def set_scenario_params(self, dirt_rate_factor: float,
                            p1_trend_factor: float,
                            flow_drop_factor: float,
                            temp_trend_per_cycle: float):
        """Setzt Szenario-Parameter – kein Zyklus-Reset erforderlich."""
        with self._lock:
            self._dirt_rate_factor     = max(0.05, dirt_rate_factor)
            self._p1_trend_factor      = max(-0.5,  min(0.5, p1_trend_factor))
            self._flow_drop_factor     = max(0.10,  min(0.99, flow_drop_factor))
            self._temp_trend_per_cycle = max(-20.0, min(20.0, temp_trend_per_cycle))
            self._rates_active         = True

    def clear_scenario_params(self):
        """Setzt alle Szenario-Parameter auf Normalbetrieb zurück."""
        with self._lock:
            self._dirt_rate_factor     = 1.0
            self._p1_trend_factor      = 0.0
            self._flow_drop_factor     = 0.75
            self._temp_trend_per_cycle = 0.0
            self._rates_active         = False

    @property
    def rates_active(self) -> bool:
        with self._lock:
            return self._rates_active

    def get_scenario_params(self) -> dict:
        """Gibt aktuelle Szenario-Parameter zurück (für quick-learn)."""
        with self._lock:
            return {
                "p1_base":              self._p1_base,
                "q_base":               self._q_base,
                "t_base":               self._t_base,
                "dirt_rate_factor":     self._dirt_rate_factor,
                "p1_trend_factor":      self._p1_trend_factor,
                "flow_drop_factor":     self._flow_drop_factor,
                "temp_trend_per_cycle": self._temp_trend_per_cycle,
            }

    def get_readings(self) -> dict:
        """Berechnet physikalische Werte aus aktuellem clogging-Zustand."""
        with self._lock:
            now = time.time()
            if self._last_time is None:
                delta_t = 0.0
            else:
                delta_t = max(0.0, now - self._last_time)
            self._last_time = now

            dirt_rate      = self._dirt_rate_factor * FilterSimulator._BASE_CLOGGING_RATE
            self._clogging = min(1.0, self._clogging + dirt_rate * delta_t)
            clogging       = self._clogging

            p1_base              = self._p1_base
            q_base               = self._q_base
            t_base               = self._t_base
            p1_trend_factor      = self._p1_trend_factor
            flow_drop_factor     = self._flow_drop_factor
            temp_trend_per_cycle = self._temp_trend_per_cycle
            dp_clean             = self.dp_clean
            dp_limit             = self.dp_limit

        # p1: Basiswert mit linearern Trend über den Zyklus
        p1 = round(p1_base * (1.0 + p1_trend_factor * clogging), 4)
        p1 = max(0.1, p1)

        # Δp: nichtlinearer Anstieg (Exponent 1.8 → exponentiell am Ende)
        dp = dp_clean + (dp_limit - dp_clean) * clogging ** 1.8
        dp = round(max(dp_clean, min(dp, dp_limit)), 4)

        # p2: immer automatisch
        p2 = round(max(0.0, p1 - dp), 4)

        # Q: sinkt mit Beladung, Minimum 10 % von Q_base
        q_min = max(1.0, q_base * 0.10)
        flow  = round(max(q_min, q_base * (1.0 - flow_drop_factor * clogging ** 1.5)), 2)

        # T: Basistemperatur + Trend über Zyklus + langsame Sinusdrift ±0,2 °C
        drift = 0.2 * math.sin(2.0 * math.pi * now / 600.0)
        temp  = round(t_base + temp_trend_per_cycle * clogging + drift, 2)

        return {"p1": p1, "p2": p2, "dp": dp, "flow": flow, "temp": temp}


# Modulweit geteilte Simulatorinstanz
_simulator = FilterSimulator()


def reset_simulation():
    """Setzt Beladungszustand zurück (Szenario-Parameter bleiben)."""
    _simulator.reset()
    logger.info("Filtersimulation zurückgesetzt.")


def full_reset_simulation():
    """Vollständiger Reset inkl. Szenario-Parameter."""
    _simulator.full_reset()
    logger.info("Filtersimulation vollständig zurückgesetzt.")


def update_simulation_params(dp_clean: float, dp_limit: float, flow_max: float,
                              p1_base: float = 4.0,
                              q_base: float = 145.0,
                              t_base: float = 25.0,
                              reset_clogging: bool = True):
    """
    Aktualisiert Basisparameter des Simulators.

    reset_clogging=True  → Beladung auf 0 zurücksetzen (Standard: nach Filterwechsel
                           oder wenn physikalisch relevante Parameter geändert wurden).
    reset_clogging=False → Beladungszustand beibehalten (z.B. beim App-Start oder
                           wenn sich nur Anzeigeeinstellungen ändern).
    """
    with _simulator._lock:
        _simulator.dp_clean  = dp_clean
        _simulator.dp_limit  = dp_limit
        _simulator.flow_max  = flow_max
        _simulator._p1_base  = p1_base
        _simulator._q_base   = q_base
        _simulator._t_base   = t_base
        if reset_clogging:
            _simulator._clogging  = 0.0
            _simulator._last_time = None


def set_simulation_scenario_params(dirt_rate_factor: float,
                                    p1_trend_factor: float,
                                    flow_drop_factor: float,
                                    temp_trend_per_cycle: float):
    """Setzt Szenario-Parameter direkt."""
    _simulator.set_scenario_params(
        dirt_rate_factor, p1_trend_factor,
        flow_drop_factor, temp_trend_per_cycle,
    )


def clear_simulation_rates():
    """Setzt Szenario auf Normalbetrieb zurück."""
    _simulator.clear_scenario_params()


def get_simulation_rates_active() -> bool:
    return _simulator.rates_active


def get_simulation_estimated_cycle_secs() -> float:
    """Geschätzte Zyklusdauer in Sekunden basierend auf aktuellem dirt_rate_factor."""
    return _simulator.estimated_cycle_secs()


def get_simulation_scenario_params() -> dict:
    """Gibt aktuelle Szenario-Parameter zurück."""
    return _simulator.get_scenario_params()


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------
# Exportiert: read_sensors, reset_simulation, update_simulation_params, probe_hardware

def read_sensors(simulation: bool = True,
                 pressure_range: float = 10.0,
                 temperature_min: float = -50.0,
                 temperature_max: float = 150.0,
                 flow_max: float = 150.0) -> dict:
    """
    Liest alle vier Sensorkanäle und gibt skalierte SensorReading-Objekte zurück.

    Rückgabe:
        {
          'p1': SensorReading,
          'p2': SensorReading,
          'temperature': SensorReading,
          'flow': SensorReading,
          'mode': 'simulation' | 'hardware'
        }
    """
    if simulation:
        # Exakte physikalische Werte direkt verwenden – keine mA-Konversion.
        # "dp_direct" enthält den Primärwert des Simulators: kein Gleitkomma-
        # Subtraktionsartefakt durch p1-p2 in der Berechnungsebene.
        phys = _simulator.get_readings()
        return {
            "p1":          SensorReading(1, 0.0, phys["p1"],   "bar"),
            "p2":          SensorReading(2, 0.0, phys["p2"],   "bar"),
            "temperature": SensorReading(3, 0.0, phys["temp"], "°C"),
            "flow":        SensorReading(4, 0.0, phys["flow"], "l/min"),
            "dp_direct":   phys["dp"],
            "mode": "simulation",
        }

    # Realbetrieb: alle 4 SPI-Kanäle lesen, bei Fehler Messung sofort stoppen.
    # Kein Simulations-Fallback im Hardwaremodus – verfälschte Messwerte sind
    # im Produktionsbetrieb nicht akzeptabel.
    ma_values: dict = {}
    failed_channels = []
    for ch in range(1, 5):
        val = _read_anopi_channel(ch)
        if val is None:
            failed_channels.append(ch)
        else:
            ma_values[ch] = val

    if failed_channels:
        names = [_CHANNEL_NAMES.get(ch, f"Kanal {ch}") for ch in failed_channels]
        logger.error(
            "Sensorfehler auf Kanal(en) %s (%s) – Messung wird gestoppt.",
            failed_channels, ", ".join(names),
        )
        return {
            "p1":          SensorReading(1, 0.0, float("nan"), "bar",   SENSOR_WIRE_BREAK),
            "p2":          SensorReading(2, 0.0, float("nan"), "bar",   SENSOR_WIRE_BREAK),
            "temperature": SensorReading(3, 0.0, float("nan"), "°C",   SENSOR_WIRE_BREAK),
            "flow":        SensorReading(4, 0.0, float("nan"), "l/min", SENSOR_WIRE_BREAK),
            "mode": "sensor_fault",
            "failed_channels": failed_channels,
            "failed_names": names,
        }

    def make_reading(channel, ma, scale_fn, unit):
        status = _check_status(ma)
        value = scale_fn(ma) if status == SENSOR_OK else float("nan")
        return SensorReading(channel=channel, raw_ma=ma, value=value,
                             unit=unit, status=status)

    return {
        "p1": make_reading(1, ma_values[1],
                           lambda m: _scale_pressure(m, pressure_range), "bar"),
        "p2": make_reading(2, ma_values[2],
                           lambda m: _scale_pressure(m, pressure_range), "bar"),
        "temperature": make_reading(3, ma_values[3],
                                    lambda m: _scale_temperature(m, temperature_min, temperature_max),
                                    "°C"),
        "flow": make_reading(4, ma_values[4],
                             lambda m: _scale_flow(m, flow_max), "l/min"),
        "mode": "hardware",
    }
