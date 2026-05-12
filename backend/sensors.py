"""
Sensormodul – liest analoge Kanäle vom AnoPi Shield oder simuliert Werte.

Kanalbelegung:
  Kanal 1 → Eintrittsdruck p1  (ifm PL5423, 0–10 bar)
  Kanal 2 → Austrittsdruck p2  (ifm PL5423, 0–10 bar)
  Kanal 3 → Temperatur T        (ifm TA2405, -50–150 °C)
  Kanal 4 → Durchfluss Q        (Keyence FD-X, 0–150 l/min)

Alle Sensoren liefern 4–20 mA Signale.
"""

import time
import math
import random
import logging
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


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

class FilterSimulator:
    """
    Simuliert einen realistischen Filterbeladungszyklus.
    Startet mit sauberem Filter und belädt ihn bis dp_limit.
    """

    def __init__(self, dp_clean: float = 0.2, dp_limit: float = 2.5,
                 cycle_seconds: float = 300.0, flow_max: float = 150.0):
        self.dp_clean = dp_clean
        self.dp_limit = dp_limit
        self.cycle_seconds = cycle_seconds
        self.flow_max = flow_max
        self._start_time = time.time()
        self._noise_seed = random.random()

    def reset(self):
        self._start_time = time.time()
        self._noise_seed = random.random()

    def _elapsed(self) -> float:
        return time.time() - self._start_time

    def get_ma_values(self) -> dict:
        """Gibt simulierte mA-Werte für alle vier Kanäle zurück."""
        elapsed = self._elapsed()
        progress = min(elapsed / self.cycle_seconds, 1.0)

        # Differenzdruck steigt S-förmig.
        # Die Schwingung wird über die ersten 60 s eingeblendet, damit
        # der Prädiktor am Zyklusanfang keinen falschen Slope-Spike bekommt.
        osc_ramp = min(elapsed / 60.0, 1.0)
        dp = self.dp_clean + (self.dp_limit - self.dp_clean) * (
            progress ** 1.5 + osc_ramp * 0.04 * math.sin(elapsed * 0.25)
        )
        dp += random.gauss(0, 0.008)
        dp = max(self.dp_clean * 0.9, min(dp, self.dp_limit * 1.02))

        # p1 schwankt leicht um 3.5 bar
        p1 = 3.5 + random.gauss(0, 0.03)
        p2 = max(0.0, p1 - dp)

        # Durchfluss sinkt mit steigendem Differenzdruck (physikalisches Modell:
        # zusetzendes Filter = höherer Widerstand = reduzierter Volumenstrom).
        # Bei dp_clean: ~53 % von flow_max; bei dp_limit: ~50 % davon (≈ Halbierung).
        flow_nominal = self.flow_max * 0.53
        dp_fraction = max(0.0, min(1.0,
            (dp - self.dp_clean) / max(self.dp_limit - self.dp_clean, 1e-6)))
        flow_base = flow_nominal * (1.0 - 0.50 * dp_fraction)
        flow = flow_base + random.gauss(0, 1.0)
        flow = max(0.0, min(self.flow_max, flow))

        # Temperatur steigt langsam von 20 auf 35 °C
        temp = 20.0 + progress * 15.0 + random.gauss(0, 0.2)

        def to_ma(value, v_min, v_max):
            ratio = (value - v_min) / (v_max - v_min)
            return MA_MIN + ratio * (MA_MAX - MA_MIN)

        return {
            1: to_ma(p1, 0.0, 10.0),
            2: to_ma(p2, 0.0, 10.0),
            3: to_ma(temp, -50.0, 150.0),
            4: to_ma(flow, 0.0, self.flow_max),
        }


# Modulweit geteilte Simulatorinstanz
_simulator = FilterSimulator()


def reset_simulation():
    """Startet die Filtersimulation neu."""
    _simulator.reset()
    logger.info("Filtersimulation zurückgesetzt.")


def update_simulation_params(dp_clean: float, dp_limit: float, flow_max: float,
                              cycle_seconds: float = 300.0):
    """Aktualisiert Simulationsparameter ohne Neustart."""
    _simulator.dp_clean = dp_clean
    _simulator.dp_limit = dp_limit
    _simulator.flow_max = flow_max
    _simulator.cycle_seconds = cycle_seconds


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
        ma_values = _simulator.get_ma_values()
        mode = "simulation"
    else:
        ma_values = {}
        for ch in range(1, 5):
            val = _read_anopi_channel(ch)
            if val is None:
                logger.warning("Kanal %d nicht lesbar – wechsle zu Simulation.", ch)
                ma_values = _simulator.get_ma_values()
                mode = "simulation_fallback"
                break
            ma_values[ch] = val
        else:
            mode = "hardware"

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
        "mode": mode,
    }
