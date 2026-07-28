import qrcode
from io import BytesIO
from flask import current_app, url_for
from PIL import Image, ImageDraw
import os
import re
from urllib.parse import unquote


def generate_qr_code(data, box_size=10, border=4):
    """
    Generiert einen QR-Code als PIL Image.
    
    Args:
        data: Die zu codierenden Daten (String)
        box_size: Größe der Boxen im QR-Code (Standard: 10)
        border: Breite des Rahmens (Standard: 4)
    
    Returns:
        PIL Image Objekt
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    return img


def generate_qr_code_bytes(data, box_size=10, border=4, format='PNG'):
    """
    Generiert einen QR-Code als Bytes (für Speicherung oder HTTP-Response).
    
    Args:
        data: Die zu codierenden Daten (String)
        box_size: Größe der Boxen im QR-Code
        border: Breite des Rahmens
        format: Bildformat ('PNG' oder 'JPEG')
    
    Returns:
        Bytes-Objekt mit dem QR-Code-Bild
    """
    img = generate_qr_code(data, box_size, border)
    
    img_bytes = BytesIO()
    img.save(img_bytes, format=format)
    img_bytes.seek(0)
    
    return img_bytes.getvalue()


def _make_circular_logo(logo_img, size, padding_ratio=0.12):
    """
    Skaliert ein Logo in einen weißen Kreis (Telegram-Stil) für die QR-Mitte.
    size: Durchmesser des fertigen Kreises in Pixeln.
    """
    logo = logo_img.convert('RGBA')
    # Weißer Kreis als Träger
    circle = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(circle)
    draw.ellipse((0, 0, size - 1, size - 1), fill=(255, 255, 255, 255))

    inner = max(int(size * (1 - 2 * padding_ratio)), 1)
    # proportional skalieren, in innere Fläche einpassen
    lw, lh = logo.size
    scale = min(inner / max(lw, 1), inner / max(lh, 1))
    new_w = max(int(lw * scale), 1)
    new_h = max(int(lh * scale), 1)
    logo = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)

    ox = (size - new_w) // 2
    oy = (size - new_h) // 2
    circle.paste(logo, (ox, oy), logo if logo.mode == 'RGBA' else None)
    return circle


def generate_qr_code_with_logo(data, logo_path, box_size=10, border=2, logo_ratio=0.22):
    """
    QR-Code mit Logo in der Mitte (hohe Fehlerkorrektur H).
    logo_ratio: Anteil der QR-Kantenlänge für den Logo-Kreis (~0.18–0.24).
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')

    if not logo_path or not os.path.exists(logo_path):
        return img.convert('RGB')

    try:
        logo_src = Image.open(logo_path)
    except Exception:
        return img.convert('RGB')

    qr_w, qr_h = img.size
    logo_diam = max(int(min(qr_w, qr_h) * logo_ratio), 8)
    badge = _make_circular_logo(logo_src, logo_diam)
    pos = ((qr_w - logo_diam) // 2, (qr_h - logo_diam) // 2)
    img.paste(badge, pos, badge)
    return img.convert('RGB')


def generate_qr_code_with_logo_bytes(data, logo_path, box_size=10, border=2,
                                     logo_ratio=0.22, format='PNG'):
    """QR mit Logo als Bytes (PNG/JPEG)."""
    img = generate_qr_code_with_logo(
        data, logo_path, box_size=box_size, border=border, logo_ratio=logo_ratio
    )
    img_bytes = BytesIO()
    img.save(img_bytes, format=format)
    img_bytes.seek(0)
    return img_bytes.getvalue()


def generate_qr_code_inverted(data, box_size=10, border=4):
    """
    Generiert einen invertierten QR-Code als PIL Image (weißer QR-Code auf schwarzem Untergrund).
    
    Args:
        data: Die zu codierenden Daten (String)
        box_size: Größe der Boxen im QR-Code (Standard: 10)
        border: Breite des Rahmens (Standard: 4)
    
    Returns:
        PIL Image Objekt
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="white", back_color="black")
    return img


def generate_qr_code_inverted_bytes(data, box_size=10, border=4, format='PNG'):
    """
    Generiert einen invertierten QR-Code als Bytes (weißer QR-Code auf schwarzem Untergrund).
    
    Args:
        data: Die zu codierenden Daten (String)
        box_size: Größe der Boxen im QR-Code
        border: Breite des Rahmens
        format: Bildformat ('PNG' oder 'JPEG')
    
    Returns:
        Bytes-Objekt mit dem QR-Code-Bild
    """
    img = generate_qr_code_inverted(data, box_size, border)
    
    img_bytes = BytesIO()
    img.save(img_bytes, format=format)
    img_bytes.seek(0)
    
    return img_bytes.getvalue()


def generate_product_qr_code(product_id):
    """
    Generiert einen QR-Code für ein Produkt.
    Format: Vollständige URL zu /inventory/public/product/{product_id}
    
    Args:
        product_id: Die Produkt-ID
    
    Returns:
        String mit der vollständigen URL für den QR-Code
    """
    try:
        from flask import url_for
        qr_data = url_for('inventory.public_product', product_id=product_id, _external=True)
    except RuntimeError:
        qr_data = f"/inventory/public/product/{product_id}"
    
    return qr_data


def generate_borrow_qr_code(transaction_number):
    """
    Generiert einen QR-Code für einen Ausleihvorgang.
    Format: BORROW-{transaction_number}
    
    Args:
        transaction_number: Die Ausleihvorgangsnummer
    
    Returns:
        String mit dem QR-Code-Daten
    """
    qr_data = f"BORROW-{transaction_number}"
    return qr_data


def generate_set_qr_code(set_id):
    """
    Generiert einen QR-Code für ein Produktset.
    Format: SET-{set_id}
    
    Args:
        set_id: Die Set-ID
    
    Returns:
        String mit dem QR-Code-Daten
    """
    qr_data = f"SET-{set_id}"
    return qr_data


def _normalize_qr_payload(qr_data):
    """Bereinigt Rohdaten inkl. typischer Handscanner-/Tastatur-Artefakte."""
    if qr_data is None:
        return ''
    text = unquote(str(qr_data))
    text = re.sub(r'[\x00-\x1F\x7F]+', '', text).strip()
    if not text:
        return ''

    # Handscanner tippt oft Sonderzeichen falsch (Layout US vs. DE):
    # "http://host:5000/inventory/..." -> "httpÖ--hostÖ5000-inventorz-..."
    repaired = text
    repaired = repaired.replace('Ö--', '://').replace('ö--', '://')
    repaired = repaired.replace('Ö', ':').replace('ö', ':')
    # Y/Z-Layout-Vertauschung in bekannten Pfadsegmenten
    repaired = re.sub(r'inventorz', 'inventory', repaired, flags=re.IGNORECASE)
    repaired = re.sub(r'inventor[yz]', 'inventory', repaired, flags=re.IGNORECASE)
    return repaired


def parse_qr_code(qr_data):
    """
    Parst QR-Code-Daten und gibt den Typ und die ID zurück.
    Unterstützt Text-Formate, saubere URLs und mangled Handscanner-URLs.
    
    Args:
        qr_data: Die QR-Code-Daten (z.B. "PROD-123", "SET-456", "BORROW-ABC123" 
                 oder URLs wie "/inventory/public/product/123")
    
    Returns:
        Tuple (type, identifier) oder None falls ungültig
        type: 'product', 'set' oder 'borrow'
        identifier: Produkt-ID, Set-ID oder Transaktionsnummer
    """
    if not qr_data:
        return None

    normalized = _normalize_qr_payload(qr_data)
    if not normalized:
        return None

    # Saubere URL-QR (Smartphone-Scan / Deep-Link), auch mehrfach hintereinander.
    product_url_match = re.search(
        r'[/\\]inventory[/\\]public[/\\]product[/\\](\d+)',
        normalized,
        re.IGNORECASE,
    )
    if product_url_match:
        try:
            return ('product', int(product_url_match.group(1)))
        except ValueError:
            return None

    # Handscanner: Separatoren als "-" und ggf. "inventorz"
    # z.B. httpÖ--127.0.0.1Ö5000-inventorz-public-product-1
    mangled_url_match = re.search(
        r'inventor[yz]?[-_/\\]+public[-_/\\]+product[-_/\\]+(\d+)',
        normalized,
        re.IGNORECASE,
    )
    if mangled_url_match:
        try:
            return ('product', int(mangled_url_match.group(1)))
        except ValueError:
            return None

    # Fallback: URL-artig + "...product-<id>"
    if re.search(r'(?:https?|inventor|localhost|127\.0\.0\.1|public[-_/\\]+product)', normalized, re.IGNORECASE):
        product_tail = re.search(r'product[-_/\\]+(\d+)', normalized, re.IGNORECASE)
        if product_tail:
            try:
                return ('product', int(product_tail.group(1)))
            except ValueError:
                return None

    upper = normalized.upper()

    product_match = re.search(r'(?:^|[^A-Z0-9])PROD[\s:_-]*([0-9]+)(?:[^0-9]|$)', upper)
    if product_match:
        try:
            return ('product', int(product_match.group(1)))
        except ValueError:
            return None

    set_match = re.search(r'(?:^|[^A-Z0-9])SET[\s:_-]*([0-9]+)(?:[^0-9]|$)', upper)
    if set_match:
        try:
            return ('set', int(set_match.group(1)))
        except ValueError:
            return None

    borrow_match = re.search(r'(?:^|[^A-Z0-9])BORROW[\s:_-]*([A-Z0-9-]+)', upper)
    if borrow_match:
        return ('borrow', borrow_match.group(1).strip('-'))

    return None


def save_qr_code_image(qr_data, save_path):
    """
    Speichert einen QR-Code als Bilddatei.
    
    Args:
        qr_data: Die zu codierenden Daten
        save_path: Vollständiger Pfad zum Speichern des Bildes
    
    Returns:
        Boolean: True wenn erfolgreich, False bei Fehler
    """
    try:
        img = generate_qr_code(qr_data)
        
        directory = os.path.dirname(save_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        
        img.save(save_path)
        return True
    except Exception as e:
        current_app.logger.error(f"Fehler beim Speichern des QR-Codes: {e}")
        return False


