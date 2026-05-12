# HETA Smart Filter Monitoring

Industrielle Filterüberwachung auf Basis des **Raspberry Pi 5**, im aktiven Einsatz auf einem
realen Testsystem. Die Software erfasst echte 4–20-mA-Sensordaten, berechnet den Filterzustand,
protokolliert Messwerte und stellt eine lokale Weboberfläche sowie ein OLED-Display mit
Encoder-Navigation bereit.

**Betriebspriorität:**
1. **Realbetrieb** – echte Sensoren via AnoPi Shield (SPI-ADC)
2. **Simulationsmodus** – explizit konfiguriert (Onboarding oder Einstellungen), ausschließlich für Tests

Kein automatischer Simulations-Fallback. Ein Sensorausfall im Hardwaremodus stoppt die Messung und
fordert den Bediener zur Prüfung auf.

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

## Teststatus

| Komponente / Funktion              | Status           | Umgebung                        |
|------------------------------------|------------------|---------------------------------|
| Backend-Start                      | ✅ getestet      | Debian 13 VM + Raspberry Pi 5   |
| Weboberfläche                      | ✅ getestet      | Debian 13 VM + Raspberry Pi 5   |
| Simulierte Messwerte               | ✅ getestet      | Debian 13 VM                    |
| Filterüberwachungs-Grundlogik      | ✅ getestet      | Debian 13 VM                    |
| Datenhaltung / Statusanzeige       | ✅ getestet      | Debian 13 VM                    |
| Raspberry Pi 5 (Echtbetrieb)       | 🔄 in Betrieb    | Raspberry Pi 5 (Testsystem)     |
| Autostart via systemd              | 🔄 in Betrieb    | Raspberry Pi 5 (Testsystem)     |
| OLED-Display (SSD1309 via SPI)     | ⏳ ausstehend    | –                               |
| ANO-Rotary-Encoder (I2C)           | ⏳ ausstehend    | –                               |
| 4–20-mA-Sensorik (AnoPi Shield)    | ⏳ ausstehend    | –                               |

> Das System läuft auf einem **realen Raspberry Pi 5 Testsystem**. Echtbetrieb mit Sensoren hat Vorrang.
> Der Simulationsmodus dient nur als Fallback oder für Entwicklung ohne Hardware.

---

## Installation (Schritt für Schritt)

### Voraussetzungen

- Raspberry Pi 5 mit **Raspberry Pi OS Lite 64-bit (Bookworm)**
- Netzwerkzugang (Ethernet oder WLAN)
- SSH-Zugriff oder direkt angeschlossene Tastatur/Monitor

### Schritt 1 – System vorbereiten

SSH-Verbindung herstellen oder Terminal öffnen:

```bash
ssh pi@<IP-Adresse>
# Beispiel: ssh pi@192.168.1.42
```

System aktualisieren:

```bash
sudo apt-get update && sudo apt-get upgrade -y
```

Git installieren (falls nicht vorhanden):

```bash
sudo apt-get install -y git
```

### Schritt 2 – Repository klonen

```bash
cd ~
git clone https://github.com/aracon30/HETA_Smart_Filter_Monitoring.git
cd HETA_Smart_Filter_Monitoring
```

Das Repository wird nach `/home/pi/HETA_Smart_Filter_Monitoring` geklont.

### Schritt 3 – SPI und I2C aktivieren

Das OLED-Display (SPI) und der ANO-Encoder (I2C) benötigen aktivierte Schnittstellen.

**Option A – raspi-config (empfohlen):**

```bash
sudo raspi-config
```

Navigation:
1. `3 Interface Options` → `I5 SPI` → `Yes`
2. `3 Interface Options` → `I4 I2C` → `Yes`
3. `Finish` → Neustart bestätigen

**Option B – manuell in `/boot/firmware/config.txt`:**

```bash
sudo nano /boot/firmware/config.txt
```

Folgende Zeilen einfügen oder einkommentieren:

```ini
dtparam=spi=on
dtparam=i2c_arm=on
```

