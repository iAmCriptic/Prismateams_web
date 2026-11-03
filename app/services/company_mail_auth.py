"""Service für Unternehmens-E-Mail-Authentifizierung und Postfach-Kopplung.

Verwaltet:
- Erkennung konfigurierter Unternehmens-E-Mail-Domains
- Live-Verifikation von Benutzeranmeldedaten gegen den Firmen-Mailserver (IMAP)
- Automatische Erstellung und Bereitstellung des persönlichen Postfachs (Mailbox)
- Synchronisation geänderter Passwörter zwischen Mailserver und Portal
- Offline-Login-Policy bei Mailserver-Ausfällen
"""

from __future__ import annotations

import imaplib
import logging
import re
import socket
import ssl
from typing import Optional

from flask import current_app

from app import db
from app.models.email import Mailbox
from app.models.settings import SystemSettings
from app.models.whitelist import WhitelistEntry
from app.utils.multi_mailboxes import encrypt_password

logger = logging.getLogger(__name__)


def _setting_str(key: str, default: str = '') -> str:
    """Holt einen String-Wert aus SystemSettings."""
    setting = SystemSettings.query.filter_by(key=key).first()
    return setting.value.strip() if setting and setting.value else default


def _setting_bool(key: str, default: bool = False) -> bool:
    """Holt einen booleschen Wert aus SystemSettings."""
    setting = SystemSettings.query.filter_by(key=key).first()
    if not setting or setting.value is None:
        return default
    val = setting.value.strip().lower()
    return val in ('1', 'true', 'yes', 'on')


def _setting_int(key: str, default: int) -> int:
    """Holt einen Integer-Wert aus SystemSettings."""
    setting = SystemSettings.query.filter_by(key=key).first()
    if not setting or not setting.value:
        return default
    try:
        return int(setting.value.strip())
    except ValueError:
        return default


def is_company_email_auth_enabled() -> bool:
    """Prüft, ob der Live-Abgleich mit dem Unternehmens-Mailserver beim Login aktiv ist."""
    return _setting_bool('company_email_auth_enabled', False)


def is_company_email_register_only() -> bool:
    """Prüft, ob die Selbst-Registrierung ausschließlich auf Unternehmens-E-Mails beschränkt ist."""
    return _setting_bool('company_email_register_only', False)


def is_user_offline_login_allowed() -> bool:
    """Prüft, ob reguläre Benutzer sich bei Mailserver-Ausfall mit ihrem letzten Passwort einloggen dürfen."""
    return _setting_bool('company_email_allow_user_offline_login', False)


def get_configured_company_domains() -> list[str]:
    """
    Gibt die Liste der konfigurierten Unternehmens-E-Mail-Domains zurück.
    
    Format der Domains: immer klein, z. B. ['@firma.de', '@holding.com'].
    Trennzeichen in den Einstellungen können Komma, Semikolon oder Zeilenumbruch sein.
    Falls keine Domain konfiguriert ist, wird auf aktive Domain-Einträge der Whitelist zurückgegriffen.
    """
    raw = _setting_str('company_email_domains', '')
    domains: list[str] = []
    
    if raw:
        tokens = re.split(r'[,;\s\n\r]+', raw)
        for token in tokens:
            token = token.strip().lower()
            if not token:
                continue
            if not token.startswith('@'):
                token = '@' + token
            if token not in domains:
                domains.append(token)
                
    if not domains:
        # Fallback: Aktive Domain-Whitelist-Einträge prüfen
        whitelist_domains = WhitelistEntry.query.filter_by(
            entry_type='domain',
            is_active=True
        ).all()
        for wd in whitelist_domains:
            entry = wd.entry.strip().lower()
            if not entry.startswith('@'):
                entry = '@' + entry
            if entry not in domains:
                domains.append(entry)
                
    return domains


