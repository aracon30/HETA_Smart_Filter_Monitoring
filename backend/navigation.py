"""
Navigationsmodul – Adafruit ANO Rotary Navigation Encoder Breakout.

Direkte GPIO-Anbindung via gpiozero (kein I2C/Seesaw erforderlich).

Verdrahtung:
  COMA und COMB an GND anschließen – die internen Pull-ups des Raspberry Pi
  werden dann für alle Signalleitungen verwendet.

Pinbelegung (BCM-Nummerierung, konfigurierbar in config/settings.json):
  ENCA → encoder_pin_enca  (Standard: 16)
  ENCB → encoder_pin_encb  (Standard: 20)
  SW1  → encoder_pin_sw1   (Standard: 21) – Drücken / OK (Mitte)
  SW2  → encoder_pin_sw2   (Standard: 12) – Unten
  SW3  → encoder_pin_sw3   (Standard: 13) – Rechts
  SW4  → encoder_pin_sw4   (Standard: 19) – Oben
  SW5  → encoder_pin_sw5   (Standard: 26) – Links
  COMA → GND  (kein GPIO erforderlich)
  COMB → GND  (kein GPIO erforderlich)
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class NavigationEvent:
    """Repräsentiert ein einzelnes Navigationsereignis."""

    ROTATE_LEFT = "ROTATE_LEFT"
    ROTATE_RIGHT = "ROTATE_RIGHT"
    PRESS = "PRESS"  # SW1 – Mitte / OK
    LEFT = "LEFT"  # SW5
    RIGHT = "RIGHT"  # SW3
    UP = "UP"  # SW4
    DOWN = "DOWN"  # SW2


class NavigationController:
    """
    Liest den ANO Rotary Encoder via direkter GPIO-Verbindung (gpiozero).

    gpiozero verwendet unter Raspberry Pi OS automatisch den lgpio-Backend
    (Pi 5) oder pigpio/RPi.GPIO (Pi 4 und älter) – kein manuelles Backend-
    Setup erforderlich.

    Fällt bei fehlender Hardware auf Dummy-Modus zurück.
    """

    def __init__(
        self,
        pin_enca: int = 16,
        pin_encb: int = 20,
        pin_sw1: int = 21,
        pin_sw2: int = 12,
        pin_sw3: int = 13,
        pin_sw4: int = 19,
        pin_sw5: int = 26,
    ):
        self._hw: dict | None = None
        self._simulated = False
        self._handlers: list[Callable] = []
        self._running = False

        try:
            self._init_hardware(pin_enca, pin_encb, pin_sw1, pin_sw2, pin_sw3, pin_sw4, pin_sw5)
        except Exception as e:
            logger.warning("ANO Encoder GPIO nicht verfügbar: %s – Simulationsmodus.", e)
            self._simulated = True

    # ------------------------------------------------------------------
    # Hardware-Initialisierung
    # ------------------------------------------------------------------

    def _init_hardware(self, enca: int, encb: int, sw1: int, sw2: int, sw3: int, sw4: int, sw5: int):
        from gpiozero import Button, RotaryEncoder  # type: ignore

        encoder = RotaryEncoder(a=enca, b=encb, max_steps=None, bounce_time=0.002)
        encoder.when_rotated_clockwise = lambda: self._dispatch(NavigationEvent.ROTATE_RIGHT)
        encoder.when_rotated_counter_clockwise = lambda: self._dispatch(NavigationEvent.ROTATE_LEFT)

        pin_event_map = [
            (sw1, NavigationEvent.PRESS),
            (sw2, NavigationEvent.DOWN),
            (sw3, NavigationEvent.RIGHT),
            (sw4, NavigationEvent.UP),
            (sw5, NavigationEvent.LEFT),
        ]
        buttons = []
        for pin, event in pin_event_map:
            btn = Button(pin, pull_up=True, bounce_time=0.05)
            btn.when_pressed = lambda ev=event: self._dispatch(ev)
            buttons.append(btn)

        self._hw = {"encoder": encoder, "buttons": buttons}
        logger.info(
            "ANO Encoder initialisiert – ENCA=GPIO%d ENCB=GPIO%d "
            "SW1=GPIO%d SW2=GPIO%d SW3=GPIO%d SW4=GPIO%d SW5=GPIO%d.",
            enca,
            encb,
            sw1,
            sw2,
            sw3,
            sw4,
            sw5,
        )

    # ------------------------------------------------------------------
    # Handler-Verwaltung
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, poll_interval: float = 0.05):
        """
        Startet den Navigations-Controller.

        Im GPIO-Modus werden Ereignisse über Interrupts ausgelöst (gpiozero),
        kein aktiver Poll-Thread erforderlich.
        """
        self._running = True
        mode = "Simulationsmodus" if self._simulated else "GPIO-Interrupt-Modus"
        logger.info("Navigations-Controller gestartet (%s).", mode)

    def stop(self):
        """Gibt alle GPIO-Ressourcen frei."""
        self._running = False
        if self._hw:
            try:
                self._hw["encoder"].close()
                for btn in self._hw["buttons"]:
                    btn.close()
            except Exception as exc:
                logger.debug("Encoder cleanup: %s", exc)

    # ------------------------------------------------------------------
    # Simulations-API (für Weboberfläche und Tests)
    # ------------------------------------------------------------------

    def simulate_event(self, event: str):
        """
        Simuliert ein Navigationsereignis programmatisch.
        Wird von der REST-API genutzt um Hardware zu simulieren.
        """
        valid = {
            NavigationEvent.ROTATE_LEFT,
            NavigationEvent.ROTATE_RIGHT,
            NavigationEvent.PRESS,
            NavigationEvent.LEFT,
            NavigationEvent.RIGHT,
            NavigationEvent.UP,
            NavigationEvent.DOWN,
        }
        if event in valid:
            self._dispatch(event)
        else:
            logger.warning("Unbekanntes Navigationsereignis: %s", event)

    # ------------------------------------------------------------------
    # Diagnose
    # ------------------------------------------------------------------

    def get_encoder_steps(self) -> int | None:
        """Gibt die aktuelle Encoder-Schrittposition zurück (für Diagnose)."""
        if self._hw:
            try:
                return self._hw["encoder"].steps
            except Exception:
                return None
        return None

    @property
    def is_simulated(self) -> bool:
        return self._simulated
