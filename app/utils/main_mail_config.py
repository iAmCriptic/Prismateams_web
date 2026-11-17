"""Zentrale Verwaltung der Haupt-E-Mail-Konfiguration (System-E-Mail) in SystemSettings."""

from __future__ import annotations

import logging
from typing import Any, Optional

from flask import current_app, has_app_context

from app import db
from app.models.settings import SystemSettings
from app.utils.bot_protection import upsert_setting
from app.utils.multi_mailboxes import (
    MAILBOX_PROVIDER_PRESETS,
    decrypt_password,
    encrypt_password,
)
from app.utils.system_settings_cache import (
    get_setting,
    invalidate_system_settings_cache,
    setting_bool,
)

PASSWORD_PLACEHOLDERS = frozenset({'••••••••', '********', '••••••••••••'})

KEY_PROVIDER = 'main_mail_provider'
KEY_SMTP_SERVER = 'main_mail_smtp_server'
KEY_SMTP_PORT = 'main_mail_smtp_port'
KEY_SMTP_USE_TLS = 'main_mail_smtp_use_tls'
KEY_SMTP_USE_SSL = 'main_mail_smtp_use_ssl'
KEY_SMTP_USERNAME = 'main_mail_smtp_username'
KEY_SMTP_PASSWORD_ENC = 'main_mail_smtp_password_enc'
KEY_IMAP_SERVER = 'main_mail_imap_server'
KEY_IMAP_PORT = 'main_mail_imap_port'
KEY_IMAP_USE_SSL = 'main_mail_imap_use_ssl'
KEY_IMAP_USERNAME = 'main_mail_imap_username'
KEY_IMAP_PASSWORD_ENC = 'main_mail_imap_password_enc'
KEY_DEFAULT_SENDER = 'main_mail_default_sender'
KEY_SENDER_NAME = 'main_mail_sender_name'
KEY_ENV_MIGRATED = 'main_mail_env_migrated'

_TRUE_VALUES = frozenset({'true', '1', 'yes', 'on'})


def _to_bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in _TRUE_VALUES


def _to_int(val: Any, default: int) -> int:
    try:
        parsed = int(val)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _has_db_main_mail_config() -> bool:
    return bool(
        get_setting(KEY_SMTP_SERVER)
        or get_setting(KEY_SMTP_USERNAME)
        or get_setting(KEY_IMAP_SERVER)
    )


def _env_fallback_config() -> dict[str, Any]:
    if not has_app_context():
        return {
            'source': 'none',
            'provider': 'custom',
            'smtp_server': '',
            'smtp_port': 587,
            'smtp_use_tls': True,
            'smtp_use_ssl': False,
            'smtp_username': '',
            'smtp_password': '',
            'has_smtp_password': False,
            'imap_server': '',
            'imap_port': 993,
            'imap_use_ssl': True,
            'imap_username': '',
            'imap_password': '',
            'has_imap_password': False,
            'default_sender': '',
            'sender_name': '',
        }

    cfg = current_app.config
    smtp_server = (cfg.get('MAIL_SERVER') or '').strip()
    smtp_user = (cfg.get('MAIL_USERNAME') or '').strip()
    smtp_pw = cfg.get('MAIL_PASSWORD') or ''
    imap_server = (cfg.get('IMAP_SERVER') or '').strip()
    default_sender = (cfg.get('MAIL_DEFAULT_SENDER') or smtp_user or '').strip()
    sender_name = (cfg.get('MAIL_SENDER_NAME') or '').strip()
    use_ssl = bool(cfg.get('MAIL_USE_SSL', False))
    use_tls = bool(cfg.get('MAIL_USE_TLS', True)) and not use_ssl
    has_any = bool(smtp_server or smtp_user or imap_server)

    return {
        'source': 'env' if has_any else 'none',
        'provider': 'custom',
        'smtp_server': smtp_server,
        'smtp_port': _to_int(cfg.get('MAIL_PORT'), 465 if use_ssl else 587),
        'smtp_use_tls': use_tls,
        'smtp_use_ssl': use_ssl,
        'smtp_username': smtp_user,
        'smtp_password': smtp_pw,
        'has_smtp_password': bool(smtp_pw),
        'imap_server': imap_server,
        'imap_port': _to_int(cfg.get('IMAP_PORT'), 993),
        'imap_use_ssl': bool(cfg.get('IMAP_USE_SSL', True)),
        'imap_username': smtp_user,
        'imap_password': smtp_pw,
        'has_imap_password': bool(smtp_pw),
        'default_sender': default_sender,
        'sender_name': sender_name,
    }


