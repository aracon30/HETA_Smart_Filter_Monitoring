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
│   ├── navigation.py       Drehencoder-Navigation (direktes GPIO via gpiozero)
│   ├── mqtt_client.py      Optionaler MQTT-Client (paho-mqtt)
│   └── modbus_server.py    Optionaler Modbus-TCP-Slave (pymodbus, 11 Holding-Register)
├── frontend/
│   ├── index.html          Single-Page Dashboard + Onboarding + Einstellungs-Modal
│   ├── style.css           Industrielles Stylesheet (HETA-Blau)
│   └── app.js              REST-API-Polling, Chart.js, Onboarding, Auth, Git-Update
├── config/
│   └── settings.json       Alle Konfigurationsparameter (Defaults für Erst-Deployment)
├── data/                   SQLite-Datenbank (auto-erstellt, nicht im Git)
├── logs/                   Log-Dateien (auto-erstellt, nicht im Git)
├── exports/                CSV-Exporte (auto-erstellt, nicht im Git)
├── docs/
│   ├── software_architecture.md
│   └── hardware_mapping.md
├── scripts/
│   ├── install.sh          Installationsskript (systemd-Service, Abhängigkeiten)
│   ├── start.sh            Manueller Start ohne systemd
│   └── deploy.sh           SSH-Deploy-Skript für Entwickler-Rechner
└── requirements.txt
```

---

## Ersteinrichtung (Onboarding)

Beim ersten Start erkennt die Software `onboarding_complete: false` in `settings.json`
und zeigt automatisch einen 8-stufigen Einrichtungsassistenten an.

| Schritt | Inhalt |
|---------|--------|
| 1 | Willkommen – Erklärung des Ablaufs |
| 2 | HETA-Code & PIN (optional) – Zahl ohne „HETA-"-Präfix, überspringbar |
| 3 | Betriebsart – Simulation oder Hardware |
| 4 | Betriebsweise – Dauerbetrieb (kontinuierlich) oder Intervallbetrieb (Batch) |
| 5 | Filterparameter – dp_limit, dp_clean, flow_max, Druckbereich |
| 6 | Temperatursensor – Messbereich min/max |
| 7 | Zugriffspasswort festlegen (mind. 4 Zeichen) |
| 8 | Zusammenfassung und Abschluss |

Der Messzyklus startet erst nach erfolgreich abgeschlossenem Onboarding.
`POST /api/simulation/start` gibt HTTP 403 zurück, solange `onboarding_complete: false`.

Frontend: `startPolling()` wird erst aufgerufen, wenn `checkOnboarding()` `true` zurückgibt
(Onboarding abgeschlossen). WIZARD_TOTAL = 8, Schritt 2 ruft `/api/heta/activate` auf.

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

## sensors.py – Architektur

### FilterSimulator

- Thread-sicher: interner `threading.Lock` (`_lock`) schützt `_step`-Zugriff
- `get_readings()` gibt `dp` als Primärwert zurück (auf 4 Stellen gerundet) – nie aus p1–p2 zurückgerechnet
- Im Simulationsmodus enthält `read_sensors()` zusätzlich den Schlüssel `"dp_direct"` mit dem physikalischen dp-Wert
- `update_simulation_params()` setzt `_step=0` innerhalb des Locks (keine Diskontinuität im Signal)

### Neue Funktion: check_hardware_sensors()

```python
check_hardware_sensors() -> dict
# Prüft alle 4 SPI-Kanäle
# Rückgabe: {"all_ok": bool, "failed_channels": [int, ...], "failed_names": [str, ...]}
```

### Kanalbezeichnungen (_CHANNEL_NAMES)

```python
_CHANNEL_NAMES = {
    1: "p1 (Eintrittsdruck)",
    2: "p2 (Austrittsdruck)",
    3: "T (Temperatur)",
    4: "Q (Durchfluss)"
}
```

### Sensor-Fault statt Fallback

`read_sensors()` im Hardwaremodus: Bei Ausfall eines Kanals wird **kein** Simulations-Fallback
ausgelöst. Stattdessen gibt die Funktion `mode="sensor_fault"` zurück. `app.py` setzt daraufhin
`_state["sensor_fault"] = True`, `_state["sensor_fault_channels"]` und `_state["sensor_fault_message"]`
und stoppt den Messzyklus.

---

## Berechnungsalgorithmen

### Differenzdruck

```
dp_bar = max(0, p1_bar - p2_bar)
```

`calculate_filter_state()` akzeptiert den optionalen Parameter `dp_override: Optional[float] = None`.
Wenn gesetzt, wird die p1–p2-Subtraktion übersprungen und `dp_override` direkt verwendet
(Simulationsmodus – verhindert Float-Artefakte durch doppelte Subtraktion).

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

## Flow-Detection-Zustandsautomat

### Zustandsdiagramm

```
[waiting_for_flow]
     |
     | Q > flow_thr AND dp > dp_clean×0.5 stabil für stability_secs
     ↓