def is_company_email(email: Optional[str]) -> bool:
    """
    Prüft, ob die angegebene E-Mail-Adresse zu einer der Unternehmens-Domains gehört.
    """
    if not email:
        return False
    normalized = email.strip().lower()
    if '@' not in normalized:
        return False
        
    allowed_domains = get_configured_company_domains()
    if not allowed_domains:
        return False
        
    for domain in allowed_domains:
        if normalized.endswith(domain):
            return True
            
    return False


def get_company_mail_server_config() -> dict:
    """
    Ermittelt die Server-Einstellungen für Unternehmenspostfächer.
    Nutzt spezifische Einstellungen aus SystemSettings mit Fallback auf die globale App-Config.
    """
    imap_server = _setting_str('company_mail_imap_server', '') or current_app.config.get('IMAP_SERVER') or ''
    imap_port = _setting_int('company_mail_imap_port', 0) or int(current_app.config.get('IMAP_PORT', 993) or 993)
    imap_use_ssl = _setting_bool('company_mail_imap_ssl', bool(current_app.config.get('IMAP_USE_SSL', True)))
    
    smtp_server = _setting_str('company_mail_smtp_server', '') or current_app.config.get('MAIL_SERVER') or ''
    smtp_port = _setting_int('company_mail_smtp_port', 0) or int(current_app.config.get('MAIL_PORT', 587) or 587)
    smtp_use_tls = _setting_bool('company_mail_smtp_tls', bool(current_app.config.get('MAIL_USE_TLS', True)))
    smtp_use_ssl = _setting_bool('company_mail_smtp_ssl', bool(current_app.config.get('MAIL_USE_SSL', False)))
    
    return {
        'imap_server': imap_server.strip(),
        'imap_port': imap_port,
        'imap_use_ssl': imap_use_ssl,
        'smtp_server': smtp_server.strip(),
        'smtp_port': smtp_port,
        'smtp_use_tls': smtp_use_tls,
        'smtp_use_ssl': smtp_use_ssl,
    }


def verify_mailbox_credentials(
    email: str,
    password: str,
    timeout: int = 15,
) -> tuple[bool, str, dict]:
    """
    Prüft die Zugangsdaten live gegen den Unternehmens-IMAP-Server.
    
    Rückgabe:
        (success: bool, status_code: str, details: dict)
        
    Mögliche Status-Codes:
        - 'OK': Authentifizierung und Zugriff auf Postfach erfolgreich.
        - 'AUTH_FAILED': Falsche Anmeldedaten oder Postfach serverseitig gesperrt/gelöscht.
        - 'CONNECTION_ERROR': Server offline, DNS-Fehler, Verbindungs-Timeout.
        - 'CONFIG_MISSING': Kein IMAP-Server konfiguriert.
    """
    if not email or not password:
        return False, 'AUTH_FAILED', {'error': 'Missing credentials'}
        
    cfg = get_company_mail_server_config()
    imap_server = cfg.get('imap_server')
    imap_port = cfg.get('imap_port', 993)
    imap_use_ssl = cfg.get('imap_use_ssl', True)
    
    if not imap_server:
        logger.warning("Unternehmens-IMAP-Server ist nicht konfiguriert.")
        return False, 'CONFIG_MISSING', {'error': 'IMAP server not configured'}
        
    conn = None
    try:
        if imap_use_ssl:
            ctx = ssl.create_default_context()
            conn = imaplib.IMAP4_SSL(imap_server, imap_port, ssl_context=ctx, timeout=timeout)
        else:
            conn = imaplib.IMAP4(imap_server, imap_port, timeout=timeout)
            try:
                conn.starttls(ssl_context=ssl.create_default_context())
            except Exception:
                pass
                
        # Authentifizierung versuchen
        res, data = conn.login(email.strip(), password)
        if res != 'OK':
            return False, 'AUTH_FAILED', {'response': res, 'data': str(data)}
            
        # Prüfen, ob INBOX geöffnet werden kann (Bestätigung aktiver Postfach-Zugriff)
        status, _ = conn.select('INBOX', readonly=True)
        if status != 'OK':
            status, _ = conn.select('"INBOX"', readonly=True)
        if status != 'OK':
            return False, 'AUTH_FAILED', {'error': f'INBOX status: {status}'}
            
        return True, 'OK', {'server': imap_server, 'port': imap_port}
        
    except imaplib.IMAP4.error as e:
        logger.info(f"IMAP-Authentifizierung für {email} fehlgeschlagen: {e}")
        return False, 'AUTH_FAILED', {'error': str(e)}
    except (TimeoutError, socket.timeout, ConnectionError, OSError, imaplib.IMAP4.abort) as e:
        logger.warning(f"Verbindungsfehler zu {imap_server}:{imap_port} für {email}: {e}")
        return False, 'CONNECTION_ERROR', {'error': str(e)}
    except Exception as e:
        logger.exception(f"Unerwarteter Fehler bei der IMAP-Prüfung für {email}: {e}")
        return False, 'CONNECTION_ERROR', {'error': str(e)}
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass


