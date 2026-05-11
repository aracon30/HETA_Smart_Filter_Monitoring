# Software-Architektur – HETA Smart Filter Monitoring

## Modulstruktur

```
HETA_Smart_Filter_Monitoring/
├── backend/
│   ├── app.py              Flask-Webserver, REST-API, Messzyklus-Thread,
│   │                       Auth, _DisplayController
│   ├── config.py           Konfigurationsmanagement, Passwort-Hashing (SHA-256)
│   ├── sensors.py          Sensorlesemodul + FilterSimulator (S-Kurve)
│   ├── calculations.py     Berechnungsalgorithmen + Statuslogik
│   ├── heta_code.py        HETA-Code-Validierung + PIN-Algorithmus
│   ├── learning.py         Lernzyklen + Referenzprofile
│   ├── prediction.py       Reststandzeit-Prognose + Glättung (3 Modi)
│   ├── service_logic.py    Serviceempfehlungen + Serviceberichte
│   ├── database.py         SQLite-Datenbankmodul + Lerndaten-Reset
│   ├── display.py          OLED-Display-Steuerung (luma.oled + PIL-Layout)
│   ├── navigation.py       Drehencoder-Navigation (Adafruit Seesaw)
│   └── mqtt_client.py      Optionaler MQTT-Client (paho-mqtt)
├── frontend/
│   ├── index.html          Single-Page Dashboard + Onboarding + Einstellungs-Modal
│   ├── style.css           Industrielles Stylesheet (HETA-Blau)
│   └── app.js              REST-API-Polling, Chart.js, Onboarding, Auth
├── config/
│   └── settings.json       Alle Konfigurationsparameter
├── data/                   SQLite-Datenbank (auto-erstellt)
├── logs/                   Log-Dateien (auto-erstellt)
├── exports/                CSV-Exporte (auto-erstellt)
├── docs/
│   ├── software_architecture.md
│   └── hardware_mapping.md
├── scripts/
│   ├── install.sh          Installationsskript
│   └── start.sh            Manueller Start
└── requirements.txt
```

---

## Ersteinrichtung (Onboarding)

Beim ersten Start erkennt die Software `onboarding_complete: false` in `settings.json`
und zeigt automatisch einen 6-stufigen Einrichtungsassistenten an.

| Schritt | Inhalt |
|---------|--------|
| 1 | Willkommen – Erklärung des Ablaufs |
| 2 | Betriebsart – Simulation oder Hardware |
| 3 | Filterparameter – dp_limit, dp_clean, flow_max, Druckbereich |
| 4 | Temperatursensor – Messbereich min/max |
| 5 | Zugriffspasswort festlegen (mind. 4 Zeichen) |
| 6 | Zusammenfassung und Abschluss |

Der Messzyklus startet erst nach erfolgreich abgeschlossenem Onboarding.

---

## Passwortgeschützter Einstellungsbereich

Einstellungen können im laufenden Betrieb über das Zahnrad-Symbol (⚙) im Dashboard
geändert werden.

### Authentifizierung

- Passwort als SHA-256-Hash in `settings.json` (`settings_password_hash`)
- Nach korrekter Eingabe: zufälliger Session-Token (`secrets.token_hex(32)`)
- Timeout: 30 Minuten Inaktivität (konfigurierbar: `session_timeout_minutes`)
- Token im Browser-`sessionStorage`, Header `X-Auth-Token` bei Schreibzugriffen

### Lernphasen-Reset bei Konfigurationsänderung

Wenn folgende Parameter geändert werden, löscht `db.reset_all_learning_data()`
alle Zyklen und Profile – das System muss 3 neue Filterzyklen durchlaufen:

| Parameter | Beschreibung |
|-----------|-------------|
| `dp_limit_bar` | Differenzdruck-Grenzwert |
| `dp_clean_bar` | Sauberwiderstand neuer Filter |
| `flow_max_l_min` | Maximaler Durchfluss (Sensorendwert) |
| `pressure_range_bar` | Messbereich der Drucksensoren |

