"""
Navigationsmodul – Adafruit ANO Rotary Encoder I2C Adapter.

Steuert Menünavigation, Werteeingabe und Bestätigungen am Feldgerät.
Fällt bei fehlender Hardware auf Tastatur-Simulation zurück.
"""

import time
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Adafruit ANO Seesaw I2C Adresse (Standard)
ANO_I2C_ADDRESS = 0x49

# Tastenbelegung (Seesaw Pin-Nummern)
BTN_SELECT = 0   # Drücken / OK
BTN_LEFT   = 3
BTN_RIGHT  = 4
BTN_UP     = 2
BTN_DOWN   = 1

# Encoder-Schrittzähler-Delta
ENCODER_THRESHOLD = 1


class NavigationEvent:
    """Repräsentiert ein einzelnes Navigationsereignis."""
    ROTATE_LEFT  = "ROTATE_LEFT"
    ROTATE_RIGHT = "ROTATE_RIGHT"
    PRESS        = "PRESS"
    LEFT         = "LEFT"
    RIGHT        = "RIGHT"
    UP           = "UP"
    DOWN         = "DOWN"


class NavigationController:
    """
    Liest den ANO Rotary Encoder und gibt Ereignisse an registrierte Handler weiter.
    Fällt bei fehlender Hardware auf Dummy-Modus zurück.
    """

    def __init__(self, i2c_address: int = ANO_I2C_ADDRESS):
        self._seesaw = None
        self._simulated = False
        self._encoder_pos = 0
        self._button_states: dict[int, bool] = {
            BTN_SELECT: False,
            BTN_LEFT: False,
            BTN_RIGHT: False,
            BTN_UP: False,
            BTN_DOWN: False,
        }
        self._handlers: list[Callable] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

        try:
            self._init_hardware(i2c_address)
        except Exception as e:
            logger.warning("ANO Encoder nicht verfügbar: %s – Simulationsmodus.", e)
            self._simulated = True

    def _init_hardware(self, address: int):
        """Initialisiert den Adafruit Seesaw."""
        import board  # type: ignore
        import busio  # type: ignore
        from adafruit_seesaw.seesaw import Seesaw  # type: ignore
        from adafruit_seesaw.encoderbase import EncoderBase  # type: ignore

        i2c = busio.I2C(board.SCL, board.SDA)
        self._seesaw = Seesaw(i2c, addr=address)
        self._seesaw.pin_mode_bulk(
            (1 << BTN_SELECT) | (1 << BTN_LEFT) | (1 << BTN_RIGHT) |
            (1 << BTN_UP) | (1 << BTN_DOWN),
            self._seesaw.INPUT_PULLUP
        )
        self._encoder_pos = self._seesaw.encoder_position()
        logger.info("ANO Rotary Encoder initialisiert (I2C 0x%02X).", address)

    def register_handler(self, handler: Callable):
        """Registriert eine Callback-Funktion für Navigationsereignisse."""
        self._handlers.append(handler)

    def _dispatch(self, event: str):
        """Sendet ein Ereignis an alle registrierten Handler."""
        for handler in self._handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error("Fehler im Navigations-Handler: %s", e)

    def start(self, poll_interval: float = 0.05):
        """Startet den Hintergrund-Poll-Thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop,
                                        args=(poll_interval,), daemon=True)
        self._thread.start()
        logger.info("Navigations-Poll gestartet.")

    def stop(self):
        """Stoppt den Poll-Thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _poll_loop(self, interval: float):
        """Liest Encoder und Tasten im Intervall."""
        while self._running:
            try:
                if not self._simulated:
                    self._poll_hardware()
            except Exception as e:
                logger.debug("Encoder-Lesefehler: %s", e)
            time.sleep(interval)

    def _poll_hardware(self):
        """Liest Encoder-Position und Tastenzustände vom Seesaw."""
        if self._seesaw is None:
            return

        # Encoder
        new_pos = self._seesaw.encoder_position()
        delta = new_pos - self._encoder_pos
        if delta >= ENCODER_THRESHOLD:
            self._encoder_pos = new_pos
            self._dispatch(NavigationEvent.ROTATE_RIGHT)
        elif delta <= -ENCODER_THRESHOLD:
            self._encoder_pos = new_pos
            self._dispatch(NavigationEvent.ROTATE_LEFT)

        # Tasten (LOW = gedrückt wegen PULLUP)
        buttons_raw = self._seesaw.digital_read_bulk(
            (1 << BTN_SELECT) | (1 << BTN_LEFT) | (1 << BTN_RIGHT) |
            (1 << BTN_UP) | (1 << BTN_DOWN)
        )
        mapping = {
            BTN_SELECT: NavigationEvent.PRESS,
            BTN_LEFT:   NavigationEvent.LEFT,
            BTN_RIGHT:  NavigationEvent.RIGHT,
            BTN_UP:     NavigationEvent.UP,
            BTN_DOWN:   NavigationEvent.DOWN,
        }
        for pin, event in mapping.items():
            pressed = not bool(buttons_raw & (1 << pin))
            was_pressed = self._button_states[pin]
            if pressed and not was_pressed:
                self._dispatch(event)
            self._button_states[pin] = pressed

    # ------------------------------------------------------------------
    # Simulations-API (für Weboberfläche und Tests)
    # ------------------------------------------------------------------

    def simulate_event(self, event: str):
        """
        Simuliert ein Navigationsereignis programmatisch.
        Wird von der REST-API genutzt um Hardware zu simulieren.
        """
        valid = {NavigationEvent.ROTATE_LEFT, NavigationEvent.ROTATE_RIGHT,
                 NavigationEvent.PRESS, NavigationEvent.LEFT,
                 NavigationEvent.RIGHT, NavigationEvent.UP, NavigationEvent.DOWN}
        if event in valid:
            self._dispatch(event)
        else:
            logger.warning("Unbekanntes Navigationsereignis: %s", event)

    @property
    def is_simulated(self) -> bool:
        return self._simulated
