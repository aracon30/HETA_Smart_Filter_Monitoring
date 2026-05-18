#!/bin/bash
# ============================================================
# HETA Smart Filter Monitoring – Update-Skript (auf dem Pi)
#
# Führt ein lokales Software-Update durch:
#   1. Einstellungen nach settings.local.json migrieren (einmalig)
#   2. git pull
#   3. Python-Pakete aktualisieren
#   4. Dienst neu starten
#
# Verwendung:
#   ./scripts/update.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="heta-monitor"
SETTINGS_JSON="${PROJECT_DIR}/config/settings.json"
SETTINGS_LOCAL="${PROJECT_DIR}/config/settings.local.json"
VENV_DIR="${PROJECT_DIR}/.venv"

echo "============================================================"
echo "  HETA Smart Filter Monitoring – Software-Update"
echo "  Projektverzeichnis: ${PROJECT_DIR}"
echo "============================================================"

cd "${PROJECT_DIR}"

# -----------------------------------------------------------
# 1. Einstellungen migrieren (einmalig, wenn nötig)
# -----------------------------------------------------------
# Falls settings.json lokal verändert wurde und settings.local.json
# noch nicht existiert: Benutzerdaten nach settings.local.json
# übertragen und settings.json auf den Git-Stand zurücksetzen.
# Danach sind künftige git pulls ohne Konflikte möglich.

if [ ! -f "${SETTINGS_LOCAL}" ] && ! git diff --quiet "${SETTINGS_JSON}" 2>/dev/null; then
    echo ""
    echo "[1/4] Einstellungen migrieren..."
    echo "  Kopiere ${SETTINGS_JSON} → ${SETTINGS_LOCAL}"
    cp "${SETTINGS_JSON}" "${SETTINGS_LOCAL}"
    echo "  Setze ${SETTINGS_JSON} auf Git-Standardwerte zurück."
    git checkout "${SETTINGS_JSON}"
    echo "  Migration abgeschlossen. Künftige Updates verlaufen ohne Konflikte."
else
    echo ""
    echo "[1/4] Einstellungen – keine Migration erforderlich."
fi

# -----------------------------------------------------------
# 2. Git pull
# -----------------------------------------------------------
echo ""
echo "[2/4] Quellcode aktualisieren (git pull)..."
git pull --ff-only

# -----------------------------------------------------------
# 3. Python-Pakete aktualisieren
# -----------------------------------------------------------
echo ""
echo "[3/4] Python-Pakete aktualisieren..."
if [ -d "${VENV_DIR}" ]; then
    "${VENV_DIR}/bin/pip" install -q --upgrade -r "${PROJECT_DIR}/requirements.txt"
    echo "  Pakete aktualisiert."
else
    echo "  Kein Virtual Environment gefunden – überspringe Paket-Update."
    echo "  Tipp: ./scripts/install.sh ausführen um das Projekt neu einzurichten."
fi

# -----------------------------------------------------------
# 4. Dienst neu starten
# -----------------------------------------------------------
echo ""
echo "[4/4] Dienst neu starten..."
if systemctl is-enabled "${SERVICE_NAME}" &>/dev/null; then
    sudo systemctl restart "${SERVICE_NAME}"
    sleep 2
    if systemctl is-active "${SERVICE_NAME}" &>/dev/null; then
        echo "  ✓ ${SERVICE_NAME} läuft."
    else
        echo "  ✗ ${SERVICE_NAME} nicht aktiv – Logs prüfen:"
        echo "    journalctl -u ${SERVICE_NAME} -n 20 --no-pager"
        exit 1
    fi
else
    echo "  Hinweis: systemd-Service nicht eingerichtet."
    echo "  Manuell starten: ./scripts/start.sh"
fi

# -----------------------------------------------------------
# Abschluss
# -----------------------------------------------------------
echo ""
echo "============================================================"
echo "  Update abgeschlossen."
echo ""
echo "  Weboberfläche:  http://$(hostname -I | awk '{print $1}'):8080"
echo "  Logs:           journalctl -u ${SERVICE_NAME} -f"
echo "============================================================"
