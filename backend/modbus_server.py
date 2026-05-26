"""
Modbus-TCP-Server – optionale Anbindung an SPS / SCADA-Systeme.

Registermap (Holding Registers, ab Adresse 0):
  Reg  0  – p1_bar          × 1000  → Integer [mbar]
  Reg  1  – p2_bar          × 1000  → Integer [mbar]
  Reg  2  – dp_bar          × 10000 → Integer [0.1 mbar]
  Reg  3  – flow_l_min      × 10    → Integer [0.1 l/min]
  Reg  4  – temperature_c   × 10    → Integer [0.1 °C]  (Offset +500 für neg. Werte)
  Reg  5  – r_eff           × 1000  → Integer [µ(bar·min/l)]
  Reg  6  – filter_health_percent × 10 → Integer [0.1 %]
  Reg  7  – remaining_seconds     → Integer [s]  (0xFFFF = unbekannt)
  Reg  8  – alarm_flag            → 0=OK / 1=WECHSEL / 2=FEHLER
  Reg  9  – cycle_count           → Integer
  Reg 10  – status_code           → 0=INIT / 1=LAUFEND / 2=WECHSEL / 3=FEHLER

Alle Werte sind unsigned 16-bit (0–65535).
Negativtemperaturen: Reg 4 = Wert + 500  (z.B. -10.5 °C → 395)
Unbekannte Werte:    0xFFFF (65535)
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Registeradressen
REG_P1          = 0
REG_P2          = 1
REG_DP          = 2
REG_FLOW        = 3
REG_TEMP        = 4
REG_REFF        = 5
REG_HEALTH      = 6
REG_REMAINING   = 7
REG_ALARM       = 8
REG_CYCLE_COUNT = 9
REG_STATUS_CODE = 10
REG_COUNT       = 11

_STATUS_CODES = {
    "INIT":    0,
    "LAUFEND": 1,
    "WECHSEL": 2,
    "FEHLER":  3,
}

_UNKNOWN = 0xFFFF


def _clamp(value: int) -> int:
    return max(0, min(0xFFFE, value))


def _encode_float(value, factor: int, offset: int = 0) -> int:
    if value is None:
        return _UNKNOWN
    return _clamp(int(round(value * factor)) + offset)


class ModbusTCPServer:
    """
    Optionaler Modbus-TCP-Slave basierend auf pymodbus.
    Wird nur gestartet wenn modbus_enabled=true in settings.json.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 502):
        self._host = host
        self._port = port
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._context = None
        self._running = False

    def start(self) -> bool:
        """Startet den Modbus-TCP-Server im Hintergrundthread."""
        try:
            from pymodbus.datastore import (          # type: ignore
                ModbusSequentialDataBlock,
                ModbusSlaveContext,
                ModbusServerContext,
            )
            from pymodbus.server import StartTcpServer  # type: ignore

            block = ModbusSequentialDataBlock(0, [0] * REG_COUNT)
            slave = ModbusSlaveContext(hr=block)
            self._context = ModbusServerContext(slaves=slave, single=True)

            self._running = True
            self._thread = threading.Thread(
                target=self._run,
                args=(StartTcpServer,),
                daemon=True,
                name="modbus-tcp",
            )
            self._thread.start()
            # kurz warten, damit der Port gebunden wird
            time.sleep(0.3)
            logger.info("Modbus-TCP-Server gestartet auf %s:%d", self._host, self._port)
            return True
        except ImportError:
            logger.warning("pymodbus nicht installiert – Modbus-TCP deaktiviert. "
                           "pip install pymodbus")
            return False
        except Exception as e:
            logger.error("Modbus-TCP-Server Startfehler: %s", e)
            return False

    def _run(self, StartTcpServer):
        try:
            StartTcpServer(
                context=self._context,
                address=(self._host, self._port),
            )
        except Exception as e:
            if self._running:
                logger.error("Modbus-TCP-Server Fehler: %s", e)

    def stop(self):
        self._running = False
        if self._server:
            try:
                self._server.server_close()
            except Exception:
                pass
        logger.info("Modbus-TCP-Server gestoppt.")

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def update(self, filter_state, state: dict):
        """
        Schreibt aktuelle Messwerte in die Holding-Register.
        Wird aus dem Messloop nach jedem Zyklus aufgerufen.
        """
        if self._context is None:
            return
        try:
            regs = [0] * REG_COUNT

            regs[REG_P1]    = _encode_float(filter_state.p1_bar,  1000)
            regs[REG_P2]    = _encode_float(filter_state.p2_bar,  1000)
            regs[REG_DP]    = _encode_float(filter_state.dp_bar,  10000)
            regs[REG_FLOW]  = _encode_float(filter_state.flow_l_min, 10)
            # Temperatur: Offset 500 für negative Werte (-50..150 °C)
            regs[REG_TEMP]  = _encode_float(filter_state.temperature_c, 10, offset=500)
            regs[REG_REFF]  = _encode_float(filter_state.r_eff,  1000)

            health = state.get("filter_health_percent")
            regs[REG_HEALTH] = _encode_float(health, 10)

            remaining = state.get("remaining_seconds")
            regs[REG_REMAINING] = _clamp(int(remaining)) if remaining is not None else _UNKNOWN

            status = filter_state.status or "INIT"
            regs[REG_STATUS_CODE] = _STATUS_CODES.get(status, 0)
            regs[REG_ALARM] = 1 if status == "WECHSEL" else (2 if status == "FEHLER" else 0)

            regs[REG_CYCLE_COUNT] = _clamp(state.get("cycle_count", 0))

            self._context[0].setValues(3, 0, regs)
        except Exception as e:
            logger.warning("Modbus register update Fehler: %s", e)
