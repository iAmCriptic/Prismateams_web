"""IMAP connection, folder naming, and mailbox mutations."""

from flask import (
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from uuid import uuid4
from app import db, mail
from app.blueprints.sse import emit_email_sync_status
from app.models.email import EmailAttachment, EmailFolder, EmailMessage, EmailPermission
from app.models.settings import SystemSettings
from app.utils.notifications import send_email_notification
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from flask_mail import Message
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import unquote
import imaplib
import email as email_module
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import threading
import time
import logging
import io
import hashlib
from markupsafe import Markup
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy import func, cast, Integer, or_
from sqlalchemy.orm import defer
import re

from app.utils.email_sender import get_logo_base64, get_logo_data, send_email_with_lock
from app.utils.lock_manager import (
    acquire_email_sync_lock,
    heartbeat_email_sync_lock,
    try_acquire_email_sync_leader,
)
from app.utils.common import format_datetime
from app.blueprints.email._bp import EMAIL_LIST_PER_PAGE, email_bp, logger


def decode_header_field(field):
    """Decode email header field properly with multiple fallback strategies."""
    if not field:
        return ''
    
    try:
        from email.header import decode_header
        decoded_parts = decode_header(field)
        decoded_string = ''
        
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                if encoding:
                    try:
                        decoded_string += part.decode(encoding, errors='ignore')
                        continue
                    except (UnicodeDecodeError, LookupError):
                        pass
                
                for fallback_encoding in ['utf-8', 'latin-1', 'cp1252', 'ascii']:
                    try:
                        decoded_string += part.decode(fallback_encoding, errors='ignore')
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                else:
                    decoded_string += part.decode('ascii', errors='replace')
            else:
                decoded_string += str(part)
        
        result = decoded_string.strip()
        if not result:
            return str(field) if field else ''
        return result
        
    except Exception as e:
        try:
            return str(field) if field else ''
        except:
            return 'Unknown'


def truncate_filename(filename, max_length=500):
    """
    Kürzt einen Dateinamen auf die maximale Länge, behält dabei die Dateiendung.
    
    Args:
        filename: Der zu kürzende Dateiname
        max_length: Maximale Länge (Standard: 500 Zeichen)
    
    Returns:
        Gekürzter Dateiname
    """
    if not filename or len(filename) <= max_length:
        return filename
    
    # Behalte Dateiendung und kürze den Namen
    if '.' in filename:
        name, ext = filename.rsplit('.', 1)
        max_name_length = max_length - len(ext) - 1  # -1 für den Punkt
        if max_name_length < 1:
            # Falls die Endung zu lang ist, kürze einfach den ganzen Namen
            return filename[:max_length]
        return name[:max_name_length] + '.' + ext
    else:
        return filename[:max_length]


def _is_placeholder_imap_config(imap_server, username, password):
    """Return True if IMAP config still contains example/placeholder values."""
    values = [str(v).strip().lower() for v in (imap_server, username, password) if v]
    if not values:
        return True

    placeholder_markers = (
        'example.com',
        'imap.example.com',
        'smtp.example.com',
        'your-',
        'your_',
        'changeme',
        'change-me',
    )
    return any(any(marker in value for marker in placeholder_markers) for value in values)


def _format_imap_error(exc):
    """IMAP-Fehler lesbar machen (oft bytes in Exception-Args)."""
    parts = []
    for arg in getattr(exc, 'args', ()) or ():
        if isinstance(arg, bytes):
            parts.append(arg.decode('utf-8', errors='replace'))
        elif arg is not None:
            parts.append(str(arg))
    if parts:
        return ' '.join(parts).strip()
    if isinstance(exc, bytes):
        return exc.decode('utf-8', errors='replace')
    return str(exc)


def _imap_error_is_transient(exc):
    """True bei temporären Provider-/Verbindungsfehlern (Retry sinnvoll)."""
    text = _format_imap_error(exc).upper()
    markers = (
        'TOO MANY',
        'CONNECTION',
        'TIMEOUT',
        'TIMED OUT',
        'TEMPORAR',
        'UNAVAILABLE',
        'TRY AGAIN',
        'RATE',
        'LIMIT',
        'BUSY',
        'EOF',
        'BROKEN PIPE',
        'RESET',
        'SSL',
    )
    return any(m in text for m in markers) or isinstance(
        exc, (TimeoutError, OSError, ConnectionError, imaplib.IMAP4.abort)
    )


def _open_imap_connection(timeout=20, mailbox=None):
    """
    Öffnet eine IMAP-Verbindung aus App-Config oder Mailbox-Credentials (ohne Ordner-Select).
    Raises bei Fehler.
    """
    import ssl
    from app.utils.multi_mailboxes import get_mailbox_imap_config

    cfg = get_mailbox_imap_config(mailbox)
    imap_server = cfg.get('server')
    imap_port = int(cfg.get('port') or 993)
    imap_use_ssl = cfg.get('use_ssl', True)
    username = cfg.get('user')
    password = cfg.get('password')
    auth_type = cfg.get('auth_type') or 'password'
    timeout = int(current_app.config.get('MAIL_TIMEOUT', timeout) or timeout)

    if not imap_server or not username:
        raise RuntimeError('IMAP-Konfiguration unvollständig')

    if auth_type != 'oauth' and not password:
        raise RuntimeError('IMAP-Konfiguration unvollständig')

    if auth_type != 'oauth' and _is_placeholder_imap_config(imap_server, username, password):
        raise RuntimeError('IMAP enthält Platzhalterwerte')

    if imap_use_ssl:
        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(imap_server, imap_port, ssl_context=ctx, timeout=timeout)
    else:
        conn = imaplib.IMAP4(imap_server, imap_port, timeout=timeout)
        try:
            conn.starttls(ssl_context=ssl.create_default_context())
        except Exception:
            # Server ohne STARTTLS auf Klartext-Port
            pass

    if auth_type == 'oauth' and mailbox is not None:
        from app.utils.mailbox_oauth import get_valid_access_token, imap_authenticate_xoauth2
        token = get_valid_access_token(mailbox)
        imap_authenticate_xoauth2(conn, username, token)
    else:
        conn.login(username, password)
    return conn, imap_server, imap_port


def probe_imap_connection(timeout=20, retries=3, wait_for_sync_seconds=8, mailbox=None):
    """
    Prüft IMAP Login + INBOX (für Einstellungs-Test).

    Versucht kurz, den Sync-Lock zu bekommen (weniger Parallel-Logins),
    retryt bei transienten Provider-Fehlern.

    Returns:
        (ok: bool, message: str, meta: dict)
    """
    last_error = None
    sync_was_busy = False

    def _do_probe():
        conn = None
        try:
            conn, server, port = _open_imap_connection(timeout=timeout, mailbox=mailbox)
            status, _ = conn.select('INBOX', readonly=True)
            if status != 'OK':
                status, _ = conn.select('"INBOX"', readonly=True)
            if status != 'OK':
                status, _ = conn.select('INBOX')
            if status != 'OK':
                return False, f"INBOX konnte nicht geöffnet werden (Status: {status})", {
                    'server': server, 'port': port,
                }
            return True, f"{server}:{port}", {'server': server, 'port': port}
        finally:
            _imap_logout(conn)

    def _run_attempts():
        nonlocal last_error
        attempts = max(1, int(retries))
        for attempt in range(attempts):
            try:
                ok, msg, meta = _do_probe()
                if ok and sync_was_busy:
                    meta = dict(meta or {})
                    meta['sync_was_busy'] = True
                return ok, msg, meta
            except Exception as e:
                last_error = e
                if attempt + 1 < attempts and _imap_error_is_transient(e):
                    time.sleep(1.2 * (attempt + 1))
                    continue
                hint = ''
                if sync_was_busy:
                    hint = ' (Sync parallel — ggf. Verbindungs-Limit des Providers)'
                return False, _format_imap_error(e) + hint, {}
        return False, _format_imap_error(last_error) if last_error else 'IMAP-Test fehlgeschlagen', {}

    # Warte auf freien Sync-Lock, halte ihn während des Probes
    deadline = time.time() + max(0, float(wait_for_sync_seconds))
    while True:
        with acquire_email_sync_lock(timeout=0) as acquired:
            if acquired:
                return _run_attempts()
            sync_was_busy = True

        if time.time() >= deadline:
            # Letzter Versuch ohne exklusiven Lock
            return _run_attempts()
        time.sleep(0.75)


def _imap_logout(mail_conn):
    """Schließt und loggt eine IMAP-Verbindung aus (best effort)."""
    if not mail_conn:
        return
    try:
        mail_conn.close()
    except Exception:
        pass
    try:
        mail_conn.logout()
    except Exception:
        pass


def _send_flask_message_via_smtp(msg, smtp_cfg: dict):
    """Sendet eine Flask-Mail Message über dynamische SMTP-Credentials (Multi-Postfach)."""
    import ssl as ssl_mod

    server = smtp_cfg.get('server')
    port = int(smtp_cfg.get('port') or 587)
    user = smtp_cfg.get('user')
    password = smtp_cfg.get('password')
    use_ssl = bool(smtp_cfg.get('use_ssl', False))
    use_tls = bool(smtp_cfg.get('use_tls', True)) and not use_ssl
    auth_type = smtp_cfg.get('auth_type') or 'password'
    mailbox_obj = smtp_cfg.get('mailbox')
    if not server or not user:
        raise RuntimeError('SMTP-Konfiguration des Postfachs unvollständig')
    if auth_type != 'oauth' and not password:
        raise RuntimeError('SMTP-Konfiguration des Postfachs unvollständig')

    # Flask-Mail baut die MIME-Message lazy über .message
    mime = getattr(msg, 'message', None)
    if mime is None:
        raise RuntimeError('E-Mail-Nachricht konnte nicht aufgebaut werden')

    recipients = list(msg.recipients or [])
    if msg.cc:
        recipients.extend(msg.cc)
    if msg.bcc:
        recipients.extend(msg.bcc)

    timeout = int(current_app.config.get('MAIL_TIMEOUT', 20) or 20)
    context = ssl_mod.create_default_context()

    def _login(smtp):
        if auth_type == 'oauth' and mailbox_obj is not None:
            from app.utils.mailbox_oauth import get_valid_access_token, smtp_authenticate_xoauth2
            token = get_valid_access_token(mailbox_obj)
            smtp_authenticate_xoauth2(smtp, user, token)
        else:
            smtp.login(user, password)

    if use_ssl:
        with smtplib.SMTP_SSL(server, port, timeout=timeout, context=context) as smtp:
            _login(smtp)
            smtp.send_message(mime, from_addr=user, to_addrs=recipients)
    else:
        with smtplib.SMTP(server, port, timeout=timeout) as smtp:
            if use_tls:
                smtp.starttls(context=context)
            _login(smtp)
            smtp.send_message(mime, from_addr=user, to_addrs=recipients)


def connect_imap(folder='INBOX', mailbox=None):
    """Connect to IMAP server with robust error handling.
    
    Args:
        folder: IMAP folder to select (default: 'INBOX')
        mailbox: optional Mailbox model (None = Hauptpostfach aus App-Config)
    
    Returns:
        IMAP connection object or None if connection failed
    """
    try:
        mail_conn, _, _ = _open_imap_connection(timeout=30, mailbox=mailbox)
        
        logging.debug(f"Selecting folder: {folder}")
        status, messages = mail_conn.select(folder)
        if status != 'OK':
            try:
                status, messages = mail_conn.select(f'"{folder}"')
            except Exception:
                pass
            if status != 'OK':
                logging.warning(f"Could not select folder '{folder}', status: {status}")
                mail_conn.select('INBOX')
        
        logging.debug("IMAP connection established successfully")
        return mail_conn
    except imaplib.IMAP4.error as e:
        error_msg = _format_imap_error(e).encode('ascii', errors='replace').decode('ascii')
        logging.error(f"IMAP authentication error: {error_msg}")
        return None
    except Exception as e:
        error_msg = _format_imap_error(e).encode('ascii', errors='replace').decode('ascii')
        logging.error(f"IMAP connection failed: {error_msg}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        return None


def _select_imap_folder(mail_conn, folder_name):
    """Select IMAP folder; returns (ok: bool, messages/error payload)."""
    status, messages = mail_conn.select(folder_name)
    if status != 'OK':
        try:
            status, messages = mail_conn.select(f'"{folder_name}"')
        except Exception:
            pass
    return status == 'OK', messages


def is_sent_folder(folder_name):
    """
    Prüft, ob ein Ordner-Name ein Gesendet-Ordner ist.
    Unterstützt verschiedene IMAP-Server und deren Ordner-Namen.
    
    Args:
        folder_name: Der Name des IMAP-Ordners
        
    Returns:
        True wenn es sich um einen Gesendet-Ordner handelt, sonst False
    """
    if not folder_name:
        return False
    
    folder_name = folder_name.strip()
    
    # Liste aller möglichen Gesendet-Ordner-Namen verschiedener IMAP-Server
    sent_folder_names = [
        'Sent',                    # Standard
        'Sent Messages',           # Infomaniak, einige andere
        'Gesendet',                # Deutsche Variante
        'Gesendete Nachrichten',   # Infomaniak (deutsch)
        'Sent Items',              # Microsoft Outlook/Exchange
        'INBOX.Sent',              # Einige IMAP-Server (z.B. Dovecot)
        'INBOX/Sent',              # Alternative Struktur
        'INBOX\\Sent',             # Windows-Pfad-Struktur (selten)
        '[Gmail]/Sent Mail',
        '[Google Mail]/Sent Mail',
        '[Gmail]/Gesendet',
        '[Google Mail]/Gesendet',
    ]
    
    if folder_name in sent_folder_names:
        return True
    leaf = folder_name.replace('\\', '/').rsplit('/', 1)[-1].strip().lower()
    return leaf in ('sent', 'sent mail', 'sent messages', 'sent items', 'gesendet', 'gesendete nachrichten')


# Gmail-Namespace-Root (nicht auswählbar) – Kinder wie [Gmail]/Trash müssen bleiben
_GMAIL_NAMESPACE_ROOTS = frozenset({
    '[Gmail]',
    '[Google Mail]',
    '&XfJT0ZAB-',  # historisch / lokalisierte Roots
    '&XfJSI-',
})

_GMAIL_LEAF_ROLES = {
    'trash': 'Trash',
    'bin': 'Trash',
    'papierkorb': 'Trash',
    'drafts': 'Drafts',
    'entwürfe': 'Drafts',
    'entwuerfe': 'Drafts',
    'spam': 'Spam',
    'junk': 'Spam',
    'sent': 'Sent',
    'sent mail': 'Sent',
    'gesendet': 'Sent',
    'archive': 'Archive',
    'archiv': 'Archive',
    'all mail': 'All Mail',
    'alle nachrichten': 'All Mail',
    'starred': 'Starred',
    'markiert': 'Starred',
    'important': 'Important',
    'wichtig': 'Important',
}


def decode_imap_modutf7(value: str) -> str:
    """IMAP Modified UTF-7 (z. B. Entw&APw-rfe → Entwürfe) dekodieren."""
    if not value or '&' not in value:
        return value or ''
    import base64
    import re

    def _repl(match):
        body = match.group(1)
        if body == '':
            return '&'
        raw = body.replace(',', '/')
        pad = '=' * (-len(raw) % 4)
        try:
            return base64.b64decode(raw + pad).decode('utf-16-be')
        except Exception:
            return match.group(0)

    try:
        return re.sub(r'&([^-]*)-', _repl, value)
    except Exception:
        return value


def _imap_folder_leaf(folder_name: str) -> str:
    leaf = (folder_name or '').replace('\\', '/').rsplit('/', 1)[-1].strip()
    return decode_imap_modutf7(leaf)


def gmail_folder_role(folder_name: str):
    """Mappt Gmail/Google-Mail-Sonderordner auf Rollen (Trash, Sent, …) oder None."""
    if not folder_name:
        return None
    name = folder_name.strip()
    if name in _GMAIL_NAMESPACE_ROOTS:
        return None
    lower = name.lower()
    if not (
        lower.startswith('[gmail]/')
        or lower.startswith('[google mail]/')
        or name.startswith('&')
    ):
        return None
    leaf = _imap_folder_leaf(name).lower()
    # Umlaute normalisieren
    leaf_ascii = (
        leaf.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
    )
    return _GMAIL_LEAF_ROLES.get(leaf) or _GMAIL_LEAF_ROLES.get(leaf_ascii)


def is_standard_mail_folder(folder_name: str) -> bool:
    """Ob Ordner als Standardordner (nicht Custom) behandelt wird."""
    if not folder_name:
        return False
    name = folder_name.strip()
    if name == 'INBOX' or is_sent_folder(name):
        return True
    if name in (
        'Drafts', 'Trash', 'Deleted Messages', 'Spam', 'Junk',
        'Archive', 'Archives', 'All Mail', 'Starred', 'Important',
    ):
        return True
    return gmail_folder_role(name) is not None


def is_gmail_namespace_root(folder_name: str) -> bool:
    return (folder_name or '').strip() in _GMAIL_NAMESPACE_ROOTS


def find_sent_folder(mail_conn):
    """Find the Sent folder name on IMAP server (auto-detect)."""
    try:
        status, folders = mail_conn.list()
        if status != 'OK':
            return None
        
        for folder_info in folders:
            try:
                folder_name, _ = _parse_imap_list_line(folder_info)
                if folder_name and is_sent_folder(folder_name):
                    return folder_name
            except Exception:
                continue
        
        # Fallback: Versuche 'Sent' direkt
        try:
            status, _ = mail_conn.select('Sent')
            if status == 'OK':
                return 'Sent'
        except:
            pass
        
        return None
    except Exception as e:
        logging.error(f"Error finding Sent folder: {e}")
        return None


def save_email_to_imap_sent(msg):
    """Save sent email to IMAP Sent folder.
    
    Returns:
        tuple: (success: bool, folder_name: str|None) - Erfolg und Name des Gesendet-Ordners
    """
    try:
        imap_server = current_app.config.get('IMAP_SERVER')
        imap_port = current_app.config.get('IMAP_PORT', 993)
        imap_use_ssl = current_app.config.get('IMAP_USE_SSL', True)
        username = current_app.config.get('MAIL_USERNAME')
        password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([imap_server, username, password]):
            logging.warning("IMAP configuration missing, cannot save to Sent folder")
            return False, None
        
        # Verbindung herstellen
        try:
            if imap_use_ssl:
                mail_conn = imaplib.IMAP4_SSL(imap_server, imap_port, timeout=30)
            else:
                mail_conn = imaplib.IMAP4(imap_server, imap_port, timeout=30)
            
            mail_conn.login(username, password)
        except Exception as conn_error:
            logging.error(f"Fehler beim Verbinden mit IMAP zum Speichern der gesendeten E-Mail: {conn_error}")
            return False, None
        
        # Sent-Ordner finden
        sent_folder = find_sent_folder(mail_conn)
        if not sent_folder:
            logging.warning("Sent folder not found on IMAP server, cannot save email")
            try:
                mail_conn.close()
            except:
                pass
            try:
                mail_conn.logout()
            except:
                pass
            return False, None
        
        # E-Mail als RFC822-String konvertieren
        email_string = msg.as_string()
        email_bytes = email_string.encode('utf-8')
        
        # E-Mail im Sent-Ordner speichern
        try:
            mail_conn.select(sent_folder)
            result = mail_conn.append(sent_folder, None, None, email_bytes)
            
            if result[0] == 'OK':
                logging.info(f"Email saved to IMAP Sent folder '{sent_folder}'")
                try:
                    mail_conn.close()
                except:
                    pass
                try:
                    mail_conn.logout()
                except:
                    pass
                return True, sent_folder
            else:
                logging.warning(f"Failed to save email to IMAP Sent folder: {result}")
                try:
                    mail_conn.close()
                except:
                    pass
                try:
                    mail_conn.logout()
                except:
                    pass
                return False, sent_folder
        except Exception as e:
            logging.error(f"Error saving email to IMAP Sent folder: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            try:
                mail_conn.close()
            except:
                pass
            try:
                mail_conn.logout()
            except:
                pass
            return False, sent_folder
            
    except Exception as e:
        logging.error(f"Error connecting to IMAP to save sent email: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        return False, None


def _parse_imap_list_line(folder_info):
    """
    Parse IMAP LIST response line.
    Supports both:
      (\\HasNoChildren) "/" INBOX
      (\\HasNoChildren) "/" "Sent Messages"
    Returns (folder_name, separator) or (None, '/') if unusable.
    """
    import re
    if isinstance(folder_info, bytes):
        folder_str = folder_info.decode('utf-8', errors='ignore')
    else:
        folder_str = str(folder_info)

    match = re.match(
        r'''^\s*\(.*\)\s+("(?P<sep1>[^"]*)"|(?P<sep2>\S+))\s+("(?P<name1>.*)"|(?P<name2>\S+))\s*$''',
        folder_str,
    )
    if not match:
        parts = folder_str.split('"')
        if len(parts) >= 3:
            sep = (parts[1] or '/').strip() or '/'
            name = (parts[-2] or '').strip()
            if name and name not in ('/', '.'):
                return name, sep
        return None, '/'

    sep = match.group('sep1') if match.group('sep1') is not None else (match.group('sep2') or '/')
    sep = (sep or '/').strip() or '/'
    name = match.group('name1') if match.group('name1') is not None else match.group('name2')
    name = (name or '').strip()
    if not name or name in ('/', '.'):
        return None, sep
    return name, sep
def delete_email_from_imap(email_id, folder_name):
    """Delete email from IMAP server."""
    # Validiere email_id
    if not email_id:
        return False, "Ungültige E-Mail-ID (leer oder None)"
    
    # Konvertiere zu String und prüfe, ob es eine gültige UID ist
    try:
        uid_str = str(email_id).strip()
        if not uid_str or uid_str == 'None' or uid_str == '':
            return False, "Ungültige E-Mail-ID (leer)"
        # Prüfe, ob es eine Zahl ist (UIDs sind normalerweise Zahlen)
        int(uid_str)
    except (ValueError, AttributeError):
        return False, f"Ungültige E-Mail-ID Format: {email_id}"
    
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    try:
        status, messages = mail_conn.select(folder_name)
        if status != 'OK':
            mail_conn.logout()
            return False, f"Ordner '{folder_name}' konnte nicht geöffnet werden"
        
        # Versuche, die E-Mail als gelöscht zu markieren
        # Verwende UID STORE statt STORE, da wir mit UIDs arbeiten
        status, response = mail_conn.uid('STORE', uid_str, '+FLAGS', '\\Deleted')
        if status != 'OK':
            mail_conn.logout()
            error_msg = str(response) if response else "Unbekannter Fehler"
            return False, f"E-Mail konnte nicht als gelöscht markiert werden: {error_msg}"
        
        # Lösche die E-Mail endgültig
        status, response = mail_conn.expunge()
        if status != 'OK':
            mail_conn.logout()
            return False, f"E-Mail konnte nicht gelöscht werden: {response}"
        
        mail_conn.close()
        mail_conn.logout()
        return True, "E-Mail erfolgreich gelöscht"
        
    except Exception as e:
        try:
            mail_conn.logout()
        except:
            pass
        logging.error(f"IMAP delete failed: {str(e)}")
        return False, f"Lösch-Fehler: {str(e)}"


def move_email_in_imap(email_id, from_folder, to_folder):
    """Move email between IMAP folders."""
    # Validiere email_id
    if not email_id:
        return False, "Ungültige E-Mail-ID (leer oder None)"
    
    # Konvertiere zu String und prüfe, ob es eine gültige UID ist
    try:
        uid_str = str(email_id).strip()
        if not uid_str or uid_str == 'None' or uid_str == '':
            return False, "Ungültige E-Mail-ID (leer)"
        # Prüfe, ob es eine Zahl ist (UIDs sind normalerweise Zahlen)
        int(uid_str)
    except (ValueError, AttributeError):
        return False, f"Ungültige E-Mail-ID Format: {email_id}"
    
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    try:
        status, messages = mail_conn.select(from_folder)
        if status != 'OK':
            if from_folder != 'INBOX':
                status, messages = mail_conn.select('INBOX')
                if status != 'OK':
                    mail_conn.logout()
                    return False, f"Quellordner '{from_folder}' und INBOX konnten nicht geöffnet werden"
        
        # Verwende UID COPY statt COPY, da wir mit UIDs arbeiten
        status, response = mail_conn.uid('COPY', uid_str, to_folder)
        if status != 'OK':
            try:
                mail_conn.create(to_folder)
                status, response = mail_conn.uid('COPY', uid_str, to_folder)
                if status != 'OK':
                    mail_conn.logout()
                    return False, f"E-Mail konnte nicht nach '{to_folder}' kopiert werden (auch nach Ordner-Erstellung nicht)"
            except Exception as e:
                mail_conn.logout()
                return False, f"E-Mail konnte nicht nach '{to_folder}' kopiert werden: {str(e)}"
        
        # Verwende UID STORE statt STORE, da wir mit UIDs arbeiten
        status, response = mail_conn.uid('STORE', uid_str, '+FLAGS', '\\Deleted')
        if status != 'OK':
            mail_conn.logout()
            error_msg = str(response) if response else "Unbekannter Fehler"
            return False, f"E-Mail konnte nicht als gelöscht markiert werden: {error_msg}"
        
        status, response = mail_conn.expunge()
        if status != 'OK':
            mail_conn.logout()
            return False, f"E-Mail konnte nicht verschoben werden: {response}"
        
        mail_conn.close()
        mail_conn.logout()
        return True, f"E-Mail erfolgreich nach '{to_folder}' verschoben"
        
    except Exception as e:
        try:
            mail_conn.logout()
        except:
            pass
        logging.error(f"IMAP move failed: {str(e)}")
        return False, f"Verschieb-Fehler: {str(e)}"


# ---------------------------------------------------------------------------
# IMAP service operations (mail-manager Großupdate)
# Unified helpers that consolidate connect / select / execute / logout flows
# ---------------------------------------------------------------------------

SYSTEM_FOLDER_NAMES = {
    'INBOX', 'Sent', 'Sent Messages', 'Sent Items', 'Gesendet',
    'Gesendete Nachrichten', 'Drafts', 'Entwürfe',
    'Trash', 'Deleted Messages', 'Papierkorb',
    'Spam', 'Junk',
    'Archive', 'Archives', 'Archiv',
}

COLOR_DOT_CHOICES = {
    '': None,
    'none': None,
    'red': '$PrismaColorRed',
    'orange': '$PrismaColorOrange',
    'yellow': '$PrismaColorYellow',
    'green': '$PrismaColorGreen',
    'blue': '$PrismaColorBlue',
    'purple': '$PrismaColorPurple',
    'pink': '$PrismaColorPink',
    'gray': '$PrismaColorGray',
}


def _imap_error_payload(message, retryable=False, code=None):
    return {
        'success': False,
        'message': message,
        'retryable': retryable,
        'imap_status': code,
    }


def _imap_success_payload(message, extra=None):
    payload = {
        'success': True,
        'message': message,
        'imap_status': 'OK',
    }
    if extra:
        payload.update(extra)
    return payload


def _imap_select_folder(mail_conn, folder_name):
    """Select folder with fallback to quoted name. Returns (ok, status)."""
    try:
        status, _ = mail_conn.select(folder_name)
        if status == 'OK':
            return True, status
        try:
            status, _ = mail_conn.select(f'"{folder_name}"')
            if status == 'OK':
                return True, status
        except Exception:
            pass
        return False, status
    except Exception:
        return False, 'ERROR'


def _encode_imap_folder(name):
    """Encode folder path for IMAP LIST/CREATE/DELETE commands (IMAP UTF-7 simplified)."""
    # Our UI passes us UTF-8 strings; imaplib happily accepts them but quoting helps
    # with spaces or special characters.
    if name and (' ' in name or '/' in name or '.' in name):
        return f'"{name}"'
    return name


def imap_create_folder(folder_path):
    """Create an IMAP folder (supports nested paths with '/' or server separator)."""
    if not folder_path or not folder_path.strip():
        return _imap_error_payload("Ordnerpfad darf nicht leer sein")

    folder_path = folder_path.strip()

    mail_conn = connect_imap()
    if not mail_conn:
        return _imap_error_payload("IMAP-Verbindung fehlgeschlagen", retryable=True)

    try:
        encoded = _encode_imap_folder(folder_path)
        status, response = mail_conn.create(encoded)
        if status != 'OK':
            text = ''
            try:
                text = b''.join([r for r in response if isinstance(r, bytes)]).decode('utf-8', errors='ignore')
            except Exception:
                text = str(response)
            if 'ALREADYEXISTS' in text.upper() or 'already' in text.lower():
                return _imap_success_payload(f"Ordner '{folder_path}' existiert bereits")
            return _imap_error_payload(f"Ordner konnte nicht erstellt werden: {text}", code=status)

        # Subscribe to folder so it shows in IMAP clients
        try:
            mail_conn.subscribe(encoded)
        except Exception:
            pass

        return _imap_success_payload(f"Ordner '{folder_path}' erstellt")
    except Exception as e:
        logging.error(f"imap_create_folder failed: {e}")
        return _imap_error_payload(f"Ordnererstellung fehlgeschlagen: {str(e)}", retryable=True)
    finally:
        try:
            mail_conn.logout()
        except Exception:
            pass


def imap_delete_folder(folder_path):
    """Delete an IMAP folder (must be empty on most servers)."""
    if not folder_path or not folder_path.strip():
        return _imap_error_payload("Ordnerpfad darf nicht leer sein")
    folder_path = folder_path.strip()

    if folder_path in SYSTEM_FOLDER_NAMES:
        return _imap_error_payload("Systemordner können nicht gelöscht werden")

    mail_conn = connect_imap()
    if not mail_conn:
        return _imap_error_payload("IMAP-Verbindung fehlgeschlagen", retryable=True)

    try:
        encoded = _encode_imap_folder(folder_path)
        try:
            mail_conn.unsubscribe(encoded)
        except Exception:
            pass
        status, response = mail_conn.delete(encoded)
        if status != 'OK':
            text = ''
            try:
                text = b''.join([r for r in response if isinstance(r, bytes)]).decode('utf-8', errors='ignore')
            except Exception:
                text = str(response)
            return _imap_error_payload(f"Ordner konnte nicht gelöscht werden: {text}", code=status)
        return _imap_success_payload(f"Ordner '{folder_path}' gelöscht")
    except Exception as e:
        logging.error(f"imap_delete_folder failed: {e}")
        return _imap_error_payload(f"Ordnerlöschung fehlgeschlagen: {str(e)}", retryable=True)
    finally:
        try:
            mail_conn.logout()
        except Exception:
            pass


def imap_move_message(uid, from_folder, to_folder):
    """Move a message (thin wrapper around move_email_in_imap returning structured payload)."""
    if not uid:
        return _imap_error_payload("Ungültige IMAP-UID")
    if not to_folder:
        return _imap_error_payload("Zielordner fehlt")
    ok, msg = move_email_in_imap(uid, from_folder or 'INBOX', to_folder)
    if ok:
        return _imap_success_payload(msg)
    retryable = 'Verbindung' in (msg or '')
    return _imap_error_payload(msg, retryable=retryable)


def imap_mark_seen(uid, folder, seen=True):
    """Mark a message as seen/unseen on IMAP."""
    if not uid:
        return _imap_error_payload("Ungültige IMAP-UID")
    try:
        uid_str = str(uid).strip()
        int(uid_str)
    except (ValueError, AttributeError):
        return _imap_error_payload(f"Ungültige UID: {uid}")

    mail_conn = connect_imap()
    if not mail_conn:
        return _imap_error_payload("IMAP-Verbindung fehlgeschlagen", retryable=True)

    try:
        ok, status = _imap_select_folder(mail_conn, folder or 'INBOX')
        if not ok:
            return _imap_error_payload(f"Ordner '{folder}' konnte nicht geöffnet werden", code=status)
        flag_op = '+FLAGS' if seen else '-FLAGS'
        status, response = mail_conn.uid('STORE', uid_str, flag_op, '\\Seen')
        if status != 'OK':
            return _imap_error_payload(
                f"Gelesen-Status konnte nicht aktualisiert werden: {response}",
                code=status,
            )
        return _imap_success_payload("Gelesen-Status aktualisiert")
    except Exception as e:
        logging.error(f"imap_mark_seen failed: {e}")
        return _imap_error_payload(f"Gelesen-Status-Fehler: {str(e)}", retryable=True)
    finally:
        try:
            mail_conn.close()
        except Exception:
            pass
        try:
            mail_conn.logout()
        except Exception:
            pass


def imap_set_keyword(uid, folder, keyword, enabled=True):
    """Add/remove a custom IMAP keyword. Returns success payload even when server
    rejects the keyword (treat as local-only) so the caller can fall back cleanly."""
    if not uid:
        return _imap_error_payload("Ungültige IMAP-UID")
    if not keyword:
        return _imap_error_payload("Kein Schlüsselwort angegeben")

    try:
        uid_str = str(uid).strip()
        int(uid_str)
    except (ValueError, AttributeError):
        return _imap_error_payload(f"Ungültige UID: {uid}")

    mail_conn = connect_imap()
    if not mail_conn:
        return _imap_error_payload("IMAP-Verbindung fehlgeschlagen", retryable=True)

    try:
        ok, status = _imap_select_folder(mail_conn, folder or 'INBOX')
        if not ok:
            return _imap_error_payload(f"Ordner '{folder}' konnte nicht geöffnet werden", code=status)
        flag_op = '+FLAGS' if enabled else '-FLAGS'
        status, response = mail_conn.uid('STORE', uid_str, flag_op, keyword)
        if status != 'OK':
            # Keyword unsupported: return soft payload so caller keeps local state only
            return {
                'success': True,
                'imap_status': status,
                'message': 'Server unterstützt Keyword nicht, lokal gespeichert',
                'keyword_supported': False,
            }
        return {
            'success': True,
            'imap_status': 'OK',
            'message': 'Keyword aktualisiert',
            'keyword_supported': True,
        }
    except Exception as e:
        logging.error(f"imap_set_keyword failed: {e}")
        return {
            'success': True,
            'imap_status': 'ERROR',
            'message': f'Keyword nicht unterstützt: {str(e)} – lokal gespeichert',
            'keyword_supported': False,
        }
    finally:
        try:
            mail_conn.close()
        except Exception:
            pass
        try:
            mail_conn.logout()
        except Exception:
            pass