Das Ereignis wird als `LERNDATEN_RESET` in der Datenbank protokolliert.

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

> Wird im Dashboard nur angezeigt, wenn ein HETA-Code aktiv ist.
> Im Basis-Modus bleibt die Karte ausgegraut.

### Filterzustand in Prozent

```
filter_health_percent = 100 × (1 − clamp(usage, 0, 1))
```

### Statuslogik

| Bedingung | Status |
|-----------|--------|
| dp < 0,75 × dp_limit, kein Fehler | `OK` |
| dp ≥ 0,75 × dp_limit | `BEOBACHTEN` |
| dp ≥ dp_limit | `WECHSEL` |
| Filterwechsel ausgelöst, wartet auf Bestätigung | `WECHSEL_BESTAETIGEN` |
| Beladungsverhalten weicht stark vom Referenzprofil ab | `WARNUNG` |
| Sensorfehler (Kabelbruch, Über-/Unterbereich) | `FEHLER` |

---

## Datenbankstruktur (SQLite)

### Tabelle: measurements

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| id | INT | Primärschlüssel |
| timestamp | REAL | Unix-Zeitstempel |
| p1_bar | REAL | Eintrittsdruck |
| p2_bar | REAL | Austrittsdruck |
| dp_bar | REAL | Differenzdruck |
| flow_l_min | REAL | Durchfluss |
| temperature_c | REAL | Temperatur |
| r_eff | REAL | Filterwiderstand |
| filter_health_percent | REAL | Beladungsgrad % |
| status | TEXT | Filterstatus |
| heta_code | TEXT | Aktiver HETA-Code |
| sensor_mode | TEXT | `hardware` / `simulation` |

### Tabelle: filter_cycles

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| id | INT | Primärschlüssel |
| heta_code | TEXT | HETA-Code |
| start_time | REAL | Zyklusstart |
| end_time | REAL | Zyklusende |
| duration_seconds | REAL | Dauer in Sekunden |
| start_r_eff | REAL | Startwiderstand |
| end_r_eff | REAL | Endwiderstand |
| start_dp | REAL | Start-Differenzdruck |
| end_dp | REAL | End-Differenzdruck |
| average_flow | REAL | Mittlerer Durchfluss |
| average_temperature | REAL | Mittlere Temperatur |
| loading_rate | REAL | Beladungsrate (bar/s) |
| confirmed_filter_change | INT | 1 = bestätigt |

Relevante Abfragen:
- `get_cycles_for_heta(heta_code)` – alle Zyklen eines HETA-Codes
- `get_recent_cycles(limit)` – letzte N Zyklen (alle Codes, für Historie-Display)
- `count_confirmed_cycles(heta_code)` – Anzahl bestätigter Zyklen
- `reset_all_learning_data()` – löscht alle Zyklen und Profile

### Tabelle: heta_profiles

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| heta_code | TEXT | Primärschlüssel |
| reference_r_eff | REAL | Referenz-Startwiderstand |
| reference_loading_rate | REAL | Referenz-Beladungsrate |
| cycles_count | INT | Anzahl bestätigter Zyklen |
| profile_valid | INT | 1 = valides Profil (≥ 3 Zyklen) |
| last_updated | REAL | Letzte Aktualisierung |

### Tabelle: service_events

Protokolliert systemrelevante Ereignisse:
`HETA_AKTIVIERT`, `FILTERWECHSEL_BESTAETIGT`, `SERVICE_ANFRAGE`,
`LERNDATEN_RESET`, `ONBOARDING_ABGESCHLOSSEN`

---

## Prognosemodi

Filterlaufzeiten variieren je nach Anwendung extrem – von Minuten bis Tagen.
Die Anzeige passt sich dem verfügbaren Wissensstand an.

### BASIS

