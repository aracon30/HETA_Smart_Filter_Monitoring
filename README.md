# HETA Smart Filter Monitoring

Prototyp-Software für ein intelligentes Filterüberwachungssystem auf Basis des **Raspberry Pi 5**.
Die Software erfasst Sensordaten (4–20 mA), berechnet den Filterzustand, protokolliert Daten und stellt eine lokale Weboberfläche sowie ein OLED-Display bereit.

---

## Hardwareübersicht

| Komponente              | Funktion                              |
|-------------------------|---------------------------------------|
| Raspberry Pi 5          | Zentrale Recheneinheit                |
| AnoPi Raspberry Shield  | 4 × 4–20 mA Analogeingänge           |
| ifm PL5423 (×2)         | Eintrittsdruck p1 und Austrittsdruck p2 |
| ifm TA2405              | Temperaturmessung                    |
| Keyence FD-X            | Durchflussmessung Q                  |
| 2.42" OLED-Display      | Lokale Anzeige                       |
| Adafruit ANO Encoder    | Menünavigation                        |
| Ethernet                | Weboberfläche via LAN                |

---

## Installationsanleitung (Raspberry Pi 5)

### Voraussetzungen
- Raspberry Pi OS Lite 64-bit
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

Das Skript installiert alle Python-Pakete, gibt SPI/I2C-Hinweise und richtet den systemd-Dienst ein.

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

1. Betriebsart wählen (Simulation oder Hardware)
2. Filterparameter eingeben (dp-Grenzwert, Sauberwiderstand, Durchfluss)
3. Temperatursensor-Bereich konfigurieren
4. Zugriffspasswort für den Einstellungsbereich festlegen
5. Zusammenfassung bestätigen

Der Messzyklus startet erst nach Abschluss des Onboardings.

---

## Start im Simulationsmodus

```bash
./scripts/start.sh
# → Onboarding-Assistent öffnet sich beim ersten Start automatisch
```

Weboberfläche: `http://localhost:8080`

---

## Start im Hardwaremodus

Betriebsart im Onboarding oder im Einstellungsbereich (⚙) auf **Hardware** setzen.

```bash
./scripts/start.sh
```

---

## HETA-Code aktivieren

1. Weboberfläche öffnen: `http://<IP>:8080`
2. HETA-Code eingeben: `HETA-12345`
3. „Demo-PIN anzeigen" klicken → PIN wird berechnet und eingetragen
4. „Aktivieren" klicken

**Beispiel:** Code `HETA-12345` → PIN `486082`

Mit aktivem HETA-Code werden **Beladungsgrad** angezeigt und nach 3 Filterzyklen
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

## API-Endpunkte

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET  /api/status` | Vollständiger Systemstatus |
| `GET  /api/measurements/latest` | Letzte Messwerte |
| `POST /api/heta/activate` | HETA-Code + PIN aktivieren |
| `POST /api/filter/confirm-change` | Filterwechsel bestätigen |
| `POST /api/service/request` | Servicebericht erzeugen |
| `GET  /api/export/csv/download` | Messdaten als CSV herunterladen |
| `GET  /api/onboarding/status` | Onboarding-Status prüfen |
| `POST /api/onboarding/complete` | Onboarding abschließen |
| `POST /api/settings/login` | Am Einstellungsbereich anmelden |
| `POST /api/settings` | Konfiguration speichern (Token erforderlich) |

Vollständige API-Referenz: [`docs/software_architecture.md`](docs/software_architecture.md)

---

## CSV-Export

Über Weboberfläche → „CSV exportieren" oder direkt:
`http://<IP>:8080/api/export/csv/download`

---

## Fehlersuche

**Software startet nicht:**
```bash
python3 backend/app.py
# oder: journalctl -u heta-monitor -n 50
```

**Onboarding erscheint erneut:** `onboarding_complete` in `config/settings.json` prüfen.

**Passwort vergessen:** `settings_password_hash` in `config/settings.json` leeren,
dann startet das Onboarding neu.

**OLED zeigt nichts:** SPI/I2C aktiviert? Verkabelung prüfen → [`docs/hardware_mapping.md`](docs/hardware_mapping.md)

**Sensorwerte bleiben 0:** Betriebsart auf Simulation prüfen. AnoPi-Verkabelung kontrollieren.

**HETA-Code ungültig:** Format `HETA-XXXXX` (nur Ziffern), PIN 6-stellig mit führenden Nullen.

**Einstellungen gespeichert, Lernphasen neu:** Erwartetes Verhalten – bei Änderung
lernrelevanter Parameter werden alle Zyklen und Profile zurückgesetzt.

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
├── backend/     Python-Module (Flask, Sensoren, Berechnungen, Auth)
├── frontend/    Web-Dashboard (HTML, CSS, JavaScript)
├── config/      Konfigurationsdateien (settings.json)
├── data/        SQLite-Datenbank (auto-erstellt)
├── logs/        Log-Dateien (auto-erstellt)
├── exports/     CSV-Exporte (auto-erstellt)
├── docs/        Technische Dokumentation
└── scripts/     Installations- und Startskripte
```