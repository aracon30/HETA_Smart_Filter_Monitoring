# HETA Smart Filter Monitoring

Prototyp-Software für ein intelligentes Filterüberwachungssystem auf Basis des **Raspberry Pi 5**.
Die Software erfasst Sensordaten (4–20 mA), berechnet den Filterzustand, protokolliert Daten und stellt
eine lokale Weboberfläche sowie ein OLED-Display mit Encoder-Navigation bereit.

---

## Hardwareübersicht

| Komponente              | Funktion                                      |
|-------------------------|-----------------------------------------------|
| Raspberry Pi 5          | Zentrale Recheneinheit                        |
| AnoPi Raspberry Shield  | 4 × 4–20 mA Analogeingänge (SPI-ADC)         |
| ifm PL5423 (×2)         | Eintrittsdruck p1 und Austrittsdruck p2       |
| ifm TA2405              | Temperaturmessung                             |
| Keyence FD-X            | Durchflussmessung Q                           |
| Waveshare 2.42" OLED    | Lokale Anzeige (SSD1309, SPI, 128×64 px)      |
| Adafruit ANO Encoder    | Menünavigation (I2C, Seesaw)                  |
| Ethernet                | Weboberfläche via LAN                         |
| 24 V Netzteil           | Sensorversorgung                              |
| 24 V→5 V DC/DC-Wandler  | Versorgung Raspberry Pi                       |

---

## Installationsanleitung (Raspberry Pi 5)

### Voraussetzungen

- Raspberry Pi OS Lite 64-bit (Bookworm)
- Python 3.11+
- Git

### 1. Repository klonen

```bash
git clone https://github.com/aracon30/HETA_Smart_Filter_Monitoring.git
cd HETA_Smart_Filter_Monitoring
```

### 2. Installationsskript ausführen

```bash
chmod +x scripts/install.sh
./scripts/install.sh
```

Das Skript installiert alle Python-Pakete, legt Verzeichnisse an und richtet den systemd-Dienst ein.

### 3. SPI und I2C aktivieren

```bash
sudo raspi-config
# → Interface Options → SPI → Enable
# → Interface Options → I2C → Enable
sudo reboot
```

Oder manuell in `/boot/firmware/config.txt`:

```ini
dtparam=spi=on
dtparam=i2c_arm=on
```

---

## Ersteinrichtung (Onboarding)

Beim ersten Start öffnet sich automatisch ein **6-stufiger Einrichtungsassistent**:

| Schritt | Inhalt |
|---------|--------|
| 1 | Willkommen – Ablauf des Assistenten |
| 2 | Betriebsart wählen (Simulation oder Hardware) |
| 3 | Filterparameter (dp-Grenzwert, Sauberwiderstand, Durchfluss, Druckbereich) |
| 4 | Temperatursensor-Bereich konfigurieren (min/max °C) |
| 5 | Zugriffspasswort für den Einstellungsbereich festlegen (mind. 4 Zeichen) |
| 6 | Zusammenfassung bestätigen und System starten |

Der Messzyklus startet erst nach Abschluss des Onboardings.

---

## Start

```bash
./scripts/start.sh
# → Onboarding öffnet sich beim ersten Start automatisch
```

Weboberfläche: `http://localhost:8080`

Im Hardwaremodus Betriebsart im Onboarding oder Einstellungsbereich (⚙) auf **Hardware** setzen.

---

## HETA-Code aktivieren

1. Weboberfläche öffnen: `http://<IP>:8080`
2. HETA-Code eingeben, z. B. `HETA-12345`
3. „Demo-PIN anzeigen" klicken → PIN wird berechnet und eingetragen
4. „Aktivieren" klicken

**Beispiel:** Code `HETA-12345` → PIN `486082`

Mit aktivem HETA-Code werden der **Beladungsgrad** angezeigt und nach 3 Filterzyklen
eine **minutengenaue Reststandzeit** ausgegeben.

---

## Reststandzeit – Anzeigemodi

| Modus | Bedingung | Beispiel |
|-------|-----------|---------|
| **BASIS** | Kein HETA-Code | `2–4 Std.`, `1–2 Tage` |
| **HETA-Lernend** | HETA aktiv, < 3 Zyklen | `4–6 Std.` (1/3 Zyklen) |
| **HETA-Validiert** | 3 Zyklen abgeschlossen | `1 Std. 52 min`, `47 min` |

Filterlaufzeiten variieren je nach Anwendung von Minuten bis Tagen –
daher im Basis-Modus bewusst nur Bereiche ohne Minutenangabe.

---

## Einstellungen im laufenden Betrieb

Das Zahnrad-Symbol (⚙) im Header öffnet den passwortgeschützten Einstellungsbereich.

**Wichtig:** Bei Änderung folgender Parameter werden alle Lerndaten gelöscht
und die 3 Lernzyklen müssen neu durchlaufen werden:

- Differenzdruck-Grenzwert (`dp_limit_bar`)
- Sauberwiderstand (`dp_clean_bar`)
- Maximaler Durchfluss (`flow_max_l_min`)
- Druckbereich Sensoren (`pressure_range_bar`)

Ein Warnhinweis im Dialog macht darauf aufmerksam, bevor gespeichert wird.

---

## OLED-Display

Das 2.42"-Display (128×64 px, monochrom, Waveshare SSD1309) zeigt 6 Bildschirme,
zwischen denen mit dem ANO Rotary Encoder navigiert wird.
Jeder Bildschirm hat einen **invertierten Header** und **Navigationspunkte** am unteren Rand.

### Bildschirmübersicht

```
Screen 0 – Status (Hauptbildschirm)
┌──────────────────────────────────┐
│  HETA FILTER MONITOR       [SIM] │  ← invertierter Header + Modus
│ p1:2.34   p2:1.87 bar            │
│ dp: 0.470 bar           [  OK ]  │  ← Status-Abzeichen
│ [████████████░░░░░░░░]    47%    │  ← dp/dp-Grenzwert-Balken
│ Q: 82 l/min   T:23.4°C           │
│ Standzeit: 4-6 Std.              │
│      ●  □  □  □  □  □            │  ← Navigationspunkte
└──────────────────────────────────┘

Screen 1 – HETA-Code
┌──────────────────────────────────┐
│            HETA-CODE             │
│ Code: HETA-12345                 │
│ Status: ✓ AKTIV                  │
│ ──────────────────────────────── │
│ Zyklen: [■][■][□]                │  ← abgesch. / ausstehende Zyklen
│ Prognose: LERNEND                │
│      □  ●  □  □  □  □            │
└──────────────────────────────────┘

Screen 2 – Filterwechsel (awaiting)
┌──────────────────────────────────┐
│       !! FILTERWECHSEL !!        │
│ dp: 2.510 bar (LIMIT!)           │
│ Limit: 2.50 bar                  │
│ [████████████████████]   100%    │
│ OK = Bestaetigen                 │
│ <  = Abbrechen                   │
│      □  □  ●  □  □  □            │
└──────────────────────────────────┘

Screen 3 – Service
┌──────────────────┐
│     SERVICE      │
│ [NIEDRIG]        │  ← invertiert bei HOCH
│                  │
│ Betrieb normal.  │
│ Filter OK.       │
│  □  □  □  ●  □  □│
└──────────────────┘

Screen 4 – Historie
┌──────────────────────────────────┐
│            HISTORIE              │
│ #1:  142 min  23.04.25           │
│ #2:   98 min  28.04.25           │
│ #3:  167 min  02.05.25           │
│ #4:  121 min  07.05.25           │
│      □  □  □  □  ●  □            │
└──────────────────────────────────┘

Screen 5 – Netzwerk
┌──────────────────────────────────┐
│            NETZWERK              │
│ IP:   192.168.1.42               │
│ Port: 8080                       │
│ Modus: SIMULATION                │
│ ──────────────────────────────── │
│ http://192.168.1.42:8080         │
│      □  □  □  □  □  ●            │
└──────────────────────────────────┘
```

### Encoder-Bedienung

| Eingabe | Funktion |
|---------|----------|
| Drehen links / Taste ← | Vorheriger Bildschirm |
| Drehen rechts / Taste → | Nächster Bildschirm |
| OK-Taste auf Screen 2 | Filterwechsel vormerken (1. Druck) |
| OK-Taste nochmals | Filterwechsel bestätigen (2. Druck) |
| Taste ← während Vormerken | Abbrechen ohne Bestätigung |

> **Haupteinstellungen** sind ausschließlich über das Web-Dashboard (⚙) erreichbar.
> Am Gerät selbst ist nur die Filterwechsel-Bestätigung möglich.

### Display-Anschluss (SPI, Werkseinstellung)

| OLED-Pin | GPIO (BCM) | Board-Pin | Funktion |
|----------|------------|-----------|----------|
| VCC      | 3V3        | Pin 1     | Stromversorgung |
| GND      | GND        | Pin 6     | Masse |
| DIN      | GPIO 10    | Pin 19    | SPI MOSI |
| CLK      | GPIO 11    | Pin 23    | SPI SCLK |
| CS       | GPIO 8     | Pin 24    | SPI CE0 |
| DC       | **GPIO 25**| **Pin 22**| Data/Command |
| RES      | **GPIO 27**| **Pin 13**| Reset |

---

## API-Endpunkte

### Allgemein

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| GET  | `/api/status` | Vollständiger Systemstatus |
| GET  | `/api/measurements/latest` | Letzte Messwerte |
| GET  | `/api/measurements/history` | Messwerte seit Zeitstempel |
| GET  | `/api/cycles` | Filterzyklen für HETA-Code |
| GET  | `/api/profile` | Lernprofil für HETA-Code |