- Kein HETA-Code aktiv
- Adaptive Bereichsanzeige in Stunden/Tagen, **keine Minutenangaben**
- Beladungsgrad wird nicht angezeigt

| Reststandzeit | Anzeige |
|--------------|---------|
| > 5 Tage | `> 5 Tage` |
| 3–5 Tage | `3–5 Tage` |
| 2–3 Tage | `2–3 Tage` |
| 1–2 Tage | `1–2 Tage` |
| 12–24 Std. | `12–24 Std.` |
| 6–12 Std. | `6–12 Std.` |
| 4–6 Std. | `4–6 Std.` |
| 2–4 Std. | `2–4 Std.` |
| 1–2 Std. | `1–2 Std.` |
| < 1 Std. | `< 1 Std.` |

### HETA_LERNEND

- HETA-Code aktiv, aber < 3 bestätigte Zyklen
- Breite Bereichsanzeige (identische Tabelle wie BASIS)
- Lernfortschritt sichtbar: z. B. `(1/3 Zyklen)`
- Beladungsgrad wird angezeigt

### HETA_VALIDIERT

- HETA-Code aktiv **und** ≥ 3 vollständige Zyklen
- **Minutengenaue** Ausgabe: `1 Std. 52 min` oder `47 min`
- Beladungsgrad wird angezeigt

### Glättungsalgorithmus

```python
# Anstieg stark begrenzen (max. +2 % pro Update)
if new_raw > current:
    new_raw = min(new_raw, current * 1.02)
# Abfall schneller erlaubt (max. −8 % pro Update)
else:
    new_raw = max(new_raw, current * 0.92)

# Exponentielle Glättung
smoothed = current + 0.15 × (new_raw - current)
```

---

## Lernlogik

1. **Zyklus starten** – beim ersten gültigen Messwert nach Filterwechsel (mit aktivem HETA-Code)
2. **Messwerte sammeln** – flow, temperature, dp, r_eff je Sekunde
3. **Zyklus beenden** – wenn Benutzer den Filterwechsel bestätigt (Dashboard oder Encoder)
4. **Profil berechnen** – Mittelwert aller bestätigten Zyklen
5. **Validierung** – Profil gilt nach ≥ 3 vollständigen, bestätigten Zyklen

### Startverhalten-Prüfung

Nach jedem Filterwechsel wird r_eff der ersten 10 Sekunden mit dem Referenzprofil
verglichen. Abweichung > 25 % → Status `WARNUNG`.

---

## OLED-Display und Encoder-Navigation

### Display-Layout (128 × 64 px, monochrom)

```
y =  0..11  Invertierter Header-Balken (weiß/schwarz)
y = 12      Trennlinie
y = 13..57  Inhaltsbereich (5 Zeilen à 9 px, DejaVuSans 8 pt)
y = 60..62  Navigationspunkte (● aktiv / □ inaktiv)
```

### 6 Bildschirme

| Index | Name | Inhalt |
|-------|------|--------|
| 0 | **Status** | p1, p2, dp + Status-Abzeichen, dp/Grenzwert-Balken, Q, T, Reststandzeit |
| 1 | **HETA-Code** | Code, Aktivierungsstatus, Zyklen-Kästchen [■][■][□], Prognosemodus |
| 2 | **Filterwechsel** | dp, Limit, Fortschrittsbalken, zweistufige Bestätigung |
| 3 | **Service** | Prioritäts-Abzeichen (invertiert bei HOCH), Meldungstext |
| 4 | **Historie** | Letzte 4 Zyklen mit Dauer und Datum |
| 5 | **Netzwerk** | IP, Port, Betriebsmodus, vollständige URL |

Auf jedem Bildschirm zeigen 6 Punkte am unteren Rand die aktuelle Position:
`●` = aktiv, `□` = inaktiv.

### _DisplayController (backend/app.py)

Verbindet `NavigationController` (Encoder) mit `OLEDDisplay` (Display).

