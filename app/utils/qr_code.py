import qrcode
from io import BytesIO
from flask import current_app, url_for
from PIL import Image
import os


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


def parse_qr_code(qr_data):
    """
    Parst QR-Code-Daten und gibt den Typ und die ID zurück.
    Unterstützt sowohl alte Text-Formate als auch neue URL-Formate.
    
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
    
    qr_data = qr_data.strip()
    
    if '/inventory/public/product/' in qr_data or '/inventory/public/product/' in qr_data.lower():
        import re
        match = re.search(r'/inventory/public/product/(\d+)', qr_data, re.IGNORECASE)
        if match:
            try:
                product_id = int(match.group(1))
                return ('product', product_id)
            except ValueError:
                return None
    
    qr_data_upper = qr_data.upper()
    
    if qr_data_upper.startswith('PROD-'):
        product_id = qr_data_upper.replace('PROD-', '')
        try:
            return ('product', int(product_id))
        except ValueError:
            return None
    elif qr_data_upper.startswith('SET-'):
        set_id = qr_data_upper.replace('SET-', '')
        try:
            return ('set', int(set_id))
        except ValueError:
            return None
    elif qr_data_upper.startswith('BORROW-'):
        transaction_number = qr_data_upper.replace('BORROW-', '')
        return ('borrow', transaction_number)
    
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