[cycle_active]  ←──────────────────────────────────────────────
     |                                                          |
     | Q == 0 für > 1 s                                        | Q > flow_thr wieder stabil
     ↓                                                          |
[cycle_paused] ──────────────────────────────────────────────→─┘
     |
     | Pause > pause_tolerance_seconds
     ↓
ZYKLUS_ABGEBROCHEN → [waiting_for_flow]
```

### Zustandsvariablen in `_state`

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `waiting_for_flow` | bool | System wartet auf stabilen Durchfluss |
| `cycle_paused` | bool | Zyklus pausiert durch Durchflussausfall |
| `cycle_active_seconds` | float | Kumulierte Betriebszeit (ohne Pausen) |
| `cycle_pause_start_time` | float / null | Unix-Zeitstempel des Pausenbeginns |
| `flow_check_q` | float | Aktueller Q-Wert (für Overlay-Anzeige) |
| `flow_check_dp` | float | Aktueller dp-Wert (für Overlay-Anzeige) |
| `flow_threshold` | float | Effektiver Schwellwert (auto oder manuell) |
| `flow_stable_pct` | int | Stabilitätsfenster-Fortschritt 0–100 % |

### Schwellwert-Logik (`_get_flow_thresholds()`)

- Manueller Override in `flow_start_threshold_l_min` hat Vorrang
- Sonst: `flow_start_threshold_auto` (aus Zyklusdaten berechnet)
- Initialer Fallback: `flow_max_l_min × 0.10`
- `_update_auto_thresholds()`: Berechnet min. operativen Q (dp > dp_clean×0.5) × 0.4

### Pausentoleranz nach Betriebsweise

- `continuous`: 30 s (auto) oder `flow_pause_tolerance_seconds`
- `batch`: 60 s (auto) oder `flow_pause_tolerance_seconds`

Max. Pausendauer: `flow_max_pause_days × 86400` Sekunden → dann `ZYKLUS_ABGEBROCHEN`

### Simulationsmodus – Bypass

Im Simulationsmodus wird die gesamte Flow-Detection-Zustandsmaschine **deaktiviert**:

- `waiting_for_flow` wird sofort auf `False` gesetzt; der Zyklus startet ohne Stabilitätsfenster
- `cycle_paused`-Zustand wird verhindert – kein Pause/Resume bei fehlendem Durchfluss
- Die Bedingungen `elif not sim_mode and cycle_paused` und `elif not sim_mode and cycle_active`
  sorgen dafür, dass die Fluss-Überwachungslogik im Sim-Modus komplett übersprungen wird

Grund: Die Simulation steuert Durchfluss und Druckverlauf intern. Eine externe Flussüberwachung
würde Schnellstart (`POST /api/simulation/start`) und automatische Lernzyklen blockieren.

### Modul-Variablen

```python
_flow_stable_since: Optional[float] = None  # Zeitpunkt stabile Fluss-Bedingung
_flow_below_since: Optional[float]  = None  # Zeitpunkt Fluss < Schwellwert
```

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
| duration_seconds | REAL | Dauer in Sekunden (Wall-Clock) |
| active_seconds | REAL | Kumulierte Betriebszeit (excl. Pausen) |
| start_r_eff | REAL | Startwiderstand |
| end_r_eff | REAL | Endwiderstand |
| start_dp | REAL | Start-Differenzdruck |
| end_dp | REAL | End-Differenzdruck |
| average_flow | REAL | Mittlerer Durchfluss |
| average_temperature | REAL | Mittlere Temperatur |
| loading_rate | REAL | Beladungsrate (bar/s) |
| confirmed_filter_change | INT | 1 = bestätigt |
| events_json | TEXT | JSON-Array mit Ereignissen (ts, ts_start, ts_end, severity, category, message) |

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
| reference_avg_flow | REAL | Referenz-Mitteldurchfluss |
| reference_avg_temp | REAL | Referenz-Mitteltemperatur |
| reference_curve_json | TEXT | Referenzkurve als JSON (dp über Zeit in %) |
| reference_duration_seconds | REAL | Mittlere Zyklusdauer (active_seconds) |
| reference_r_eff_start | REAL | Referenz r_eff zu Beginn |
| reference_r_eff_end | REAL | Referenz r_eff am Ende |
| reference_dp_clean | REAL | Mittlerer Start-dp (Sauberfilter-Referenz) |

### Tabelle: cycle_samples

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| id | INT | Primärschlüssel |
| cycle_id | INT | Fremdschlüssel auf filter_cycles |
| timestamp | REAL | Unix-Zeitstempel der Messung |
| dp_bar | REAL | Differenzdruck zum Zeitpunkt der Messung |
| flow_l_min | REAL | Durchfluss zum Zeitpunkt der Messung |
| r_eff | REAL | Filterwiderstand zum Zeitpunkt der Messung |
| filter_health_percent | REAL | Beladungsgrad zum Zeitpunkt der Messung |
| remaining_seconds | REAL | Reststandzeit zum Zeitpunkt der Messung |

### Tabelle: service_events

Protokolliert systemrelevante Ereignisse:
`HETA_AKTIVIERT`, `FILTERWECHSEL_BESTAETIGT`, `SERVICE_ANFRAGE`,
`LERNDATEN_RESET`, `ONBOARDING_ABGESCHLOSSEN`,
`ZYKLUS_ABGEBROCHEN`, `ZYKLUS_PAUSE`, `ZYKLUS_FORTGESETZT`

| Ereignis | Beschreibung |
|----------|-------------|
| `ZYKLUS_ABGEBROCHEN` | Zyklus durch max. Pausendauer (7 Tage) abgebrochen |
| `ZYKLUS_PAUSE` | Zyklus pausiert (Durchfluss weggefallen) |
| `ZYKLUS_FORTGESETZT` | Zyklus nach Pause fortgesetzt |

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
- **Sekundengenaue** Ausgabe: `1 Std. 52 min 30 s`, `47 min 15 s`, `23 s`
- Beladungsgrad wird angezeigt

### Glättungsalgorithmus

Im **BASIS-Modus** (kein Referenzprofil) – `predictor.update(dp_bar)`:
```python
# Abfall sofort übernehmen; Anstieg max. +5 % pro Tick
if raw_remaining < last_remaining:
    last_remaining = raw_remaining