```
Encoder-Ereignis → NavigationController._dispatch()
                 → _DisplayController._on_event()
                 → _handle() → Bildschirmwechsel oder Bestätigung
                             → _display.set_nav_index()
                             → _refresh_display()
```

**Encoder-Ereignisse:**

| Ereignis | Aktion |
|----------|--------|
| `ROTATE_RIGHT` / `RIGHT` | Nächster Bildschirm (Modulo 6) |
| `ROTATE_LEFT` / `LEFT` | Vorheriger Bildschirm |
| `LEFT` (während armed) | Filterwechsel-Bestätigung abbrechen |
| `PRESS` auf Screen 2, awaiting=False | kein Effekt |
| `PRESS` auf Screen 2, awaiting=True | Bestätigung vormerken (armed) |
| `PRESS` auf Screen 2, armed=True | Filterwechsel ausführen, zurück zu Screen 0 |

**Zweistufige Filterwechsel-Bestätigung:**

```
dp ≥ dp_limit
    → _state["awaiting_confirmation"] = True
    → Display springt automatisch auf Screen 2
    → show_filter_change(awaiting=True)

1. OK-Druck:
    → _confirm_armed = True
    → show_filter_change(armed=True): "SICHER? BESTAETIGEN?"

2. OK-Druck (oder Taste LINKS zum Abbrechen):
    → _do_confirm_filter_change()  ← auch via REST POST /api/filter/confirm-change
    → predictor.reset() + reset_simulation()
    → Screen 0 (Status)
```

### _do_confirm_filter_change()

Zentrale Funktion, die sowohl vom REST-API-Endpunkt als auch vom
`_DisplayController` aufgerufen wird:

1. Aktiven Lernzyklus mit `learning.end_cycle(confirmed=True)` abschließen
2. `predictor.reset()` und `reset_simulation()` aufrufen
3. `_state["awaiting_confirmation"] = False`, Zyklusdaten zurücksetzen
4. Ereignis `FILTERWECHSEL_BESTAETIGT` in Datenbank protokollieren

---

## REST-API-Endpunkte

### Allgemein (öffentlich)

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| GET | `/api/status` | Vollständiger Systemstatus |
| GET | `/api/measurements/latest` | Letzte N Messwerte (`?limit=100`) |
| GET | `/api/measurements/history` | Messwerte seit Zeitstempel (`?since=`) |
| GET | `/api/cycles` | Filterzyklen für HETA-Code |
| GET | `/api/profile` | Lernprofil für HETA-Code |
| POST | `/api/heta/activate` | HETA-Code + PIN aktivieren |
| GET | `/api/heta/demo` | Demo-PIN anzeigen (Entwicklung) |
| POST | `/api/filter/confirm-change` | Filterwechsel bestätigen |
| POST | `/api/simulation/start` | Simulation starten |
| POST | `/api/simulation/stop` | Messzyklus stoppen |
| POST | `/api/simulation/reset` | System zurücksetzen |
| GET | `/api/export/csv` | CSV-Export-Info |
| GET | `/api/export/csv/download` | CSV-Download |
| POST | `/api/service/request` | Servicebericht erzeugen |

### Display & Navigation

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| POST | `/api/navigation/event` | Encoder-Ereignis simulieren |
| GET | `/api/display/screen` | Aktiven Bildschirm und Zustand abfragen |

`POST /api/navigation/event` Body:
```json
{ "event": "ROTATE_RIGHT" }
```
Gültige Werte: `ROTATE_LEFT`, `ROTATE_RIGHT`, `PRESS`, `LEFT`, `RIGHT`, `UP`, `DOWN`

`GET /api/display/screen` Antwort:
```json
{ "screen": "Status", "screen_index": 0, "confirm_armed": false }
```

### Onboarding

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| GET | `/api/onboarding/status` | Prüfen ob Onboarding abgeschlossen |
| POST | `/api/onboarding/complete` | Onboarding abschließen, Passwort setzen |

