#!/bin/bash
# =============================================================
# deploy.sh – Schnelles Update auf den Raspberry Pi via SSH
#
# Verwendung:
#   ./scripts/deploy.sh                      # Standard: pi@raspberrypi.local
#   ./scripts/deploy.sh pi@192.168.1.42      # Explizite IP
#   ./scripts/deploy.sh pi@192.168.1.42 /opt/heta  # Anderer Zielpfad
#
# Voraussetzung:
#   - SSH-Zugriff zum Pi (Passwort oder SSH-Key)
#   - Git auf dem Pi installiert und Repository geklont
#   - systemd-Service "heta-monitor" eingerichtet (install.sh)
# =============================================================

set -e

SSH_HOST="${1:-pi@raspberrypi.local}"
REMOTE_PATH="${2:-/home/pi/HETA_Smart_Filter_Monitoring}"

echo ""
echo "┌─────────────────────────────────────────┐"
echo "│  HETA Smart Filter – Deploy via SSH     │"
echo "└─────────────────────────────────────────┘"
echo "  Ziel:  $SSH_HOST"
echo "  Pfad:  $REMOTE_PATH"
echo ""

ssh "$SSH_HOST" bash <<EOF
  set -e
  cd "$REMOTE_PATH"

  echo "── git pull ──"
  git pull --ff-only

  echo ""
  echo "── Dienst neu starten ──"
  sudo systemctl restart heta-monitor

  echo ""
  echo "── Status ──"
  sudo systemctl is-active heta-monitor && echo "✓ heta-monitor läuft." || echo "✗ Dienst nicht aktiv!"
EOF

echo ""
echo "✓ Deployment abgeschlossen."
echo "  Dashboard: http://${SSH_HOST#*@}:8080"