def get_main_mail_config() -> dict[str, Any]:
    """Liefert die aktive Haupt-E-Mail-Konfiguration (DB-vorrangig, Fallback auf App-Config)."""
    if not has_app_context() or not _has_db_main_mail_config():
        return _env_fallback_config()

    smtp_server = (get_setting(KEY_SMTP_SERVER, '') or '').strip()
    smtp_user = (get_setting(KEY_SMTP_USERNAME, '') or '').strip()
    smtp_pw = decrypt_password(get_setting(KEY_SMTP_PASSWORD_ENC)) or ''
    smtp_use_ssl = setting_bool(KEY_SMTP_USE_SSL, False)
    smtp_use_tls = setting_bool(KEY_SMTP_USE_TLS, True) and not smtp_use_ssl
    smtp_port = _to_int(get_setting(KEY_SMTP_PORT), 465 if smtp_use_ssl else 587)

    imap_server = (get_setting(KEY_IMAP_SERVER, '') or '').strip()
    imap_use_ssl = setting_bool(KEY_IMAP_USE_SSL, True)
    imap_port = _to_int(get_setting(KEY_IMAP_PORT), 993 if imap_use_ssl else 143)
    imap_user = (get_setting(KEY_IMAP_USERNAME, '') or '').strip() or smtp_user
    imap_pw = decrypt_password(get_setting(KEY_IMAP_PASSWORD_ENC)) or smtp_pw

    default_sender = (get_setting(KEY_DEFAULT_SENDER, '') or '').strip() or smtp_user
    sender_name = (get_setting(KEY_SENDER_NAME, '') or '').strip()
    provider = (get_setting(KEY_PROVIDER, 'custom') or 'custom').strip().lower()
    if provider not in MAILBOX_PROVIDER_PRESETS:
        provider = 'custom'

    return {
        'source': 'db',
        'provider': provider,
        'smtp_server': smtp_server,
        'smtp_port': smtp_port,
        'smtp_use_tls': smtp_use_tls,
        'smtp_use_ssl': smtp_use_ssl,
        'smtp_username': smtp_user,
        'smtp_password': smtp_pw,
        'has_smtp_password': bool(smtp_pw),
        'imap_server': imap_server,
        'imap_port': imap_port,
        'imap_use_ssl': imap_use_ssl,
        'imap_username': imap_user,
        'imap_password': imap_pw,
        'has_imap_password': bool(imap_pw),
        'default_sender': default_sender,
        'sender_name': sender_name,
    }


def is_main_mail_configured() -> bool:
    """True, wenn das Hauptpostfach (mindestens SMTP) vollständig konfiguriert ist."""
    cfg = get_main_mail_config()
    return bool(cfg.get('smtp_server') and cfg.get('smtp_username') and cfg.get('smtp_password'))


def get_formatted_main_sender() -> Optional[str]:
    """Gibt den formatierten Absender zurück: 'Name <email@example.com>' oder 'email@example.com'."""
    cfg = get_main_mail_config()
    sender_email = (cfg.get('default_sender') or cfg.get('smtp_username') or '').strip()
    if not sender_email:
        return None
    sender_name = (cfg.get('sender_name') or '').strip()
    if sender_name:
        return f'{sender_name} <{sender_email}>'
    return sender_email


