"""
Display-Modul – steuert das 2.42"-OLED-Display über luma.oled.

Unterstützt SSD1309/SSD1306-kompatible Displays via SPI oder I2C.
Bei fehlender Hardware wird die Ausgabe simuliert (Textlog).
"""

import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Displayauflösung
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 64

# Bildschirmnamen
SCREEN_STATUS = "Status"
SCREEN_HETA = "HETA-Code"
SCREEN_FILTER_CHANGE = "Filterwechsel"
SCREEN_SERVICE = "Service"
SCREEN_HISTORY = "Historie"
SCREEN_NETWORK = "Netzwerk"

SCREENS = [SCREEN_STATUS, SCREEN_HETA, SCREEN_FILTER_CHANGE,
           SCREEN_SERVICE, SCREEN_HISTORY, SCREEN_NETWORK]


class OLEDDisplay:
    """
    Steuert das OLED-Display.
    Fällt bei fehlender Hardware auf Simulationsmodus zurück.
    """

    def __init__(self, use_spi: bool = True, spi_port: int = 0, spi_device: int = 0,
                 i2c_address: int = 0x3C):
        self._device = None
        self._font = None
        self._font_small = None
        self._simulated = False
        self._last_screen_text = ""
        self._current_screen = SCREEN_STATUS

        try:
            self._init_hardware(use_spi, spi_port, spi_device, i2c_address)
        except Exception as e:
            logger.warning("OLED-Hardware nicht verfügbar: %s – Simulationsmodus aktiv.", e)
            self._simulated = True

    def _init_hardware(self, use_spi, spi_port, spi_device, i2c_address):
        """Initialisiert luma.oled Hardware."""
        from PIL import ImageFont  # type: ignore
        from luma.core.render import canvas  # type: ignore  # noqa: F401

        if use_spi:
            from luma.oled.device import ssd1309  # type: ignore
            from luma.core.interface.serial import spi  # type: ignore
            serial = spi(port=spi_port, device=spi_device)
            self._device = ssd1309(serial, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)
        else:
            from luma.oled.device import ssd1306  # type: ignore
            from luma.core.interface.serial import i2c  # type: ignore
            serial = i2c(port=1, address=i2c_address)
            self._device = ssd1306(serial, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)

        try:
            self._font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
            self._font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8)
        except OSError:
            self._font = ImageFont.load_default()
            self._font_small = self._font

        logger.info("OLED-Display initialisiert (%s).", "SPI" if use_spi else "I2C")

    # ------------------------------------------------------------------
    # Bildschirme
    # ------------------------------------------------------------------

    def show_status(self, data: dict):
        """Zeigt den Haupt-Statusbildschirm."""
        self._current_screen = SCREEN_STATUS
        lines = [
            f"HETA: {data.get('heta_code', '---')}",
            f"Modus: {data.get('mode', 'SIM')}",
            f"p1:{data.get('p1', 0):.2f} p2:{data.get('p2', 0):.2f}bar",
            f"dp:{data.get('dp', 0):.3f}bar Q:{data.get('flow', 0):.0f}l",
            f"Res: {data.get('remaining', 'N/A')}",
            f"Status: {data.get('status', '-')}",
        ]
        self._render_lines(lines)

    def show_heta_code(self, heta_code: str, activated: bool):
        """Zeigt den HETA-Code-Bildschirm."""
        self._current_screen = SCREEN_HETA
        lines = [
            "--- HETA-Code ---",
            heta_code if heta_code else "(kein Code)",
            "Aktiviert: " + ("JA" if activated else "NEIN"),
            "",
            "OK=Eingabe",
        ]
        self._render_lines(lines)

    def show_filter_change(self, dp_bar: float, dp_limit: float,
                           armed: bool = False, awaiting: bool = False):
        """Zeigt den Filterwechsel-Bildschirm.

        armed=True  → erster OK-Druck empfangen, wartet auf Bestätigung
        awaiting    → System wartet auf Filterwechsel-Bestätigung
        """
        self._current_screen = SCREEN_FILTER_CHANGE
        if armed:
            lines = [
                "!! FILTERWECHSEL !!",
                f"dp: {dp_bar:.3f} bar",
                "Sicher? Nochmal OK",
                "zum Bestaetigen",
                "LINKS = Abbrechen",
            ]
        elif awaiting:
            lines = [
                "!! FILTERWECHSEL !!",
                f"dp: {dp_bar:.3f} bar",
                f"Limit: {dp_limit:.2f} bar",
                "",
                "OK = Bestaetigen",
            ]
        else:
            lines = [
                "Filterwechsel",
                f"dp: {dp_bar:.3f} bar",
                f"Limit: {dp_limit:.2f} bar",
                "",
                "OK = Bestaetigen",
            ]
        self._render_lines(lines)

    def show_service(self, message: str, priority: str):
        """Zeigt einen Servicehinweis."""
        self._current_screen = SCREEN_SERVICE
        lines = [
            f"Service [{priority}]",
            "",
        ]
        # Nachricht in Zeilen aufteilen (max. 20 Zeichen pro Zeile)
        words = message.split()
        current = ""
        for word in words:
            if len(current) + len(word) + 1 <= 20:
                current += (" " if current else "") + word
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        self._render_lines(lines[:6])

    def show_history(self, cycles: list):
        """Zeigt die letzten Filterzyklen."""
        self._current_screen = SCREEN_HISTORY
        lines = ["--- Historie ---"]
        for i, c in enumerate(cycles[-4:]):
            dur = c.get("duration_seconds", 0)
            lines.append(f"#{i+1}: {int(dur//60)} min")
        self._render_lines(lines)

    def show_network(self, ip: str, port: int, mode: str):
        """Zeigt Netzwerkinformationen."""
        self._current_screen = SCREEN_NETWORK
        lines = [
            "--- Netzwerk ---",
            f"IP: {ip}",
            f"Port: {port}",
            f"Modus: {mode}",
            "Web: http://",
            f"{ip}:{port}",
        ]
        self._render_lines(lines)

    def show_menu(self, items: list, selected: int):
        """Zeigt ein Navigationsmenü."""
        lines = ["=== Menue ==="]
        for i, item in enumerate(items[:5]):
            prefix = "> " if i == selected else "  "
            lines.append(f"{prefix}{item}")
        self._render_lines(lines)

    def show_message(self, title: str, message: str):
        """Zeigt eine einzelne Nachricht."""
        lines = [title, "", message]
        self._render_lines(lines)

    def clear(self):
        """Löscht den Displayinhalt."""
        if self._device and not self._simulated:
            try:
                self._device.clear()
            except Exception as e:
                logger.debug("Display clear Fehler: %s", e)
        else:
            logger.debug("Display gelöscht (simuliert).")

    # ------------------------------------------------------------------
    # Interne Renderlogik
    # ------------------------------------------------------------------

    def _render_lines(self, lines: list):
        """Rendert Textzeilen auf dem Display."""
        text = "\n".join(str(l) for l in lines)
        self._last_screen_text = text

        if self._simulated:
            logger.debug("OLED [simuliert]:\n%s", text)
            return

        try:
            from luma.core.render import canvas  # type: ignore
            from PIL import ImageDraw  # type: ignore  # noqa: F401
            with canvas(self._device) as draw:
                y = 0
                for line in lines:
                    draw.text((0, y), str(line), fill="white", font=self._font)
                    y += 11
        except Exception as e:
            logger.error("Fehler beim Display-Rendern: %s", e)

    @property
    def current_screen(self) -> str:
        return self._current_screen

    @property
    def is_simulated(self) -> bool:
        return self._simulated