### Einstellungen (erfordert `X-Auth-Token` Header)

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| POST | `/api/settings/login` | Anmelden, Token erhalten |
| POST | `/api/settings/logout` | Abmelden, Token löschen |
| GET | `/api/settings/auth-check` | Token-Gültigkeit prüfen |
| GET | `/api/settings` | Konfiguration lesen (ohne Passwort-Hash) |
| POST | `/api/settings` | Konfiguration speichern |

### `/api/status` – Wichtige Felder

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `filter_status` | string | `OK` / `BEOBACHTEN` / `WECHSEL` / `WECHSEL_BESTAETIGEN` / `WARNUNG` / `FEHLER` |
| `prediction_mode` | string | `BASIS` / `HETA_LERNEND` / `HETA_VALIDIERT` |
| `remaining_display` | string | Formatierte Reststandzeit (modus-abhängig) |
| `show_filter_health` | bool | Beladungsgrad anzeigen (nur wenn HETA aktiv) |
| `heta_activated` | bool | HETA-Code aktiv |
| `learned_cycles` | int | Anzahl bestätigter Zyklen |
| `profile_status` | string | `LERNEND` / `VALIDIERT` |
| `awaiting_confirmation` | bool | Filterwechsel wartet auf Bestätigung |
| `anomaly_active` | bool | Startverhalten-Anomalie erkannt |
| `anomaly_percent` | float | Abweichung vom Referenzprofil in % |

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

**Beispiel:** `HETA-12345` → PIN `486082`

---

## Betriebsmodi

| Modus | Beschreibung |
|-------|-------------|
| Simulation | Simulierte Sensordaten ohne Hardware (Standard beim Onboarding) |
| Hardware | Echte 4–20 mA Werte vom AnoPi Shield |
| Simulations-Fallback | Automatisch wenn Hardware nicht erkannt wird |

Umschaltung über Onboarding, Einstellungsbereich (⚙) oder `POST /api/settings`.

---

## Konfigurationsparameter (`config/settings.json`)

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `onboarding_complete` | `false` | Ersteinrichtung abgeschlossen |
| `settings_password_hash` | `""` | SHA-256-Hash des Einstellungspassworts |
| `session_timeout_minutes` | `30` | Timeout der Einstellungs-Session |
| `simulation_mode` | `true` | Simulationsmodus aktiv |
| `dp_limit_bar` | `2.5` | Differenzdruck-Grenzwert für Filterwechsel ⚠ |
| `dp_clean_bar` | `0.2` | Differenzdruck eines sauberen Filters ⚠ |
| `pressure_range_bar` | `10` | Messbereich Drucksensoren (20 mA-Endwert) ⚠ |
| `temperature_min_c` | `-50` | Messbereich Temperatursensor Minimum |
| `temperature_max_c` | `150` | Messbereich Temperatursensor Maximum |
| `flow_max_l_min` | `150` | Maximaler Durchfluss (20 mA-Endwert) ⚠ |
| `sampling_interval_seconds` | `1` | Messintervall in Sekunden |
| `required_cycles_for_profile` | `3` | Anzahl Zyklen für valides Profil |
| `clean_resistance_tolerance` | `0.25` | Toleranz Startverhalten-Prüfung (25 %) |
| `smoothing_factor` | `0.15` | Glättungsfaktor Reststandzeit |
| `max_increase_percent_per_update` | `2` | Max. Anstieg Reststandzeit pro Update |
| `max_decrease_percent_per_update` | `8` | Max. Abfall Reststandzeit pro Update |
| `mqtt_enabled` | `false` | MQTT-Client aktivieren |
| `webserver_port` | `8080` | HTTP-Port der Weboberfläche |
| `db_path` | `data/heta_monitor.db` | Datenbankpfad |
| `log_path` | `logs/` | Log-Verzeichnis |
| `export_path` | `exports/` | CSV-Export-Verzeichnis |

⚠ = Lernrelevanter Parameter: Änderung löscht alle Zyklen und Profile.