def save_main_mail_config(data: dict[str, Any], commit: bool = True) -> dict[str, Any]:
    """Speichert die Haupt-E-Mail-Konfiguration verschlüsselt in SystemSettings."""
    provider = str(data.get('provider') or 'custom').strip().lower()
    if provider not in MAILBOX_PROVIDER_PRESETS:
        provider = 'custom'

    smtp_use_ssl = _to_bool(data.get('smtp_use_ssl'), False)
    smtp_use_tls = _to_bool(data.get('smtp_use_tls'), True) and not smtp_use_ssl
    smtp_port = _to_int(data.get('smtp_port'), 465 if smtp_use_ssl else 587)
    smtp_server = str(data.get('smtp_server') or '').strip()
    smtp_username = str(data.get('smtp_username') or '').strip()

    raw_smtp_pw = str(data.get('smtp_password') or '')
    if raw_smtp_pw and raw_smtp_pw not in PASSWORD_PLACEHOLDERS:
        smtp_password_enc = encrypt_password(raw_smtp_pw) or ''
    else:
        existing_row = SystemSettings.query.filter_by(key=KEY_SMTP_PASSWORD_ENC).first()
        smtp_password_enc = existing_row.value if existing_row and existing_row.value else ''

    imap_use_ssl = _to_bool(data.get('imap_use_ssl'), True)
    imap_port = _to_int(data.get('imap_port'), 993 if imap_use_ssl else 143)
    imap_server = str(data.get('imap_server') or '').strip()
    imap_username = str(data.get('imap_username') or '').strip()

    raw_imap_pw = str(data.get('imap_password') or '')
    if raw_imap_pw and raw_imap_pw not in PASSWORD_PLACEHOLDERS:
        imap_password_enc = encrypt_password(raw_imap_pw) or ''
    else:
        existing_imap_row = SystemSettings.query.filter_by(key=KEY_IMAP_PASSWORD_ENC).first()
        imap_password_enc = existing_imap_row.value if existing_imap_row and existing_imap_row.value else ''

    default_sender = str(data.get('default_sender') or '').strip() or smtp_username
    sender_name = str(data.get('sender_name') or '').strip()

    entries = [
        (KEY_PROVIDER, provider, 'Haupt-E-Mail-Provider'),
        (KEY_SMTP_SERVER, smtp_server, 'Haupt-E-Mail SMTP-Server'),
        (KEY_SMTP_PORT, str(smtp_port), 'Haupt-E-Mail SMTP-Port'),
        (KEY_SMTP_USE_TLS, 'true' if smtp_use_tls else 'false', 'Haupt-E-Mail SMTP STARTTLS'),
        (KEY_SMTP_USE_SSL, 'true' if smtp_use_ssl else 'false', 'Haupt-E-Mail SMTP SSL'),
        (KEY_SMTP_USERNAME, smtp_username, 'Haupt-E-Mail SMTP-Benutzername'),
        (KEY_SMTP_PASSWORD_ENC, smtp_password_enc, 'Haupt-E-Mail SMTP-Passwort (verschlüsselt)'),
        (KEY_IMAP_SERVER, imap_server, 'Haupt-E-Mail IMAP-Server'),
        (KEY_IMAP_PORT, str(imap_port), 'Haupt-E-Mail IMAP-Port'),
        (KEY_IMAP_USE_SSL, 'true' if imap_use_ssl else 'false', 'Haupt-E-Mail IMAP SSL'),
        (KEY_IMAP_USERNAME, imap_username, 'Haupt-E-Mail IMAP-Benutzername'),
        (KEY_IMAP_PASSWORD_ENC, imap_password_enc, 'Haupt-E-Mail IMAP-Passwort (verschlüsselt)'),
        (KEY_DEFAULT_SENDER, default_sender, 'Haupt-E-Mail Standard-Absender'),
        (KEY_SENDER_NAME, sender_name, 'Haupt-E-Mail Absendername'),
        (KEY_ENV_MIGRATED, 'true', 'Legacy .env Mail-Konfiguration migriert'),
    ]
    for key, value, desc in entries:
        upsert_setting(key, value, desc)

    if commit:
        db.session.commit()
    invalidate_system_settings_cache()
    return get_main_mail_config()


