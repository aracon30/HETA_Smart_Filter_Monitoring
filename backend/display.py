"""
Display-Modul – steuert das 2.42"-OLED-Display (Waveshare SSD1309) über luma.oled.

Hardwareanschluss (BCM-Nummerierung, getestet mit AnoPi Shield auf Pi 3B+):
  DIN  → GPIO 10  (SPI0 MOSI, Pin 19)
  CLK  → GPIO 11  (SPI0 SCLK, Pin 23)
  CS   → GPIO  7  (SPI0 CE1, Pin 26)
  DC   → GPIO  4  (Pin 7)    ← GPIO22 vom Pi-OS display_auto_detect belegt
  RST  → GPIO 27  (Pin 13)

I2C-Betrieb (optional, Lötbrücke auf Modul umstellen):
  DIN  → GPIO  2  (SDA)
  CLK  → GPIO  3  (SCL)
  DC   → LOW → Adresse 0x3C | HIGH → Adresse 0x3D

Layout (128 × 64 px, monochrom):
  y= 0..11  Invertierter Header-Balken (weißer Hintergrund, schwarzer Text)
  y=12      Trennlinie
  y=13..57  Inhaltsbereich (5 Zeilen à 9 px, 8-pt-Schrift)
  y=60..62  Navigationspunkte (● aktiv, □ inaktiv)

Bei fehlender Hardware wird die Ausgabe simuliert (Textlog).
"""

import logging
import time

logger = logging.getLogger(__name__)


class _LgpioBitbangSSD1309:
    """
    Direkter lgpio-Bitbang-Treiber für SSD1309 OLED (kein luma.oled).
    Kompatibel mit luma.core.render.canvas (hat .mode, .size, .display()).
    RST muss extern auf 3.3V verdrahtet sein (kein Software-Reset).
    """

    mode = "1"

    def __init__(self, sclk: int, sda: int, ce: int, dc: int, width: int = 128, height: int = 64):
        import lgpio  # type: ignore

        self._lgpio = lgpio
        self._gh = lgpio.gpiochip_open(0)
        self._sclk = sclk
        self._sda = sda
        self._ce = ce
        self._dc = dc
        self._width = width
        self._height = height

        for p in [sclk, sda, ce, dc]:
            try:
                lgpio.gpio_free(self._gh, p)
            except Exception:
                pass
            lgpio.gpio_claim_output(self._gh, p)

        lgpio.gpio_write(self._gh, ce, 1)
        lgpio.gpio_write(self._gh, sclk, 0)
        time.sleep(0.1)
        self._init()

    @property
    def size(self):
        return (self._width, self._height)

    def _send(self, byte: int, is_data: bool):
        gh = self._gh
        lg = self._lgpio
        lg.gpio_write(gh, self._ce, 0)
        lg.gpio_write(gh, self._dc, 1 if is_data else 0)
        for i in range(7, -1, -1):
            lg.gpio_write(gh, self._sda, (byte >> i) & 1)
            lg.gpio_write(gh, self._sclk, 1)
            lg.gpio_write(gh, self._sclk, 0)
        lg.gpio_write(gh, self._ce, 1)

    def _cmd(self, c: int):
        self._send(c, False)

    def _dat(self, d: int):
        self._send(d, True)

    def _init(self):
        for b in [
            0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
            0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA, 0x12,
            0x81, 0xFF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF,
        ]:
            self._cmd(b)

    def display(self, image):
        """Sendet ein PIL-Image (beliebiger Modus) ans Display."""
        from PIL import Image  # type: ignore

        if image.mode != "1":
            image = image.convert("1")
        for page in range(8):
            self._cmd(0xB0 | page)
            self._cmd(0x00)
            self._cmd(0x10)
            for col in range(self._width):
                byte = 0
                for bit in range(8):
                    y = page * 8 + bit
                    if y < self._height and image.getpixel((col, y)):
                        byte |= 1 << bit
                self._dat(byte)

    def clear(self):
        from PIL import Image  # type: ignore

        self.display(Image.new("1", self.size, 0))

    def cleanup(self):
        try:
            self.clear()
        except Exception:
            pass
        for p in [self._sclk, self._sda, self._ce, self._dc]:
            try:
                self._lgpio.gpio_free(self._gh, p)
            except Exception:
                pass
        try:
            self._lgpio.gpiochip_close(self._gh)
        except Exception:
            pass


