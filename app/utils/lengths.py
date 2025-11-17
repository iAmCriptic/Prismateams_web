"""Hilfsfunktionen zur Verarbeitung von Längenangaben im Inventarsystem."""

from __future__ import annotations

import re
from typing import Optional, Tuple


_LENGTH_PATTERN = re.compile(
    r"""
    ^\s*
    (?P<number>[-+]?\d+(?:[.,]\d+)?)
    \s*
    (?P<unit>m|meter|metern|meters|cm|millimeter|mm|kilometer|km)?  # optionale Einheit
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def parse_length_to_meters(raw_value: Optional[str]) -> Optional[float]:
    """Parst eine Längenangabe und gibt die Länge in Metern zurück.

    Unterstützte Eingaben:
        - "5", "5.2", "5,2"  -> Meter (Standard)
        - "5m", "5 meter"
        - "120cm", "120 cm"
        - "1200mm"
        - "1.2km"

    Gibt None zurück, wenn der Wert nicht interpretiert werden kann.
    """
    if raw_value is None:
        return None

    if isinstance(raw_value, (int, float)):
        return float(raw_value)

    text = str(raw_value).strip()
    if not text:
        return None

    match = _LENGTH_PATTERN.match(text.lower())
    if not match:
        return None

    number_str = match.group("number").replace(",", ".")
    try:
        value = float(number_str)
    except ValueError:
        return None

    unit = match.group("unit")
    if not unit or unit in {"m", "meter", "metern", "meters"}:
        multiplier = 1.0
    elif unit == "cm":
        multiplier = 0.01
    elif unit in {"mm", "millimeter"}:
        multiplier = 0.001
    elif unit in {"km", "kilometer"}:
        multiplier = 1000.0
    else:
        # Unbekannte Einheit
        return None

    return round(value * multiplier, 6)


def format_length_from_meters(
    meters: Optional[float], decimal_places: int = 2
) -> Optional[str]:
    """Formatiert eine Länge in Meter als string wie '5,25 m'."""
    if meters is None:
        return None

    try:
        value = float(meters)
    except (TypeError, ValueError):
        return None

    format_str = f"{{:.{decimal_places}f}}"
    formatted = format_str.format(value)
    # Nachkommastellen säubern (entferne trailing zeros und Punkt)
    formatted = formatted.rstrip("0").rstrip(".")
    if formatted == "":
        formatted = "0"
    # Für deutschsprachige Darstellung Komma verwenden
    formatted = formatted.replace(".", ",")
    return f"{formatted} m"


def normalize_length_input(raw_value: Optional[str]) -> Tuple[Optional[str], Optional[float]]:
    """Gibt (formatierte Länge, Meterwert) zurück oder (None, None) bei ungültiger Eingabe."""
    if raw_value is None:
        return (None, None)

    if isinstance(raw_value, (int, float)):
        meters = parse_length_to_meters(str(raw_value))
    else:
        meters = parse_length_to_meters(raw_value)

    if meters is None:
        return (None, None)

    return (format_length_from_meters(meters), meters)


__all__ = [
    "format_length_from_meters",
    "normalize_length_input",
    "parse_length_to_meters",
]













