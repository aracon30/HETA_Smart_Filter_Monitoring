# Software-Architektur – HETA Smart Filter Monitoring

## Modulstruktur

```
HETA_Smart_Filter_Monitoring/
├── backend/
│   ├── app.py              # Flask-Webserver, REST-API, Messzyklus-Thread
│   ├── config.py           # Konfigurationsmanagement (settings.json)
│   ├── sensors.py          # Sensorlesemodul + Filtersimulator
│   ├── calculations.py     # Berechnungsalgorithmen + Statuslogik
│   ├── heta_code.py        # HETA-Code-Validierung + PIN-Algorithmus
│   ├── learning.py         # Lernzyklen + Referenzprofile
│   ├── prediction.py       # Reststandzeit-Prognose + Glättung
│   ├── service_logic.py    # Serviceempfehlungen + Serviceberichte
│   ├── database.py         # SQLite-Datenbankmodul
│   ├── display.py          # OLED-Display-Steuerung (luma.oled)
│   ├── navigation.py       # Drehencoder-Navigation (Seesaw)
│   └── mqtt_client.py      # Optionaler MQTT-Client (paho-mqtt)
├── frontend/
│   ├── index.html          # Single-Page Dashboard
│   ├── style.css           # Industrielles Stylesheet (HETA-Blau)
│   └── app.js              # REST-API-Polling + Chart.js
├── config/
│   └── settings.json       # Alle Konfigurationsparameter
├── data/                   # SQLite-Datenbank (auto-erstellt)
├── logs/                   # Log-Dateien (auto-erstellt)
├── exports/                # CSV-Exporte (auto-erstellt)
├── docs/
│   ├── software_architecture.md
│   └── hardware_mapping.md
├── scripts/
│   ├── install.sh          # Installationsskript
│   └── start.sh            # Manueller Startskript
└── requirements.txt
```

---

## Berechnungsalgorithmen

### Differenzdruck

```
dp_bar = max(0, p1_bar - p2_bar)
```

### Effektiver Filterwiderstand

```
r_eff = dp_bar / max(flow_l_min, 0.1)    [bar·min/l]
```

### Beladungsgrad

```
usage = (dp_bar - dp_clean) / (dp_limit - dp_clean)
```

### Filterzustand in Prozent

```
filter_health_percent = 100 × (1 - clamp(usage, 0, 1))
```

### Statuslogik

| Bedingung                              | Status                |
|---------------------------------------|-----------------------|
| dp < 0,75 × dp_limit, kein Fehler     | OK                    |
| dp ≥ 0,75 × dp_limit                  | BEOBACHTEN            |
| dp ≥ dp_limit                         | WECHSEL               |
| Filterwechsel ausgelöst, wartet auf Bestätigung | WECHSEL_BESTAETIGEN |
| Beladungsverhalten weicht stark ab    | WARNUNG               |
| Sensorfehler                          | FEHLER                |

---

## Datenbankstruktur (SQLite)

### Tabelle: measurements

| Feld                   | Typ   | Beschreibung              |
|------------------------|-------|---------------------------|
| id                     | INT   | Primärschlüssel           |
| timestamp              | REAL  | Unix-Zeitstempel          |
| p1_bar                 | REAL  | Eintrittsdruck            |
| p2_bar                 | REAL  | Austrittsdruck            |
| dp_bar                 | REAL  | Differenzdruck            |
| flow_l_min             | REAL  | Durchfluss                |
| temperature_c          | REAL  | Temperatur                |
| r_eff                  | REAL  | Filterwiderstand          |
| filter_health_percent  | REAL  | Filterzustand %           |
| status                 | TEXT  | Filterstatus              |
| heta_code              | TEXT  | Aktiver HETA-Code         |
| sensor_mode            | TEXT  | hardware/simulation       |

### Tabelle: filter_cycles

| Feld                    | Typ   | Beschreibung              |
|-------------------------|-------|---------------------------|
| id                      | INT   | Primärschlüssel           |
| heta_code               | TEXT  | HETA-Code                 |
| start_time              | REAL  | Zyklusstart               |
| end_time                | REAL  | Zyklusende                |
| duration_seconds        | REAL  | Dauer in Sekunden         |
| start_r_eff             | REAL  | Startwiderstand           |
| end_r_eff               | REAL  | Endwiderstand             |
| start_dp                | REAL  | Start-Differenzdruck      |
| end_dp                  | REAL  | End-Differenzdruck        |
| average_flow            | REAL  | Mittlerer Durchfluss      |
| average_temperature     | REAL  | Mittlere Temperatur       |
| loading_rate            | REAL  | Beladungsrate (bar/s)     |
| confirmed_filter_change | INT   | 1 = bestätigt             |

