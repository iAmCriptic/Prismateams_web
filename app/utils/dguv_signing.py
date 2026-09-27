"""DGUV V3 organisational PKCS#12 signing (self-signed FES/EES)."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from app.utils.encryption import read_encryption_key

logger = logging.getLogger(__name__)

PFX_FILENAME = 'dguv_org.pfx'
SETTING_PASSPHRASE = 'dguv_signing_pfx_passphrase'
SETTING_CN = 'dguv_signing_cert_cn'
SETTING_NOT_AFTER = 'dguv_signing_cert_not_after'
SETTING_SERIAL = 'dguv_signing_cert_serial'
DEFAULT_R_PE_LIMIT = 0.3
DEFAULT_R_ISO_LIMIT = 1.0


def _instance_certs_dir() -> str:
    from flask import current_app

    root = current_app.instance_path
    path = os.path.join(root, 'certs')
    os.makedirs(path, exist_ok=True)
    return path


def pfx_path() -> str:
    return os.path.join(_instance_certs_dir(), PFX_FILENAME)


def _fernet():
    from cryptography.fernet import Fernet
    import base64
    import hashlib

    key = read_encryption_key('DGUV_SIGNING_KEY', 'TOTP_ENCRYPTION_KEY', 'SECRET_KEY')
    if not key:
        raise RuntimeError('No encryption key for DGUV signing passphrase')
    try:
        Fernet(key)
        return Fernet(key)
    except Exception:
        digest = hashlib.sha256(key).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_passphrase(plain: str) -> str:
    return _fernet().encrypt(plain.encode('utf-8')).decode('utf-8')


def _decrypt_passphrase(token: str) -> str:
    return _fernet().decrypt(token.encode('utf-8')).decode('utf-8')


def _upsert_setting(key: str, value: str, description: str) -> None:
    from app import db
    from app.models.settings import SystemSettings

    row = SystemSettings.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(SystemSettings(key=key, value=value, description=description))


def _get_setting(key: str) -> Optional[str]:
    from app.models.settings import SystemSettings

    row = SystemSettings.query.filter_by(key=key).first()
    return row.value if row and row.value else None


def _portal_org_name() -> str:
    from app.models.settings import SystemSettings
    from flask import current_app

    row = SystemSettings.query.filter_by(key='portal_name').first()
    if row and row.value and row.value.strip():
        return row.value.strip()[:64]
    return (current_app.config.get('APP_NAME') or 'Prismateams')[:64]


def has_signing_certificate() -> bool:
    return os.path.isfile(pfx_path()) and bool(_get_setting(SETTING_PASSPHRASE))


def certificate_status() -> dict[str, Any]:
    """Status dict for admin UI."""
    path = pfx_path()
    exists = os.path.isfile(path)
    cn = _get_setting(SETTING_CN)
    not_after_s = _get_setting(SETTING_NOT_AFTER)
    serial = _get_setting(SETTING_SERIAL)
    valid = False
    expired = False
    not_after = None
    if exists and not_after_s:
        try:
            not_after = datetime.fromisoformat(not_after_s)
            if not_after.tzinfo is None:
                not_after = not_after.replace(tzinfo=timezone.utc)
            valid = not_after > datetime.now(timezone.utc)
            expired = not valid
        except ValueError:
            pass
    return {
        'exists': exists,
        'configured': exists and bool(_get_setting(SETTING_PASSPHRASE)),
        'cn': cn,
        'serial': serial,
        'not_after': not_after_s,
        'valid': valid,
        'expired': expired,
    }


def generate_org_certificate(*, validity_days: int = 3650, cn: Optional[str] = None) -> dict[str, Any]:
    """Create self-signed RSA-2048 cert + PKCS#12, store passphrase encrypted."""
    from app import db

    org = (cn or _portal_org_name()).strip() or 'Prismateams'
    passphrase = secrets.token_urlsafe(24)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, org),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
    ])
    now = datetime.now(timezone.utc)
    not_after = now + timedelta(days=int(validity_days))
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    pfx_bytes = pkcs12.serialize_key_and_certificates(
        name=b'dguv-org',
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode('utf-8')),
    )
    path = pfx_path()
    with open(path, 'wb') as fh:
        fh.write(pfx_bytes)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    serial_hex = format(cert.serial_number, 'x')
    _upsert_setting(SETTING_PASSPHRASE, _encrypt_passphrase(passphrase), 'Encrypted DGUV PKCS#12 passphrase')
    _upsert_setting(SETTING_CN, org, 'DGUV signing certificate CN')
    _upsert_setting(SETTING_NOT_AFTER, not_after.isoformat(), 'DGUV signing certificate expiry')
    _upsert_setting(SETTING_SERIAL, serial_hex, 'DGUV signing certificate serial')
    db.session.commit()
    return certificate_status()


def load_pkcs12_bytes() -> tuple[bytes, bytes]:
    """Return (pfx_bytes, passphrase_bytes). Raises if missing."""
    path = pfx_path()
    if not os.path.isfile(path):
        raise FileNotFoundError('DGUV signing certificate missing')
    enc = _get_setting(SETTING_PASSPHRASE)
    if not enc:
        raise FileNotFoundError('DGUV signing passphrase missing')
    passphrase = _decrypt_passphrase(enc)
    with open(path, 'rb') as fh:
        return fh.read(), passphrase.encode('utf-8')


def sign_pdf_bytes(pdf_bytes: bytes, *, reason: str, location: str, contact_info: str) -> tuple[bytes, str]:
    """
    Sign PDF with organisational PKCS#12 via pyHanko.
    Returns (signed_pdf_bytes, certificate_serial_hex).
    """
    from io import BytesIO

    from pyhanko.sign import signers
    from pyhanko.sign.fields import SigFieldSpec
    from pyhanko.sign.signers.pdf_signer import PdfSignatureMetadata, PdfSigner
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    path = pfx_path()
    if not os.path.isfile(path):
        raise FileNotFoundError('DGUV signing certificate missing')
    enc = _get_setting(SETTING_PASSPHRASE)
    if not enc:
        raise FileNotFoundError('DGUV signing passphrase missing')
    passphrase = _decrypt_passphrase(enc).encode('utf-8')

    signer = signers.SimpleSigner.load_pkcs12(
        pfx_file=path,
        passphrase=passphrase,
    )
    serial = ''
    if signer.signing_cert is not None:
        serial = format(signer.signing_cert.serial_number, 'x')

    meta = PdfSignatureMetadata(
        field_name='DGUV_FES_Signature',
        reason=reason[:200] if reason else 'DGUV V3 Prüfprotokoll',
        location=location[:200] if location else '',
        contact_info=contact_info[:200] if contact_info else '',
    )
    writer = IncrementalPdfFileWriter(BytesIO(pdf_bytes))
    out = BytesIO()
    PdfSigner(
        meta,
        signer=signer,
        new_field_spec=SigFieldSpec(sig_field_name='DGUV_FES_Signature', on_page=0, box=(50, 40, 280, 100)),
    ).sign_pdf(writer, output=out)
    return out.getvalue(), serial or (_get_setting(SETTING_SERIAL) or '')
