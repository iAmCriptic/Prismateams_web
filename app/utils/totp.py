"""
TOTP (Time-based One-Time Password) Utility für 2FA.
"""
import pyotp
import qrcode
import io
import base64
from flask import current_app
from cryptography.fernet import Fernet
import os


def get_encryption_key():
    """Holt oder erstellt den Verschlüsselungsschlüssel für TOTP-Secrets."""
    # Versuche den Schlüssel aus der Umgebung zu holen
    key = os.environ.get('TOTP_ENCRYPTION_KEY')
    
    if not key:
        # Falls kein Schlüssel gesetzt ist, generiere einen (nur für Development)
        # In Production sollte dieser in der .env gesetzt werden
        key = Fernet.generate_key().decode()
        try:
            from flask import current_app
            current_app.logger.warning("TOTP_ENCRYPTION_KEY nicht gesetzt! Verwende temporären Schlüssel.")
        except:
            pass  # current_app nicht verfügbar
    
    # Stelle sicher, dass der Schlüssel die richtige Länge hat
    if isinstance(key, str):
        key = key.encode()
    
    # Falls der Schlüssel nicht 32 Bytes hat, generiere einen neuen
    if len(key) != 44:  # Base64-encoded Fernet key ist 44 Zeichen
        key = Fernet.generate_key()
        try:
            from flask import current_app
            current_app.logger.warning("TOTP_ENCRYPTION_KEY hat falsche Länge! Verwende neuen Schlüssel.")
        except:
            pass  # current_app nicht verfügbar
    
    return key


def encrypt_secret(secret):
    """Verschlüsselt ein TOTP-Secret für die Speicherung in der Datenbank."""
    try:
        key = get_encryption_key()
        f = Fernet(key)
        encrypted = f.encrypt(secret.encode())
        return encrypted.decode()
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.error(f"Fehler beim Verschlüsseln des TOTP-Secrets: {e}")
        except:
            pass
        raise


def decrypt_secret(encrypted_secret):
    """Entschlüsselt ein TOTP-Secret aus der Datenbank."""
    if not encrypted_secret:
        return None
    
    try:
        key = get_encryption_key()
        f = Fernet(key)
        decrypted = f.decrypt(encrypted_secret.encode())
        return decrypted.decode()
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.error(f"Fehler beim Entschlüsseln des TOTP-Secrets: {e}")
        except:
            pass
        return None


def generate_totp_secret():
    """Generiert ein neues TOTP-Secret."""
    return pyotp.random_base32()


def get_totp_uri(user_email, secret, issuer_name=None):
    """Erstellt eine TOTP-URI für QR-Code-Generierung."""
    if not issuer_name:
        try:
            from flask import current_app
            issuer_name = current_app.config.get('APP_NAME', 'Prismateams')
        except:
            issuer_name = 'Prismateams'
    
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(
        name=user_email,
        issuer_name=issuer_name
    )


def generate_qr_code(uri):
    """Generiert einen QR-Code aus einer TOTP-URI."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Konvertiere zu Base64 für HTML-Einbettung
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    img_base64 = base64.b64encode(buffer.getvalue()).decode()
    
    return f"data:image/png;base64,{img_base64}"


def verify_totp(secret, token):
    """Verifiziert einen TOTP-Token gegen ein Secret."""
    if not secret or not token:
        return False
    
    try:
        # Entschlüssele das Secret falls nötig
        if len(secret) > 32:  # Verschlüsseltes Secret ist länger
            secret = decrypt_secret(secret)
            if not secret:
                return False
        
        totp = pyotp.TOTP(secret)
        return totp.verify(token, valid_window=1)  # Erlaubt 1 Zeitfenster Toleranz
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.error(f"Fehler bei TOTP-Verifizierung: {e}")
        except:
            pass
        return False
