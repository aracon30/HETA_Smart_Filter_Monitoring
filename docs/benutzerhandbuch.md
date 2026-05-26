# Bedienungsanleitung – HETA Smart Filter Monitoring

Diese Anleitung richtet sich an Anwender, die das System über den Browser bedienen.
Sie benötigen keine Programmierkenntnisse.

---

## Inhaltsverzeichnis

1. [System starten und aufrufen](#1-system-starten-und-aufrufen)
2. [Ersteinrichtung (Onboarding)](#2-ersteinrichtung-onboarding)
3. [Betriebsweise und Durchflusserkennung](#3-betriebsweise-und-durchflusserkennung)
4. [Das Dashboard](#4-das-dashboard)
5. [Zyklen & Profil](#5-zyklen--profil)
6. [HETA-Code aktivieren](#6-heta-code-aktivieren)
7. [Filterwechsel bestätigen](#7-filterwechsel-bestätigen)
8. [Einstellungen ändern](#8-einstellungen-ändern)
9. [Simulationsmodus](#9-simulationsmodus)
10. [OLED-Display und Encoder](#10-oled-display-und-encoder)
11. [Systemmeldungen im Detail](#11-systemmeldungen-im-detail)
12. [Fehlermeldungen](#12-fehlermeldungen)
13. [Häufige Fragen](#13-häufige-fragen)

---

## 1. System starten und aufrufen

Das HETA-Monitoringsystem läuft auf einem Raspberry Pi, der direkt an die Anlage
angeschlossen ist. Sie benötigen kein Internet – der Pi stellt seine eigene
Webseite im lokalen Netzwerk bereit.

### Weboberfläche öffnen

1. Stellen Sie sicher, dass Ihr Computer oder Tablet im **gleichen Netzwerk**
   wie der Raspberry Pi ist.
2. Öffnen Sie einen Webbrowser (Chrome, Firefox, Edge, Safari).
3. Geben Sie in die Adresszeile ein:

   ```
   http://<IP-Adresse>:8080
   ```

   Die IP-Adresse des Pi finden Sie:
   - Auf dem **OLED-Display** am Gerät (Bildschirm 6 – Netzwerk)
   - Oder fragen Sie Ihren Administrator

   Beispiel: `http://192.168.1.42:8080`

> **Kein OLED-Display vorhanden?** Verbinden Sie eine Tastatur und ein Monitor
> direkt am Pi und geben Sie `hostname -I` ein.

Das **`?`-Symbol** im oberen rechten Bereich des Dashboards öffnet dieses Benutzerhandbuch
direkt im Browser – ohne separaten Download oder Dateiöffnung.

---

## 2. Ersteinrichtung (Onboarding)

Beim allerersten Start des Systems erscheint automatisch der **Einrichtungsassistent**.
Er führt Sie in 8 Schritten durch die Grundkonfiguration.

> **Wichtig:** Während der Ersteinrichtung ist die Messung gesperrt. Die Simulation startet
> erst, nachdem Sie den Assistenten vollständig abgeschlossen haben.

### Schritt 1 – Willkommen

Lesen Sie die Übersicht und klicken Sie auf **„Weiter"**.

### Schritt 2 – HETA-Code und PIN (optional)

Wenn Sie bereits einen HETA-Code besitzen, können Sie ihn hier eingeben:

1. Tragen Sie **nur die Zahlenkombination** Ihres Codes ein – **ohne** das Präfix „HETA-".
   Beispiel: Ihr Code lautet `HETA-12345` → Sie tippen `12345`.
2. Geben Sie den zugehörigen **6-stelligen PIN** ein.
3. Klicken Sie auf **„Aktivieren"**.

Das System prüft die Kombination sofort. Bei Erfolg erscheint eine Bestätigung und der
Lernprozess beginnt mit dem ersten vollständigen Filterzyklus.

> Sie können diesen Schritt auch **überspringen** und den HETA-Code später im Dashboard aktivieren.

### Schritt 3 – Betriebsart

Wählen Sie, wie das System Messwerte erfasst:

| Option | Wann wählen |
|--------|-------------|
| **Hardware (Realbetrieb)** | Echte Drucksensoren, Temperatursensor und Durchflussmesser sind angeschlossen |
| **Simulation** | Für Vorführungen und Tests ohne reale Sensorhardware |

> Wenn Sie unsicher sind, wählen Sie **Hardware**. Der Simulationsmodus kann
> jederzeit nachträglich in den Einstellungen aktiviert werden.

### Schritt 4 – Betriebsweise

Wählen Sie, wie Ihre Anlage betrieben wird:

| Option | Wann wählen |
|--------|-------------|
| **Dauerbetrieb (kontinuierlich)** | Die Pumpe läuft nahezu ununterbrochen |
| **Intervallbetrieb (Batch)** | Die Pumpe schaltet regelmäßig ab und an (z. B. täglich mehrfach) |

#### Dauerbetrieb (kontinuierlich)

Das System läuft ununterbrochen. Bei kurzen Unterbrechungen (Pumpe kurz aus) wird
der Zyklus für bis zu **30 Sekunden** pausiert und dann automatisch fortgesetzt.
Bleibt die Pumpe länger als 30 Sekunden aus, wird der Zyklus abgebrochen und das
System kehrt in den Wartezustand zurück.

#### Intervallbetrieb (Batch)

Der Filter läuft in regelmäßigen Zyklen – die Pumpe geht täglich mehrfach an und aus.
Pausen bis zu **60 Sekunden** werden toleriert. Die Reststandzeit basiert auf der
**kumulierten Betriebszeit** (nicht der Wanduhrzeit), sodass Stillstandzeiten die
Prognose nicht verfälschen.

> **Hinweis:** Die Betriebsweise beeinflusst, wie Pausen behandelt werden.
> Bei Unsicherheit wählen Sie **Dauerbetrieb**.

### Schritt 5 – Filterparameter

Tragen Sie die Kenndaten Ihres Filterkreislaufs ein:

| Feld | Bedeutung | Typischer Wert |
|------|-----------|---------------|
| **Differenzdruck-Grenzwert** | dp-Wert, bei dem der Filter gewechselt werden muss | 2,5 bar |
| **Druckabfall sauberer Filter** | dp-Wert eines fabrikneuen Filters | 0,2 bar |
| **Maximaler Durchfluss** | Endwert des Durchflusssensors (= 20 mA) | 150 l/min |
| **Drucksensor-Messbereich** | Endwert der Drucksensoren (= 20 mA) | 10 bar |

> Diese Werte stehen im Datenblatt Ihres Filters und Ihrer Sensoren.

### Schritt 6 – Temperatursensorbereich

Tragen Sie den Messbereich Ihres Temperatursensors ein (Minimum und Maximum in °C).
Standardwert: −50 °C bis +150 °C.

### Schritt 7 – Passwort festlegen

Legen Sie ein Passwort für den geschützten Einstellungsbereich fest.
Das Passwort muss **mindestens 4 Zeichen** lang sein.

> Notieren Sie das Passwort. Falls Sie es vergessen, muss ein Administrator
> es über die Konsole zurücksetzen.

### Schritt 8 – Zusammenfassung

Prüfen Sie alle Angaben – einschließlich der gewählten Betriebsweise.
Klicken Sie auf **„Einrichtung abschließen"** – das System startet die Messung.

---

## 3. Betriebsweise und Durchflusserkennung

### Automatischer Zyklusstart

Das System startet einen Messzyklus **nicht** sofort nach dem Einschalten oder nach
einem Filterwechsel. Es wartet, bis folgende Bedingungen gleichzeitig erfüllt sind:

1. Durchfluss Q liegt über dem Schwellwert (automatisch berechnet, typisch 10–40 % des maximalen Durchflusses)
2. Differenzdruck dp liegt über 50 % des Druckabfalls bei sauberem Filter (Zeichen: Fluss läuft durch den Filter)
3. Beide Bedingungen sind **stabil** für mindestens 10 Sekunden (Standard)

Während des Wartens erscheint ein **bernsteinfarbenes Overlay** im Dashboard mit:
- Aktuellem Durchfluss Q und dem Schwellwert
- Fortschrittsbalken der Stabilitätsprüfung
- Hinweis: System startet automatisch, sobald Durchfluss stabil erkannt wurde

### Zykluspause bei Durchflussausfall

Fällt der Durchfluss während eines laufenden Zyklus auf 0 (Pumpe aus), pausiert das
System den Zyklus und speichert einen Ereignis-Eintrag. Ein **blaues Overlay** erscheint
mit:
- Bisher aktiver Messzeit
- Pausendauer

Kehrt der Durchfluss zurück, wird der Zyklus **automatisch fortgesetzt**. Die Messzeit
(aktive Sekunden) wird nur während des Flusses gezählt.

### Maximale Pausendauer

Bleibt der Durchfluss länger als **7 Tage** aus, wird der Zyklus abgebrochen und als
`ZYKLUS_ABGEBROCHEN` in der Datenbank protokolliert. Das System wechselt zurück in
den Wartezustand.

### Schwellwerte (automatisch vs. manuell)

- **Automatisch** (Standard): Nach dem ersten Zyklus berechnet das System den Schwellwert
  aus den gesammelten Messdaten (min. Betriebsdurchfluss × 0,4). Kein Eingriff nötig.
- **Manuell** (Einstellungen → Betriebsweise & Durchflusserkennung): Fester Wert in l/min,
  der den automatisch berechneten Wert überschreibt.

---

## 4. Das Dashboard

Nach der Einrichtung sehen Sie das Haupt-Dashboard.

### Statusbereich (oben)

| Anzeige | Bedeutung |
|---------|-----------|
| **Filterstatus** | Aktueller Zustand: OK / Beobachten / Wechsel |
| **Reststandzeit** | Verbleibende Zeit bis zum Filterwechsel |
| **Beladungsgrad** | Prozentualer Verschmutzungsgrad (nur mit HETA-Code) |

#### Filterstatus-Farben

| Farbe | Status | Bedeutung |
|-------|--------|-----------|
| Grün | **OK** | Filter in Ordnung, kein Handlungsbedarf |
| Gelb | **Beobachten** | dp erreicht 75 % des Grenzwerts – Filter überwachen |
| Orange | **Warnung** | Messwerte weichen deutlich vom gelernten Muster ab |
| Rot | **Wechsel** | dp-Grenzwert erreicht – Filter sofort wechseln |
| Rot blinkend | **Wechsel bestätigen** | Filterwechsel wurde erkannt, Bestätigung erforderlich |

### Live-Messwerte

Direkt unter dem Statusbereich sehen Sie die aktuellen Messwerte:

- **p1** – Eintrittsdruck (bar)
- **p2** – Austrittsdruck (bar)
- **dp** – Differenzdruck = p1 − p2 (bar)
- **Q** – Durchfluss (l/min)
- **T** – Temperatur (°C)
- **r_eff** – Effektiver Filterwiderstand (bar·min/l)

### Live-Diagramm (System-Tab)

Das Diagramm auf dem **System-Tab** zeigt die **Änderungsraten** der Messkanäle
über den **Zyklusfortschritt (0–100 %)** auf der x-Achse – nicht die Absolutwerte
und nicht die Uhrzeit.

| Kanal | Einheit | Bedeutung |
|-------|---------|-----------|
| **Δp** | mbar/s | Beladungsgeschwindigkeit – wie schnell steigt der Differenzdruck? |
| **ΔQ** | l/min/min | Veränderungsrate des Durchflusses |
| **ΔT** | °C/min | Temperaturänderungsrate |
| **ΔR_eff** | µ(b·min/l)/s | Widerstandsänderungsrate |

Mit aktivem HETA-Code und validem Profil werden zusätzlich die gelernten
**Referenzraten** (gestrichelt) und **Toleranzbänder** eingeblendet. Da Live-Messung
und Referenz in denselben Einheiten dargestellt werden, sind Abweichungen vom
Normalverhalten direkt ablesbar – ohne Überlagerung der Kurven.

> **p1 und p2** sind über die Chip-Schaltflächen zuschaltbar und werden als
> Absolutdruck in bar angezeigt.

> **Zykluswechsel:** Die Kurven werden automatisch gelöscht und beginnen bei 0 %,
> sobald ein neuer Zyklus startet.

### Betriebsmodus-Badge

Oben rechts im Dashboard:

| Badge | Bedeutung |
|-------|-----------|
| `REAL` (blau) | Echte Sensordaten werden erfasst |
| `SIM` (grau) | Simulationsmodus aktiv |
| `FEHLER` (rot) | Sensor ausgefallen – Messung gestoppt |

#### Betriebszustand-Overlays

| Overlay | Farbe | Bedeutung |
|---------|-------|-----------|
| Warte auf stabilen Durchfluss | Bernstein (amber) | System bereit, wartet auf Durchfluss |
| Messzyklus pausiert | Blau | Zyklus läuft, Durchfluss kurz unterbrochen |

---

## 5. Zyklen & Profil

Der Tab **„Zyklen & Profil"** im Dashboard zeigt den vollständigen Lernfortschritt
und alle aufgezeichneten Filterzyklen. Er ist nur sichtbar, wenn ein HETA-Code aktiv ist.

### Profil-Kacheln

Oben im Tab befinden sich zwei Kacheln:

| Kachel | Bedeutung |
|--------|-----------|
| **Lernzyklen** | Anzahl der für das Profil benötigten Zyklen (max. 3 von 3). Nach 3 Zyklen erscheint der grüne „Validiert"-Badge. |
| **Messzyklen** | Anzahl aller weiteren Zyklen, die nach Abschluss der Lernphase aufgezeichnet wurden. |

### Zyklustabelle

Die Tabelle zeigt alle abgeschlossenen und den aktuell laufenden Zyklus:

| Spalte | Inhalt |
|--------|--------|
| **#** | Zyklus-Nummer |
| **Start** | Startzeit des Zyklus |
| **Ende** | Endezeit (oder „läuft" bei aktivem Zyklus) |
| **Dauer** | Kumulierte Betriebszeit (ohne Pausen) |
| **Status** | `Läuft`, `OK` oder `Abgeschlossen` |
| **Diagramm & Probleme** | Schaltfläche zum Öffnen des Zyklus-Detaildiagramms |

> Die Schaltfläche zeigt die Anzahl der erkannten Probleme an, z. B. „Diagramm & Probleme (2)".

### Zyklus-Detaildiagramm

Ein Klick auf **„Diagramm & Probleme"** öffnet ein modales Fenster mit:

- **Mehrkanaldiagramm**: Vier Kanäle wählbar (dp, Durchfluss Q, Temperatur T, r_eff)
- **Referenzkurven** (gestrichelt) und **Toleranzbänder** aus dem validen Profil
- **Problembereiche** als farbige Schattierungen: Der genaue Zeitraum eines Fehlers
  wird als vertikaler Bereich eingeblendet (z. B. rot für FEHLER, orange für WARNUNG)
- **Ereignisliste**: Jedes Ereignis wird mit seinem genauen Zeitraum angezeigt,
  z. B. „08:12:05 – 08:15:30 (3 min 25 s)"

#### Kanal-Toggles

Mit den Chip-Schaltflächen oberhalb des Diagramms können Sie einzelne Kanäle
ein- und ausblenden. Standardmäßig sind **dp** und **Q** aktiv.

---

## 6. HETA-Code aktivieren (im laufenden Betrieb)

Mit einem HETA-Code schaltet das System erweiterte Funktionen frei:

- **Beladungsgrad** in Prozent (wie voll ist der Filter?)
- **Lernprofil** – das System lernt das typische Verhalten Ihres Filterkreislaufs
- **Sekundengenaue Reststandzeit** – nach 3 abgeschlossenen Filterzyklen

### So aktivieren Sie einen HETA-Code

Sie können einen HETA-Code auf zwei Wegen eingeben:

**Während des Onboardings (Schritt 2):**
1. Tragen Sie **nur die Zahlenkombination** ein (z. B. `12345` für Code `HETA-12345`)
2. Geben Sie den zugehörigen 6-stelligen PIN ein
3. Klicken Sie auf **„Aktivieren"** oder **„Überspringen"** zum späteren Nachholen

**Im laufenden Betrieb (Dashboard):**
1. Klicken Sie im Dashboard auf das Eingabefeld **„HETA-Code"**
2. Geben Sie Ihren Code ein, z. B. `HETA-12345`
3. Geben Sie den zugehörigen **PIN** ein (6-stellig)
4. Klicken Sie auf **„Aktivieren"**

> Den PIN erhalten Sie von HETA oder über den HETA-PIN-Generator.
> Im Entwicklungsmodus / auf der Messe können Sie auf „Demo-PIN anzeigen" klicken.

### Prognosemodi – was die Anzeige bedeutet

Das System zeigt je nach Lernstand unterschiedlich präzise Zeitangaben:

| Anzeige | Bedeutung |
|---------|-----------|
| `2–4 Std.` | **Kein HETA-Code** aktiv – grobe Schätzung |
| `4–6 Std. (1/3)` | HETA aktiv, **Lernphase** – System sammelt Daten (1 von 3 Zyklen) |
| `1 Std. 52 min 30 s` | **Vollständig gelernt** – sekundengenaue Prognose |

Die Lernphase dauert **3 vollständige Filterzyklen** (von Filterwechsel bis zum nächsten
Filterwechsel). Danach berechnet das System die Reststandzeit anhand des gelernten
Referenzprofils – präzise und selbst-adaptierend bei Prozessänderungen.

---

## 7. Filterwechsel bestätigen

Wenn der Filter sein Limit erreicht hat, zeigt das System den Status **„Wechsel"** an.

### Ablauf

1. **Rotes Banner erscheint** im Dashboard: „Filterwechsel erforderlich"
2. Wechseln Sie den Filter physisch
3. Klicken Sie auf **„Filterwechsel bestätigen"**
4. Das System startet automatisch einen neuen Zyklus

> **Wichtig:** Bestätigen Sie den Wechsel erst **nach** dem tatsächlichen Einbau des
> neuen Filters. Die Bestätigung startet die Zeitmessung für den neuen Zyklus.

Nach der Bestätigung:
- Lernzyklus wird abgeschlossen und gespeichert
- Zykluszähler erhöht sich (Fortschritt zum validen Profil)
- Ab 3 Zyklen: sekundengenaue Reststandzeit aktiv

---

## 8. Einstellungen ändern

Klicken Sie auf das **Zahnrad-Symbol (⚙)** oben rechts im Dashboard.

### Anmeldung

Geben Sie das Passwort ein, das Sie bei der Ersteinrichtung festgelegt haben.
Die Sitzung bleibt 30 Minuten aktiv.

### Einstellungsbereiche

#### Filterparameter
Differenzdruck-Grenzwert, Druckabfall sauberer Filter, Durchfluss- und Druckbereich.

> **Achtung:** Änderungen an diesen Werten löschen alle bisherigen Lerndaten.
> Das System beginnt erneut mit der Lernphase (3 neue Zyklen erforderlich).

#### Temperatursensorbereich
Messbereich Ihres Temperatursensors in °C.

#### Betriebsmodus
Umschaltung zwischen Hardware (echte Sensoren) und Simulation.

#### Toleranzen
Prozentuale Abweichung, ab der eine Warnung ausgelöst wird (Standard: 25 %).

#### Betriebsweise & Durchflusserkennung

- **Betriebsweise**: Dauerbetrieb (kontinuierlich) oder Intervallbetrieb (Batch)
- **Durchflussschwellwert (Überschreibung)**: Fester Wert in l/min – leer lassen für automatische Berechnung
- **Stabilitätsfenster (Überschreibung)**: Sekunden stabilen Durchflusses vor Zyklusstart – leer lassen für auto (10 s)
- **Pausentoleranz (Überschreibung)**: Max. Pause in Sekunden – leer lassen für auto (30 s im Dauerbetrieb / 60 s im Intervallbetrieb)

> Änderungen dieser Werte erfordern **kein** Zurücksetzen der Lerndaten.

#### Systemparameter
Messintervall, Sitzungs-Timeout, Log-Level.

#### MQTT (optional)
Verbindung zu einem MQTT-Broker für die Anbindung an Cloud-Systeme, Node-RED oder Home Assistant.
Aktivierung: `mqtt_enabled = true` in `config/settings.local.json`.

#### Modbus TCP (optional)
Macht den Raspberry Pi zu einem **Modbus-TCP-Slave**, den jede SPS oder jedes SCADA-System
direkt auslesen kann – ohne Broker oder Middleware.

| Register | Wert | Einheit |
|----------|------|---------|
| 0 | Druck p1 | mbar (×1000) |
| 1 | Druck p2 | mbar (×1000) |
| 2 | Differenzdruck dp | 0,1 mbar (×10000) |
| 3 | Durchfluss | 0,1 l/min (×10) |
| 4 | Temperatur | 0,1 °C + Offset 500 |
| 5 | Widerstandsfaktor R_eff | ×1000 |
| 6 | Filtergesundheit | 0,1 % (×10) |
| 7 | Reststandzeit | Sekunden |
| 8 | Alarm-Flag | 0=OK / 1=Wechsel / 2=Fehler |
| 9 | Zyklenanzahl | – |
| 10 | Statuskode | 0=INIT / 1=Laufend / 2=Wechsel / 3=Fehler |

Aktivierung in `config/settings.local.json`:
```json
{
  "modbus_enabled": true,
  "modbus_host": "0.0.0.0",
  "modbus_port": 5020
}
```
> Port 502 (Modbus-Standard) benötigt Root-Rechte auf Linux.
> Für den Testbetrieb empfiehlt sich Port **5020** (kein Root nötig).

#### Software-Update
Klicken Sie auf **„Update von GitHub holen"**, um die neueste Version zu installieren.
Das System startet nach dem Update automatisch neu (ca. 10 Sekunden).

#### Passwort ändern
Altes Passwort eingeben, neues Passwort zweimal bestätigen.

---

## 9. Simulationsmodus

Der Simulationsmodus ermöglicht eine vollständige Vorführung des Systems **ohne
angeschlossene Sensoren** – ideal für Messen, Schulungen und Entwicklungstests.

> **Hinweis:** Im Simulationsmodus ist die Durchflusserkennung vollständig deaktiviert.
> Das bernsteinfarbene Overlay „Warte auf stabilen Durchfluss" erscheint **nicht**.
> Der Messzyklus startet sofort nach dem Klick auf „Simulation starten".

### Simulation starten

1. Einstellungen (⚙) → **Betriebsmodus** → „Simulation" aktivieren → Speichern
2. Im Dashboard erscheint das **„SIM"-Badge** (grau)
3. Im Simulationsbereich auf **„Simulation starten"** klicken

### Lernzyklen automatisch erstellen (Schnellstart)

Damit das System sofort mit einer validen Prognose demonstriert werden kann:

1. Simulation starten
2. Im Simulationsbereich auf **„3 Lernzyklen erstellen"** klicken
3. Das System simuliert 3 vollständige Filterzyklen im Zeitraffer
4. Die sekundengenaue Reststandzeit ist sofort verfügbar

### Simulationsszenarien

Wählen Sie ein Szenario, um verschiedene Betriebsbedingungen zu demonstrieren:

| Szenario | Beschreibung |
|----------|-------------|
| **Normal** | Typischer Filterbetrieb gemäß Referenzprofil |
| **Hohe Beladung** | 50 % schnellere Verschmutzung – Restzeit verkürzt sich |
| **Niedriger Eintrittsdruck** | p1 fällt um 5 % – zeigt Druckabfallreaktion |
| **Hoher Durchflussabfall** | Starker Durchflussabfall durch Filterverstopfung |
| **Steigende Temperatur** | Temperatur steigt pro Zyklus um 3 °C |
| **Atypisch** | Kombination mehrerer Abweichungen – zeigt Warnungsreaktion |

### Zyklusdauer einstellen

Mit dem Schieberegler **„Zyklusdauer"** stellen Sie ein, wie lange ein simulierter
Filterzyklus dauert – von 10 Sekunden (Schnellvorführung) bis zu 2 Stunden.

### Beladungsintensität einstellen

Der Schieberegler **„Beladungsintensität"** steuert, wie schnell der Filter verschmutzt.
Bei 100 % entspricht die Simulation dem gelernten Referenzprofil.

### Simulation zurücksetzen

Klicken Sie auf **„Zurücksetzen"**, um die Simulation von vorne zu beginnen.

---

## 10. OLED-Display und Encoder

Das OLED-Display am Gerät zeigt dieselben Messwerte wie das Browser-Dashboard –
ohne Computer oder Smartphone.

### Navigation

| Aktion | Funktion |
|--------|----------|
| **Drehen links / rechts** | Zwischen 6 Bildschirmen wechseln |
| **Taste Links** | Vorheriger Bildschirm |
| **Taste Rechts** | Nächster Bildschirm |
| **Drücken (OK)** | Filterwechsel einleiten (zweistufig) |

### Die 6 Bildschirme

| Nr. | Bildschirm | Inhalt |
|-----|------------|--------|
| 1 | **Status** | p1, p2, dp, Durchfluss, Temperatur, Reststandzeit, Filterstatus |
| 2 | **HETA-Code** | Aktiver Code, Lernfortschritt (1/3, 2/3, 3/3), Prognosemodus |
| 3 | **Filterwechsel** | dp-Wert, Grenzwert, Fortschrittsbalken, Bestätigungsdialog |
| 4 | **Service** | Aktueller Servicehinweis und Priorität |
| 5 | **Historie** | Die letzten 4 abgeschlossenen Filterzyklen mit Dauer und Datum |
| 6 | **Netzwerk** | IP-Adresse, Port und vollständige Browser-URL |

Kleine Punkte am unteren Rand zeigen, auf welchem Bildschirm Sie sich befinden.

### Filterwechsel über den Encoder bestätigen

1. System zeigt Status **„Wechsel"** → Display springt automatisch auf Bildschirm 3
2. **1× OK drücken** → Anzeige wechselt zu „SICHER? BESTÄTIGEN?"
3. **2× OK drücken** → Filterwechsel bestätigt, System startet neuen Zyklus
4. **Taste Links drücken** → Bestätigung abbrechen (falls versehentlich gedrückt)

---

## 11. Systemmeldungen im Detail

Das System gibt kontinuierlich Rückmeldung über den Zustand des Filters und der Anlage.
Dieser Abschnitt erklärt jede mögliche Meldung, welche Messwerte dazu geführt haben und
was Sie als Bediener konkret tun sollten.

---

### 11.1 Filterstatus-Meldungen

Der Filterstatus ist die zentrale Statusanzeige im Dashboard. Er fasst alle Messwerte
zu einer klaren Handlungsempfehlung zusammen.

---

#### Status: OK ✔

| Anzeige | Farbe |
|---------|-------|
| **OK** | Grün |

**Was das bedeutet:**
Der Filter arbeitet normal. Der Differenzdruck dp liegt bei weniger als 75 % des
eingestellten Grenzwerts (dp < 0,75 × dp_Grenzwert). Alle Sensoren liefern gültige Werte.

**Relevante Messwerte:**
- Differenzdruck dp (bar) – muss unterhalb des Beobachtungsschwellwerts liegen
- Eintrittsdruck p1 und Austrittsdruck p2 – beide plausibel

**Was Sie tun sollten:**
Kein Handlungsbedarf. Regelmäßige Überprüfung der Reststandzeit-Anzeige genügt.

**Servicehinweis im Dashboard:**
> „Filter in Ordnung. Filterzustand: XX %. Reststandzeit: …"

---

#### Status: BEOBACHTEN ⚠

| Anzeige | Farbe |
|---------|-------|
| **Beobachten** | Gelb |

**Was das bedeutet:**
Der Differenzdruck hat 75 % des Grenzwerts überschritten. Der Filter nähert sich dem
Wechselzeitpunkt. Es besteht noch kein unmittelbarer Handlungsbedarf, aber ein
Ersatzfilter sollte bereitgelegt werden.

**Relevante Messwerte:**
- dp ≥ 0,75 × dp_Grenzwert (Beispiel: Grenzwert 2,5 bar → Schwelle bei 1,875 bar)

**Was Sie tun sollten:**
1. Ersatzfilter bereitstellen
2. Reststandzeit-Anzeige im Auge behalten
3. Filterwechsel planen (nicht sofort notwendig)

**Servicehinweis im Dashboard:**
> „Filter nähert sich dem Grenzwert. Filterzustand: XX %. Reststandzeit: … Ersatzfilter bereitstellen."

---

#### Status: WARNUNG ⚡

| Anzeige | Farbe |
|---------|-------|
| **Warnung** | Orange |

**Was das bedeutet:**
Das Beladungsverhalten des Filters weicht deutlich vom gelernten Referenzprofil ab.
Der effektive Filterwiderstand r_eff zu Beginn des Zyklus ist mehr als 25 % höher als
der Referenzwert aus den Lernzyklen. Dies kann auf einen falschen Filtertyp, eine
veränderte Prozesssituation oder einen mechanischen Defekt hinweisen.

**Relevante Messwerte:**
- r_eff (bar·min/l) – effektiver Filterwiderstand beim Zyklusstart
- Referenzwert r_eff_Referenz aus dem gelernten Profil
- Abweichung in % (Standardschwelle: 25 %, einstellbar unter Einstellungen → Toleranzen)
- dp, p1, p2, Durchfluss Q

**Was Sie tun sollten:**
1. Filter prüfen: Ist der richtige Filtertyp eingebaut?
2. Anlage prüfen: Hat sich die Prozesssituation geändert (Druck, Durchfluss, Medium)?
3. Vergleich mit dem Live-Diagramm: Weicht die dp-Kurve deutlich von der gestrichelten Referenzkurve ab?
4. Falls der neue Betriebszustand dauerhaft ist: Lerndaten zurücksetzen (Einstellungen → Lerndaten zurücksetzen), damit das System ein neues Referenzprofil aufbaut

> **Hinweis:** Die Messung läuft bei WARNUNG normal weiter. Das System passt die
> Prognose automatisch an die aktuellen Messwerte an.

**Servicehinweis im Dashboard:**
> „Abweichendes Beladungsverhalten erkannt. Anlage und Filter prüfen."

---

#### Status: WECHSEL 🔴

| Anzeige | Farbe |
|---------|-------|
| **Wechsel** | Rot |

**Was das bedeutet:**
Der Differenzdruck hat den eingestellten Grenzwert erreicht oder überschritten
(dp ≥ dp_Grenzwert). Der Filter ist vollständig beladen und muss sofort gewechselt werden.

**Relevante Messwerte:**
- dp ≥ dp_Grenzwert (konfiguriert unter Einstellungen → Differenzdruck-Grenzwert)
- Beladungsgrad: 100 % (oder nahe daran)
- Reststandzeit: 0 s (oder „< 1 s")

**Was Sie tun sollten:**
1. Filter sofort wechseln
2. Nach dem Einbau des neuen Filters: **„Filterwechsel bestätigen"** im Dashboard klicken
3. Bestätigung startet den neuen Zyklus und die Lernphase für den nächsten Wechselzeitpunkt

**Servicehinweis im Dashboard:**
> „Filterwechsel erforderlich! Grenzwert überschritten. Filter sofort tauschen und Wechsel bestätigen."

---

#### Status: WECHSEL BESTÄTIGEN 🔴 (blinkend)

| Anzeige | Farbe |
|---------|-------|
| **Wechsel bestätigen** | Rot blinkend |

**Was das bedeutet:**
Das System hat automatisch erkannt, dass der Grenzwert überschritten wurde und wartet
auf die Bestätigung des tatsächlich durchgeführten Filterwechsels. Die Messung ist
vorübergehend pausiert.

**Was Sie tun sollten:**
1. Filter physisch wechseln (falls noch nicht geschehen)
2. Im Dashboard auf **„Filterwechsel bestätigen"** klicken
3. Alternativ: Am OLED-Display auf Bildschirm 3 navigieren und zweimal OK drücken

> **Wichtig:** Bestätigen Sie erst **nach** dem tatsächlichen Einbau des neuen Filters.
> Die Bestätigung startet sofort die Zeitmessung für den neuen Zyklus.

---

#### Status: FEHLER ⛔

| Anzeige | Farbe |
|---------|-------|
| **Fehler** | Dunkelrot |

**Was das bedeutet:**
Mindestens einer der vier Sensoren liefert kein gültiges Signal. Die Messung wurde
automatisch gestoppt. Im Browser erscheint ein **rotes blockierendes Overlay**, das
die betroffenen Kanäle benennt.

Mögliche Ursachen je nach betroffenem Kanal:

| Signal | < 3,6 mA | 3,6–4,0 mA | > 20,5 mA |
|--------|----------|------------|-----------|
| **Bedeutung** | Kabelbruch | Unterbereich | Überbereich / Kurzschluss |

**Was Sie tun sollten:**
→ Siehe [Abschnitt 12 – Fehlermeldungen: Sensor ausgefallen](#rotes-overlay-sensor-ausgefallen)

---

### 11.2 Prognosemeldungen

Die Reststandzeit-Anzeige zeigt je nach verfügbarem Wissensstand unterschiedliche
Meldungen. Alle Angaben beziehen sich auf den aktuellen Messwert und das gelernte
Referenzprofil.

---

#### „Wird berechnet …"

**Wann:** In den ersten Sekunden nach einem Filterwechsel oder Systemstart,
bevor mindestens 5 Messwerte vorliegen.

**Relevant:** dp-Verlauf der letzten Sekunden, Beladungsrate (bar/s)

**Was tun:** Abwarten – die Anzeige aktualisiert sich automatisch nach wenigen Sekunden.

---

#### Bereichsanzeige: z. B. „2–4 Std." oder „1–2 Tage"

**Wann:** Kein HETA-Code aktiv (Modus BASIS) oder HETA-Code aktiv aber Lernphase noch
nicht abgeschlossen (Modus HETA-Lernend).

**Bedeutung:** Grobe Schätzung auf Basis der gemessenen Beladungsrate. Da
Filterlaufzeiten je nach Anwendung von Minuten bis Tagen variieren können, werden
absichtlich breite Zeitbereiche angegeben – keine Minutenangaben.

**Relevant:** dp-Anstieg pro Sekunde (Beladungsrate), dp-Grenzwert

| Anzeigestufe | dp-Bereich bis Grenzwert |
|-------------|--------------------------|
| > 5 Tage | Sehr geringe Beladungsrate |
| 3–5 Tage | Geringe Beladungsrate |
| 1–2 Tage | Moderate Beladungsrate |
| 6–12 Std. | Erhöhte Beladungsrate |
| 1–2 Std. | Hohe Beladungsrate |
| < 1 Std. | Sehr hohe Beladungsrate oder dp nahe am Grenzwert |

**Was tun:** HETA-Code aktivieren und 3 Filterzyklen abschließen, um die sekundengenaue Prognose zu erhalten.

---

#### Sekundengenaue Anzeige: z. B. „1 Std. 52 min 30 s"

**Wann:** HETA-Code aktiv und mindestens 3 vollständige Lernzyklen abgeschlossen
(Modus HETA-Validiert).

**Bedeutung:** Das System kennt die typische dp-Kurve Ihres Filterkreislaufs aus
den Lernzyklen. Durch Invertierung dieser Referenzkurve rechnet es den aktuellen
dp-Wert direkt in verbleibende Zeit um. Die Anzeige läuft als gerade Linie –
auch wenn dp nicht linear steigt.

**Relevant:**
- Aktueller dp-Wert
- Referenzkurve aus den 3 Lernzyklen (dp-Verlauf über die Zeit)
- Referenz-Zyklusdauer (Durchschnitt der 3 Lernzyklen)

**Passt sich automatisch an, wenn:**
- Die Beladung schneller als üblich verläuft → Restzeit wird kürzer
- Die Beladung langsamer als üblich verläuft (z. B. reduzierte Schmutzfracht) →
  die Kurveninvertierung erkennt den niedrigen dp-Fortschritt und verlängert die
  Restzeit automatisch – ohne Eingriff

**Was tun:** Keine Aktion erforderlich. Bei dauerhaft verändertem Betrieb (anderer Filtertyp,
veränderter Prozess): Lerndaten zurücksetzen, damit das System neu lernt.

---

### 11.3 Lernphasen-Meldungen

---

#### „Lernphase – X von 3 Zyklen"

**Wann:** HETA-Code aktiv, aber noch nicht alle erforderlichen Lernzyklen abgeschlossen.

**Was das bedeutet:** Das System sammelt Daten. Jeder bestätigte Filterwechsel schließt
einen Lernzyklus ab. Nach 3 Zyklen wird das Referenzprofil berechnet und die sekundengenaue
Prognose aktiviert.

**Relevant:** Anzahl bestätigter Zyklen (angezeigt im Dashboard und auf OLED-Bildschirm 2)

**Was tun:** Filterwechsel wie gewohnt durchführen und im Dashboard immer bestätigen.
Nicht bestätigte Wechsel werden nicht als Lernzyklus gezählt.

---

#### „Lerndaten wurden zurückgesetzt"

**Wann:** Erscheint als gelber Hinweis nach dem Speichern von Einstellungen,
wenn ein lernrelevanter Parameter geändert wurde.

**Betroffene Parameter:**
- Differenzdruck-Grenzwert (dp_limit)
- Druckabfall sauberer Filter (dp_clean)
- Maximaler Durchfluss (flow_max)
- Drucksensor-Messbereich (pressure_range)

**Was das bedeutet:** Das bisherige Referenzprofil ist mit den neuen Einstellungen
nicht mehr gültig und wurde automatisch gelöscht. Das System muss erneut 3 Filterzyklen
lernen, bevor die sekundengenaue Prognose wieder verfügbar ist.

**Was tun:** 3 neue Filterzyklen mit den aktualisierten Einstellungen abschließen.
Die Grobprognose (Bereichsanzeige) ist weiterhin aktiv.

---

### 11.4 Analyse-Meldungen (Simulationsmodus)

Diese Meldungen erscheinen im Simulationsbereich, wenn ein abweichendes Szenario
aktiv ist und das System das laufende Verhalten mit dem Referenzprofil vergleicht.

---

#### „Erhöhte Beladung: +XX %"

**Was das bedeutet:** Die Beladungsrate (dp-Anstieg pro Sekunde) liegt XX % über
dem Referenzwert aus den Lernzyklen. Der Filter wird schneller voll als gewohnt.

**Mögliche Ursachen:**
- Erhöhte Schmutzkonzentration im Medium
- Verändertes Fluid (Viskosität, Partikelgröße)
- Verstopfter Filter von vorneherein (Lagerware geöffnet)

**Relevant:** Beladungsrate aktuell vs. Referenz-Beladungsrate (bar/s)

---

#### „Durchflussabfall: XX %"

**Was das bedeutet:** Der Durchfluss Q ist um XX % gegenüber dem Referenzdurchfluss
gesunken. Der Filter hat einen erhöhten Strömungswiderstand.

**Mögliche Ursachen:**
- Zunehmende Filterverstopfung
- Druckabfall in der Anlage
- Leckage oder Bypass

**Relevant:** Q aktuell (l/min) vs. Referenz-Q (l/min)

---

#### „Temperaturabweichung: +X °C"

**Was das bedeutet:** Die Mediumtemperatur weicht vom Referenzwert ab.
Höhere Temperaturen können die Viskosität des Fluids verändern und den
Differenzdruck beeinflussen.

**Mögliche Ursachen:**
- Jahreszeitliche Temperaturschwankungen
- Veränderte Prozesstemperatur
- Defekter Temperatursensor

**Relevant:** T aktuell (°C) vs. Referenz-T (°C)

---

### 11.5 Overlay: Warte auf stabilen Durchfluss

**Wann:** Nach Systemstart, nach einem Filterwechsel oder nach Abbruch eines Zyklus.

**Relevante Messwerte:** Q (l/min), Schwellwert (l/min), Stabilitäts-Fortschritt (%)

**Was tun:** Nichts – das System startet automatisch, sobald Durchfluss stabil erkannt
wurde. Falls das Overlay dauerhaft bleibt:

1. Prüfen Sie, ob die Pumpe läuft und Durchfluss tatsächlich fließt
2. Schwellwert in den Einstellungen manuell senken, falls der automatisch berechnete Wert zu hoch ist (Einstellungen → Betriebsweise & Durchflusserkennung)
3. Im Simulationsmodus: Simulation starten

---

### 11.6 Overlay: Messzyklus pausiert

**Wann:** Durchfluss ist während eines aktiven Zyklus auf 0 gefallen (Pumpe aus).

**Relevante Werte:** Aktive Messzeit, Pausendauer

**Was tun:** Pumpe prüfen und wieder einschalten. Der Zyklus setzt automatisch fort,
sobald der Durchfluss zurückkehrt.

Bei dauerhafter Pause über 7 Tage: Der Zyklus wird abgebrochen und das System kehrt
in den Wartezustand zurück.

---

## 12. Fehlermeldungen

### Rotes Overlay: Sensor ausgefallen {#rotes-overlay-sensor-ausgefallen}

Ein oder mehrere Sensoren liefern kein gültiges Signal. Die Messung wurde gestoppt.

**Was tun:**
1. Prüfen Sie die Verdrahtung und Spannungsversorgung der genannten Sensoren
2. Klicken Sie auf **„Alle Sensoren angeschlossen – System prüfen"**
3. Das System testet alle 4 Kanäle automatisch
   - Alle OK → Messung startet, Overlay verschwindet
   - Noch Fehler → Overlay bleibt mit aktualisierter Kanalliste
4. Falls Sie ohne echte Sensoren weiterarbeiten möchten (nur Tests):
   Klappen Sie **„Im Simulationsmodus fortfahren"** auf und geben Sie das
   Einstellungspasswort ein

### Warnung: Messwerte weichen vom Profil ab

Das System hat erkannt, dass die aktuellen Messwerte stärker als erwartet vom
gelernten Referenzprofil abweichen (Standardschwelle: 25 %).

**Mögliche Ursachen:**
- Falsch eingebauter Filter (anderer Typ)
- Prozessänderung (Druckschwankungen, Temperaturwechsel)
- Beginn einer erhöhten Beladungsphase

Die Messung läuft weiter. Das System passt die Prognose an die neuen Messwerte an.

### Lerndaten wurden zurückgesetzt

Erscheint nach einer Änderung der lernrelevanten Filterparameter. Dies ist
**kein Fehler**, sondern erwartetes Verhalten. Das System muss erneut 3 Filterzyklen
aufzeichnen, bevor die sekundengenaue Prognose wieder verfügbar ist.

### Reststandzeit zeigt „Wird berechnet …"

Das System hat noch nicht genug Messdaten für eine Schätzung (weniger als 5 Messwerte
seit dem letzten Filterwechsel). Die Anzeige aktualisiert sich automatisch nach
wenigen Sekunden.

---

## 13. Häufige Fragen

**Wie lange dauert die Lernphase?**

Das System benötigt 3 vollständige Filterzyklen. Ein Zyklus beginnt nach der
Bestätigung eines Filterwechsels und endet mit der Bestätigung des nächsten.
Die Dauer eines Zyklus hängt von Ihrem Filterkreislauf ab.

**Was passiert, wenn ich einen anderen Filtertyp einbaue?**

Wenn sich der neue Filtertyp deutlich vom gelernten Profil unterscheidet, zeigt
das System eine **Warnung**. Das System lernt den neuen Filtertyp automatisch
innerhalb der nächsten 3 Zyklen. Falls Sie den Filtertyp dauerhaft wechseln,
empfiehlt es sich, die Lerndaten über die Einstellungen zurückzusetzen.

**Kann ich das Dashboard auf dem Smartphone nutzen?**

Ja. Die Weboberfläche ist für alle Bildschirmgrößen optimiert. Öffnen Sie einfach
`http://<IP>:8080` im Browser Ihres Smartphones oder Tablets.

**Warum sehe ich keinen Beladungsgrad?**

Der Beladungsgrad (prozentuale Filterauslastung) wird nur angezeigt, wenn ein
**HETA-Code aktiv** ist. Ohne HETA-Code zeigt das System nur den Filterstatus
und eine grobe Reststandzeit-Schätzung.

**Das System fragt beim Start nach der Einrichtung – warum?**

Entweder wurde die Ersteinrichtung noch nicht abgeschlossen, oder das Passwort
wurde zurückgesetzt. Schließen Sie den Einrichtungsassistenten vollständig ab.

**Wie sichere ich meine Messdaten?**

Unter Einstellungen (⚙) finden Sie die Funktion **„CSV-Export"** – damit laden Sie
alle Messdaten als Datei herunter. Alternativ können Sie Daten via **MQTT** in ein
Cloud-System oder via **Modbus TCP** direkt an eine SPS übertragen
(Einstellungen → MQTT bzw. `modbus_enabled` in der Konfiguration).

**Was bedeutet „Simulationsmodus" auf der Messe?**

Im Simulationsmodus werden keine echten Sensoren benötigt. Das System simuliert
einen realistischen Filterkreislauf und demonstriert alle Funktionen – Lernphase,
Reststandzeit, Warnungen und Filterwechsel – vollständig ohne Hardware.

**Was ist der Unterschied zwischen Dauerbetrieb und Intervallbetrieb?**

Im Dauerbetrieb erwartet das System, dass die Pumpe fast ununterbrochen läuft –
kurze Pausen bis 30 s werden toleriert. Im Intervallbetrieb (Batch) schaltet die
Pumpe regelmäßig ab; Pausen bis 60 s sind normal. Die Reststandzeit im Intervallbetrieb
basiert auf der kumulierten Betriebszeit, nicht auf der Wanduhrzeit.

**Das bernsteinfarbene Overlay erscheint, obwohl die Pumpe läuft – was tun?**

Das System erwartet, dass der Durchfluss über dem automatisch berechneten Schwellwert
liegt UND der Differenzdruck über 50 % des Sauberfilter-Druckabfalls. Mögliche Ursachen:
zu hoher Schwellwert → manuellen Wert in Einstellungen setzen (Einstellungen →
Betriebsweise & Durchflusserkennung); dp zu niedrig → Filter läuft noch nicht unter Last.

**Wie lange darf die Pumpe zwischen den Messzyklen abgeschaltet sein?**

Bis zur eingestellten Pausentoleranz (Standard: 30 s im Dauerbetrieb, 60 s im
Intervallbetrieb). Danach wird der Zyklus abgebrochen. Für regelmäßig längere Pausen:
Intervallbetrieb wählen und die manuelle Pausentoleranz entsprechend setzen
(Einstellungen → Betriebsweise & Durchflusserkennung).