### Tabelle: heta_profiles

| Feld                    | Typ   | Beschreibung              |
|-------------------------|-------|---------------------------|
| heta_code               | TEXT  | Primärschlüssel           |
| reference_r_eff         | REAL  | Referenz-Startwiderstand  |
| reference_loading_rate  | REAL  | Referenz-Beladungsrate    |
| cycles_count            | INT   | Anzahl bestätigter Zyklen |
| profile_valid           | INT   | 1 = valides Profil        |
| last_updated            | REAL  | Letzte Aktualisierung     |

---

## Prognosemodi

### Basis-Modus
- Aktiv wenn kein valides HETA-Profil vorhanden
- Ausgabe als Bereich in 10-Minuten-Schritten: `80–90 min`
- Berechnung über lineare Regression der letzten 30 dp-Messwerte

### HETA-Validierter Modus
- Aktiv nach 3 bestätigten Filterzyklen mit aktivem HETA-Code
- Ausgabe als konkreter geglätteter Wert: `112 min`
- Exponentielle Glättung mit Sprungbegrenzung

### Glättungsalgorithmus

```python
# Sprung nach oben begrenzen (max. +2% pro Update)
if new_raw > current:
    new_raw = min(new_raw, current × 1.02)

# Sprung nach unten schneller erlaubt (max. -8% pro Update)
else:
    new_raw = max(new_raw, current × 0.92)

# Exponentielle Glättung
smoothed = current + 0.15 × (new_raw - current)
```

---

## Lernlogik

1. **Zyklus starten** – beim ersten Messwert nach Filterwechsel
2. **Messwerte sammeln** – flow, temperature, dp, r_eff je Sekunde
3. **Zyklus beenden** – wenn Filterwechsel bestätigt wird
4. **Profil berechnen** – Mittelwert aus allen bestätigten Zyklen
5. **Validierung** – Profil gilt nach ≥ 3 vollständigen Zyklen

### Startverhalten-Prüfung

Nach Filterwechsel wird der Startwiderstand r_eff mit dem Referenzprofil verglichen.
Abweichung > 25 % (konfigurierbar) → Status `WARNUNG`

---

## REST-API-Endpunkte

| Methode | Endpunkt                      | Beschreibung                     |
|---------|-------------------------------|----------------------------------|
| GET     | /api/status                   | Vollständiger Systemstatus       |
| GET     | /api/measurements/latest      | Letzte N Messwerte               |
| GET     | /api/measurements/history     | Messwerte seit Zeitstempel       |
| POST    | /api/heta/activate            | HETA-Code + PIN aktivieren       |
| GET     | /api/heta/demo                | Demo-PIN anzeigen (nur Test)     |
| POST    | /api/filter/confirm-change    | Filterwechsel bestätigen         |
| GET     | /api/settings                 | Konfiguration lesen              |
| POST    | /api/settings                 | Konfiguration schreiben          |
| POST    | /api/simulation/start         | Simulation starten               |
| POST    | /api/simulation/stop          | Simulation stoppen               |
| POST    | /api/simulation/reset         | System zurücksetzen              |
| POST    | /api/service/request          | Servicebericht erzeugen          |
| GET     | /api/export/csv               | CSV-Export (Dateiinfo)           |
| GET     | /api/export/csv/download      | CSV-Export (Download)            |
| GET     | /api/cycles                   | Filterzyklen für HETA-Code       |
| GET     | /api/profile                  | Lernprofil für HETA-Code         |

---

## HETA-Code-Aktivierungsalgorithmus

```python
def calculate_activation_code(heta_number: str) -> str:
    sum_value = 0
    for i, digit in enumerate(heta_number):
        sum_value = (sum_value + int(digit) * (i + 3) * 17) % 1_000_000
    pin = (sum_value * 7919 + 43127) % 1_000_000
    return str(pin).zfill(6)
```

**Beispiel:**
- HETA-Code: `HETA-12345`
- Aktivierungscode: `486082`

Der Algorithmus ist identisch mit dem separaten HTML-PIN-Generator.

---

## Betriebsmodi

| Modus             | Beschreibung                                      |
|-------------------|---------------------------------------------------|
| Simulation        | Simulierte Sensordaten ohne Hardware              |
| Hardware          | Echte 4–20 mA Werte vom AnoPi Shield              |
| Simulations-Fallback | Automatisch wenn Hardware nicht erkannt wird  |

Umschaltung über `config/settings.json` → `simulation_mode: true/false`
oder über die REST-API `/api/simulation/start` / `/api/simulation/stop`.