Speichern (`Ctrl+O`, `Enter`, `Ctrl+X`) und neu starten:

```bash
sudo reboot
```

Nach dem Neustart prüfen ob die Schnittstellen aktiv sind:

```bash
# SPI prüfen – muss Gerätedateien anzeigen
ls /dev/spidev*
# Erwartet: /dev/spidev0.0  /dev/spidev0.1

# I2C prüfen – muss Gerätedatei anzeigen
ls /dev/i2c-*
# Erwartet: /dev/i2c-1

# I2C-Adressen scannen (Encoder bei 0x49)
i2cdetect -y 1
```

### Schritt 4 – Installationsskript ausführen

```bash
cd ~/HETA_Smart_Filter_Monitoring
chmod +x scripts/install.sh
./scripts/install.sh
```

Das Skript führt folgende Schritte automatisch aus:

| Schritt | Was passiert |
|---------|-------------|
| 1/7 | Systempakete aktualisieren (`python3`, `libfreetype6-dev`, `fonts-dejavu-core`, …) |
| 2/7 | SPI/I2C-Konfiguration prüfen und Hinweise ausgeben |
| 3/7 | Python Virtual Environment erstellen (`.venv/`) |
| 4/7 | Python-Pakete installieren (`flask`, `luma.oled`, `Pillow`, `adafruit-seesaw`, …) |
| 5/7 | Verzeichnisse anlegen (`data/`, `logs/`, `exports/`) |
| 6/7 | systemd-Service `heta-monitor` installieren und aktivieren |
| 7/7 | Abschlussmeldung mit nächsten Schritten |

**Erwartete Ausgabe am Ende:**

```
============================================================
  Installation abgeschlossen!

  Manueller Start:   sudo systemctl start heta-monitor
  Status prüfen:     sudo systemctl status heta-monitor
  Logs ansehen:      journalctl -u heta-monitor -f

  Weboberfläche:     http://<IP-Adresse>:8080

  WICHTIG: Raspberry Pi neu starten um SPI/I2C zu aktivieren!
    sudo reboot
============================================================
```

### Schritt 5 – Neustart (falls noch nicht erfolgt)

```bash
sudo reboot
```

---

## Programm starten

Es gibt drei Möglichkeiten, die Software zu starten. Für den Dauerbetrieb
wird der systemd-Service empfohlen.

### Option A – systemd-Service (empfohlen, Dauerbetrieb)

Der Service wird beim Boot automatisch gestartet. Nach der Installation läuft er
nach dem nächsten Neustart automatisch.

```bash
# Service manuell starten
sudo systemctl start heta-monitor

# Autostart beim Boot aktivieren (wird durch install.sh bereits gesetzt)
sudo systemctl enable heta-monitor

# Status prüfen
sudo systemctl status heta-monitor
```

Erwartete Ausgabe bei laufendem Service:

```
● heta-monitor.service - HETA Smart Filter Monitoring
     Loaded: loaded (/etc/systemd/system/heta-monitor.service; enabled)
     Active: active (running) since ...
```

Log verfolgen:

```bash
journalctl -u heta-monitor -f
```

Service stoppen oder neu starten:

```bash
sudo systemctl stop heta-monitor
sudo systemctl restart heta-monitor
```

### Option B – Manuell im Terminal (Entwicklung / Fehlersuche)

```bash
cd ~/HETA_Smart_Filter_Monitoring
./scripts/start.sh
```

Das Skript aktiviert das Virtual Environment und startet `backend/app.py`.
Die Ausgabe erscheint direkt im Terminal – praktisch um Fehler zu sehen.

Alternativ direkt mit Python:

```bash
cd ~/HETA_Smart_Filter_Monitoring
source .venv/bin/activate
python3 backend/app.py
```

Mit `Ctrl+C` stoppen.

### Option C – Direkt mit Python ohne Virtual Environment

Nur falls kein `.venv` vorhanden ist:

```bash
cd ~/HETA_Smart_Filter_Monitoring
python3 backend/app.py
```

> **Hinweis:** In diesem Fall müssen alle Abhängigkeiten systemweit installiert sein.

