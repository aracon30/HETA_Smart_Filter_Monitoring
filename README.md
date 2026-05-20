# HETA Smart Filter Monitoring

Industrielles Filterüberwachungssystem für den **Raspberry Pi 5**. Erfasst 4–20-mA-Sensordaten
via AnoPi Shield (SPI-ADC), berechnet den Filterzustand in Echtzeit und stellt bereit:

- **Weboberfläche** (lokal, kein Internet erforderlich) mit Live-Diagrammen und Reststandzeit
- **OLED-Display** (Waveshare 2.42") mit Encoder-Navigation für den direkten Einsatz am Gerät
- **MQTT-Interface** für die optionale Anbindung an übergeordnete Leitsysteme
- **Lernprofil** – nach 3 Filterzyklen sekundengenaue Reststandzeit-Prognose

**Betriebsmodi:**

| Modus | Beschreibung |
|-------|-------------|
| Hardware (Standard) | Echte Sensormessung via 4–20 mA / AnoPi Shield |
| Simulation | Simulierter Filterkreislauf – ausschließlich für Tests und Präsentationen |

Kein automatischer Simulations-Fallback. Ein Sensorausfall stoppt die Messung sofort und
fordert den Bediener zur Prüfung auf.

---

## Inhaltsverzeichnis

1. [Hardware](#hardware)
2. [Installation](#installation)
3. [Ersteinrichtung (Onboarding)](#ersteinrichtung-onboarding)
4. [HETA-Code und Prognose](#heta-code-und-prognose)
5. [Konfiguration](#konfiguration)
6. [Software-Update](#software-update)
7. [Projektstruktur](#projektstruktur)
8. [REST-API](#rest-api)
9. [Fehlersuche](#fehlersuche)

---

## Hardware

| Komponente              | Funktion                                            |
|-------------------------|-----------------------------------------------------|
| Raspberry Pi 5          | Zentrale Recheneinheit                              |
| AnoPi Raspberry Shield  | 4 × 4–20 mA Analogeingänge (SPI-ADC)               |
| ifm PL5423 (×2)         | Eintrittsdruck p1 und Austrittsdruck p2 (0–10 bar)  |
| ifm TA2405              | Temperaturmessung (−50–150 °C)                      |
| Keyence FD-X            | Durchflussmessung Q (0–150 l/min, konfigurierbar)   |
| Waveshare 2.42" OLED    | Lokale Anzeige (SSD1309, SPI, 128 × 64 px)          |
| Adafruit ANO Encoder    | Menünavigation (direktes GPIO, kein I2C)             |
| 24 V Netzteil           | Sensorversorgung                                    |
| 24 V → 5 V DC/DC-Wandler| Versorgung Raspberry Pi                             |

Vollständige Pinbelegungen, Skalierungsformeln und Anschlussdiagramme:
[`docs/hardware_mapping.md`](docs/hardware_mapping.md)

---

## Installation

### Voraussetzungen

- Raspberry Pi 5, Raspberry Pi OS Lite 64-bit (Bookworm)
- SSH-Zugriff oder direktes Terminal
- SPI aktiviert: `sudo raspi-config` → Interface Options → SPI → Enable

### Schnellstart

```bash
# 1. Repository klonen
git clone https://github.com/aracon30/HETA_Smart_Filter_Monitoring.git
cd HETA_Smart_Filter_Monitoring

# 2. Installationsskript ausführen
#    Richtet Python-venv, systemd-Service und Verzeichnisse ein
chmod +x scripts/install.sh
./scripts/install.sh

# 3. Raspberry Pi neu starten (aktiviert SPI-Treiber)
sudo reboot

# 4. Service starten
sudo systemctl start heta-monitor
```

Weboberfläche öffnen: `http://<IP-Adresse>:8080`

IP-Adresse ermitteln: `hostname -I`  
Alternativ: OLED-Display → Bildschirm 5 (Netzwerk)

### Manueller Start (Entwicklung / Debugging)

```bash
./scripts/start.sh
# oder:
source .venv/bin/activate
python3 backend/app.py
```

### Autostart via systemd

```bash
sudo systemctl enable heta-monitor    # Autostart beim Boot aktivieren
sudo systemctl status heta-monitor    # Laufstatus prüfen
journalctl -u heta-monitor -f         # Log live verfolgen
journalctl -u heta-monitor -n 50      # Letzte 50 Log-Zeilen
```

### Abhängigkeiten

```
flask, flask-cors           – Web-Backend
luma.oled, Pillow           – OLED-Display
gpiozero (≥ 2.0)            – Encoder-GPIO
lgpio                       – GPIO-Backend für Pi 5 (via apt, nicht pip)
paho-mqtt                   – Optionaler MQTT-Client
spidev                      – SPI-ADC (AnoPi Shield)
```

```bash
# lgpio für Pi 5 (muss via apt installiert werden)
sudo apt-get install -y python3-lgpio
```

---

## Ersteinrichtung (Onboarding)

Beim ersten Start erkennt die Software `onboarding_complete: false` in `config/settings.json`
und zeigt automatisch einen 6-stufigen Einrichtungsassistenten an.
Der Messzyklus startet erst nach Abschluss.

| Schritt | Inhalt |
|---------|--------|
| 1 | Willkommen – Systemübersicht |
| 2 | Betriebsart: **Hardware** (Realbetrieb) oder **Simulation** (nur Tests) |
| 3 | Filterparameter: dp-Grenzwert, Druckabfall sauberer Filter, max. Durchfluss, Druckbereich |
| 4 | Temperatursensorbereich (Minimum und Maximum in °C) |
| 5 | Zugriffspasswort festlegen (mind. 4 Zeichen) |
| 6 | Zusammenfassung – Bestätigen startet das System |

> **Passwort vergessen?**
> ```bash
> nano config/settings.local.json
> # settings_password_hash auf "" setzen, dann:
> sudo systemctl restart heta-monitor
> # → Onboarding startet neu
> ```

---

## HETA-Code und Prognose

### HETA-Code aktivieren

1. Weboberfläche öffnen: `http://<IP>:8080`
2. HETA-Code eingeben, z. B. `HETA-12345`
3. Zugehörigen PIN eingeben (oder im Entwicklungsmodus: „Demo-PIN anzeigen")
4. „Aktivieren" klicken

Beispiel: `HETA-12345` → PIN `486082`

### Prognosemodi

Das System passt die Reststandzeit-Anzeige automatisch an das verfügbare Wissen an:

| Modus | Bedingung | Anzeigebeispiel |
|-------|-----------|----------------|
| **BASIS** | Kein HETA-Code aktiv | `2–4 Std.` |
| **HETA-Lernend** | HETA aktiv, < 3 bestätigte Zyklen | `4–6 Std. (1/3 Zyklen)` |
| **HETA-Validiert** | HETA aktiv, ≥ 3 vollständige Zyklen | `1 Std. 52 min 30 s` |

Nach 3 Lernzyklen berechnet das System ein Referenzprofil für die nicht-lineare
dp-Kurve. Die Reststandzeit-Inversion über dieses Profil liefert eine
präzise lineare Anzeige – auch wenn der Differenzdruck exponentiell steigt.

### Lernphasen-Reset

Folgende Einstellungsänderungen löschen alle Lerndaten (3 neue Zyklen erforderlich):
`dp_limit_bar`, `dp_clean_bar`, `flow_max_l_min`, `pressure_range_bar`

---

## Konfiguration

### Drei-Schicht-System

| Priorität | Datei | Beschreibung |
|-----------|-------|-------------|
| 1 (niedrigste) | Code-Defaults | Fallback-Werte in `config.py` |
| 2 | `config/settings.json` | Git-versionierte Standardwerte |
| 3 (höchste) | `config/settings.local.json` | Lokale Übersteuerungen, **gitignored** |

Alle Änderungen über das Dashboard oder Onboarding werden in `settings.local.json`
gespeichert. `git pull` überschreibt diese Datei nie.

### Wichtige Parameter

| Parameter | Standard | Lernrelevant ⚠ | Beschreibung |
|-----------|---------|:--------------:|-------------|
| `dp_limit_bar` | `2.5` | ✓ | Differenzdruck-Grenzwert für Filterwechsel |
| `dp_clean_bar` | `0.2` | ✓ | dp-Wert eines fabrikneuen Filters |
| `flow_max_l_min` | `150` | ✓ | Sensor-Endwert Durchfluss (= 20 mA) |
| `pressure_range_bar` | `10` | ✓ | Sensor-Endwert Drucksensoren (= 20 mA) |
| `temperature_min_c` | `-50` | | Sensor-Anfangswert Temperatur (= 4 mA) |
| `temperature_max_c` | `150` | | Sensor-Endwert Temperatur (= 20 mA) |
| `simulation_mode` | `true` | | Simulationsmodus aktiv |
| `sampling_interval_seconds` | `1` | | Messintervall in Sekunden |
| `required_cycles_for_profile` | `3` | | Zyklen bis valides Profil |
| `webserver_port` | `8080` | | HTTP-Port der Weboberfläche |
| `mqtt_enabled` | `false` | | MQTT-Client aktivieren |
| `display_enabled` | `true` | | OLED-Display aktivieren |
| `navigation_enabled` | `true` | | Encoder-Navigation aktivieren |

⚠ Änderung löscht alle Lernzyklen und Profile.

Vollständige Parameterliste: [`docs/software_architecture.md`](docs/software_architecture.md)

---

## Software-Update

### Auf dem Raspberry Pi (empfohlen)

```bash
./scripts/update.sh
```

### Via Dashboard

Einstellungen (⚙) → „Software-Update" → „Update von GitHub holen"

Erfordert Einstellungspasswort. Das System lädt die Seite nach dem Update automatisch neu.

### Vom Entwicklungsrechner per SSH

```bash
./scripts/deploy.sh pi@192.168.1.42
```

---

## Projektstruktur

```
HETA_Smart_Filter_Monitoring/
├── backend/
│   ├── app.py              Flask-Server, REST-API, Messzyklus-Thread, Auth
│   ├── config.py           Konfigurationsmanagement (3-Schicht), Passwort-Hashing
│   ├── sensors.py          Sensorlesemodul (SPI-ADC) + FilterSimulator
│   ├── calculations.py     dp, r_eff, Beladungsgrad, Statuslogik
│   ├── heta_code.py        HETA-Code-Validierung + PIN-Algorithmus
│   ├── learning.py         Lernzyklen + zeitbasierte Referenzprofile
│   ├── prediction.py       Reststandzeit-Prognose (3 Modi, Referenzkurven-Inversion)
│   ├── service_logic.py    Serviceempfehlungen + Berichte
│   ├── database.py         SQLite-Datenbankmodul
│   ├── display.py          OLED-Steuerung (luma.oled, PIL, 6 Bildschirme)
│   ├── navigation.py       ANO-Encoder-Navigation (gpiozero)
│   └── mqtt_client.py      Optionaler MQTT-Client (paho-mqtt)
├── frontend/
│   ├── index.html          Dashboard, Onboarding, Einstellungs-Modal
│   ├── style.css           HETA-Industriedesign (dunkles Theme)
│   └── app.js              REST-Polling, Chart.js 4.x, Onboarding-Automat, Auth
├── config/
│   ├── settings.json       Git-versionierte Standardkonfiguration
│   └── settings.local.json Lokale Übersteuerungen (gitignored, auto-erstellt)
├── data/                   SQLite-Datenbank (gitignored, auto-erstellt)
├── logs/                   Log-Dateien (gitignored, auto-erstellt)
├── exports/                CSV-Exporte (gitignored, auto-erstellt)
├── docs/
│   ├── benutzerhandbuch.md Bedienungsanleitung für Endbenutzer
│   ├── software_architecture.md  API, Datenbankschema, Algorithmen
│   └── hardware_mapping.md       Pinbelegungen, Skalierungsformeln
└── scripts/
    ├── install.sh          Erstinstallation (einmalig ausführen)
    ├── start.sh            Manueller Start ohne systemd
    ├── update.sh           Update auf dem Pi (git pull + Neustart)
    └── deploy.sh           SSH-Deploy vom Entwicklungsrechner
```

---

## REST-API

Alle Endpunkte antworten mit JSON. Schreibende Endpunkte erfordern den Header
`X-Auth-Token` (wird nach Login via `POST /api/settings/login` zurückgegeben).

### Öffentliche Endpunkte

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| GET | `/api/status` | Vollständiger Systemstatus (wird im 1-s-Takt gepollt) |
| GET | `/api/measurements/latest` | Letzte N Messwerte (`?limit=100`) |
| GET | `/api/measurements/history` | Messwerte seit Zeitstempel (`?since=<unix>`) |
| GET | `/api/cycles` | Filterzyklen für aktiven HETA-Code |
| GET | `/api/profile` | Lernprofil + Referenzkurve (`?heta_code=`) |
| POST | `/api/heta/activate` | HETA-Code + PIN aktivieren |
| POST | `/api/filter/confirm-change` | Filterwechsel bestätigen |
| POST | `/api/simulation/start` | Messung starten (auch: sensor_fault löschen) |
| POST | `/api/simulation/stop` | Messung stoppen |
| POST | `/api/sensor/recheck` | Sensoren nach Fehler erneut prüfen |
| GET | `/api/export/csv/download` | Messdaten als CSV herunterladen |
| GET | `/api/diagnostics` | Hardware-Selbstcheck |

### Authentifizierte Endpunkte (`X-Auth-Token` erforderlich)

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| POST | `/api/settings/login` | Anmelden, Token erhalten |
| POST | `/api/settings/logout` | Abmelden |
| GET | `/api/settings` | Konfiguration lesen |
| POST | `/api/settings` | Konfiguration speichern |
| POST | `/api/update/pull` | git pull + Neustart |

Vollständige API-Dokumentation mit Feldbeschreibungen:
[`docs/software_architecture.md`](docs/software_architecture.md)

---

## Fehlersuche

### Software startet nicht

```bash
source .venv/bin/activate && python3 backend/app.py   # Fehler direkt sehen
journalctl -u heta-monitor -n 50 --no-pager           # systemd-Logs
```

### Weboberfläche nicht erreichbar

```bash
hostname -I                           # IP-Adresse des Pi ermitteln
sudo systemctl status heta-monitor   # Läuft der Dienst?
ss -tlnp | grep 8080                  # Port belegt durch anderen Prozess?
```

### OLED-Display zeigt nichts

- SPI aktiviert? `ls /dev/spidev*` muss `/dev/spidev0.0` zeigen
- DC-Pin → GPIO 25 (Board-Pin 22), RES-Pin → GPIO 27 (Board-Pin 13)
- Vollständige Belegung: [`docs/hardware_mapping.md`](docs/hardware_mapping.md)
- Display deaktiviert? `display_enabled: true` in `config/settings.local.json` prüfen

### Encoder reagiert nicht

- COMA und COMB müssen an **GND** angeschlossen sein (nicht VCC)
- `pip install gpiozero lgpio` oder `sudo apt-get install python3-lgpio`
- GPIO-Pins in `config/settings.json` prüfen (`encoder_pin_enca` etc.)

### Sensor-Fault (rotes Overlay im Browser)

1. Verdrahtung und Sensorversorgung der genannten Kanäle prüfen
2. „Alle Sensoren angeschlossen – System prüfen" klicken
3. Für Testbetrieb ohne Hardware: Simulationsmodus im Overlay aktivieren (Passwort erforderlich)

### Passwort vergessen

```bash
nano config/settings.local.json
# Zeile "settings_password_hash" auf "" setzen
sudo systemctl restart heta-monitor
# → Onboarding-Assistent startet neu, neues Passwort festlegen
```

### Lerndaten ungewollt zurückgesetzt

Erwartetes Verhalten: Änderung eines lernrelevanten Parameters (`dp_limit_bar`,
`dp_clean_bar`, `flow_max_l_min`, `pressure_range_bar`) löscht automatisch alle
Zyklen und Profile. Das System muss erneut 3 Filterzyklen durchlaufen.

### Onboarding erscheint nach jedem Start

```bash
grep onboarding_complete config/settings.local.json   # Muss "true" sein
# Falls Datei fehlt oder Wert false: Onboarding erneut abschließen
```

---

## Endbenutzer-Anleitung

Für die Bedienung der Weboberfläche (Dashboard, HETA-Code, Filterwechsel, OLED-Display):
[`docs/benutzerhandbuch.md`](docs/benutzerhandbuch.md)