elif raw_remaining > last_remaining * 1.05:
    last_remaining = raw_remaining          # großer Anstieg sofort
else:
    last_remaining += 0.4 * (raw_remaining - last_remaining)
```

Im **HETA_VALIDIERT-Modus** – `predictor.update_with_reference_curve(dp_bar, ref_duration, ref_curve, elapsed)`:

Statt Steigungsberechnung wird die Referenzkurve invertiert:
1. `t_pct` = Position in der Referenzkurve, wo `dp_ref ≈ dp_bar` (lineare Interpolation)
2. Tatsächliche Zyklusdauer schätzen: `actual_duration = elapsed / (t_pct / 100)`
   → reduzierte Last: dp niedrig → t_pct klein → actual_duration groß → Restzeit steigt
   → erhöhte Last: dp hoch → t_pct groß → actual_duration klein → Restzeit sinkt
3. `remaining = actual_duration × (1 − t_pct / 100)`

```python
# Abstieg sofort; echter Anstieg (ratio > 1.05) sofort; Rauschen sanft glätten
ratio = remaining / max(last_remaining, 0.1)
if ratio > 1.05:
    last_remaining = remaining
else:
    last_remaining += 0.4 * (remaining - last_remaining)
```

> `_dp_history` wird in beiden Methoden gepflegt, damit `get_current_slope()`
> (für die Prozessanalyse) stets aktuelle Daten liefert.

### Seed-Mechanismus (Zyklusstart)

Beim Start eines neuen Zyklus wird `predictor.seed(ref_duration)` mit der
`reference_duration_seconds` des validen Profils aufgerufen (`_seed_predictor_from_profile`).
Der Seeded-Countdown (1 s/Tick) ist nur im BASIS/HETA_LERNEND-Modus aktiv – im
HETA_VALIDIERT-Modus übernimmt sofort `update_with_reference_curve()`:

```python
def seed(self, initial_seconds: float):
    if initial_seconds > 0:
        self._last_remaining  = float(initial_seconds)
        self._seeded_ceiling  = float(initial_seconds)