### Weboberfläche öffnen

Nach dem Start im Browser aufrufen:

```
http://<IP-Adresse>:8080
```

Die IP-Adresse des Pi ermitteln:

```bash
hostname -I
# Beispiel: 192.168.1.42
```

Beim **ersten Start** öffnet sich automatisch der Einrichtungsassistent (Onboarding).

---

## Ersteinrichtung (Onboarding)

Beim ersten Start öffnet sich automatisch ein **6-stufiger Einrichtungsassistent**.
Der Messzyklus startet erst nach Abschluss.

| Schritt | Inhalt |
|---------|--------|
| 1 | Willkommen – Ablauf des Assistenten |
| 2 | Betriebsart wählen: **Hardware** (Realbetrieb, Voreinstellung) oder **Simulation** (Fallback/Test) |
| 3 | Filterparameter: dp-Grenzwert, Sauberwiderstand, max. Durchfluss, Druckbereich |
| 4 | Temperatursensor-Bereich (min/max °C) |
| 5 | Zugriffspasswort für den Einstellungsbereich festlegen (mind. 4 Zeichen) |
| 6 | Zusammenfassung bestätigen → System startet |

> **Hardwaremodus** ist die Voreinstellung. Wird ein Sensor nicht erreicht, stoppt die Messung
> sofort und ein Overlay fordert den Bediener zur Prüfung der Verdrahtung auf. Der Simulationsmodus
> ist kein automatischer Fallback – er muss bewusst aktiviert werden (hier im Onboarding oder später
> über die Einstellungen).

---

## HETA-Code aktivieren

1. Weboberfläche öffnen: `http://<IP>:8080`
2. HETA-Code eingeben, z. B. `HETA-12345`
3. „Demo-PIN anzeigen" klicken → PIN wird automatisch berechnet
4. „Aktivieren" klicken

**Beispiel:** Code `HETA-12345` → PIN `486082`

Mit aktivem HETA-Code werden der **Beladungsgrad** angezeigt und nach 3 Filterzyklen
eine **sekundengenaue Reststandzeit** ausgegeben.

---

## Reststandzeit – Anzeigemodi

| Modus | Bedingung | Beispiel |
|-------|-----------|---------|
| **BASIS** | Kein HETA-Code | `2–4 Std.`, `1–2 Tage` |
| **HETA-Lernend** | HETA aktiv, < 3 Zyklen | `4–6 Std.` (1/3 Zyklen) |
| **HETA-Validiert** | 3 Zyklen abgeschlossen | `1 Std. 52 min 30 s`, `47 min 15 s`, `23 s` |

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

## Software-Updates (Entwicklung & Testphase)

### Option A – Update-Button im Dashboard (empfohlen)

Der einfachste Weg: direkt im Browser, ohne Terminal.

1. Einstellungen öffnen (⚙-Symbol oben rechts)
2. Passwort eingeben und anmelden
3. Ganz unten: Abschnitt **„Software-Update"**
4. Button **„↓ Update von GitHub holen"** klicken

Was passiert:
- `git pull --ff-only` wird auf dem Pi ausgeführt
- Die Git-Ausgabe erscheint direkt im Terminal-Fenster
- Bei vorhandenen Änderungen startet der Dienst automatisch neu
- Die Seite lädt sich nach dem Neustart selbst neu

```
┌──────────────────────────────────────────────┐
│  Software-Update                             │
│  Holt den aktuellen Stand von GitHub und     │
│  startet den Dienst automatisch neu.         │
│                                              │
│  [ ↓ Update von GitHub holen ]              │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │ remote: Enumerating objects: 5 ...     │  │
│  │ From github.com/aracon30/HETA_Smart... │  │
│  │    b59b95a..a1c3e7f  main -> main      │  │
│  │ Updating b59b95a..a1c3e7f             │  │
│  │ ✓ Änderungen geladen.                  │  │
│  │ Dienst wird neu gestartet…             │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

> **Bereits aktuell?** Das Dashboard zeigt `✓ Bereits auf dem aktuellen Stand.`
> und startet den Dienst nicht neu.

### Option B – SSH-Deploy-Skript (Entwicklungsrechner)

Für schnelle Deployments direkt vom Entwicklungsrechner (Mac/Linux/Windows mit WSL):

```bash
# Standard – Pi über Hostname erreichbar
./scripts/deploy.sh