# ── Displaykonstanten ──────────────────────────────────────────────────────────
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 64

# GPIO-Pins (BCM) – Waveshare 2.42" OLED SSD1309
# Bitbang-SPI auf freien Pins (GPIO17/27 vom AnoPi auf 0V gezogen)
_SPI_GPIO_SCLK = 23
_SPI_GPIO_SDA = 24
_SPI_GPIO_CE = 25
_SPI_GPIO_DC = 22
_SPI_GPIO_RST = None  # RST dauerhaft mit 3.3V verbunden

# Layout-Konstanten
_HDR_H = 12  # Header-Höhe
_LINE0 = 13  # erste Inhaltszeile
_LINE1 = 22
_LINE2 = 31
_LINE3 = 40
_LINE4 = 49
_DOTS_Y = 60  # y-Position Navigationspunkte

# Bildschirmnamen
SCREEN_STATUS = "Status"
SCREEN_HETA = "HETA-Code"
SCREEN_FILTER_CHANGE = "Filterwechsel"
SCREEN_SERVICE = "Service"
SCREEN_HISTORY = "Historie"
SCREEN_NETWORK = "Netzwerk"

SCREENS = [
    SCREEN_STATUS,
    SCREEN_HETA,
    SCREEN_FILTER_CHANGE,
    SCREEN_SERVICE,
    SCREEN_HISTORY,
    SCREEN_NETWORK,
]

# Status-Kurzbezeichnungen für das Abzeichen rechts neben dp
_STATUS_BADGE = {
    "OK": "OK",
    "BEOBACHTEN": "??",
    "WECHSEL": "!!",
    "WECHSEL_BESTAETIGEN": "!!",
    "WARNUNG": "!!",
    "FEHLER": "ERR",
}


