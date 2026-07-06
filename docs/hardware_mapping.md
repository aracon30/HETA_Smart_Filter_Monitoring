# Hardware-Zuordnung – HETA Smart Filter Monitoring

## Überblick

| Komponente              | Funktion                                        |
|-------------------------|-------------------------------------------------|
| Raspberry Pi 5          | Zentrale Recheneinheit                          |
| AnoPi Raspberry Shield  | Analoge Eingangskanäle (4–20 mA)                |
| ifm PL5423 (×2)         | Drucksensoren p1 und p2                         |
| ifm TA2405              | Temperatursensor T                              |
| Keyence FD-X            | Durchflusssensor Q                              |
| 2.42" OLED-Display      | Lokale Feldgeräteanzeige                        |
| Adafruit ANO Encoder    | Menünavigation                                  |
| Raspberry Pi Ethernet   | LAN-Anbindung Weboberfläche                     |
| 24V DC Netzteil         | Sensorversorgung                                |
| 24V→5V DC/DC-Wandler    | Spannungsversorgung Raspberry Pi                |

---

## AnoPi Shield – Kanalbelegung

| Kanal | Sensor       | Signal   | Messgröße          | Bereich         |
|-------|-------------|----------|--------------------|-----------------|
| 1     | ifm PL5423  | 4–20 mA  | Eintrittsdruck p1  | 0–10 bar        |
| 2     | ifm PL5423  | 4–20 mA  | Austrittsdruck p2  | 0–10 bar        |
| 3     | ifm TA2405  | 4–20 mA  | Temperatur T       | -50–150 °C      |
| 4     | Keyence FD-X| 4–20 mA  | Durchfluss Q       | 0–150 l/min*    |

*parametrierbar in `config/settings.json` → `flow_max_l_min`

### Skalierungsformeln

```
p1_bar       = ((mA - 4) / 16) × 10
p2_bar       = ((mA - 4) / 16) × 10
temperature  = -50 + ((mA - 4) / 16) × 200
flow         = ((mA - 4) / 16) × flow_max
```

### Fehlerzustände

| mA-Bereich     | Status        | Bedeutung                   |
|---------------|---------------|-----------------------------|
| < 3,6 mA      | KABELBRUCH    | Leitung unterbrochen        |
| 3,6–4,0 mA    | UNTERBEREICH  | Messwert unterhalb Bereich  |
| 4,0–20,0 mA   | OK            | Normalbetrieb               |
| > 20,5 mA     | UEBERBEREICH  | Messwert oberhalb Bereich   |

---

## Sensor-Fault-Verhalten (Hardwaremodus)

Wenn im Hardwaremodus mindestens einer der 4 SPI-Kanäle nicht lesbar ist:

- Messung wird sofort gestoppt (kein Simulations-Fallback)
- State: `sensor_fault=True`, `sensor_fault_channels` (Liste ausgefallener Kanal-Nummern), `sensor_fault_message`
- Frontend: blockierendes rotes Overlay zeigt ausgefallene Kanäle mit Namen (z. B. „p1 (Eintrittsdruck)", „Q (Durchfluss)")
- Bediener prüft Verdrahtung und Versorgung → klickt „System prüfen" → `POST /api/sensor/recheck`
  - Alle Kanäle OK: `sensor_fault=False`, Messung startet automatisch neu
  - Noch Fehler: Overlay bleibt mit aktualisierten Kanalinformationen
- Optional aus dem Overlay: Simulationsmodus aktivieren (passwortgeschützt) – nur für Tests

Kanalbezeichnungen (aus `_CHANNEL_NAMES` in `sensors.py`):

| Kanal | Name |
|-------|------|
| 1 | p1 (Eintrittsdruck) |
| 2 | p2 (Austrittsdruck) |
| 3 | T (Temperatur) |
| 4 | Q (Durchfluss) |

---

## OLED-Display

| Parameter  | Wert                          |
|------------|-------------------------------|
| Hersteller | Waveshare 2.42inch OLED Module |
| Größe      | 2,42 Zoll                     |
| Auflösung  | 128 × 64 Pixel                |
| Controller | SSD1309                       |
| Interface  | 4-Wire SPI (Standard) oder I2C (Lötbrücke umstellen) |
| Bibliothek | luma.oled (`ssd1309`)         |

