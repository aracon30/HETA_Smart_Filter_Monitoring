#!/bin/bash
# ============================================================
# HETA Smart Filter Monitoring – Installationsskript
# Raspberry Pi 5 / Raspberry Pi OS Lite 64-bit
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="heta-monitor"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PYTHON_BIN="python3"
VENV_DIR="${PROJECT_DIR}/.venv"
INSTALL_USER="$(whoami)"

echo "============================================================"
echo "  HETA Smart Filter Monitoring – Installation"
echo "  Projektverzeichnis: ${PROJECT_DIR}"
echo "============================================================"

# -----------------------------------------------------------
# 1. Systempakete aktualisieren
# -----------------------------------------------------------
echo ""
echo "[1/7] Systempakete aktualisieren..."
sudo apt-get update -y
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    python3-dev gcc make \
    python3-lgpio \
    libfreetype6-dev libjpeg-dev \
    i2c-tools \
    fonts-dejavu-core

# -----------------------------------------------------------
# 2. SPI und I2C aktivieren
# -----------------------------------------------------------
echo ""
echo "[2/7] SPI und I2C-Konfiguration prüfen..."
if ! grep -q "^dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null; then
    echo "  Hinweis: SPI ist nicht in /boot/firmware/config.txt aktiviert."
    echo "  Füge folgende Zeilen manuell hinzu und starte neu:"
    echo "    dtparam=spi=on"
    echo "    dtparam=i2c_arm=on"
else
    echo "  SPI ist bereits aktiviert."
fi

if ! lsmod | grep -q i2c_dev 2>/dev/null; then
    echo "  Hinweis: i2c_dev Modul nicht geladen. Prüfe Raspberry Pi Konfiguration."
fi

# -----------------------------------------------------------
# 3. Python Virtual Environment erstellen
# -----------------------------------------------------------
echo ""
echo "[3/7] Python Virtual Environment erstellen in ${VENV_DIR}..."
# --system-site-packages erlaubt Zugriff auf system-installiertes python3-lgpio
"${PYTHON_BIN}" -m venv --system-site-packages "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

# -----------------------------------------------------------
# 4. Python-Pakete installieren
# -----------------------------------------------------------
echo ""
echo "[4/7] Python-Pakete installieren..."
pip install --upgrade pip
pip install -r "${PROJECT_DIR}/requirements.txt"

# lgpio wird für gpiozero auf dem Raspberry Pi 5 benötigt.
# Es wird als Systempaket installiert (pip-Build schlägt ohne Kernel-Header fehl).
# Das Virtual Environment wurde mit --system-site-packages erstellt,
# daher ist das Systempaket python3-lgpio automatisch sichtbar.
echo "  lgpio ist als Systempaket python3-lgpio installiert (via apt, Schritt 1)."

echo ""
echo "  Installierte Pakete:"
pip list --format=columns | grep -Ei "flask|luma|pillow|paho|gpiozero|spidev"

# -----------------------------------------------------------
# 5. Verzeichnisse erstellen
# -----------------------------------------------------------
echo ""
echo "[5/7] Datenverzeichnisse erstellen..."
mkdir -p "${PROJECT_DIR}/data"
mkdir -p "${PROJECT_DIR}/logs"
mkdir -p "${PROJECT_DIR}/exports"

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
echo "  Service '${SERVICE_NAME}' installiert und aktiviert."

# Sudoers-Eintrag: Installationsbenutzer darf den Service ohne Passwort neu starten
# (wird vom Software-Update über die Weboberfläche benötigt)
SUDOERS_FILE="/etc/sudoers.d/heta-monitor"
SUDOERS_LINE="${INSTALL_USER} ALL=(ALL) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}"
if ! sudo grep -qF "${SUDOERS_LINE}" "${SUDOERS_FILE}" 2>/dev/null; then
    echo "${SUDOERS_LINE}" | sudo tee "${SUDOERS_FILE}" > /dev/null
    sudo chmod 0440 "${SUDOERS_FILE}"
    echo "  Sudoers-Eintrag für 'systemctl restart ${SERVICE_NAME}' angelegt."
else
    echo "  Sudoers-Eintrag bereits vorhanden."
fi

# -----------------------------------------------------------
# 7. Abschluss
# -----------------------------------------------------------
echo ""
echo "============================================================"
echo "  Installation abgeschlossen!"
echo ""
echo "  Manueller Start:   sudo systemctl start ${SERVICE_NAME}"
echo "  Status prüfen:     sudo systemctl status ${SERVICE_NAME}"
echo "  Logs ansehen:      journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "  Weboberfläche:     http://<IP-Adresse>:8080"
echo ""
echo "  WICHTIG: Raspberry Pi neu starten um SPI/I2C zu aktivieren!"
echo "    sudo reboot"
echo "============================================================"