def provision_user_company_mailbox(user, password: str) -> Mailbox:
    """
    Legt das persönliche Unternehmens-Postfach für den Benutzer an oder aktualisiert es.
    """
    cfg = get_company_mail_server_config()
    
    # Suche bestehendes persönliches Postfach
    existing_mb = Mailbox.query.filter_by(
        owner_id=user.id,
        mailbox_type='private'
    ).first()
    
    encrypted_pw = encrypt_password(password)
    
    if existing_mb:
        existing_mb.imap_server = cfg['imap_server']
        existing_mb.imap_port = cfg['imap_port']
        existing_mb.imap_use_ssl = cfg['imap_use_ssl']
        existing_mb.imap_username = user.email
        existing_mb.imap_password_enc = encrypted_pw
        
        existing_mb.smtp_server = cfg['smtp_server']
        existing_mb.smtp_port = cfg['smtp_port']
        existing_mb.smtp_use_tls = cfg['smtp_use_tls']
        existing_mb.smtp_use_ssl = cfg['smtp_use_ssl']
        existing_mb.smtp_username = user.email
        existing_mb.smtp_password_enc = encrypted_pw
        existing_mb.is_active = True
        db.session.commit()
        return existing_mb
        
    new_mb = Mailbox(
        name='Unternehmenspostfach',
        display_name=user.email,
        mailbox_type='private',
        owner_id=user.id,
        provider='custom',
        auth_type='password',
        imap_server=cfg['imap_server'],
        imap_port=cfg['imap_port'],
        imap_use_ssl=cfg['imap_use_ssl'],
        imap_username=user.email,
        imap_password_enc=encrypted_pw,
        smtp_server=cfg['smtp_server'],
        smtp_port=cfg['smtp_port'],
        smtp_use_tls=cfg['smtp_use_tls'],
        smtp_use_ssl=cfg['smtp_use_ssl'],
        smtp_username=user.email,
        smtp_password_enc=encrypted_pw,
        is_active=True,
    )
    db.session.add(new_mb)
    db.session.commit()
    return new_mb


def sync_credentials_if_needed(user, password: str) -> None:
    """
    Synchronisiert Passwortänderungen vom Mailserver mit dem Portal:
    - Aktualisiert den lokalen Argon2-Passworthash des Nutzers
    - Aktualisiert das verschlüsselte Passwort in der persönlichen Mailbox
    """
    if not user:
        return
        
    try:
        # Falls das lokale Passwort abweicht, aktualisieren
        if not user.check_password(password):
            user.set_password(password)
            
        encrypted_pw = encrypt_password(password)
        mb = Mailbox.query.filter_by(
            owner_id=user.id,
            mailbox_type='private'
        ).first()
        if mb:
            mb.imap_password_enc = encrypted_pw
            mb.smtp_password_enc = encrypted_pw
            mb.is_active = True
            
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Fehler bei Passwort-Synchronisation für User {user.id}: {e}")

