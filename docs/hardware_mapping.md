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

| Parameter  | Wert                        |
|------------|-----------------------------|
| Größe      | 2,42 Zoll                   |
| Auflösung  | 128 × 64 Pixel              |
| Controller | SSD1309 (SPI) / SSD1306 (I2C)|
| Interface  | SPI (bevorzugt) oder I2C    |
| Bibliothek | luma.oled                   |

### SPI-Anschluss (Raspberry Pi 5)

| OLED-Pin | Raspberry Pi GPIO | Funktion |
|----------|-------------------|----------|
| VCC      | 3V3 (Pin 1)       | Stromversorgung |
| GND      | GND (Pin 6)       | Masse |
| DIN/MOSI | GPIO 10 (Pin 19)  | SPI MOSI |
| CLK/SCK  | GPIO 11 (Pin 23)  | SPI Clock |
| CS       | GPIO 8 (Pin 24)   | SPI Chip Select 0 |
| DC       | GPIO 24 (Pin 18)  | Data/Command |
| RST      | GPIO 25 (Pin 22)  | Reset |

### I2C-Anschluss (Alternative)

| OLED-Pin | Raspberry Pi GPIO | Funktion |
|----------|-------------------|----------|
| VCC      | 3V3 (Pin 1)       | Stromversorgung |
| GND      | GND (Pin 6)       | Masse |
| SCL      | GPIO 3 (Pin 5)    | I2C Clock |
| SDA      | GPIO 2 (Pin 3)    | I2C Data |

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

### Tastenzuordnung

| Eingabe        | Funktion              |
|----------------|-----------------------|
| Drehen links   | Vorheriger Menüpunkt  |
| Drehen rechts  | Nächster Menüpunkt    |
| Drücken        | OK / Bestätigen       |
| Taste Links    | Zurück                |
| Taste Rechts   | Untermenü             |
| Taste Oben     | Wert erhöhen          |
| Taste Unten    | Wert verringern       |

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