### SPI-Anschluss (Raspberry Pi 5) – Werkseinstellung

| OLED-Pin | Signal      | Raspberry Pi GPIO | Board-Pin | Funktion            |
|----------|-------------|-------------------|-----------|---------------------|
| VCC      | 3,3 V       | 3V3               | Pin 1     | Stromversorgung     |
| GND      | GND         | GND               | Pin 6     | Masse               |
| DIN      | SPI MOSI    | GPIO 10           | Pin 19    | SPI-Daten           |
| CLK      | SPI SCLK    | GPIO 11           | Pin 23    | SPI-Takt            |
| CS       | SPI CE0     | GPIO  8           | Pin 24    | Chip Select (aktiv Low) |
| DC       | Data/Cmd    | **GPIO 25**       | **Pin 22**| Data=High, Cmd=Low  |
| RES      | Reset       | **GPIO 24**       | **Pin 18**| Reset (aktiv Low)   |

> **Wichtig bei AnoPi Shield:** GPIO 17 und GPIO 27 werden vom AnoPi Shield
> hardwareseitig dauerhaft auf 0V gezogen. RES darf deshalb **nicht** auf
> GPIO 27 liegen (Display bliebe dauerhaft im Reset/schwarz), sondern auf
> GPIO 24.
>
> **Konfigurierbar:** DC und RES sind über `config/settings.json` einstellbar:
> `display_gpio_dc` (Standard: 25) und `display_gpio_rst` (Standard: 24).
> SPI-Bus und CE über `display_spi_port` / `display_spi_device`.
> Zum Deaktivieren des Displays: `display_enabled: false`.

### I2C-Anschluss (Alternative – Lötbrücke auf Modul umstellen)

| OLED-Pin | Signal   | Raspberry Pi GPIO | Board-Pin | Funktion         |
|----------|----------|-------------------|-----------|------------------|
| VCC      | 3,3 V    | 3V3               | Pin 1     | Stromversorgung  |
| GND      | GND      | GND               | Pin 6     | Masse            |
| DIN      | I2C SDA  | GPIO  2           | Pin 3     | I2C-Daten        |
| CLK      | I2C SCL  | GPIO  3           | Pin 5     | I2C-Takt         |
| DC       | Adresse  | GND / 3V3         | –         | Low=0x3C / High=0x3D |
| RES      | Reset    | **GPIO 27**       | **Pin 13**| Reset (aktiv Low)|

> Für I2C in `config/settings.json` setzen: `display_use_spi: false`,
> `display_i2c_address: 60` (0x3C) bzw. `61` (0x3D).

---

## Adafruit ANO Rotary Navigation Encoder Breakout (direktes GPIO)

| Parameter     | Wert                                                         |
|---------------|--------------------------------------------------------------|
| Modell        | Adafruit ANO Rotary Navigation Encoder Breakout – Pre-Soldered |
| Interface     | Direktes GPIO (kein I2C/Seesaw)                              |
| Bibliothek    | gpiozero ≥ 2.0 + lgpio (Pi 5) / RPi.GPIO (Pi 4)             |

> Zum Deaktivieren: `navigation_enabled: false` in `config/settings.json`.  
> GPIO-Pins sind über `encoder_pin_enca` … `encoder_pin_sw5` konfigurierbar.

### Pinbeschreibung (Breakout)

| Breakout-Pin | Bedeutung                                    |
|-------------|----------------------------------------------|
| ENCA        | Drehgeber Signal A                           |
| ENCB        | Drehgeber Signal B                           |
| SW1         | Mitteltaste (Drücken / OK)                   |
| SW2         | Taste Unten                                  |
| SW3         | Taste Rechts                                 |
| SW4         | Taste Oben                                   |
| SW5         | Taste Links                                  |
| COMA        | Common für ENCA, ENCB, SW1 → **an GND**      |
| COMB        | Common für SW2–SW5 → **an GND**              |

