#!/usr/bin/env python3
"""
Erstellt ein einfaches Logo für das Team Portal
"""
from PIL import Image, ImageDraw, ImageFont
import os

def create_logo():
    # Logo-Dimensionen
    width, height = 64, 64
    
    # Neues Bild erstellen
    img = Image.new('RGBA', (width, height), (13, 110, 253, 255))  # Bootstrap Primary Blue
    draw = ImageDraw.Draw(img)
    
    # Abgerundete Ecken simulieren
    # Hintergrund
    draw.rectangle([0, 0, width, height], fill=(13, 110, 253, 255))
    
    # Team-Icon zeichnen
    # Personen (Kreise für Köpfe)
    draw.ellipse([12, 16, 28, 32], fill=(255, 255, 255, 255))  # Person 1 Kopf
    draw.ellipse([36, 16, 52, 32], fill=(255, 255, 255, 255))  # Person 2 Kopf
    
    # Körper (abgerundete Rechtecke)
    draw.rectangle([8, 32, 24, 48], fill=(255, 255, 255, 255))  # Person 1 Körper
    draw.rectangle([40, 32, 56, 48], fill=(255, 255, 255, 255))  # Person 2 Körper
    
    # Verbindungslinie
    draw.line([20, 32, 44, 32], fill=(255, 255, 255, 255), width=3)
    
    # Text hinzufügen (falls Font verfügbar)
    try:
        font = ImageFont.truetype("arial.ttf", 8)
    except:
        font = ImageFont.load_default()
    
    # "PORTAL" Text
    text = "PORTAL"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_x = (width - text_width) // 2
    draw.text((text_x, 50), text, fill=(255, 255, 255, 255), font=font)
    
    return img

if __name__ == "__main__":
    # Logo erstellen
    logo = create_logo()
    
    # Speichern
    logo_path = "app/static/img/logo.png"
    logo.save(logo_path, "PNG")
    
    print(f"Logo erstellt: {logo_path}")
    print(f"Größe: {logo.size}")
