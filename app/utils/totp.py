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
import base64 as std_base64
import hashlib


def get_encryption_key():
    """Holt oder erstellt den Verschlüsselungsschlüssel für TOTP-Secrets."""
    # Versuche den Schlüssel aus der Umgebung zu holen.
    # Wir akzeptieren auch Werte mit Anführungszeichen aus .env-Dateien.
    env_key = os.environ.get('TOTP_ENCRYPTION_KEY')
    if env_key:
        normalized = env_key.strip().strip('"').strip("'")
        try:
            key_bytes = normalized.encode()
            # Validiert, dass es ein gültiger Fernet-Key ist
            Fernet(key_bytes)
            return key_bytes
        except Exception:
            try:
                current_app.logger.warning(
                    "TOTP_ENCRYPTION_KEY ist ungültig, verwende deterministischen Fallback-Key."
                )
            except Exception:
                pass

    # Stabiler Fallback: aus SECRET_KEY ableiten (statt Zufalls-Key pro Aufruf).
    # So bleiben gespeicherte Secrets zwischen Requests/Neustarts entschlüsselbar.
    secret_seed = os.environ.get('SECRET_KEY')
    if not secret_seed:
        try:
            secret_seed = current_app.config.get('SECRET_KEY')
        except Exception:
            secret_seed = None

    if not secret_seed:
        try:
            current_app.logger.error(
                "Weder TOTP_ENCRYPTION_KEY noch SECRET_KEY gesetzt; TOTP kann nicht sicher verwendet werden."
            )
        except Exception:
            pass
        raise RuntimeError("Missing TOTP_ENCRYPTION_KEY or SECRET_KEY for TOTP encryption.")

    digest = hashlib.sha256(secret_seed.encode('utf-8')).digest()
    return std_base64.urlsafe_b64encode(digest)


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


def get_totp_issuer_name() -> str:
    """Portalname für TOTP-Issuer (Authenticator-App-Anzeige)."""
    issuer = None
    try:
        from app.models.settings import SystemSettings
        row = SystemSettings.query.filter_by(key='portal_name').first()
        if row and row.value and str(row.value).strip():
            issuer = str(row.value).strip()
    except Exception:
        pass

    if not issuer:
        try:
            issuer = current_app.config.get('APP_NAME', 'Prismateams')
        except Exception:
            issuer = 'Prismateams'

    # Kompatibilität mit älteren Authenticator-Apps
    if len(issuer) > 32:
        issuer = issuer[:32]
    return issuer


def get_totp_uri(user_email, secret, issuer_name=None):
    """Erstellt eine TOTP-URI für QR-Code-Generierung."""
    if not issuer_name:
        issuer_name = get_totp_issuer_name()

    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(
        name=user_email,
        issuer_name=issuer_name
    )


def _overlay_logo_on_qr(qr_img, logo_path):
    """Zentriertes Logo auf dem QR-Code (nur visuelle Darstellung in der UI)."""
    try:
        from PIL import Image
    except ImportError:
        return qr_img

    if not logo_path or not os.path.isfile(logo_path):
        return qr_img

    try:
        logo = Image.open(logo_path).convert('RGBA')
        qr_width, qr_height = qr_img.size
        logo_size = int(min(qr_width, qr_height) * 0.22)
        logo = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)

        bg_size = logo_size + 8
        bg = Image.new('RGBA', (bg_size, bg_size), (255, 255, 255, 255))
        offset = (bg_size - logo_size) // 2
        bg.paste(logo, (offset, offset), logo)

        pos = ((qr_width - bg_size) // 2, (qr_height - bg_size) // 2)
        if qr_img.mode != 'RGBA':
            qr_img = qr_img.convert('RGBA')
        qr_img.paste(bg, pos, bg)
        return qr_img.convert('RGB')
    except Exception:
        return qr_img


def generate_qr_code(uri, logo_path=None):
    """Generiert einen QR-Code aus einer TOTP-URI."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H if logo_path else qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    if logo_path:
        img = _overlay_logo_on_qr(img, logo_path)

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