```

Während `_seeded_ceiling is not None` läuft die **Seeded-Phase**:
- Zählt 1 s/Tick herunter (kein Sprung nach oben)
- Sobald die echte Slope-Berechnung (ohne `min_slope`-Clamp) einen **niedrigeren**
  Wert liefert, übernimmt die normale Slope-Logik: `_seeded_ceiling = None`

```python
raw_true = (dp_limit - dp_bar) / slope  # kein min_slope-Clamp hier!
if raw_true < self._last_remaining:
    self._last_remaining = max(0.0, raw_true)
    self._seeded_ceiling = None
```

---

## Lernlogik

1. **Zyklus starten** – wenn `waiting_for_flow` → `cycle_active` wechselt (Dual-Kondition: Q > flow_thr AND dp > dp_clean×0.5, stabil für stability_secs, mit aktivem HETA-Code)
2. **Messwerte sammeln** – flow, temperature, dp, r_eff je Sekunde
3. **Zyklus beenden** – wenn Benutzer den Filterwechsel bestätigt (Dashboard oder Encoder)
4. **Profil berechnen** – Mittelwert aller bestätigten Zyklen
5. **Validierung** – Profil gilt nach ≥ 3 vollständigen, bestätigten Zyklen

`end_cycle()` akzeptiert den `active_seconds`-Parameter. Die Beladungsrate und Referenzdauer
basieren auf `active_seconds` (kumulierte Betriebszeit ohne Pausen), nicht auf dem
Wall-Clock-Wert `duration_seconds`. Dies sorgt dafür, dass die Prognose im Batch-Betrieb
korrekt auf Betriebsstunden basiert.

### Ereignisstruktur (events_json)

Jeder Zyklus speichert ein JSON-Array mit Ereignissen. Jedes Ereignis hat folgende Felder:

```json
{
  "ts":       1716300000,
  "ts_start": 1716300000,
  "ts_end":   1716300180,
  "severity": "WARNUNG",
  "category": "dp",
  "message":  "Erhöhte dp-Abweichung: +32 %"
}
```

| Feld | Beschreibung |
|------|-------------|
| `ts` | Zeitstempel des Ereignisses (Unix, Sekunden) |
| `ts_start` | Beginn des Problemzeitraums |
| `ts_end` | Ende des Problemzeitraums (null = noch offen) |
| `severity` | `INFO`, `WARNUNG`, `FEHLER` |
| `category` | `dp`, `flow`, `reff`, `status`, `pause` oder leer |
| `message` | Lesbare Beschreibung |

### Event-Methoden (learning.py)

```python
add_event(severity, message, category="")
# Fügt ein neues offenes Ereignis (ts_end=None) zum aktiven Zyklus hinzu.

close_event(category="", severity="", ts_end=None)
# Schließt das letzte offene Ereignis, das category/severity passt (ts_end setzen).

close_all_events(ts_end=None)
# Schließt alle noch offenen Ereignisse (ts_end=None) des aktiven Zyklus.
# Wird in end_cycle() automatisch aufgerufen.
```

### Abweichungs-Tracking (app.py)

Im Messzyklus-Thread wird nach jeder Kurvenanalyse geprüft, ob dp, flow oder r_eff
signifikant vom Referenzprofil abweichen. Abweichungen werden als persistente,
zeitgespannte Ereignisse gespeichert:

```python
_state["_dev_active"] = {"dp": False, "flow": False, "reff": False}
```

- **Abweichung neu**: `_dev_active[ch]` wird `True`, `add_event("WARNUNG", ..., category=ch)`
- **Abweichung endet**: `_dev_active[ch]` wird `False`, `close_event(category=ch)`

Im Frontend werden diese Zeitbereiche als **farbige Boxannotationen** im Zyklus-Diagramm
dargestellt (Chart.js annotation plugin). Ereignisse mit `ts_end` → Box (xMin/xMax),
Punkt-Ereignisse → vertikale Linie.

### Startverhalten-Prüfung

Nach jedem Filterwechsel wird r_eff der ersten 10 Sekunden mit dem Referenzprofil
verglichen. Abweichung > 25 % → Status `WARNUNG`.

`add_event("WARNUNG", ..., category="status")` öffnet ein Status-Ereignis.
`close_event(category="status")` schließt es, wenn r_eff wieder im Toleranzbereich liegt.

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

### Display-Methoden

```python
show_waiting_for_flow(q_val, q_thr, dp_val, dp_thr, stable_pct, stab_secs)
# Zeigt bernsteinfarbenes Warte-Overlay auf OLED (wenn vorhanden)

