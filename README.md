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

## Start im Simulationsmodus

```bash
# simulation_mode ist in config/settings.json standardmäßig true
./scripts/start.sh
```

Weboberfläche: `http://localhost:8080`

---

## Start im Hardwaremodus

```bash
# In config/settings.json setzen: "simulation_mode": false
./scripts/start.sh
```

---

## HETA-Code Demo

1. Weboberfläche öffnen: `http://<IP>:8080`
2. HETA-Code eingeben: `HETA-12345`
3. "Demo-PIN anzeigen" klicken → PIN wird berechnet und eingetragen
4. "Aktivieren" klicken

**Beispiel:** Code `HETA-12345` → PIN `486082`

---

## Konfiguration

Alle Parameter in `config/settings.json`:

```json
{
  "dp_limit_bar": 2.5,
  "dp_clean_bar": 0.2,
  "flow_max_l_min": 150,
  "sampling_interval_seconds": 1,
  "simulation_mode": true,
  "webserver_port": 8080
}
```

---

## API-Endpunkte

| Endpunkt                          | Beschreibung                  |
|-----------------------------------|-------------------------------|
| `GET  /api/status`                | Vollständiger Systemstatus    |
| `GET  /api/measurements/latest`   | Letzte Messwerte              |
| `POST /api/heta/activate`         | HETA-Code + PIN aktivieren    |
| `POST /api/filter/confirm-change` | Filterwechsel bestätigen      |
| `POST /api/service/request`       | Servicebericht erzeugen       |
| `GET  /api/export/csv/download`   | Messdaten als CSV herunterladen |
| `GET  /api/settings`              | Konfiguration lesen           |
| `POST /api/settings`              | Konfiguration schreiben       |

Vollständige Dokumentation: [`docs/software_architecture.md`](docs/software_architecture.md)

---

## CSV-Export

Über Weboberfläche → "CSV exportieren" oder direkt:
`http://<IP>:8080/api/export/csv/download`

---

## Fehlersuche

**Software startet nicht:**
```bash
python3 backend/app.py
# oder: journalctl -u heta-monitor -n 50
```

**OLED zeigt nichts:** SPI/I2C aktiviert? Verkabelung prüfen → [`docs/hardware_mapping.md`](docs/hardware_mapping.md)

**Sensorwerte 0:** `simulation_mode: true` in settings.json? AnoPi-Verkabelung prüfen.

**HETA-Code ungültig:** Format `HETA-XXXXX`, nur Ziffern, PIN 6-stellig.

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
├── backend/     Python-Module (Flask, Sensoren, Berechnungen)
├── frontend/    Web-Dashboard (HTML, CSS, JavaScript)
├── config/      Konfigurationsdateien
├── data/        SQLite-Datenbank (auto-erstellt)
├── logs/        Log-Dateien (auto-erstellt)
├── exports/     CSV-Exporte (auto-erstellt)
├── docs/        Technische Dokumentation
└── scripts/     Installations- und Startskripte
```