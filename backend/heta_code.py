"""
HETA-Code-Modul – Validierung und Aktivierungscode-Berechnung.

Der Aktivierungsalgorithmus muss exakt mit dem separaten
HTML-PIN-Generator übereinstimmen.
"""

import logging
import re

logger = logging.getLogger(__name__)

HETA_PREFIX = "HETA-"
HETA_PATTERN = re.compile(r"^HETA-(\d+)$")


def calculate_activation_code(heta_number: str) -> str:
    """
    Berechnet den 6-stelligen Aktivierungscode aus der numerischen HETA-Nummer.

    Algorithmus identisch mit dem HTML-PIN-Generator:
      1. Gewichtete Quersumme modulo 1000000
      2. Multiplikation mit Primzahl + Offset modulo 1000000
      3. Ausgabe als 6-stellige Zeichenkette mit führenden Nullen
    """
    sum_value = 0
    for i, digit in enumerate(heta_number):
        sum_value = (sum_value + int(digit) * (i + 3) * 17) % 1_000_000
    pin = (sum_value * 7919 + 43127) % 1_000_000
    return str(pin).zfill(6)


def validate_heta_format(heta_code: str) -> tuple[bool, str]:
    """
    Prüft das Format eines HETA-Codes.

    Rückgabe:
        (gültig: bool, heta_nummer: str)  – heta_nummer ist leer bei ungültigem Format
    """
    if not heta_code:
        return False, ""
    match = HETA_PATTERN.match(heta_code.strip().upper())
    if not match:
        return False, ""
    return True, match.group(1)


def verify_activation(heta_code: str, entered_pin: str) -> dict:
    """
    Prüft ob der eingegebene PIN zum HETA-Code passt.

    Rückgabe:
        {
          'valid': bool,
          'heta_code': str,
          'heta_number': str,
          'expected_pin': str,
          'message': str
        }
    """
    valid_format, heta_number = validate_heta_format(heta_code)
    if not valid_format:
        return {
            "valid": False,
            "heta_code": heta_code,
            "heta_number": "",
            "expected_pin": "",
            "message": "Ungültiges HETA-Code-Format. Erwartet: HETA-XXXXX",
        }

    expected = calculate_activation_code(heta_number)
    entered_clean = entered_pin.strip().zfill(6)

    if entered_clean == expected:
        logger.info("HETA-Code %s erfolgreich aktiviert.", heta_code)
        return {
            "valid": True,
            "heta_code": heta_code.strip().upper(),
            "heta_number": heta_number,
            "expected_pin": expected,
            "message": "Aktivierung erfolgreich.",
        }
    else:
        logger.warning("Falscher PIN für HETA-Code %s.", heta_code)
        return {
            "valid": False,
            "heta_code": heta_code.strip().upper(),
            "heta_number": heta_number,
            "expected_pin": "",  # Aus Sicherheitsgründen nicht zurückgeben
            "message": "Ungültiger Aktivierungscode.",
        }


def get_demo_info(heta_code: str) -> dict:
    """
    Gibt Demo-Informationen inkl. Aktivierungscode zurück (nur für Testzwecke).
    Im Produktionsbetrieb sollte dieser Endpunkt deaktiviert sein.
    """
    valid_format, heta_number = validate_heta_format(heta_code)
    if not valid_format:
        return {"valid": False, "message": "Ungültiges Format"}
    code = calculate_activation_code(heta_number)
    return {
        "valid": True,
        "heta_code": heta_code.strip().upper(),
        "heta_number": heta_number,
        "activation_code": code,
        "message": "Demo-Modus: Aktivierungscode wird angezeigt.",
    }
