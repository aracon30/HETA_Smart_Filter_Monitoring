#!/usr/bin/env bash
# Erzeugt Schaltplan-PDF, Netzliste, Stückliste und Fertigungsdaten (Gerber/Bohrdaten)
# aus dem KiCad-Projekt. Benötigt kicad-cli (KiCad >= 7) und python3.
#
#   ./hardware/heta-hat/scripts/export.sh [Ausgabeverzeichnis]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRJ="${HERE}/.."
OUT="${1:-${PRJ}/fertigung}"
SCH="${PRJ}/heta-hat.kicad_sch"
PCB="${PRJ}/heta-hat.kicad_pcb"
mkdir -p "${OUT}/gerber"

kicad-cli version
kicad-cli sch export pdf -o "${OUT}/heta-hat-schaltplan.pdf" "${SCH}"
kicad-cli sch export netlist -o "${OUT}/heta-hat.net" "${SCH}"
python3 "${HERE}/bom.py" "${OUT}/heta-hat.net" "${OUT}/heta-hat-stueckliste.csv"

# ERC/DRC-Berichte (kicad-cli ab KiCad 8). Solange die Platine nicht geroutet ist,
# meldet der DRC offene Verbindungen – daher hier nur Bericht, kein Abbruch.
if kicad-cli sch erc --help >/dev/null 2>&1; then
    kicad-cli sch erc -o "${OUT}/erc.rpt" "${SCH}" || true
    kicad-cli pcb drc -o "${OUT}/drc.rpt" "${PCB}" || true
fi

kicad-cli pcb export gerbers -o "${OUT}/gerber/" \
    --layers "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts" "${PCB}"
kicad-cli pcb export drill -o "${OUT}/gerber/" "${PCB}"
kicad-cli pcb export pos -o "${OUT}/heta-hat-bestueckung.csv" --format csv --units mm "${PCB}"
echo "Fertig: ${OUT}"
