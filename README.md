# HETA Smart Filter Monitoring

Industrielles Filterüberwachungssystem für den **Raspberry Pi 5**. Erfasst 4–20-mA-Sensordaten
via AnoPi Shield (SPI-ADC), berechnet den Filterzustand und stellt eine lokale Weboberfläche,
ein OLED-Display mit Encoder-Navigation sowie ein MQTT-Interface bereit.

**Betriebsmodi:**
- **Realbetrieb** (Standard) – echte Sensoren via AnoPi Shield
- **Simulationsmodus** – explizit konfiguriert, nur für Tests

Kein automatischer Simulations-Fallback. Ein Sensorausfall stoppt die Messung und fordert den
Bediener zur Prüfung auf.

---

## Hardware

| Komponente              | Funktion                                      |
|-------------------------|-----------------------------------------------|
| Raspberry Pi 5          | Zentrale Recheneinheit                        |
| AnoPi Raspberry Shield  | 4 × 4–20 mA Analogeingänge (SPI-ADC)         |
| ifm PL5423 (×2)         | Eintrittsdruck p1 und Austrittsdruck p2       |
| ifm TA2405              | Temperaturmessung                             |
| Keyence FD-X            | Durchflussmessung Q                           |
| Waveshare 2.42" OLED    | Lokale Anzeige (SSD1309, SPI, 128×64 px)      |
| Adafruit ANO Encoder    | Menünavigation (direktes GPIO, kein I2C)      |
| 24 V Netzteil           | Sensorversorgung                              |
| 24 V → 5 V DC/DC-Wandler| Versorgung Raspberry Pi                       |

---

## Installation

### Voraussetzungen

- Raspberry Pi 5, Raspberry Pi OS Lite 64-bit (Bookworm)
- SSH-Zugriff oder Terminal
- SPI aktiviert (`sudo raspi-config` → Interface Options → SPI)

### Schnellstart

```bash
# 1. Repository klonen
git clone https://github.com/aracon30/HETA_Smart_Filter_Monitoring.git
cd HETA_Smart_Filter_Monitoring

# 2. Installationsskript ausführen (venv, systemd-Service, Verzeichnisse)
chmod +x scripts/install.sh
./scripts/install.sh

# 3. Raspberry Pi neu starten (aktiviert SPI/I2C)
sudo reboot

# 4. Service starten
sudo systemctl start heta-monitor
```

Weboberfläche öffnen: `http://<IP-Adresse>:8080`

IP-Adresse ermitteln: `hostname -I`

### Manueller Start (Entwicklung)

```bash
./scripts/start.sh
# oder:
source .venv/bin/activate
python3 backend/app.py
```

### Autostart via systemd

```bash
sudo systemctl enable heta-monitor   # Autostart aktivieren
sudo systemctl status heta-monitor   # Status prüfen
journalctl -u heta-monitor -f        # Logs verfolgen
```

---

## Ersteinrichtung (Onboarding)

Beim ersten Start öffnet sich automatisch ein 6-stufiger Einrichtungsassistent.
Der Messzyklus startet erst nach Abschluss.

| Schritt | Inhalt |
|---------|--------|
| 1 | Willkommen |
| 2 | Betriebsart: **Hardware** (Standard) oder **Simulation** |
| 3 | Filterparameter: dp-Grenzwert, Sauberwiderstand, max. Durchfluss, Druckbereich |
| 4 | Temperatursensorbereich (min/max °C) |
| 5 | Zugriffspasswort (mind. 4 Zeichen) |
| 6 | Zusammenfassung bestätigen → System startet |

---

## HETA-Code aktivieren

1. Weboberfläche öffnen: `http://<IP>:8080`
2. HETA-Code eingeben, z. B. `HETA-12345`
3. „Demo-PIN anzeigen" klicken oder PIN aus dem HETA-PIN-Generator berechnen
4. „Aktivieren" klicken

**Beispiel:** `HETA-12345` → PIN `486082`

Mit aktivem HETA-Code werden Beladungsgrad angezeigt und nach 3 Filterzyklen eine
sekundengenaue Reststandzeit ausgegeben.

| Modus | Bedingung | Beispiel |
|-------|-----------|---------|
| **BASIS** | Kein HETA-Code | `2–4 Std.` |
| **HETA-Lernend** | HETA aktiv, < 3 Zyklen | `4–6 Std. (1/3)` |
| **HETA-Validiert** | 3 Zyklen abgeschlossen | `1 Std. 52 min 30 s` |

---

## Einstellungen

Das Zahnrad-Symbol (⚙) öffnet den passwortgeschützten Einstellungsbereich.

Bei Änderung dieser Parameter werden alle Lerndaten gelöscht:
`dp_limit_bar`, `dp_clean_bar`, `flow_max_l_min`, `pressure_range_bar`

---

## Software-Update

```bash
# Auf dem Pi (empfohlen):
./scripts/update.sh

# Vom Entwicklungsrechner per SSH:
./scripts/deploy.sh pi@192.168.1.42
```

Alternativ: Im Dashboard unter ⚙ → „Software-Update" → „Update von GitHub holen".