def migrate_main_mail_from_env_if_needed() -> bool:
    """Migriert bestehende MAIL_*/IMAP_*-Werte aus .env/App-Config einmalig in SystemSettings."""
    if not has_app_context():
        return False
    try:
        migrated_row = SystemSettings.query.filter_by(key=KEY_ENV_MIGRATED).first()
        if migrated_row and str(migrated_row.value or '').strip().lower() in _TRUE_VALUES:
            return False

        existing_smtp = SystemSettings.query.filter_by(key=KEY_SMTP_SERVER).first()
        existing_user = SystemSettings.query.filter_by(key=KEY_SMTP_USERNAME).first()
        if (existing_smtp and existing_smtp.value) or (existing_user and existing_user.value):
            upsert_setting(KEY_ENV_MIGRATED, 'true', 'Legacy .env Mail-Konfiguration migriert')
            db.session.commit()
            invalidate_system_settings_cache()
            return False

        env_cfg = _env_fallback_config()
        if env_cfg['source'] != 'env':
            return False

        save_main_mail_config(env_cfg, commit=True)
        logging.info('Haupt-E-Mail-Konfiguration erfolgreich aus .env in SystemSettings migriert.')
        return True
    except Exception as exc:
        db.session.rollback()
        logging.warning('Migration der Haupt-E-Mail aus .env fehlgeschlagen: %s', exc)
        return False


def parse_main_mail_form(form: Any) -> dict[str, Any]:
    """Parst Formularfelder des Haupt-E-Mail-Wizards einheitlich für Setup & Admin."""
    provider = str(form.get('provider') or 'custom').strip().lower()
    if provider not in MAILBOX_PROVIDER_PRESETS:
        provider = 'custom'

    smtp_security = str(form.get('smtp_security') or '').strip().lower()
    if smtp_security == 'ssl':
        smtp_use_ssl, smtp_use_tls = True, False
    elif smtp_security == 'tls':
        smtp_use_ssl, smtp_use_tls = False, True
    elif smtp_security == 'none':
        smtp_use_ssl, smtp_use_tls = False, False
    else:
        smtp_use_ssl = _to_bool(form.get('smtp_use_ssl'), False)
        smtp_use_tls = _to_bool(form.get('smtp_use_tls'), True) and not smtp_use_ssl

    smtp_username = str(form.get('smtp_username') or form.get('email') or '').strip()
    smtp_password = str(form.get('smtp_password') or form.get('password') or '')
    imap_username = str(form.get('imap_username') or '').strip()
    imap_password = str(form.get('imap_password') or '')

    return {
        'provider': provider,
        'smtp_server': str(form.get('smtp_server') or '').strip(),
        'smtp_port': _to_int(form.get('smtp_port'), 465 if smtp_use_ssl else 587),
        'smtp_use_tls': smtp_use_tls,
        'smtp_use_ssl': smtp_use_ssl,
        'smtp_username': smtp_username,
        'smtp_password': smtp_password,
        'imap_server': str(form.get('imap_server') or '').strip(),
        'imap_port': _to_int(form.get('imap_port'), 993),
        'imap_use_ssl': _to_bool(form.get('imap_use_ssl'), True),
        'imap_username': imap_username,
        'imap_password': imap_password,
        'default_sender': str(form.get('default_sender') or '').strip() or smtp_username,
        'sender_name': str(form.get('sender_name') or '').strip(),
    }


def _resolve_test_password(raw_pw: str, fallback_key: str) -> str:
    if raw_pw and raw_pw not in PASSWORD_PLACEHOLDERS:
        return raw_pw
    existing = get_main_mail_config()
    return str(existing.get(fallback_key) or '')


def test_main_smtp_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    """Prüft SMTP-Verbindung + Login mit Formular-Daten (Fallback auf gespeichertes Passwort)."""
    from app.utils.mailbox_autodiscover import test_smtp_connection

    server = str(payload.get('smtp_server') or '').strip()
    user = str(payload.get('smtp_username') or payload.get('email') or '').strip()
    password = _resolve_test_password(
        str(payload.get('smtp_password') or payload.get('password') or ''),
        'smtp_password',
    )
    if not server or not user or not password:
        return False, 'missing_fields'

    use_ssl = _to_bool(payload.get('smtp_use_ssl'), False)
    use_tls = _to_bool(payload.get('smtp_use_tls'), True) and not use_ssl
    port = _to_int(payload.get('smtp_port'), 465 if use_ssl else 587)
    ok, _is_auth, err = test_smtp_connection(server, port, use_tls, use_ssl, user, password, timeout=15.0)
    return ok, err