show_cycle_paused(active_seconds, pause_seconds)
# Zeigt blaues Pause-Overlay auf OLED (wenn vorhanden)
```

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

### Frontend (app.js / index.html)

- **Sensor-Fault-Overlay:** Blockierendes rotes Overlay, wenn `sensor_fault=True` im Status.
  Zeigt ausgefallene Kanäle, Prüf-Button und aufklappbaren Bereich zur Sim-Aktivierung.
- **Sim-Mode-Aktivierung aus dem Overlay:** Passwortgeschützt – Login erforderlich bevor
  `POST /api/settings` und `POST /api/simulation/start` aufgerufen werden.
- **Sim-Mode-Warnung in Einstellungen:** Sobald die Simulation-Checkbox aktiviert wird,
  erscheint eine gelbe Warnbox: „Im Simulationsmodus werden keine echten Sensordaten erfasst –
  nur für Tests."
- **Amber Overlay** (`flow-wait-overlay`): Erscheint wenn `d.waiting_for_flow === true`. Zeigt Q,
  Schwellwert und Stabilitäts-Fortschrittsbalken. Verschwindet automatisch bei Zyklusstart.
- **Blau Overlay** (`flow-pause-overlay`): Erscheint wenn `d.cycle_paused === true`. Zeigt aktive
  Messzeit und Pausendauer.

### System-Tab: Live-Chart (combinedChart)

Der kombinierte Chart zeigt **Änderungsraten** (nicht Absolutwerte) über
**Zyklusfortschritt [%]** auf der x-Achse.

**Live-Datasets (ds[0–6]) – Datenquelle je Kanal:**

| Index | Label | Einheit | Quelle in `/api/status` | y-Achse |
|-------|-------|---------|-------------------------|---------|
| 0 | p1 | bar | `p1_bar` | yPressure |
| 1 | p2 | bar | `p2_bar` | yPressure |
| 2 | Δp | mbar/s | `analysis_dp_rate_current × 1000` | yDpRate |
| 3 | Q | l/min/min | `analysis_flow_rate_current × 60` | yFlow |
| 4 | T | °C/min | `analysis_temp_rate_current × 60` | yTemp |
| 5 | R_eff | µ(b·min/l)/s | `analysis_reff_rate_current × 1e6` | yReff |
| 6 | Reststandzeit | min | `remaining_seconds / 60` | yTime |

x-Wert: `analysis_cycle_progress_pct` (0–100 %). Bei Zyklus-Reset (`cycle_start_time` ändert
sich) werden ds[0–6] automatisch geleert (`_knownLiveCycleStart`-Tracking).

**Referenzoverlay (ds[7–18]) – numerische Ableitung der Referenzkurve:**

Je konsekutives Kurvenpaar `(p0, p1)` mit `dt_s = (p1.t_pct − p0.t_pct) / 100 × ref_duration`:

```
dpRate   [mbar/s]       = (p1.dp   − p0.dp)   / dt_s × 1000
flowRate [l/min/min]    = (p1.flow − p0.flow) / dt_s × 60
tempRate [°C/min]       = (p1.temp − p0.temp) / dt_s × 60
reffRate [µ(b·min/l)/s] = (p1.r_eff − p0.r_eff) / dt_s × 1e6
```

x-Wert: `(p0.t_pct + p1.t_pct) / 2`. Toleranzbänder: `±tolXxx` relativ zur Referenzrate.

**Prozessanalyse-Aufruf-Reihenfolge (app.py Messzyklus):**

1. `predictor.update_channels(flow, temp, r_eff)` — aktualisiert Historien
2. `predictor.update_with_reference_curve()` oder `predictor.update()` — aktualisiert `_dp_history` und berechnet Restzeit
3. `predictor.get_current_slope()` + `predictor.get_channel_slopes()` — lesen frische Werte
4. `learning.get_curve_analysis(...)` — verwendet die frischen Steigungen

Diese Reihenfolge stellt sicher, dass `cur_dp_slope` in der Prozessanalyse immer den
aktuellen Messwert enthält (nicht den des vorherigen Ticks).

### Tab: Zyklen & Profil

Zeigt Lernfortschritt und alle Zyklen eines aktiven HETA-Codes.

**Profil-Kacheln** (`profile-tiles-row`):
- **Lernzyklen**: `min(learned_cycles, required_cycles)` / `required_cycles` – max. 3 von 3; grüner „Validiert"-Badge nach Validierung
- **Messzyklen**: `max(0, cycles.length - required_cycles)` – Zyklen nach Abschluss der Lernphase

**Zyklustabelle** (6 Spalten): #, Start, Ende, Dauer, Status, „Diagramm & Probleme (N)"

**Zyklus-Detaildiagramm** (`modal-cycle`):
- 4 Kanäle (dp, Q, T, r_eff) mit je 4 Datasets: tol_up, tol_lo, ref (gestrichelt), measured
- Multi-Achsen: yDp, yFlow, yTemp, yReff (je separate y-Achse)
- Kanal-Toggle-Chips: dp/Q standardmäßig aktiv, T/r_eff deaktiviert
- Annotationen: Box für Ereignisse mit `ts_end` (xMin/xMax in % der Zyklusdauer),
  Linie für Punktereignisse; Farbe nach Severity (`_sevColors(sev)`)
- Ereignisliste: Zeitraum mit Δt, z. B. „08:12:05 – 08:15:30 (3 min 25 s)"

### _do_confirm_filter_change()

Zentrale Funktion, die sowohl vom REST-API-Endpunkt als auch vom
`_DisplayController` aufgerufen wird:

0. `_update_auto_thresholds()` aus den aktuellen Zyklusproben aufrufen
1. Aktiven Lernzyklus mit `learning.end_cycle(confirmed=True, active_seconds=_state["cycle_active_seconds"])` abschließen
2. `predictor.reset()` und `reset_simulation()` aufrufen
3. `_state["awaiting_confirmation"] = False`, Zyklusdaten zurücksetzen
4. Ereignis `FILTERWECHSEL_BESTAETIGT` in Datenbank protokollieren
5. Flow-Detection-State zurücksetzen: `waiting_for_flow=True`, `cycle_paused=False`, `cycle_active_seconds=0.0`, `cycle_pause_start_time=None`
6. Modul-Variablen zurücksetzen: `_flow_stable_since=None`, `_flow_below_since=None`

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
| POST | `/api/simulation/start` | Simulation starten (löscht auch `sensor_fault`-State) |
| POST | `/api/simulation/stop` | Messzyklus stoppen |
| POST | `/api/sensor/recheck` | Alle 4 SPI-Kanäle nach Bediener-Bestätigung prüfen – Messung neu starten wenn alle OK |
| POST | `/api/simulation/reset` | System zurücksetzen |
| GET | `/api/export/csv` | CSV-Export-Info |
| GET | `/api/export/csv/download` | CSV-Download |
| POST | `/api/service/request` | Servicebericht erzeugen |
| GET | `/help` | Benutzerhandbuch als HTML (in-app Dokumentation, kein Auth erforderlich) |

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

### Software-Update

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| POST | `/api/update/pull` | `git pull --ff-only` ausführen und bei Änderung neu starten |

Erfordert `X-Auth-Token` Header.

`POST /api/update/pull` Antwort:
```json
{
  "success": true,
  "changed": true,
  "restarting": true,
  "output": "From github.com:aracon30/...\nUpdating abc1234..def5678\nFast-forward\n ..."
}
```

Bei `"restarting": true` startet der systemd-Service `heta-monitor` automatisch neu
(Fallback: `os.execv()`). Das Dashboard lädt die Seite nach ~8 Sekunden selbst neu.

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
| `anomaly_active` | bool | Startverhalten-Anomalie erkannt (r_eff > Toleranz) |
| `anomaly_percent` | float | Abweichung r_eff vom Referenzprofil in % |
| `dev_active` | dict | Aktive Abweichungen: `{"dp": bool, "flow": bool, "reff": bool}` |
| `sensor_fault` | bool | Mindestens ein Sensor nicht erreichbar (Messung gestoppt) |
| `sensor_fault_channels` | list | Kanal-Nummern ausgefallener Sensoren |
| `sensor_fault_message` | string | Lesbare Fehlerbeschreibung |
| `waiting_for_flow` | bool | System wartet auf stabilen Durchfluss |
| `cycle_paused` | bool | Zyklus pausiert durch Durchflussausfall |
| `cycle_active_seconds` | float | Kumulierte Betriebszeit (ohne Pausen) |
| `cycle_pause_start_time` | float / null | Unix-Zeitstempel des Pausenbeginns |
| `flow_check_q` | float | Aktueller Q-Wert (für Overlay-Anzeige) |
| `flow_check_dp` | float | Aktueller dp-Wert (für Overlay-Anzeige) |
| `flow_threshold` | float | Effektiver Schwellwert (auto oder manuell) |
| `flow_stable_pct` | int | Stabilitätsfenster-Fortschritt 0–100 % |

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
| Hardware | Echte 4–20 mA Werte vom AnoPi Shield (Voreinstellung) |
| Simulation | Simulierte Sensordaten, explizit konfiguriert (Onboarding oder Einstellungen) – nur für Tests |

Kein automatischer Simulations-Fallback. Wird im Hardwaremodus ein Sensor nicht erreicht, setzt
`read_sensors()` den State `sensor_fault=True` und gibt `mode="sensor_fault"` zurück – die Messung
stoppt sofort.

Umschaltung über Onboarding, Einstellungsbereich (⚙) oder `POST /api/settings`.

---

## Sensor-Fault-Handling

### Flow bei Sensorausfall (Hardwaremodus)

```
read_sensors() → Kanal nicht lesbar
    → gibt mode="sensor_fault" zurück
    → app.py: _state["sensor_fault"] = True
              _state["sensor_fault_channels"] = [<Kanal-Nr>, ...]
              _state["sensor_fault_message"] = "<Beschreibung>"
    → Messzyklus stoppt sofort
    → /api/status liefert sensor_fault=True an das Frontend