# Mit expliziter IP-Adresse
./scripts/deploy.sh pi@192.168.1.42

# Mit individuellem Pfad
./scripts/deploy.sh pi@192.168.1.42 /opt/heta
```

Das Skript führt auf dem Pi aus:

```
── git pull ──
From github.com/aracon30/HETA_Smart_Filter_Monitoring
   b59b95a..a1c3e7f  main -> main

── Dienst neu starten ──

── Status ──
active
✓ heta-monitor läuft.

✓ Deployment abgeschlossen.
  Dashboard: http://192.168.1.42:8080
```

**Voraussetzung für Option B:**
SSH-Zugang ohne Passwort einrichten (empfohlen für häufige Deployments):

```bash
# Einmalig auf dem Entwicklungsrechner:
ssh-copy-id pi@<IP-Adresse>
```

### Wann welche Option?

| Situation | Empfehlung |
|-----------|-----------|
| Update schnell vom Browser aus | Option A (Dashboard) |
| Viele schnelle Iterationen vom PC | Option B (deploy.sh) |
| Kein SSH eingerichtet | Option A |
| Neues Gerät ohne SSH-Key | Option A für ersten Boot, dann Option B |

### Neustart-Logik

Der Dienst startet nach einem Update automatisch neu:

1. Versuch: `sudo systemctl restart heta-monitor` (systemd-Service, bevorzugt)
2. Fallback: Ein losgelöster Kindprozess startet `backend/app.py` nach 3 Sekunden neu
   (kein FD-Erbe, kein „Port belegt"-Fehler – funktioniert auch ohne systemd)

Der sudo-Eintrag für `systemctl restart` wird automatisch durch `install.sh` angelegt.
Falls nötig manuell einrichten:

```bash
sudo visudo -f /etc/sudoers.d/heta-monitor
# Zeile:
pi ALL=(ALL) NOPASSWD: /bin/systemctl restart heta-monitor
```

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

Screen 3 – Service          Screen 4 – Historie
┌──────────────────────┐    ┌────────────────────────────┐
│       SERVICE        │    │         HISTORIE            │
│ [NIEDRIG]            │    │ #1:  142 min  23.04.25      │
│                      │    │ #2:   98 min  28.04.25      │
│ Betrieb normal.      │    │ #3:  167 min  02.05.25      │
│ Filter OK.           │    │ #4:  121 min  07.05.25      │
│  □  □  □  ●  □  □    │    │      □  □  □  □  ●  □       │
└──────────────────────┘    └────────────────────────────┘

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
| POST | `/api/sensor/recheck` | Sensoren nach Bediener-Bestätigung prüfen – Messung neu starten |

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

### Service, Export & Update

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| POST | `/api/service/request` | Servicebericht erzeugen |
| GET  | `/api/export/csv/download` | Messdaten als CSV herunterladen |
| POST | `/api/update/pull` | `git pull` ausführen und Dienst neu starten (`X-Auth-Token` erforderlich) |

---

## Fehlersuche

**Software startet nicht:**
```bash
# Direkt im Terminal starten – Fehler werden sofort angezeigt
cd ~/HETA_Smart_Filter_Monitoring
source .venv/bin/activate
python3 backend/app.py

# Oder systemd-Logs prüfen
journalctl -u heta-monitor -n 50 --no-pager
```

**Weboberfläche nicht erreichbar:**
```bash
# IP-Adresse prüfen
hostname -I

# Läuft der Dienst?
sudo systemctl status heta-monitor

# Port belegt?
ss -tlnp | grep 8080

