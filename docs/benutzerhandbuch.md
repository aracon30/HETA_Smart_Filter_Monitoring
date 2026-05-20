# Bedienungsanleitung – HETA Smart Filter Monitoring

Diese Anleitung richtet sich an Anwender, die das System über den Browser bedienen.
Sie benötigen keine Programmierkenntnisse.

---

## Inhaltsverzeichnis

1. [System starten und aufrufen](#1-system-starten-und-aufrufen)
2. [Ersteinrichtung (Onboarding)](#2-ersteinrichtung-onboarding)
3. [Das Dashboard](#3-das-dashboard)
4. [HETA-Code aktivieren](#4-heta-code-aktivieren)
5. [Filterwechsel bestätigen](#5-filterwechsel-bestätigen)
6. [Einstellungen ändern](#6-einstellungen-ändern)
7. [Simulationsmodus](#7-simulationsmodus)
8. [OLED-Display und Encoder](#8-oled-display-und-encoder)
9. [Systemmeldungen im Detail](#9-systemmeldungen-im-detail)
10. [Fehlermeldungen](#10-fehlermeldungen)
11. [Häufige Fragen](#11-häufige-fragen)

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

---

## 2. Ersteinrichtung (Onboarding)

Beim allerersten Start des Systems erscheint automatisch der **Einrichtungsassistent**.
Er führt Sie in 6 Schritten durch die Grundkonfiguration.

### Schritt 1 – Willkommen

Lesen Sie die Übersicht und klicken Sie auf **„Weiter"**.

### Schritt 2 – Betriebsart

Wählen Sie, wie das System Messwerte erfasst:

| Option | Wann wählen |
|--------|-------------|
| **Hardware (Realbetrieb)** | Echte Drucksensoren, Temperatursensor und Durchflussmesser sind angeschlossen |
| **Simulation** | Für Vorführungen und Tests ohne reale Sensorhardware |

> Wenn Sie unsicher sind, wählen Sie **Hardware**. Der Simulationsmodus kann
> jederzeit nachträglich in den Einstellungen aktiviert werden.

### Schritt 3 – Filterparameter

Tragen Sie die Kenndaten Ihres Filterkreislaufs ein:

| Feld | Bedeutung | Typischer Wert |
|------|-----------|---------------|
| **Differenzdruck-Grenzwert** | dp-Wert, bei dem der Filter gewechselt werden muss | 2,5 bar |
| **Druckabfall sauberer Filter** | dp-Wert eines fabrikneuen Filters | 0,2 bar |
| **Maximaler Durchfluss** | Endwert des Durchflusssensors (= 20 mA) | 150 l/min |
| **Drucksensor-Messbereich** | Endwert der Drucksensoren (= 20 mA) | 10 bar |

> Diese Werte stehen im Datenblatt Ihres Filters und Ihrer Sensoren.

### Schritt 4 – Temperatursensorbereich

Tragen Sie den Messbereich Ihres Temperatursensors ein (Minimum und Maximum in °C).
Standardwert: −50 °C bis +150 °C.

### Schritt 5 – Passwort festlegen

Legen Sie ein Passwort für den geschützten Einstellungsbereich fest.
Das Passwort muss **mindestens 4 Zeichen** lang sein.

> Notieren Sie das Passwort. Falls Sie es vergessen, muss ein Administrator
> es über die Konsole zurücksetzen.

### Schritt 6 – Zusammenfassung

Prüfen Sie alle Angaben. Klicken Sie auf **„Einrichtung abschließen"** –
das System startet die Messung.

---

## 3. Das Dashboard

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

### Live-Diagramm

Das Diagramm zeigt den zeitlichen Verlauf der Messwerte. Mit dem HETA-Code aktiv
werden zusätzlich die **Referenzkurve** (gestrichelt) und die **Toleranzbänder**
eingeblendet, so dass Abweichungen vom Normalverhalten sofort sichtbar sind.

### Betriebsmodus-Badge

Oben rechts im Dashboard:

| Badge | Bedeutung |
|-------|-----------|
| `REAL` (blau) | Echte Sensordaten werden erfasst |
| `SIM` (grau) | Simulationsmodus aktiv |
| `FEHLER` (rot) | Sensor ausgefallen – Messung gestoppt |

---

## 4. HETA-Code aktivieren

Mit einem HETA-Code schaltet das System erweiterte Funktionen frei:

- **Beladungsgrad** in Prozent (wie voll ist der Filter?)
- **Lernprofil** – das System lernt das typische Verhalten Ihres Filterkreislaufs
- **Sekundengenaue Reststandzeit** – nach 3 abgeschlossenen Filterzyklen

### So aktivieren Sie einen HETA-Code

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

## 5. Filterwechsel bestätigen

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

## 6. Einstellungen ändern

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

#### Systemparameter
Messintervall, Sitzungs-Timeout, Log-Level.

#### MQTT (optional)
Verbindung zu einem MQTT-Broker für die Anbindung an übergeordnete Systeme.

#### Software-Update
Klicken Sie auf **„Update von GitHub holen"**, um die neueste Version zu installieren.
Das System startet nach dem Update automatisch neu (ca. 10 Sekunden).

#### Passwort ändern
Altes Passwort eingeben, neues Passwort zweimal bestätigen.

---

## 7. Simulationsmodus

Der Simulationsmodus ermöglicht eine vollständige Vorführung des Systems **ohne
angeschlossene Sensoren** – ideal für Messen, Schulungen und Entwicklungstests.

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

## 8. OLED-Display und Encoder

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

## 9. Systemmeldungen im Detail

Das System gibt kontinuierlich Rückmeldung über den Zustand des Filters und der Anlage.
Dieser Abschnitt erklärt jede mögliche Meldung, welche Messwerte dazu geführt haben und
was Sie als Bediener konkret tun sollten.

---

### 9.1 Filterstatus-Meldungen

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
→ Siehe [Abschnitt 10 – Fehlermeldungen: Sensor ausgefallen](#rotes-overlay-sensor-ausgefallen)

---

### 9.2 Prognosemeldungen

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
- Die Beladung langsamer als üblich verläuft → Restzeit wird länger (gedämpft, max. +2 %/s)

**Was tun:** Keine Aktion erforderlich. Bei dauerhaft verändertem Betrieb (anderer Filtertyp,
veränderter Prozess): Lerndaten zurücksetzen, damit das System neu lernt.

---

### 9.3 Lernphasen-Meldungen

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

### 9.4 Analyse-Meldungen (Simulationsmodus)

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

## 10. Fehlermeldungen

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

## 11. Häufige Fragen

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
alle Messdaten als Datei herunter. Alternativ können Sie Daten via MQTT in ein
übergeordnetes System übertragen (Einstellungen → MQTT).

**Was bedeutet „Simulationsmodus" auf der Messe?**

Im Simulationsmodus werden keine echten Sensoren benötigt. Das System simuliert
einen realistischen Filterkreislauf und demonstriert alle Funktionen – Lernphase,
Reststandzeit, Warnungen und Filterwechsel – vollständig ohne Hardware.