```

### Frontend: Sensor-Fault-Overlay

- Blockierendes rotes Overlay überlagert das Dashboard
- Zeigt ausgefallene Kanäle mit Namen (aus `_CHANNEL_NAMES`)
- Primär-Button: „Alle Sensoren angeschlossen – System prüfen"
  → `POST /api/sensor/recheck`
  → Alle OK: `sensor_fault=False`, Messung startet neu, Overlay verschwindet
  → Noch Fehler: Overlay bleibt, zeigt aktualisierte Kanalliste
- Sekundär (aufklappbar): „Im Simulationsmodus fortfahren"
  → Passwort-Eingabe → Login (`POST /api/settings/login`)
  → `POST /api/settings` (simulation_mode=true)
  → `POST /api/simulation/start` (löscht sensor_fault-State)

### Sensor-Badge

| Zustand | Badge | Farbe |
|---------|-------|-------|
| Hardwaremodus, alle Sensoren OK | `REAL` | blau |
| Simulationsmodus | `SIM` | grau |
| Sensor-Fault aktiv | `FEHLER` | dunkelrot |

---

## Konfigurationsparameter (`config/settings.json`)

**Allgemein**

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `onboarding_complete` | `false` | Ersteinrichtung abgeschlossen |
| `settings_password_hash` | `""` | SHA-256-Hash des Einstellungspassworts |
| `session_timeout_minutes` | `30` | Timeout der Einstellungs-Session |
| `simulation_mode` | `true` | Simulationsmodus aktiv |
| `sampling_interval_seconds` | `1` | Messintervall in Sekunden |
| `log_level` | `"INFO"` | Log-Level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `webserver_port` | `8080` | HTTP-Port der Weboberfläche |
| `webserver_host` | `"0.0.0.0"` | Bind-Adresse des Webservers |
| `db_path` | `"data/heta_monitor.db"` | Datenbankpfad |
| `log_path` | `"logs/"` | Log-Verzeichnis |
| `export_path` | `"exports/"` | CSV-Export-Verzeichnis |

**Filterparameter**

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `dp_limit_bar` | `2.5` | Differenzdruck-Grenzwert für Filterwechsel ⚠ |
| `dp_clean_bar` | `0.2` | Differenzdruck eines sauberen Filters ⚠ |
| `pressure_range_bar` | `10` | Messbereich Drucksensoren (20 mA-Endwert) ⚠ |
| `temperature_min_c` | `-50` | Messbereich Temperatursensor Minimum |
| `temperature_max_c` | `150` | Messbereich Temperatursensor Maximum |
| `flow_max_l_min` | `150` | Maximaler Durchfluss (20 mA-Endwert) ⚠ |

**Durchflusserkennung & Betriebsweise**

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `operation_mode` | `"continuous"` | Betriebsweise: `continuous` oder `batch` |
| `flow_start_threshold_l_min` | `null` | Manueller Schwellwert (null = auto) |
| `flow_stability_seconds` | `null` | Stabilitätsfenster (null = auto = 10 s) |
| `flow_pause_tolerance_seconds` | `null` | Pausentoleranz (null = auto: 30/60 s) |
| `flow_max_pause_days` | `7` | Max. Pause bis Zyklusabbruch |
| `flow_start_threshold_auto` | `0.0` | Intern: auto-berechneter Schwellwert |
| `flow_stability_seconds_auto` | `10` | Intern: auto-berechnetes Stabilitätsfenster |
| `flow_pause_tolerance_auto` | `30` | Intern: auto-berechnete Pausentoleranz |

**Lern- und Prognosealgorithmus**

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `required_cycles_for_profile` | `3` | Anzahl Zyklen für valides Profil |
| `clean_resistance_tolerance` | `0.25` | Toleranz Startverhalten-Prüfung (25 %) |
| `anomaly_threshold_percent` | `25` | Anomalie-Schwelle für WARNUNG-Status (%) |
| `smoothing_factor` | `0.15` | Glättungsfaktor Reststandzeit |
| `max_increase_percent_per_update` | `2` | Max. Anstieg Reststandzeit pro Update (%) |
| `max_decrease_percent_per_update` | `8` | Max. Abfall Reststandzeit pro Update (%) |
| `min_slope` | `0.001` | Minimale Beladungsrate (verhindert Division durch 0) |

**MQTT** (optional)

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `mqtt_enabled` | `false` | MQTT-Client aktivieren |
| `mqtt_broker` | `"localhost"` | Hostname oder IP des MQTT-Brokers |
| `mqtt_port` | `1883` | Port des MQTT-Brokers |
| `mqtt_client_id` | `"heta_monitor"` | MQTT Client-ID |

**Modbus TCP** (optional)

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `modbus_enabled` | `false` | Modbus-TCP-Server aktivieren |
| `modbus_host` | `"0.0.0.0"` | Bind-Adresse (alle Interfaces) |
| `modbus_port` | `502` | TCP-Port (Standard Modbus; < 1024 → Root / authbind) |

Registermap (Holding Registers, Function Code 3, Slave-ID 1):

| Adresse | Inhalt | Skalierung | Wertebereich |
|---------|--------|-----------|-------------|
| 0 | p1_bar | ×1000 | mbar |
| 1 | p2_bar | ×1000 | mbar |
| 2 | dp_bar | ×10000 | 0,1 mbar |
| 3 | flow_l_min | ×10 | 0,1 l/min |
| 4 | temperature_c | ×10 + 500 | 0,1 °C (Offset für neg. Werte) |
| 5 | r_eff | ×1000 | µ(bar·min/l) |
| 6 | filter_health_percent | ×10 | 0,1 % |
| 7 | remaining_seconds | ×1 | s (0xFFFF = unbekannt) |
| 8 | alarm_flag | – | 0=OK / 1=WECHSEL / 2=FEHLER |
| 9 | cycle_count | ×1 | – |
| 10 | status_code | – | 0=INIT / 1=LAUFEND / 2=WECHSEL / 3=FEHLER |

Der Server wird als Daemon-Thread gestartet und aktualisiert die Register nach jedem Messzyklus.
Implementierung: `backend/modbus_server.py`, Bibliothek: `pymodbus >= 3.6`.

**OLED-Display** (Waveshare 2.42" SSD1309)

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `display_enabled` | `true` | Display-Initialisierung aktivieren |
| `display_use_spi` | `true` | `true` = SPI, `false` = I2C |
| `display_spi_port` | `0` | SPI-Bus-Nummer |
| `display_spi_device` | `0` | SPI CE-Nummer (CE0 = 0) |
| `display_gpio_dc` | `25` | GPIO-Nummer Data/Command-Pin |
| `display_gpio_rst` | `27` | GPIO-Nummer Reset-Pin |
| `display_i2c_address` | `60` | I2C-Adresse in Dezimal (0x3C = 60, 0x3D = 61) |

**ANO-Rotary-Encoder** (direktes GPIO, kein I2C/Seesaw)

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `navigation_enabled` | `true` | Encoder-Initialisierung aktivieren |
| `encoder_pin_enca` | `16` | GPIO-Pin Drehgeber Signal A |
| `encoder_pin_encb` | `20` | GPIO-Pin Drehgeber Signal B |
| `encoder_pin_sw1`  | `21` | GPIO-Pin Mitteltaste (OK) |
| `encoder_pin_sw2`  | `12` | GPIO-Pin Taste Unten |
| `encoder_pin_sw3`  | `13` | GPIO-Pin Taste Rechts |
| `encoder_pin_sw4`  | `19` | GPIO-Pin Taste Oben |
| `encoder_pin_sw5`  | `26` | GPIO-Pin Taste Links |

⚠ = Lernrelevanter Parameter: Änderung löscht alle Zyklen und Profile.