> **Wichtig:** COMA und COMB **an GND anschließen** (nicht an VCC). Die internen  
> Pull-ups des Raspberry Pi übernehmen dann die Signalpegel.

### GPIO-Anschluss (Raspberry Pi, BCM-Nummerierung, Standardwerte)

| Breakout-Pin | Raspberry Pi GPIO  | Board-Pin | settings.json-Schlüssel   |
|-------------|-------------------|-----------|---------------------------|
| VCC         | 3V3               | Pin 1     | –                         |
| GND         | GND               | Pin 6     | –                         |
| COMA        | GND               | Pin 6/14  | –  (an GND, kein GPIO)    |
| COMB        | GND               | Pin 6/14  | –  (an GND, kein GPIO)    |
| ENCA        | **GPIO 16**       | Pin 36    | `encoder_pin_enca`        |
| ENCB        | **GPIO 20**       | Pin 38    | `encoder_pin_encb`        |
| SW1 (OK)    | **GPIO 21**       | Pin 40    | `encoder_pin_sw1`         |
| SW2 (Unten) | **GPIO 12**       | Pin 32    | `encoder_pin_sw2`         |
| SW3 (Rechts)| **GPIO 13**       | Pin 33    | `encoder_pin_sw3`         |
| SW4 (Oben)  | **GPIO 19**       | Pin 35    | `encoder_pin_sw4`         |
| SW5 (Links) | **GPIO 26**       | Pin 37    | `encoder_pin_sw5`         |

> GPIO-Pins können in `config/settings.json` angepasst werden, falls andere Pins belegt sind.

### Tastenzuordnung (Display-Navigation)

| Eingabe        | Funktion                                               |
|----------------|--------------------------------------------------------|
| Drehen links   | Vorheriger Bildschirm                                  |
| Drehen rechts  | Nächster Bildschirm                                    |
| Taste Links    | Vorheriger Bildschirm / Filterwechsel-Bestätigung abbrechen |
| Taste Rechts   | Nächster Bildschirm                                    |
| Drücken (OK)   | Filterwechsel vormerken (1. Druck) oder bestätigen (2. Druck) |
| Taste Oben     | (reserviert)                                           |
| Taste Unten    | (reserviert)                                           |

### Bildschirmreihenfolge

| Index | Bildschirm    | Inhalt                                         |
|-------|---------------|------------------------------------------------|
| 0     | Status        | p1, p2, dp, Durchfluss, Reststandzeit, Status  |
| 1     | HETA-Code     | Aktiver Code und Aktivierungsstatus             |
| 2     | Filterwechsel | dp-Wert, Grenzwert, zweistufige Bestätigung    |
| 3     | Service       | Aktueller Servicehinweis mit Priorität          |
| 4     | Historie      | Letzte 4 abgeschlossene Filterzyklen            |
| 5     | Netzwerk      | IP-Adresse, Port, Betriebsmodus                 |

> **Haupteinstellungen** sind nur über das Web-Dashboard (`http://<IP>:8080 → ⚙`) erreichbar, nicht über den Encoder.

---

## Spannungsversorgung

```
230V AC
  └── 24V DC Hutschienen-Netzteil
        ├── 24V DC → Sensoren (ifm PL5423, ifm TA2405, Keyence FD-X)
        └── 24V → 5V DC/DC-Wandler → Raspberry Pi 5 (USB-C oder GPIO)
```

**Hinweis:** Die Software übernimmt keine Netzteilsteuerung.
Die Architektur wird nur zu Dokumentationszwecken abgebildet.

---

## LAN-Anschluss

| Parameter  | Wert                                      |
|------------|-------------------------------------------|
| Interface  | Raspberry Pi Ethernet                     |
| Protokoll  | HTTP (Flask)                              |
| Port       | 8080 (konfigurierbar: `webserver_port`)   |
| Bind       | 0.0.0.0 (konfigurierbar: `webserver_host`)|
| Webzugriff | `http://<IP>:8080`                        |

IP-Adresse auf dem OLED-Display (Bildschirm 5 – Netzwerk) ablesen oder mit `hostname -I` ermitteln.
