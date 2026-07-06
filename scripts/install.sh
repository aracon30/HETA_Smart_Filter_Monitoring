#!/bin/bash
# ============================================================
# HETA Smart Filter Monitoring – Installationsskript
# Raspberry Pi 5 / Raspberry Pi OS Lite 64-bit (Bookworm)
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="heta-monitor"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PYTHON_BIN="python3"
VENV_DIR="${PROJECT_DIR}/.venv"
INSTALL_USER="$(whoami)"

# Boot-Konfigurationsdatei: Bookworm = /boot/firmware/config.txt,
# ältere Pi OS Versionen = /boot/config.txt
if [ -f /boot/firmware/config.txt ]; then
    BOOT_CONFIG="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
    BOOT_CONFIG="/boot/config.txt"
else
    BOOT_CONFIG=""
fi

echo "============================================================"
echo "  HETA Smart Filter Monitoring – Installation"
echo "  Projektverzeichnis: ${PROJECT_DIR}"
echo "  Benutzer:           ${INSTALL_USER}"
echo "============================================================"

# -----------------------------------------------------------
# 1. Systempakete aktualisieren
# -----------------------------------------------------------
echo ""
echo "[1/7] Systempakete aktualisieren..."
sudo apt-get update
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    python3-dev gcc make \
    libfreetype6-dev libjpeg-dev \
    i2c-tools \
    fonts-dejavu-core

# lgpio als Systempaket – pip-Build schlägt ohne Kernel-Header fehl.
# Fehler hier ist nicht kritisch (Paket heißt auf manchen Versionen anders
# oder ist bereits vorinstalliert).
echo "  Installiere python3-lgpio (GPIO-Backend für Pi 5)..."
sudo apt-get install -y python3-lgpio || echo "  Hinweis: python3-lgpio nicht verfügbar – gpiozero nutzt verfügbares Backend."

# -----------------------------------------------------------
# 2. I2C aktivieren (AnoPi Shield)
# -----------------------------------------------------------
echo ""
echo "[2/7] I2C-Konfiguration prüfen und aktivieren..."

if [ -n "${BOOT_CONFIG}" ]; then
    if grep -q "^dtparam=i2c_arm=on" "${BOOT_CONFIG}" 2>/dev/null; then
        echo "  I2C: bereits aktiviert (${BOOT_CONFIG})"
    else
        echo "  I2C aktivieren in ${BOOT_CONFIG}..."
        echo "dtparam=i2c_arm=on" | sudo tee -a "${BOOT_CONFIG}" > /dev/null
        echo "  I2C: aktiviert – Neustart erforderlich."
    fi
else
    echo "  Boot-Konfigurationsdatei nicht gefunden – I2C manuell prüfen."
    echo "  Bitte ausführen: sudo raspi-config → Interface Options → I2C → Yes"
fi

# I2C-Gerät prüfen
if ls /dev/i2c-* &>/dev/null; then
    echo "  I2C-Gerät: $(ls /dev/i2c-* | tr '\n' ' ')(aktiv)"
else
    echo "  I2C-Gerät: nicht gefunden – Neustart nach Aktivierung erforderlich."
fi

# -----------------------------------------------------------
# 3. Python Virtual Environment erstellen
# -----------------------------------------------------------
echo ""
echo "[3/7] Python Virtual Environment erstellen in ${VENV_DIR}..."
# --system-site-packages: system-installiertes python3-lgpio ist im venv sichtbar
# --clear: stellt bei Neuinstallation einen sauberen Zustand sicher
"${PYTHON_BIN}" -m venv --system-site-packages --clear "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

# -----------------------------------------------------------
# 4. Python-Pakete installieren
# -----------------------------------------------------------
echo ""
echo "[4/7] Python-Pakete installieren..."
pip install --upgrade pip --quiet
pip install -r "${PROJECT_DIR}/requirements.txt"

echo ""
echo "  Installierte Pakete:"
pip list --format=columns | grep -Ei "flask|luma|pillow|paho|gpiozero|spidev" || true

# -----------------------------------------------------------
# 5. Verzeichnisse erstellen
# -----------------------------------------------------------
echo ""
echo "[5/7] Datenverzeichnisse erstellen..."
mkdir -p "${PROJECT_DIR}/data"
mkdir -p "${PROJECT_DIR}/logs"
mkdir -p "${PROJECT_DIR}/exports"
echo "  data/, logs/, exports/ vorhanden."

# -----------------------------------------------------------
# 6. systemd-Service installieren
# -----------------------------------------------------------
echo ""
echo "[6/7] systemd-Service installieren..."

VENV_PYTHON="${VENV_DIR}/bin/python3"

sudo tee "${SERVICE_FILE}" > /dev/null <<EOF
[Unit]
Description=HETA Smart Filter Monitoring
After=network.target

[Service]
Type=simple
User=${INSTALL_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_PYTHON} ${PROJECT_DIR}/backend/app.py
Restart=always
RestartSec=3
TimeoutStopSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
echo "  Service '${SERVICE_NAME}' installiert und aktiviert (User: ${INSTALL_USER})."

# Sudoers-Eintrag: Benutzer darf den Service ohne Passwort neu starten
# (wird vom Software-Update über die Weboberfläche benötigt)
SUDOERS_FILE="/etc/sudoers.d/heta-monitor"
SUDOERS_LINE="${INSTALL_USER} ALL=(ALL) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}"
if ! sudo grep -qF "${SUDOERS_LINE}" "${SUDOERS_FILE}" 2>/dev/null; then
    echo "${SUDOERS_LINE}" | sudo tee "${SUDOERS_FILE}" > /dev/null
    sudo chmod 0440 "${SUDOERS_FILE}"
    echo "  Sudoers-Eintrag angelegt."
else
    echo "  Sudoers-Eintrag bereits vorhanden."
fi

# -----------------------------------------------------------
# 7. Abschluss
# -----------------------------------------------------------
LOCAL_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -z "${LOCAL_IP}" ] && LOCAL_IP="<IP-Adresse>"

echo ""
echo "============================================================"
echo "  Installation abgeschlossen!"
echo ""
echo "  Manueller Start:   sudo systemctl start ${SERVICE_NAME}"
echo "  Status prüfen:     sudo systemctl status ${SERVICE_NAME}"
echo "  Logs ansehen:      journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "  Weboberfläche:     http://${LOCAL_IP}:8080"
echo ""
if [ -n "${BOOT_CONFIG}" ]; then
    if ! grep -q "^dtparam=i2c_arm=on" "${BOOT_CONFIG}" 2>/dev/null; then
        echo "  WICHTIG: I2C noch nicht aktiviert!"
        echo "  Einstellungen vornehmen, dann neu starten:"
        echo "    sudo reboot"
        echo ""
    fi
fi
echo "============================================================"
