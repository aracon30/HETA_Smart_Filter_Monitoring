#!/bin/bash
# ============================================================
# HETA Smart Filter Monitoring – Manueller Startskript
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="${PROJECT_DIR}/.venv"

if [ -d "${VENV_DIR}" ]; then
    PYTHON="${VENV_DIR}/bin/python3"
else
    PYTHON="python3"
    echo "Hinweis: Kein Virtual Environment gefunden. Verwende System-Python."
fi

echo "HETA Smart Filter Monitoring wird gestartet..."
echo "Projektverzeichnis: ${PROJECT_DIR}"
echo "Python: ${PYTHON}"
echo ""

cd "${PROJECT_DIR}"
exec "${PYTHON}" backend/app.py
