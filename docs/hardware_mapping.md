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
| RES      | Reset       | **GPIO 27**       | **Pin 13**| Reset (aktiv Low)   |

> **Wichtig:** DC=GPIO 25 und RES=GPIO 27 sind in `display.py` als Standardwerte hinterlegt (`_SPI_GPIO_DC = 25`, `_SPI_GPIO_RST = 27`). Bei abweichender Verkabelung die Werte im Konstruktor überschreiben.

### I2C-Anschluss (Alternative – Lötbrücke auf Modul umstellen)

| OLED-Pin | Signal   | Raspberry Pi GPIO | Board-Pin | Funktion         |
|----------|----------|-------------------|-----------|------------------|
| VCC      | 3,3 V    | 3V3               | Pin 1     | Stromversorgung  |
| GND      | GND      | GND               | Pin 6     | Masse            |
| DIN      | I2C SDA  | GPIO  2           | Pin 3     | I2C-Daten        |
| CLK      | I2C SCL  | GPIO  3           | Pin 5     | I2C-Takt         |
| DC       | Adresse  | GND / 3V3         | –         | Low=0x3C / High=0x3D |
| RES      | Reset    | **GPIO 27**       | **Pin 13**| Reset (aktiv Low)|

---

## Adafruit ANO Rotary Encoder (I2C)

| Parameter     | Wert                        |
|---------------|-----------------------------|
| Interface     | I2C                         |
| I2C-Adresse   | 0x49 (Standard)             |
| Bibliothek    | adafruit-circuitpython-seesaw |

### I2C-Anschluss

| Encoder-Pin | Raspberry Pi GPIO | Funktion |
|------------|-------------------|----------|
| VCC        | 3V3 (Pin 1)       | Stromversorgung |
| GND        | GND (Pin 6)       | Masse |
| SCL        | GPIO 3 (Pin 5)    | I2C Clock |
| SDA        | GPIO 2 (Pin 3)    | I2C Data |

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

| Parameter  | Wert                  |
|------------|-----------------------|
| Interface  | Raspberry Pi Ethernet |
| Protokoll  | HTTP (Flask)          |
| Port       | 8080 (konfigurierbar) |
| Webzugriff | `http://<IP>:8080`    |

IP-Adresse auf dem OLED-Display ablesen oder mit `hostname -I` ermitteln.