def test_main_imap_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    """Prüft IMAP-Verbindung + Login mit Formular-Daten (Fallback auf gespeichertes Passwort)."""
    from app.utils.mailbox_autodiscover import test_imap_connection

    server = str(payload.get('imap_server') or '').strip()
    user = str(payload.get('imap_username') or payload.get('smtp_username') or payload.get('email') or '').strip()
    raw_pw = str(payload.get('imap_password') or payload.get('smtp_password') or payload.get('password') or '')
    password = _resolve_test_password(raw_pw, 'imap_password')
    if not server or not user or not password:
        return False, 'missing_fields'

    use_ssl = _to_bool(payload.get('imap_use_ssl'), True)
    port = _to_int(payload.get('imap_port'), 993 if use_ssl else 143)
    ok, _is_auth, err = test_imap_connection(server, port, use_ssl, user, password, timeout=15.0)
    return ok, err


def main_mail_autodiscover_response(data: dict[str, Any]) -> dict[str, Any]:
    """Gemeinsamer JSON-Handler für Autodiscover im Setup & Admin-Bereich."""
    from app.utils.i18n import translate
    from app.utils.mailbox_autodiscover import autodiscover_and_verify

    email = str(data.get('email') or '').strip()
    raw_pw = str(data.get('password') or '').strip()
    password = _resolve_test_password(raw_pw, 'smtp_password')

    if not email or '@' not in email or not password:
        return {
            'success': False,
            'message': translate('settings.mailboxes.autodiscover_incomplete'),
        }

    result = autodiscover_and_verify(email, password)
    if result.get('success'):
        imap_host = (result.get('imap') or {}).get('server', '')
        smtp_host = (result.get('smtp') or {}).get('server', '')
        result['message'] = translate('settings.mailboxes.autodiscover_ok', imap=imap_host, smtp=smtp_host)
    elif result.get('auth_error'):
        result['message'] = translate('settings.mailboxes.autodiscover_auth_failed')
    else:
        result['message'] = translate('settings.mailboxes.autodiscover_failed')
    return result


def main_mail_test_smtp_response(data: dict[str, Any]) -> dict[str, Any]:
    """Gemeinsamer JSON-Handler für SMTP-Live-Test im Setup & Admin-Bereich."""
    from app.utils.i18n import translate

    ok, err = test_main_smtp_payload(data)
    if ok:
        server = str(data.get('smtp_server') or '').strip()
        port = _to_int(data.get('smtp_port'), 587)
        return {
            'success': True,
            'message': translate('settings.mailboxes.test_smtp_ok', server=server, port=port),
        }
    if err == 'missing_fields':
        return {
            'success': False,
            'message': translate('settings.admin.email_module.test.smtp_incomplete'),
        }
    return {
        'success': False,
        'message': translate('settings.mailboxes.test_fail', error=err),
    }


def main_mail_test_imap_response(data: dict[str, Any]) -> dict[str, Any]:
    """Gemeinsamer JSON-Handler für IMAP-Live-Test im Setup & Admin-Bereich."""
    from app.utils.i18n import translate

    ok, err = test_main_imap_payload(data)
    if ok:
        server = str(data.get('imap_server') or '').strip()
        port = _to_int(data.get('imap_port'), 993)
        return {
            'success': True,
            'message': translate('settings.mailboxes.test_imap_ok', server=server, port=port),
        }
    if err == 'missing_fields':
        return {
            'success': False,
            'message': translate('settings.admin.email_module.test.imap_incomplete'),
        }
    return {
        'success': False,
        'message': translate('settings.mailboxes.test_fail', error=err),
    }


