"""Farbzuordnungs-Logik für Längen in QR-Code-Labels."""

import colorsys
from typing import Dict, Optional
from app import db
from app.models.inventory import Product, LengthColorMapping
from app.utils.lengths import parse_length_to_meters


def generate_color_for_index(index: int, total: int) -> str:
    """
    Generiert eine eindeutige Farbe basierend auf dem Index.
    Verwendet HSL-Farbraum für maximale Unterscheidbarkeit.
    
    Args:
        index: Index der Farbe (0-basiert)
        total: Gesamtanzahl der Farben
    
    Returns:
        Hex-Farbcode (z.B. "#FF0000")
    """
    if total == 0:
        return "#000000"
    
    # Verwende HSL-Farbraum für gleichmäßige Verteilung
    # Hue: 0-360 Grad (Farbton)
    # Saturation: 70-100% (Sättigung)
    # Lightness: 40-60% (Helligkeit)
    
    hue = (index * 360.0 / total) % 360
    saturation = 70 + (index % 3) * 10  # 70, 80, 90%
    lightness = 45 + (index % 2) * 10  # 45, 55%
    
    # Konvertiere HSL zu RGB
    rgb = colorsys.hls_to_rgb(hue / 360.0, lightness / 100.0, saturation / 100.0)
    
    # Konvertiere zu Hex
    r, g, b = [int(x * 255) for x in rgb]
    return f"#{r:02X}{g:02X}{b:02X}"


def get_or_create_color_mapping(length_meters: float) -> str:
    """
    Holt die Farbe für eine Länge oder erstellt eine neue Zuordnung.
    
    Args:
        length_meters: Länge in Metern
    
    Returns:
        Hex-Farbcode
    """
    if length_meters is None:
        return "#000000"
    
    # Runde auf 2 Dezimalstellen für Konsistenz
    length_meters = round(float(length_meters), 2)
    
    # Prüfe ob Zuordnung bereits existiert
    mapping = LengthColorMapping.query.filter_by(length_meters=length_meters).first()
    
    if mapping:
        return mapping.color_hex
    
    # Erstelle neue Zuordnung
    # Hole alle vorhandenen Längen für Farbverteilung
    all_lengths = db.session.query(Product.length).distinct().all()
    all_lengths_meters = []
    for length_tuple in all_lengths:
        if length_tuple[0]:
            meters = parse_length_to_meters(length_tuple[0])
            if meters is not None:
                all_lengths_meters.append(round(meters, 2))
    
    # Entferne Duplikate und sortiere
    all_lengths_meters = sorted(set(all_lengths_meters))
    
    # Finde Index der aktuellen Länge
    try:
        index = all_lengths_meters.index(length_meters)
    except ValueError:
        # Falls Länge nicht in Liste, füge hinzu und sortiere neu
        all_lengths_meters.append(length_meters)
        all_lengths_meters = sorted(all_lengths_meters)
        index = all_lengths_meters.index(length_meters)
    
    # Generiere Farbe basierend auf Index
    color = generate_color_for_index(index, len(all_lengths_meters))
    
    # Speichere Zuordnung
    mapping = LengthColorMapping(
        length_meters=length_meters,
        color_hex=color
    )
    db.session.add(mapping)
    db.session.commit()
    
    return color


def get_color_for_length(length: Optional[str]) -> Optional[str]:
    """
    Holt die Farbe für eine Längenangabe (String).
    
    Args:
        length: Längenangabe (z.B. "5m", "1.5", "120cm")
    
    Returns:
        Hex-Farbcode oder None
    """
    if not length:
        return None
    
    meters = parse_length_to_meters(length)
    if meters is None:
        return None
    
    return get_or_create_color_mapping(meters)


def get_all_color_mappings() -> Dict[float, str]:
    """
    Holt alle Längen-Farb-Zuordnungen.
    
    Returns:
        Dictionary mit length_meters -> color_hex
    """
    mappings = LengthColorMapping.query.order_by(LengthColorMapping.length_meters).all()
    return {mapping.length_meters: mapping.color_hex for mapping in mappings}


def initialize_color_mappings():
    """
    Initialisiert Farbzuordnungen für alle vorhandenen Längen in der Datenbank.
    Wird beim ersten Aufruf der QR-Code-Generierung ausgeführt.
    """
    # Hole alle eindeutigen Längen aus der Datenbank
    all_lengths = db.session.query(Product.length).distinct().all()
    all_lengths_meters = []
    
    for length_tuple in all_lengths:
        if length_tuple[0]:
            meters = parse_length_to_meters(length_tuple[0])
            if meters is not None:
                all_lengths_meters.append(round(meters, 2))
    
    # Entferne Duplikate und sortiere
    all_lengths_meters = sorted(set(all_lengths_meters))
    
    # Erstelle Zuordnungen für alle Längen
    for index, length_meters in enumerate(all_lengths_meters):
        # Prüfe ob bereits existiert
        existing = LengthColorMapping.query.filter_by(length_meters=length_meters).first()
        if not existing:
            color = generate_color_for_index(index, len(all_lengths_meters))
            mapping = LengthColorMapping(
                length_meters=length_meters,
                color_hex=color
            )
            db.session.add(mapping)
    
    db.session.commit()

