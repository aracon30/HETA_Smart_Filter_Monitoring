"""
Hardware-Diagnose – Selbstcheck aller Systemkomponenten.
Wird von /api/diagnostics (GET) aufgerufen.
"""
import logging
import os
import platform
import subprocess
import sys
import time

logger = logging.getLogger(__name__)


def run_diagnostics(
    state,
    state_lock,
    settings: dict,
    db,
    base_dir: str,
    get_local_ip,        # callable: () -> str
    mqtt=None,
    modbus=None,
    display=None,
    navigation=None,
) -> dict:
    """Führt den Selbstcheck durch und gibt {overall, timestamp, checks} zurück."""
    checks = []

    # ── System ──────────────────────────────────────────────────────────────
    checks.append({
        "id": "system",
        "label": "System",
        "status": "ok",
        "detail": (f"Python {sys.version.split()[0]}  ·  "
                   f"{platform.machine()}  ·  "
                   f"{platform.system()} {platform.release()}"),
        "hints": [],
    })

    # ── Software-Version ────────────────────────────────────────────────────
    try:
        gres = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=5, cwd=base_dir,
        )
        git_info = gres.stdout.strip() if gres.returncode == 0 else "unbekannt"
    except Exception:
        git_info = "git nicht verfügbar"
    checks.append({
        "id": "git",
        "label": "Software-Version (Git)",
        "status": "ok",
        "detail": git_info,
        "hints": [],
    })

    # ── Betriebsmodus ───────────────────────────────────────────────────────
    with state_lock:
        sim_mode    = state["simulation_mode"]
        hw_avail    = state.get("sensor_hw_available", False)
        meas_running = state["running"]
        awaiting     = state["awaiting_confirmation"]
        cycle_active = state["cycle_active"]
        sensor_fault = state.get("sensor_fault", False)
        sensor_err   = state.get("sensor_error", False)
        heta_code    = state.get("heta_code", "")

    if sim_mode:
        mode_status = "info"
        mode_detail = "Simulationsmodus aktiv"
        if hw_avail:
            mode_detail += " (Hardware erkannt – Echtbetrieb verfügbar)"
        else:
            mode_detail += " – kein AnoPi Shield gefunden"
        mode_hints = (["Für Echtbetrieb: simulation_mode=false in den Einstellungen"]
                      if hw_avail else [])
    else:
        if sensor_fault:
            mode_status = "error"
            mode_detail = f"Hardware-Modus – Sensorfehler: {state.get('sensor_fault_message', '')}"
            mode_hints  = ["Verkabelung aller 4 Kanäle prüfen", "Sensorneuprüfung über den Button starten"]
        elif sensor_err:
            mode_status = "warning"
            mode_detail = "Hardware-Modus – Sensorlesefehler (Messung läuft)"
            mode_hints  = ["Sensor-Kabelverbindungen prüfen"]
        else:
            mode_status = "ok"
            mode_detail = "Hardware-Modus – AnoPi Shield aktiv"
            mode_hints  = []
    checks.append({
        "id": "mode",
        "label": "Betriebsmodus",
        "status": mode_status,
        "detail": mode_detail,
        "hints": mode_hints,
    })

    # ── Messzyklus ──────────────────────────────────────────────────────────
    if not meas_running and not awaiting:
        cyc_status = "warning"
        cyc_detail = "Messung gestoppt"
        cyc_hints  = ["Messung über den Start-Button starten"]
    elif awaiting:
        cyc_status = "warning"
        cyc_detail = "Messung pausiert – Filterwechsel bestätigen"
        cyc_hints  = ["Filterwechsel durchführen und bestätigen um fortzufahren"]
    elif cycle_active:
        cyc_status = "ok"
        cyc_detail = f"Messung läuft – Zyklus aktiv{(' · ' + heta_code) if heta_code else ''}"
        cyc_hints  = []
    else:
        cyc_status = "ok"
        cyc_detail = "Messung läuft – warte auf Zyklusstart (dp unterhalb Startschwelle)"
        cyc_hints  = []
    checks.append({
        "id": "measurement",
        "label": "Messzyklus",
        "status": cyc_status,
        "detail": cyc_detail,
        "hints": cyc_hints,
    })

    # ── Datenbank ─────────────────────────────────────────────────────────────
    try:
        with db._conn() as _dbcon:
            meas_count  = _dbcon.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
            cycle_count = _dbcon.execute("SELECT COUNT(*) FROM filter_cycles").fetchone()[0]
        checks.append({
            "id": "database",
            "label": "Datenbank (SQLite)",
            "status": "ok",
            "detail": (f"{meas_count} Messwerte  ·  {cycle_count} Filterzyklen  ·  "
                       f"Pfad: {db.db_path}"),
            "hints": [],
        })
    except Exception as exc:
        checks.append({
            "id": "database",
            "label": "Datenbank (SQLite)",
            "status": "error",
            "detail": f"Datenbankfehler: {exc}",
            "hints": ["data/-Verzeichnis vorhanden?", "Schreibrechte prüfen"],
        })

    # ── MQTT ────────────────────────────────────────────────────────────────
    mqtt_enabled = settings.get("mqtt_enabled", False)
    if not mqtt_enabled:
        checks.append({
            "id": "mqtt",
            "label": "MQTT",
            "status": "info",
            "detail": "MQTT deaktiviert (mqtt_enabled=false in den Einstellungen)",
            "hints": [],
        })
    elif mqtt is None:
        checks.append({
            "id": "mqtt",
            "label": "MQTT",
            "status": "error",
            "detail": "MQTT-Client konnte nicht initialisiert werden",
            "hints": [
                "pip install paho-mqtt",
                f"Broker-Adresse prüfen: {settings.get('mqtt_broker','localhost')}:{settings.get('mqtt_port',1883)}",
            ],
        })
    elif mqtt.is_connected:
        checks.append({
            "id": "mqtt",
            "label": "MQTT",
            "status": "ok",
            "detail": (f"Verbunden mit {settings.get('mqtt_broker','localhost')}:"
                       f"{settings.get('mqtt_port',1883)}  ·  "
                       f"Client-ID: {settings.get('mqtt_client_id','heta_monitor')}"),
            "hints": [],
        })
    else:
        checks.append({
            "id": "mqtt",
            "label": "MQTT",
            "status": "warning",
            "detail": (f"Nicht verbunden mit "
                       f"{settings.get('mqtt_broker','localhost')}:{settings.get('mqtt_port',1883)}"),
            "hints": [
                "MQTT-Broker erreichbar?  ping " + settings.get("mqtt_broker", "localhost"),
                "Broker-Port und Zugangsdaten in den Einstellungen prüfen",
            ],
        })

    # ── Modbus TCP ───────────────────────────────────────────────────────────
    modbus_enabled = settings.get("modbus_enabled", False)
    if not modbus_enabled:
        checks.append({
            "id": "modbus",
            "label": "Modbus TCP",
            "status": "info",
            "detail": "Modbus TCP deaktiviert (modbus_enabled=false in den Einstellungen)",
            "hints": [],
        })
    elif modbus is None:
        checks.append({
            "id": "modbus",
            "label": "Modbus TCP",
            "status": "error",
            "detail": "Modbus-TCP-Server konnte nicht initialisiert werden",
            "hints": [
                "pip install pymodbus",
                f"Port prüfen: {settings.get('modbus_port', 502)} (Root-Rechte nötig für Port < 1024)",
            ],
        })
    elif modbus.is_running:
        checks.append({
            "id": "modbus",
            "label": "Modbus TCP",
            "status": "ok",
            "detail": (f"Server aktiv auf {settings.get('modbus_host','0.0.0.0')}:"
                       f"{settings.get('modbus_port', 502)}  ·  11 Holding-Register"),
            "hints": [],
        })
    else:
        checks.append({
            "id": "modbus",
            "label": "Modbus TCP",
            "status": "warning",
            "detail": (f"Server nicht aktiv  "
                       f"({settings.get('modbus_host','0.0.0.0')}:{settings.get('modbus_port',502)})"),
            "hints": [
                f"Port {settings.get('modbus_port',502)} bereits belegt?  "
                f"sudo lsof -i :{settings.get('modbus_port',502)}",
                "Port < 1024 benötigt Root oder authbind",
            ],
        })

    # ── OLED-Display ─────────────────────────────────────────────────────────
    if not settings.get("display_enabled", True):
        checks.append({
            "id": "display",
            "label": "OLED-Display (SSD1309)",
            "status": "info",
            "detail": "Display deaktiviert (display_enabled=false in den Einstellungen)",
            "hints": [],
        })
    elif display is None:
        checks.append({
            "id": "display",
            "label": "OLED-Display (SSD1309)",
            "status": "error",
            "detail": "Display-Modul konnte beim Start nicht geladen werden",
            "hints": [
                "pip install luma.oled",
                "Logs prüfen: journalctl -u heta-monitor | grep -i display",
            ],
        })
    elif display.is_simulated:
        use_spi = settings.get("display_use_spi", True)
        if use_spi:
            spi_port   = settings.get("display_spi_port", 0)
            spi_device = settings.get("display_spi_device", 0)
            dc  = settings.get("display_gpio_dc", 25)
            rst = settings.get("display_gpio_rst", 27)
            hw_hints = [
                f"SPI-Verbindung: DC→GPIO{dc}, RST→GPIO{rst}, DIN→GPIO10, CLK→GPIO11, CS→GPIO8",
                f"SPI-Bus prüfen: ls /dev/spidev{spi_port}.{spi_device}",
                "SPI aktivieren: sudo raspi-config → Interface Options → SPI",
                "pip install luma.oled",
            ]
        else:
            addr = settings.get("display_i2c_address", 60)
            hw_hints = [
                f"I2C-Adresse: 0x{addr:02X}  ·  I2C-Bus prüfen: ls /dev/i2c*",
                "I2C aktivieren: sudo raspi-config → Interface Options → I2C",
                "i2c-Gerät scannen: sudo i2cdetect -y 1",
            ]
        checks.append({
            "id": "display",
            "label": "OLED-Display (SSD1309)",
            "status": "warning",
            "detail": "Kein Hardware-Display erkannt – läuft im Simulationsmodus (kein Ausgabegerät)",
            "hints": hw_hints,
        })
    else:
        try:
            display.show_network(get_local_ip(), settings.get("webserver_port", 8080), "DIAGNOSE")
            checks.append({
                "id": "display",
                "label": "OLED-Display (SSD1309)",
                "status": "ok",
                "detail": "Display aktiv – Testbild erfolgreich gerendert",
                "hints": [],
            })
        except Exception as exc:
            checks.append({
                "id": "display",
                "label": "OLED-Display (SSD1309)",
                "status": "error",
                "detail": f"Render-Fehler: {exc}",
                "hints": ["Verkabelung prüfen", "sudo pip install --upgrade luma.oled"],
            })

    # ── SPI-Bus (nur relevant wenn Display SPI nutzt oder Hardware-Modus aktiv)
    display_uses_spi = settings.get("display_enabled", True) and settings.get("display_use_spi", True)
    if display_uses_spi or not sim_mode:
        spi_port   = settings.get("display_spi_port", 0)
        spi_device = settings.get("display_spi_device", 0)
        spi_dev    = f"/dev/spidev{spi_port}.{spi_device}"
        spi_exists = os.path.exists(spi_dev)
        checks.append({
            "id": "spi",
            "label": f"SPI-Bus ({spi_dev})",
            "status": "ok" if spi_exists else "error",
            "detail": f"{spi_dev} {'gefunden' if spi_exists else 'nicht gefunden – SPI nicht aktiviert'}",
            "hints": [] if spi_exists else [
                "SPI aktivieren: sudo raspi-config → Interface Options → SPI",
                "Neustart: sudo reboot",
                "Prüfen: ls /dev/spidev*",
            ],
        })

    # ── I2C-Bus (nur relevant wenn Display I2C nutzt) ────────────────────────
    display_uses_i2c = settings.get("display_enabled", True) and not settings.get("display_use_spi", True)
    if display_uses_i2c:
        i2c_dev    = "/dev/i2c-1"
        i2c_exists = os.path.exists(i2c_dev)
        checks.append({
            "id": "i2c_bus",
            "label": f"I2C-Bus ({i2c_dev})",
            "status": "ok" if i2c_exists else "error",
            "detail": f"{i2c_dev} {'gefunden' if i2c_exists else 'nicht gefunden – I2C nicht aktiviert'}",
            "hints": [] if i2c_exists else [
                "I2C aktivieren: sudo raspi-config → Interface Options → I2C",
                "Neustart: sudo reboot",
                "Prüfen: ls /dev/i2c*",
            ],
        })

    # ── ANO-Encoder ──────────────────────────────────────────────────────────
    if not settings.get("navigation_enabled", True):
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (GPIO)",
            "status": "info",
            "detail": "Encoder deaktiviert (navigation_enabled=false in den Einstellungen)",
            "hints": [],
        })
    elif navigation is None:
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (GPIO)",
            "status": "error",
            "detail": "Encoder-Modul konnte beim Start nicht geladen werden",
            "hints": [
                "pip install gpiozero lgpio",
                "Logs prüfen: journalctl -u heta-monitor | grep -i encoder",
            ],
        })
    elif navigation.is_simulated:
        enc_pins = {
            "ENCA": settings.get("encoder_pin_enca", 16),
            "ENCB": settings.get("encoder_pin_encb", 20),
            "SW1":  settings.get("encoder_pin_sw1", 21),
            "SW2":  settings.get("encoder_pin_sw2", 12),
            "SW3":  settings.get("encoder_pin_sw3", 13),
            "SW4":  settings.get("encoder_pin_sw4", 19),
            "SW5":  settings.get("encoder_pin_sw5", 26),
        }
        pin_summary = "  ·  ".join(f"{n}=GPIO{p}" for n, p in enc_pins.items())
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (GPIO)",
            "status": "warning",
            "detail": f"Kein Hardware-Encoder erkannt – läuft im Simulationsmodus  ·  {pin_summary}",
            "hints": [
                "Encoder anschließen: ENCA, ENCB, SW1–SW5, COMA→GND, COMB→GND",
                "GPIO-Pins in den Einstellungen prüfen",
                "pip install gpiozero lgpio",
            ],
        })
    else:
        steps = navigation.get_encoder_steps()
        checks.append({
            "id": "encoder",
            "label": "ANO-Encoder (GPIO)",
            "status": "ok",
            "detail": f"Encoder aktiv – Schrittposition: {steps}",
            "hints": [],
        })

    # ── Sensoren / AnoPi Shield ───────────────────────────────────────────────
    if sim_mode:
        checks.append({
            "id": "sensors",
            "label": "Sensoren (4–20 mA / AnoPi Shield)",
            "status": "info",
            "detail": ("Simulationsmodus – Sensor-Hardware nicht geprüft"
                       + ("  ·  AnoPi Shield erreichbar" if hw_avail else "  ·  kein AnoPi Shield erkannt")),
            "hints": (["Für Echtbetrieb: simulation_mode=false in den Einstellungen"]
                      if hw_avail else []),
        })
    elif not hw_avail:
        checks.append({
            "id": "sensors",
            "label": "Sensoren (4–20 mA / AnoPi Shield)",
            "status": "error",
            "detail": "AnoPi Shield nicht erreichbar – SPI-Kommunikation fehlgeschlagen",
            "hints": [
                "AnoPi Shield korrekt aufgesteckt?",
                "SPI-Bus aktiv? (ls /dev/spidev*)",
                "pip install spidev",
            ],
        })
    else:
        try:
            import spidev  # type: ignore
            _spi = spidev.SpiDev()
            _spi.open(0, 0)
            _spi.max_speed_hz = 1_350_000
            raw = _spi.xfer2([1, (8 + 0) << 4, 0])
            _spi.close()
            adc_raw = ((raw[1] & 3) << 8) + raw[2]
            checks.append({
                "id": "sensors",
                "label": "Sensoren (4–20 mA / AnoPi Shield)",
                "status": "ok",
                "detail": f"AnoPi Shield antwortet – ADC Kanal 0 Rohwert: {adc_raw} / 4095",
                "hints": [],
            })
        except ImportError:
            checks.append({
                "id": "sensors",
                "label": "Sensoren (4–20 mA / AnoPi Shield)",
                "status": "error",
                "detail": "spidev-Bibliothek nicht installiert",
                "hints": ["pip install spidev"],
            })
        except Exception as exc:
            checks.append({
                "id": "sensors",
                "label": "Sensoren (4–20 mA / AnoPi Shield)",
                "status": "error",
                "detail": f"SPI-Lesefehler: {exc}",
                "hints": [
                    "AnoPi Shield korrekt aufgesteckt?",
                    "SPI-Gerätekonflikte? (Display und Shield auf unterschiedlichen CE)",
                ],
            })

    # ── Gesamtstatus ──────────────────────────────────────────────────────────
    statuses = [c["status"] for c in checks]
    if "error" in statuses:
        overall = "error"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "ok"

    return {
        "overall": overall,
        "timestamp": time.time(),
        "checks": checks,
    }