---

## Projektstruktur

```
├── backend/
│   ├── app.py              Flask-Server, REST-API, Messzyklus, Auth, DisplayController
│   ├── config.py           Konfigurationsmanagement (3-Schicht: defaults / settings.json / settings.local.json)
│   ├── sensors.py          Sensorlesemodul (SPI-ADC) + FilterSimulator
│   ├── calculations.py     Berechnungen: dp, r_eff, Beladungsgrad, Statuslogik
│   ├── heta_code.py        HETA-Code-Validierung + PIN-Algorithmus
│   ├── learning.py         Lernzyklen + zeitbasierte Referenzprofile
│   ├── prediction.py       Reststandzeit-Prognose (3 Modi)
│   ├── service_logic.py    Serviceempfehlungen + Berichte
│   ├── database.py         SQLite-Datenbankmodul
│   ├── display.py          OLED-Display-Steuerung (luma.oled, PIL)
│   ├── navigation.py       ANO-Encoder-Navigation (direktes GPIO via gpiozero)
│   └── mqtt_client.py      Optionaler MQTT-Client
├── frontend/
│   ├── index.html          Dashboard, Onboarding, Einstellungs-Modal
│   ├── style.css           Stylesheet (HETA-Branding, dunkles Industriedesign)
│   └── app.js              REST-Polling, Chart.js, Onboarding-Zustandsautomat, Auth
├── config/
│   └── settings.json       Alle Konfigurationsparameter (Standard-/Vorgabewerte)
│   # settings.local.json   Lokale Überschreibungen – wird von git ignoriert
├── data/                   SQLite-Datenbank (automatisch erstellt)
├── logs/                   Log-Dateien (automatisch erstellt)
├── exports/                CSV-Exporte (automatisch erstellt)
├── docs/
│   ├── software_architecture.md   API-Endpunkte, Datenbankschema, Modulbeschreibungen
│   └── hardware_mapping.md        Sensorkanäle, Skalierungsformeln, Pin-Belegungen
└── scripts/
    ├── install.sh          Erstinstallation (einmalig)
    ├── start.sh            Manueller Start
    ├── update.sh           Update auf dem Pi
    └── deploy.sh           SSH-Deploy vom Entwicklungsrechner
```

---

## REST-API (Überblick)

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| GET  | `/api/status` | Vollständiger Systemstatus |
| GET  | `/api/measurements/latest` | Letzte Messwerte |
| POST | `/api/heta/activate` | HETA-Code + PIN aktivieren |
| POST | `/api/filter/confirm-change` | Filterwechsel bestätigen |
| POST | `/api/sensor/recheck` | Sensoren erneut prüfen und Messung neu starten |
| GET  | `/api/settings` | Konfiguration lesen |
| POST | `/api/settings` | Konfiguration speichern (Auth erforderlich) |
| POST | `/api/settings/login` | Anmelden, Token erhalten |
| POST | `/api/update/pull` | git pull + Neustart (Auth erforderlich) |
| GET  | `/api/diagnostics` | Hardware-Selbstcheck |
| GET  | `/api/export/csv/download` | Messdaten als CSV herunterladen |

Vollständige API-Dokumentation: [`docs/software_architecture.md`](docs/software_architecture.md)

---

## Fehlersuche

**Software startet nicht:**
```bash
source .venv/bin/activate && python3 backend/app.py   # Fehler direkt sehen
journalctl -u heta-monitor -n 50 --no-pager           # systemd-Logs
```

**Weboberfläche nicht erreichbar:**
```bash
hostname -I                           # IP-Adresse ermitteln
sudo systemctl status heta-monitor   # Läuft der Dienst?
ss -tlnp | grep 8080                  # Port belegt?
```

**OLED zeigt nichts:**
- SPI aktiviert? `ls /dev/spidev*` muss `/dev/spidev0.0` zeigen
- DC → GPIO 25 (Pin 22), RES → GPIO 27 (Pin 13) – Details: `docs/hardware_mapping.md`

**Encoder reagiert nicht:**
- COMA und COMB müssen an GND angeschlossen sein
- GPIO-Pins in `config/settings.json` prüfen (`encoder_pin_enca` etc.)
- `pip install gpiozero lgpio`

**Sensor-Fault (rotes Overlay):**
1. Verdrahtung der genannten Kanäle prüfen
2. „Alle Sensoren angeschlossen – System prüfen" klicken
3. Falls Weiterbetrieb nötig: Simulationsmodus über das Dashboard aktivieren

**Passwort vergessen:**
```bash
# settings.local.json bearbeiten und settings_password_hash auf "" setzen
nano config/settings.local.json
sudo systemctl restart heta-monitor   # Onboarding startet neu
```

**Onboarding erscheint nach jedem Start:**
```bash
grep onboarding_complete config/settings.local.json   # Muss true sein
```

**Lerndaten unerwünscht zurückgesetzt:**
Erwartetes Verhalten – bei Änderung lernrelevanter Parameter werden alle
Zyklen und Profile automatisch gelöscht.