# Port noch belegt nach Update/Neustart:
sudo fuser -k 8080/tcp          # Prozess auf Port 8080 sofort beenden
sudo systemctl start heta-monitor
```

**Nach Service-Update (`install.sh` erneut ausführen) muss die Unit neu geladen werden:**
```bash
sudo systemctl daemon-reload
sudo systemctl restart heta-monitor
```

**Onboarding erscheint nach jedem Start:**
```bash
# Prüfen ob onboarding_complete gesetzt ist
cat config/settings.json | grep onboarding_complete
# Muss "onboarding_complete": true sein
```

**Passwort vergessen:**
```bash
# settings_password_hash leeren – Onboarding startet neu
nano config/settings.json
# settings_password_hash auf "" setzen, speichern
sudo systemctl restart heta-monitor
```

**OLED zeigt nichts:**
- SPI aktiviert? `ls /dev/spidev*` muss `/dev/spidev0.0` zeigen
- DC an **GPIO 25** (Board-Pin 22)? RES an **GPIO 27** (Board-Pin 13)?
- Lötbrücke auf dem Modul: SPI-Position (Werkseinstellung)?
- Weitere Details: [`docs/hardware_mapping.md`](docs/hardware_mapping.md)

**Encoder reagiert nicht:**
```bash
# I2C aktiviert?
ls /dev/i2c-*

# Encoder gefunden? Muss 0x49 zeigen
i2cdetect -y 1
```

**Sensor-Fault – Overlay erscheint, Messung gestoppt:**

Ein Sensorausfall im Hardwaremodus stoppt die Messung sofort. Im Dashboard erscheint ein blockierendes
rotes Overlay mit den ausgefallenen Kanälen (z. B. „p1 (Eintrittsdruck)", „Q (Durchfluss)").

Vorgehensweise:
1. Verdrahtung und Versorgung der genannten Kanäle prüfen
2. „Alle Sensoren angeschlossen – System prüfen" klicken → `POST /api/sensor/recheck`
   - Alle OK: Messung startet automatisch neu, Overlay verschwindet
   - Noch Fehler: Overlay bleibt mit aktualisierten Kanalinformationen
3. Falls Weiterbetrieb im Simulationsmodus nötig: aufklappbaren Bereich „Im Simulationsmodus fortfahren"
   öffnen → Passwort eingeben → Simulation wird aktiviert (nur für Tests)

Prüfpunkte bei Sensor-Fault:
- SPI aktiviert? `ls /dev/spidev*` muss `/dev/spidev0.0` zeigen
- AnoPi Shield korrekt aufgesteckt?
- 24-V-Sensorversorgung vorhanden?
- Header-Badge `SIM` (grau): Simulationsmodus bewusst gewählt
- Header-Badge `FEHLER` (dunkelrot): aktiver Sensor-Fault

**HETA-Code ungültig:**
Format `HETA-XXXXX` (nur Ziffern nach dem Bindestrich), PIN 6-stellig mit führenden Nullen.

**Update schlägt fehl (`git pull` Fehler):**
```bash
# Manuell prüfen
cd ~/HETA_Smart_Filter_Monitoring
git status
git pull
```
Lokale Änderungen an Konfigurationsdateien können Konflikte verursachen:
```bash
git stash
git pull
git stash pop
```

**Einstellungen gespeichert, Lernphasen neu:**
Erwartetes Verhalten – bei Änderung lernrelevanter Parameter werden alle
Zyklen und Profile zurückgesetzt.

---

## Systemd-Service – Übersicht

```bash
# Starten
sudo systemctl start heta-monitor

# Stoppen
sudo systemctl stop heta-monitor

# Neu starten
sudo systemctl restart heta-monitor

# Status anzeigen
sudo systemctl status heta-monitor

# Autostart aktivieren/deaktivieren
sudo systemctl enable heta-monitor
sudo systemctl disable heta-monitor

# Logs live verfolgen
journalctl -u heta-monitor -f

# Letzte 100 Log-Zeilen
journalctl -u heta-monitor -n 100 --no-pager
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
    ├── install.sh          Installationsskript (einmalig ausführen)
    ├── start.sh            Manueller Start (Entwicklung)
    └── deploy.sh           SSH-Deploy vom Entwicklungsrechner
```
