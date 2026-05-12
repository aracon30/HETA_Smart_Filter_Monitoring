#!/bin/bash
# ============================================================
# HETA Smart Filter Monitoring – Manuelles Startskript
# Für Entwicklung und Fehlersuche (Alternative zu systemd).
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="${PROJECT_DIR}/.venv"
CONFIG="${PROJECT_DIR}/config/settings.json"

# Port aus settings.json lesen (Fallback: 8080)
PORT=$(python3 -c "
import json, sys
try:
    d = json.load(open('${CONFIG}'))
    print(d.get('webserver_port', 8080))
except Exception:
    print(8080)
" 2>/dev/null || echo 8080)

echo "============================================================"
echo "  HETA Smart Filter Monitoring – Manueller Start"
echo "  Projektverzeichnis: ${PROJECT_DIR}"
echo "  Port: ${PORT}"
echo "============================================================"

# Port-Konflikt prüfen
if ! python3 -c "
import socket, sys
try:
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    s.bind(('', ${PORT})); s.close(); sys.exit(0)
except OSError:
    sys.exit(1)
" 2>/dev/null; then
    echo ""
    echo "FEHLER: Port ${PORT} ist bereits belegt!"
    echo "  Prozess ermitteln:  ss -tlnp | grep :${PORT}"
    echo "  Prozess beenden:    sudo fuser -k ${PORT}/tcp"
    echo "  Dienst prüfen:      sudo systemctl status heta-monitor"
    echo ""
    exit 1
fi

# Python-Interpreter wählen
if [ -d "${VENV_DIR}" ]; then
    PYTHON="${VENV_DIR}/bin/python3"
else
    PYTHON="python3"
    echo "Hinweis: Kein Virtual Environment gefunden – verwende System-Python."
fi

echo "Python: ${PYTHON}"
echo ""

cd "${PROJECT_DIR}"
exec "${PYTHON}" backend/app.py
