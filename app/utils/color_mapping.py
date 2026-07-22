"""Farbzuordnungs-Logik für Längen in QR-Code-Labels.

Nahe Längen bekommen bewusst weit auseinanderliegende Farbtöne (Hue),
damit z.B. 1 m und 1,5 m gut unterscheidbar bleiben.
"""

import colorsys
from typing import Dict, List, Optional

from app import db
from app.models.inventory import Product, LengthColorMapping
from app.utils.lengths import parse_length_to_meters


GOLDEN_ANGLE = 137.50776405003785  # Grad


def _collect_sorted_lengths(extra: Optional[float] = None) -> List[float]:
    all_lengths_meters = []
    for length_tuple in db.session.query(Product.length).distinct().all():
        if length_tuple[0]:
            meters = parse_length_to_meters(length_tuple[0])
            if meters is not None:
                all_lengths_meters.append(round(meters, 2))
    for mapping in LengthColorMapping.query.all():
        all_lengths_meters.append(round(float(mapping.length_meters), 2))
    if extra is not None:
        all_lengths_meters.append(round(float(extra), 2))
    return sorted(set(all_lengths_meters))


def generate_color_for_slot(slot: int, total: int) -> str:
    """Farbe für Slot in einer maximierten Hue-Verteilung."""
    if total <= 0:
        return "#000000"
    # Golden-angle Walk: benachbarte Slots liegen im Farbkreis weit auseinander
    hue = (slot * GOLDEN_ANGLE) % 360.0
    saturation = 0.78 + (slot % 3) * 0.06  # 0.78–0.90
    lightness = 0.42 + (slot % 2) * 0.08   # 0.42 / 0.50
    r, g, b = colorsys.hls_to_rgb(hue / 360.0, lightness, saturation)
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


def assign_colors_for_sorted_lengths(sorted_lengths: List[float]) -> Dict[float, str]:
    """
    Ordnet sortierten Längen Farben so zu, dass benachbarte Längen
    große Hue-Abstände bekommen (golden-angle Indexierung).
    """
    n = len(sorted_lengths)
    if n == 0:
        return {}
    # Permutation: Index i in sortierter Liste → Slot = bit-reversal-ähnlicher golden Schritt
    # Einfach: Slot = i (golden angle auf Slot) reicht, weil golden angle benachbarte Slots trennt.
    # Zusätzlich: gerade/ungerade Indexe in zwei Halbkreise spiegeln für Extra-Abstand.
    result = {}
    for i, length in enumerate(sorted_lengths):
        slot = (i * 2) % n if n > 1 else 0
        if i % 2 == 1 and n > 1:
            slot = (slot + n // 2) % n
        result[length] = generate_color_for_slot(slot if n > 1 else i, max(n, 1))
    return result


def generate_color_for_index(index: int, total: int) -> str:
    """Compat-Alias."""
    return generate_color_for_slot(index, total)


def reassign_all_color_mappings() -> Dict[float, str]:
    """Berechnet alle Farben neu und speichert sie (benachbarte Längen = großer Hue-Abstand)."""
    sorted_lengths = _collect_sorted_lengths()
    color_map = assign_colors_for_sorted_lengths(sorted_lengths)
    from sqlalchemy.exc import IntegrityError

    try:
        with db.session.no_autoflush:
            for length_meters, color in color_map.items():
                existing = LengthColorMapping.query.filter_by(length_meters=length_meters).first()
                if existing:
                    existing.color_hex = color
                else:
                    db.session.add(LengthColorMapping(length_meters=length_meters, color_hex=color))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        for length_meters, color in color_map.items():
            existing = LengthColorMapping.query.filter_by(length_meters=length_meters).first()
            if existing:
                existing.color_hex = color
            else:
                try:
                    db.session.add(LengthColorMapping(length_meters=length_meters, color_hex=color))
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
    return color_map


def get_or_create_color_mapping(length_meters: float) -> str:
    """Holt die Farbe für eine Länge oder erstellt/aktualisiert die Zuordnung."""
    if length_meters is None:
        return "#000000"

    length_meters = round(float(length_meters), 2)
    mapping = LengthColorMapping.query.filter_by(length_meters=length_meters).first()
    if mapping:
        return mapping.color_hex

    # Neue Länge: alle Farben neu verteilen, damit Abstände stimmen
    color_map = reassign_all_color_mappings()
    return color_map.get(length_meters, "#000000")


def get_color_for_length(length: Optional[str]) -> Optional[str]:
    if not length:
        return None
    meters = parse_length_to_meters(length)
    if meters is None:
        return None
    return get_or_create_color_mapping(meters)


def get_all_color_mappings() -> Dict[float, str]:
    mappings = LengthColorMapping.query.order_by(LengthColorMapping.length_meters).all()
    return {mapping.length_meters: mapping.color_hex for mapping in mappings}


def initialize_color_mappings():
    """Initialisiert bzw. aktualisiert Farbzuordnungen für alle Längen."""
    from flask import current_app
    try:
        reassign_all_color_mappings()
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning(f"Fehler beim Initialisieren der Farbzuordnungen: {e}")
        raise