### HETA-Code & Filter

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| POST | `/api/heta/activate` | HETA-Code + PIN aktivieren |
| GET  | `/api/heta/demo` | Demo-PIN berechnen |
| POST | `/api/filter/confirm-change` | Filterwechsel bestätigen |

### Display & Navigation

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| POST | `/api/navigation/event` | Encoder-Ereignis simulieren |
| GET  | `/api/display/screen` | Aktiven Bildschirm abfragen |

Gültige Ereignisse: `ROTATE_LEFT`, `ROTATE_RIGHT`, `PRESS`, `LEFT`, `RIGHT`, `UP`, `DOWN`

### Onboarding & Einstellungen

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| GET  | `/api/onboarding/status` | Onboarding-Status prüfen |
| POST | `/api/onboarding/complete` | Onboarding abschließen |
| POST | `/api/settings/login` | Anmelden, Token erhalten |
| POST | `/api/settings/logout` | Abmelden |
| GET  | `/api/settings/auth-check` | Token-Gültigkeit prüfen |
| GET  | `/api/settings` | Konfiguration lesen |
| POST | `/api/settings` | Konfiguration speichern (`X-Auth-Token` erforderlich) |

### Service & Export

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| POST | `/api/service/request` | Servicebericht erzeugen |
| GET  | `/api/export/csv/download` | Messdaten als CSV herunterladen |

---

## CSV-Export

Über Weboberfläche → „CSV exportieren" oder direkt:

```
http://<IP>:8080/api/export/csv/download
```

---

## Fehlersuche

**Software startet nicht:**
```bash
python3 backend/app.py
# oder:
journalctl -u heta-monitor -n 50
```

**Onboarding erscheint erneut:**
`onboarding_complete` in `config/settings.json` prüfen.

**Passwort vergessen:**
`settings_password_hash` in `config/settings.json` leeren → Onboarding startet neu.

**OLED zeigt nichts:**
- SPI aktiviert? (`dtparam=spi=on` in `/boot/firmware/config.txt`)
- DC an GPIO 25 (Pin 22)? RES an GPIO 27 (Pin 13)?
- Lötbrücke auf Modul: SPI-Position (Werkseinstellung)?
- Details: [`docs/hardware_mapping.md`](docs/hardware_mapping.md)

**Encoder reagiert nicht:**
- I2C aktiviert? (`dtparam=i2c_arm=on`)
- `i2cdetect -y 1` → muss Adresse `0x49` zeigen
- SDA an GPIO 2 (Pin 3), SCL an GPIO 3 (Pin 5)

**Sensorwerte bleiben 0:**
Betriebsart auf Simulation prüfen. AnoPi-Verkabelung kontrollieren.

**HETA-Code ungültig:**
Format `HETA-XXXXX` (nur Ziffern), PIN 6-stellig mit führenden Nullen.

**Einstellungen gespeichert, Lernphasen neu:**
Erwartetes Verhalten – bei Änderung lernrelevanter Parameter werden alle
Zyklen und Profile zurückgesetzt.

---

## Systemd-Service

```bash
sudo systemctl start heta-monitor
sudo systemctl status heta-monitor
journalctl -u heta-monitor -f
```

---

## Projektstruktur

```
├── backend/
│   ├── app.py              Flask-Server, REST-API, Messzyklus, Auth, DisplayController
│   ├── config.py           Konfigurationsmanagement, Passwort-Hashing
│   ├── sensors.py          Sensorlesemodul + Filtersimulator
│   ├── calculations.py     Berechnungsalgorithmen + Statuslogik
│   ├── heta_code.py        HETA-Code-Validierung + PIN-Algorithmus
│   ├── learning.py         Lernzyklen + Referenzprofile
│   ├── prediction.py       Reststandzeit-Prognose (3 Modi)
│   ├── service_logic.py    Serviceempfehlungen + Berichte
│   ├── database.py         SQLite-Datenbankmodul
│   ├── display.py          OLED-Display-Steuerung (luma.oled, PIL-Layout)
│   ├── navigation.py       Encoder-Navigation (Adafruit Seesaw)
│   └── mqtt_client.py      Optionaler MQTT-Client
├── frontend/
│   ├── index.html          Dashboard + Onboarding + Einstellungs-Modal
│   ├── style.css           Industrielles Stylesheet (HETA-Blau)
│   └── app.js              REST-Polling, Chart.js, Auth-Logik
├── config/
│   └── settings.json       Alle Konfigurationsparameter
├── data/                   SQLite-Datenbank (auto-erstellt)
├── logs/                   Log-Dateien (auto-erstellt)
├── exports/                CSV-Exporte (auto-erstellt)
├── docs/
│   ├── software_architecture.md
│   └── hardware_mapping.md
└── scripts/
    ├── install.sh          Installationsskript
    └── start.sh            Manueller Start
```