class OLEDDisplay:
    """
    Steuert das 2.42" OLED-Display (SSD1309, SPI-Betrieb).
    Fällt bei fehlender Hardware auf Simulationsmodus (Textlog) zurück.
    """

    def __init__(
        self,
        use_spi: bool = True,
        spi_port: int = 0,
        spi_device: int = 1,
        gpio_dc: int = _SPI_GPIO_DC,
        gpio_rst=_SPI_GPIO_RST,
        i2c_address: int = 0x3C,
        gpio_sclk: int = _SPI_GPIO_SCLK,
        gpio_sda: int = _SPI_GPIO_SDA,
        gpio_ce: int = _SPI_GPIO_CE,
    ):
        self._device = None
        self._font = None  # 9 pt – Header
        self._font_sm = None  # 8 pt – Inhalt
        self._simulated = False
        self._nav_idx = 0  # aktiver Navigationspunkt
        self._current_screen = SCREEN_STATUS

        try:
            self._init_hardware(use_spi, spi_port, spi_device, gpio_dc, gpio_rst, i2c_address, gpio_sclk, gpio_sda, gpio_ce)
        except Exception as exc:
            logger.warning("OLED-Hardware nicht verfügbar: %s – Simulationsmodus.", exc)
            self._simulated = True

    # ── Hardware-Init ──────────────────────────────────────────────────────────

    def _init_hardware(self, use_spi, spi_port, spi_device, gpio_dc, gpio_rst, i2c_addr, gpio_sclk=23, gpio_sda=24, gpio_ce=25):
        from PIL import ImageFont  # type: ignore

        if use_spi:
            self._device = _LgpioBitbangSSD1309(
                sclk=gpio_sclk, sda=gpio_sda, ce=gpio_ce, dc=gpio_dc,
                width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT,
            )
        else:
            from luma.core.interface.serial import i2c  # type: ignore
            from luma.oled.device import ssd1309  # type: ignore

            serial = i2c(port=1, address=i2c_addr)
            self._device = ssd1309(serial, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)

        ttf = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        try:
            self._font = ImageFont.truetype(ttf, 9)
            self._font_sm = ImageFont.truetype(ttf, 8)
        except OSError:
            self._font = ImageFont.load_default()
            self._font_sm = self._font

        logger.info("OLED initialisiert (lgpio-Bitbang, SCLK=GPIO%d, SDA=GPIO%d, CE=GPIO%d, DC=GPIO%d).", gpio_sclk, gpio_sda, gpio_ce, gpio_dc)

    # ── Öffentliche Schnittstelle ──────────────────────────────────────────────

    def set_nav_index(self, idx: int):
        """Setzt den aktiven Navigationspunkt (wird vor jedem Render aufgerufen)."""
        self._nav_idx = max(0, min(idx, len(SCREENS) - 1))

    def clear(self):
        if self._simulated:
            return
        try:
            self._device.clear()
        except Exception as exc:
            logger.debug("Display clear: %s", exc)

    def show_boot_animation(self, duration: float = 2.5):
        """
        Startanimation beim Hochfahren:
          1. Logo + Produktname erscheinen (Wipe-Effekt, Zeile für Zeile)
          2. Ladebalken füllt sich bis 100 %
        """
        if self._simulated:
            logger.info("OLED Boot-Animation (Simulation).")
            return

        try:
            from luma.core.render import canvas  # type: ignore
        except ImportError:
            return

        LOGO_LINES = ["  HETA  ", "Smart Filter", "Monitor"]
        TOTAL_FRAMES = 30
        frame_delay = duration / TOTAL_FRAMES

        for frame in range(TOTAL_FRAMES + 1):
            ratio = frame / TOTAL_FRAMES
            try:
                with canvas(self._device) as draw:
                    # ── Logo (Wipe: Zeilen erscheinen nacheinander) ──────────────
                    y_offsets = [10, 27, 40]
                    for i, (line, y) in enumerate(zip(LOGO_LINES, y_offsets)):
                        appear_at = i / len(LOGO_LINES) * 0.6  # erste 60 % der Zeit
                        if ratio >= appear_at:
                            # Schrift: erste Zeile mit normalem Font, Rest klein
                            fnt = self._font if i == 0 else self._font_sm
                            tw = self._text_w(draw, line, fnt)
                            x = (DISPLAY_WIDTH - tw) // 2
                            draw.text((x, y), line, fill="white", font=fnt)

                    # ── Trennlinie ───────────────────────────────────────────────
                    if ratio >= 0.3:
                        draw.line([(10, 52), (DISPLAY_WIDTH - 10, 52)], fill="white")

                    # ── Ladebalken (ab 40 % der Animation) ──────────────────────
                    if ratio >= 0.4:
                        bar_ratio = (ratio - 0.4) / 0.6  # 0..1
                        bx, by, bw, bh = 10, 55, DISPLAY_WIDTH - 20, 5
                        draw.rectangle([(bx, by), (bx + bw - 1, by + bh - 1)], outline="white", fill="black")
                        fill_w = max(1, int(bar_ratio * (bw - 2)))
                        draw.rectangle([(bx + 1, by + 1), (bx + fill_w, by + bh - 2)], fill="white")

            except Exception as exc:
                logger.debug("Boot-Animation Fehler Frame %d: %s", frame, exc)
                return

            time.sleep(frame_delay)

        # Kurze Pause mit vollem Logo bevor der erste Echtbildschirm kommt
        time.sleep(0.3)

    # ── Bildschirme ────────────────────────────────────────────────────────────

    def show_status(self, data: dict):
        """
        Haupt-Statusbildschirm.

        Erwartete Schlüssel in data:
          p1, p2, dp, dp_limit, flow, temperature, remaining, status, mode
        """
        self._current_screen = SCREEN_STATUS

        p1 = data.get("p1", 0.0)
        p2 = data.get("p2", 0.0)
        dp = data.get("dp", 0.0)
        dp_limit = data.get("dp_limit", 2.5)
        flow = data.get("flow", 0.0)
        temp = data.get("temperature", 0.0)
        remaining = data.get("remaining", "---")
        status = data.get("status", "OK")
        mode = data.get("mode", "SIM")

        ratio = min(1.0, dp / dp_limit) if dp_limit > 0 else 0.0
        pct = int(ratio * 100)
        badge = _STATUS_BADGE.get(status, status[:3])

        def draw_fn(d):
            # ── Header ──
            self._draw_header(d, "HETA FILTER MONITOR")
            # Modus-Tag rechts oben im Header
            d.text((104, 2), mode, fill="black", font=self._font_sm)

            # ── p1 / p2 ──
            d.text((0, _LINE0), f"p1:{p1:.2f}   p2:{p2:.2f} bar", fill="white", font=self._font_sm)

            # ── dp + Status-Abzeichen ──
            d.text((0, _LINE1), f"dp: {dp:.3f} bar", fill="white", font=self._font_sm)
            bx = 99
            d.rectangle([(bx, _LINE1 - 1), (127, _LINE1 + 9)], outline="white", fill="black")
            tw = self._text_w(d, badge, self._font_sm)
            d.text((bx + (29 - tw) // 2, _LINE1), badge, fill="white", font=self._font_sm)

            # ── Fortschrittsbalken (dp / dp_limit) ──
            self._draw_bar(d, 0, _LINE2, 102, 6, ratio)
            d.text((104, _LINE2 - 1), f"{pct}%", fill="white", font=self._font_sm)

            # ── Durchfluss + Temperatur ──
            d.text((0, _LINE3), f"Q: {flow:.0f} l/min", fill="white", font=self._font_sm)
            d.text((70, _LINE3), f"T:{temp:.1f}°C", fill="white", font=self._font_sm)

            # ── Reststandzeit ──
            d.text((0, _LINE4), remaining, fill="white", font=self._font_sm)

            self._draw_dots(d)

        self._render(draw_fn, f"dp={dp:.3f} Q={flow:.0f} T={temp:.1f} | {remaining} | {status}")

    def show_heta_code(
        self,
        heta_code: str,
        activated: bool,
        learned_cycles: int = 0,
        required_cycles: int = 3,
        prediction_mode: str = "BASIS",
    ):
        """HETA-Code-Bildschirm mit Aktivierungs- und Lernstatus."""
        self._current_screen = SCREEN_HETA

        code_txt = heta_code if heta_code else "(kein Code)"
        act_txt = "✓ AKTIV" if activated else "  INAKTIV"
        mode_txt = {"BASIS": "BASIS", "HETA_LERNEND": "LERNEND", "HETA_VALIDIERT": "VALIDIERT"}.get(
            prediction_mode, prediction_mode
        )

        def draw_fn(d):
            self._draw_header(d, "HETA-CODE")

            d.text((0, _LINE0), f"Code: {code_txt}", fill="white", font=self._font_sm)
            d.text((0, _LINE1), f"Status: {act_txt}", fill="white", font=self._font_sm)

            # Trennlinie
            d.line([(0, _LINE2 - 2), (127, _LINE2 - 2)], fill="white")

            # Zyklen als kleine Kästchen visualisieren
            d.text((0, _LINE2 + 1), "Zyklen:", fill="white", font=self._font_sm)
            for i in range(required_cycles):
                bx = 46 + i * 14
                by = _LINE2 + 1
                if i < learned_cycles:
                    d.rectangle([(bx, by), (bx + 10, by + 8)], fill="white")
                else:
                    d.rectangle([(bx, by), (bx + 10, by + 8)], outline="white", fill="black")

            d.text((0, _LINE3), f"Prognose: {mode_txt}", fill="white", font=self._font_sm)

            self._draw_dots(d)

        self._render(
            draw_fn,
            f"HETA={code_txt} {'AKTIV' if activated else 'INAKTIV'} "
            f"Zyklen={learned_cycles}/{required_cycles} {mode_txt}",
        )

    def show_filter_change(self, dp_bar: float, dp_limit: float, armed: bool = False, awaiting: bool = False):
        """
        Filterwechsel-Bildschirm mit zweistufiger Bestätigungslogik.

          awaiting=False, armed=False → normaler Bildschirm (Infoanzeige)
          awaiting=True,  armed=False → Aufforderung zur Bestätigung
          awaiting=True,  armed=True  → Rückfrage vor Ausführung
        """
        self._current_screen = SCREEN_FILTER_CHANGE

        ratio = min(1.0, dp_bar / dp_limit) if dp_limit > 0 else 0.0
        pct = int(ratio * 100)

        if armed:
            header = "SICHER? BESTAETIGEN?"
            line3 = "OK = Ja, wechseln"
            line4 = "<  = Nein, abbrechen"
        elif awaiting:
            header = "!! FILTERWECHSEL !!"
            line3 = "OK = Bestaetigen"
            line4 = "<  = Abbrechen"
        else:
            header = "FILTERWECHSEL"
            line3 = "Kein Wechsel"
            line4 = "noetig"

        def draw_fn(d):
            self._draw_header(d, header)

            # dp-Anzeige
            limit_note = " (LIMIT!)" if dp_bar >= dp_limit else ""
            d.text((0, _LINE0), f"dp: {dp_bar:.3f} bar{limit_note}", fill="white", font=self._font_sm)
            d.text((0, _LINE1), f"Limit: {dp_limit:.2f} bar", fill="white", font=self._font_sm)

            # Fortschrittsbalken (volle Breite)
            self._draw_bar(d, 0, _LINE2, 102, 6, ratio)
            d.text((104, _LINE2 - 1), f"{pct}%", fill="white", font=self._font_sm)

            d.text((0, _LINE3), line3, fill="white", font=self._font_sm)
            d.text((0, _LINE4), line4, fill="white", font=self._font_sm)

            self._draw_dots(d)

        state = "armed" if armed else ("awaiting" if awaiting else "normal")
        self._render(draw_fn, f"Filterwechsel dp={dp_bar:.3f}/{dp_limit:.2f} [{state}]")

    def show_service(self, message: str, priority: str):
        """Servicehinweis mit Prioritätsabzeichen."""
        self._current_screen = SCREEN_SERVICE

        # Nachricht in maximal 3 Zeilen umbrechen (≤ 21 Zeichen)
        words = message.split()
        lines_m = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 <= 21:
                current += (" " if current else "") + word
            else:
                if current:
                    lines_m.append(current)
                current = word
                if len(lines_m) >= 3:
                    break
        if current and len(lines_m) < 3:
            lines_m.append(current)

        prio_map = {"HOCH": "[ HOCH ]", "MITTEL": "[MITTEL]", "NIEDRIG": "[NIEDRIG]"}
        prio_txt = prio_map.get(priority.upper(), f"[{priority}]")

        def draw_fn(d):
            self._draw_header(d, "SERVICE")

            # Prioritäts-Abzeichen (invertiert wenn HOCH)
            if priority.upper() == "HOCH":
                tw = self._text_w(d, prio_txt, self._font_sm)
                d.rectangle([(0, _LINE0 - 1), (tw + 2, _LINE0 + 9)], fill="white")
                d.text((1, _LINE0), prio_txt, fill="black", font=self._font_sm)
            else:
                d.text((0, _LINE0), prio_txt, fill="white", font=self._font_sm)

            y_positions = [_LINE1, _LINE2, _LINE3]
            for i, line in enumerate(lines_m[:3]):
                d.text((0, y_positions[i]), line, fill="white", font=self._font_sm)

            self._draw_dots(d)

        self._render(draw_fn, f"Service [{priority}]: {message[:40]}")

    def show_history(self, cycles: list):
        """Die letzten bis zu 4 abgeschlossenen Filterzyklen."""
        self._current_screen = SCREEN_HISTORY

        def draw_fn(d):
            self._draw_header(d, "HISTORIE")

            if not cycles:
                d.text((0, _LINE1), "Noch keine Daten", fill="white", font=self._font_sm)
                d.text((0, _LINE2), "verfuegbar.", fill="white", font=self._font_sm)
            else:
                y_positions = [_LINE0, _LINE1, _LINE2, _LINE3]
                for i, cycle in enumerate(cycles[:4]):
                    dur_s = cycle.get("duration_seconds", 0) or 0
                    dur_min = int(dur_s // 60)
                    ts = cycle.get("end_time") or cycle.get("start_time", 0)
                    # Datum aus Unix-Timestamp
                    try:
                        import time as _time

                        date_str = _time.strftime("%d.%m.%y", _time.localtime(ts))
                    except Exception:
                        date_str = "-----"

                    line = f"#{i + 1}: {dur_min:>4} min  {date_str}"
                    d.text((0, y_positions[i]), line, fill="white", font=self._font_sm)

            self._draw_dots(d)

        count = len(cycles)
        self._render(draw_fn, f"Historie: {count} Zyklen")

    def show_network(self, ip: str, port: int, mode: str):
        """Netzwerkinformationen und URL."""
        self._current_screen = SCREEN_NETWORK

        def draw_fn(d):
            self._draw_header(d, "NETZWERK")

            d.text((0, _LINE0), f"IP:   {ip}", fill="white", font=self._font_sm)
            d.text((0, _LINE1), f"Port: {port}", fill="white", font=self._font_sm)
            d.text((0, _LINE2), f"Modus: {mode}", fill="white", font=self._font_sm)

            # Trennlinie
            d.line([(0, _LINE3 - 2), (127, _LINE3 - 2)], fill="white")

            # URL aufgeteilt
            d.text((0, _LINE3), "http://", fill="white", font=self._font_sm)
            d.text((0, _LINE4), f"{ip}:{port}", fill="white", font=self._font_sm)

            self._draw_dots(d)

        self._render(draw_fn, f"Netzwerk: http://{ip}:{port} [{mode}]")

    def show_message(self, title: str, message: str):
        """Einfache Nachrichtenanzeige (z. B. Startbildschirm)."""

        def draw_fn(d):
            self._draw_header(d, title[:20])
            d.text((0, _LINE1), message[:21], fill="white", font=self._font_sm)
            self._draw_dots(d)

        self._render(draw_fn, f"{title}: {message}")

    def show_sensor_fault(
        self,
        failed_names: list,
        checking: bool = False,
        channel_ma: dict | None = None,
        failed_channels: list | None = None,
    ):
        """
        Sensorfehler-Bildschirm.

        Mit channel_ma (ch→mA, ch 1..4) wird eine Pro-Kanal-Tabelle angezeigt:
          AI0  p1   4.06mA  OK
          AI1  p2   4.06mA  OK
          AI2  T    0.00mA  KABEL
          AI3  Q    0.00mA  KABEL
        Ohne channel_ma erscheint die einfache Fehlerliste.
        checking=True → Prüf-Animation statt Tabelle.
        """
        _LABELS = {1: "p1", 2: "p2", 3: "T", 4: "Q"}
        _PREFIXES = {1: "AI0", 2: "AI1", 3: "AI2", 4: "AI3"}
        failed_set = set(failed_channels or [])

        def draw_fn(d):
            self._draw_header(d, "SENSORFEHLER")

            if checking:
                d.text((0, _LINE1), "Pruefe Sensoren ...", fill="white", font=self._font_sm)
                d.text((0, _LINE2), "Bitte warten.", fill="white", font=self._font_sm)
            elif channel_ma:
                # Kompakte 4-Zeilen-Tabelle: AI0 p1  4.06mA OK
                for i, ch in enumerate([1, 2, 3, 4]):
                    y = _LINE0 + i * 9
                    ma = channel_ma.get(ch, 0.0) or 0.0
                    ok = ch not in failed_set
                    status = "OK" if ok else "KABEL"
                    label = f"{_PREFIXES[ch]} {_LABELS[ch]}  {ma:5.2f}mA {status}"
                    d.text((0, y), label, fill="white", font=self._font_sm)
            else:
                d.text((0, _LINE0), "Fehlende Sensoren:", fill="white", font=self._font_sm)
                y_positions = [_LINE1, _LINE2, _LINE3]
                for i, name in enumerate(failed_names[:3]):
                    d.text((2, y_positions[i]), f"* {name[:20]}", fill="white", font=self._font_sm)

            # Hinweis-Zeile unten
            d.line([(0, _LINE4 - 2), (DISPLAY_WIDTH - 1, _LINE4 - 2)], fill="white")
            hint = "Pruefen ..." if checking else "OK = Erneut pruefen"
            tw = self._text_w(d, hint, self._font_sm)
            d.text(((DISPLAY_WIDTH - tw) // 2, _LINE4), hint, fill="white", font=self._font_sm)

        channels_str = ", ".join(failed_names) if failed_names else "unbekannt"
        self._render(draw_fn, f"SensorFault checking={checking} channels=[{channels_str}]")

    def show_waiting_for_flow(
        self, q_val: float, q_thr: float, dp_val: float, dp_thr: float, stable_pct: int, stab_secs: float
    ):
        """Wartet auf stabilen Durchfluss nach Filterwechsel / Systemstart."""
        q_ok = q_val >= q_thr
        dp_ok = dp_val >= dp_thr

        def draw_fn(d):
            self._draw_header(d, "WARTE AUF DURCHFL.")
            d.text((0, _LINE1), f"Q:  {q_val:5.1f}/{q_thr:.1f} l/min", fill="white", font=self._font_sm)
            d.text(
                (0, _LINE2),
                f"Qp: {'OK ' if q_ok else 'N  '} | dp {'OK' if dp_ok else 'N '}",
                fill="white",
                font=self._font_sm,
            )
            self._draw_bar(d, 0, _LINE3, DISPLAY_WIDTH, 6, stable_pct / 100)
            d.text((0, _LINE4), f"Stabil {stable_pct:3d}% / {stab_secs:.0f}s", fill="white", font=self._font_sm)

        self._render(draw_fn, f"WaitFlow Q={q_val:.1f}/{q_thr:.1f} stable={stable_pct}%")

    def show_cycle_paused(self, active_seconds: float, pause_seconds: float):
        """Zyklus pausiert wegen fehlendem Durchfluss."""

        def _fmt(s: float) -> str:
            s = int(max(0, s))
            h, m = divmod(s, 3600)
            m, sc = divmod(m, 60)
            if h > 0:
                return f"{h}h {m:02d}m"
            return f"{m}m {sc:02d}s"

        def draw_fn(d):
            self._draw_header(d, "ZYKLUS PAUSIERT")
            d.text((0, _LINE1), "Kein Durchfluss", fill="white", font=self._font_sm)
            d.text((0, _LINE2), f"Betr.: {_fmt(active_seconds)}", fill="white", font=self._font_sm)
            d.text((0, _LINE3), f"Pause: {_fmt(pause_seconds)}", fill="white", font=self._font_sm)
            d.text((0, _LINE4), "Warte auf Durchfluss", fill="white", font=self._font_sm)

        self._render(draw_fn, f"CyclePaused active={active_seconds:.0f}s pause={pause_seconds:.0f}s")

    # ── Zeichen-Helfer ─────────────────────────────────────────────────────────

    def _draw_header(self, draw, title: str):
        """Invertierter Header-Balken: weißer Hintergrund, schwarzer Text (zentriert)."""
        draw.rectangle([(0, 0), (DISPLAY_WIDTH - 1, _HDR_H - 1)], fill="white")
        draw.line([(0, _HDR_H), (DISPLAY_WIDTH - 1, _HDR_H)], fill="white")
        tw = self._text_w(draw, title, self._font_sm)
        x = max(1, (DISPLAY_WIDTH - tw) // 2)
        draw.text((x, 2), title, fill="black", font=self._font_sm)

    def _draw_bar(self, draw, x: int, y: int, w: int, h: int, ratio: float):
        """Horizontaler Fortschrittsbalken mit Umrandung."""
        ratio = max(0.0, min(1.0, ratio))
        draw.rectangle([(x, y), (x + w - 1, y + h - 1)], outline="white", fill="black")
        if ratio > 0:
            fill_w = max(1, int(ratio * (w - 2)))
            draw.rectangle([(x + 1, y + 1), (x + fill_w, y + h - 2)], fill="white")

    def _draw_dots(self, draw):
        """Navigationspunkte: aktiver = gefüllt, inaktive = Umrandung."""
        n = len(SCREENS)
        dw = 5  # Breite eines Punktes
        gap = 3  # Abstand zwischen Punkten
        total = n * dw + (n - 1) * gap
        sx = (DISPLAY_WIDTH - total) // 2
        for i in range(n):
            bx = sx + i * (dw + gap)
            if i == self._nav_idx:
                draw.rectangle([(bx, _DOTS_Y), (bx + dw - 1, _DOTS_Y + 2)], fill="white")
            else:
                draw.rectangle([(bx, _DOTS_Y), (bx + dw - 1, _DOTS_Y + 2)], outline="white", fill="black")

    @staticmethod
    def _text_w(draw, text: str, font) -> int:
        """Textbreite in Pixeln (PIL 8+)."""
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except AttributeError:
            return len(text) * 5  # Fallback: 5 px/Zeichen

    # ── Render-Engine ──────────────────────────────────────────────────────────

    def _render(self, draw_fn, sim_label: str = ""):
        """Führt draw_fn auf dem luma.oled-Canvas aus; im Sim-Modus nur Logging."""
        if self._simulated:
            logger.debug("OLED[SIM] %s | Screen=%d", sim_label, self._nav_idx)
            return
        try:
            from luma.core.render import canvas  # type: ignore

            with canvas(self._device) as draw:
                draw_fn(draw)
        except Exception as exc:
            logger.error("Display-Render-Fehler: %s", exc)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def current_screen(self) -> str:
        return self._current_screen

    @property
    def is_simulated(self) -> bool:
        return self._simulated
