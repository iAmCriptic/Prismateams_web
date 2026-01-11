from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file, Response
from flask_login import login_required, current_user
from uuid import uuid4
from app import db, mail
from app.blueprints.sse import emit_email_sync_status
from app.models.email import EmailMessage, EmailPermission, EmailAttachment, EmailFolder
from app.models.settings import SystemSettings
from app.utils.notifications import send_email_notification
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from flask_mail import Message
from datetime import datetime, timedelta
from html import unescape
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
from sqlalchemy import func, cast, Integer
import re

from app.utils.email_sender import get_logo_base64, get_logo_data, send_email_with_lock
from app.utils.lock_manager import acquire_email_sync_lock

email_bp = Blueprint('email', __name__)


def get_portal_display_name():
    portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
    if portal_name_setting and portal_name_setting.value and portal_name_setting.value.strip():
        return portal_name_setting.value
    return current_app.config.get('APP_NAME', 'Prismateams')


def html_to_plain_text(html_content: str) -> str:
    if not html_content:
        return ''

    text = re.sub(r'<\s*br\s*/?>', '\n', html_content, flags=re.IGNORECASE)
    text = re.sub(r'</\s*p\s*>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return unescape(text).strip()


def build_footer_html():
    footer_template = SystemSettings.query.filter_by(key='email_footer_template').first()
    portal_name = get_portal_display_name()

    if footer_template and footer_template.value:
        footer_html = footer_template.value
        replacements = {
            '<user>': current_user.full_name or '',
            '<email>': current_user.email or '',
            '<app_name>': portal_name,
            '<date>': datetime.utcnow().strftime('%d.%m.%Y'),
            '<time>': datetime.utcnow().strftime('%H:%M')
        }
        for placeholder, value in replacements.items():
            footer_html = footer_html.replace(placeholder, value)
        
        paragraphs = re.split(r'\n\n+', footer_html)
        formatted_paragraphs = []
        for para in paragraphs:
            if para.strip():
                para_with_br = para.strip().replace('\n', '<br>')
                formatted_paragraphs.append(f'<p>{para_with_br}</p>')
        
        footer_html = ''.join(formatted_paragraphs) if formatted_paragraphs else footer_html
        return footer_html

    footer_text_setting = SystemSettings.query.filter_by(key='email_footer_text').first()

    lines = []
    if footer_text_setting and footer_text_setting.value:
        lines.append(footer_text_setting.value)
    lines.append(f"Gesendet von {current_user.full_name}")

    return ''.join(f'<p>{line}</p>' for line in lines if line and line.strip())


def render_custom_email(subject: str, body_html: str, logo_cid: str = None, is_preview: bool = False):
    body_html = body_html or ''
    footer_html = build_footer_html()
    
    if footer_html:
        combined_html = body_html + '<p style="margin-top: 1em;"></p>' + footer_html
    else:
        combined_html = body_html

    app_name = get_portal_display_name()
    logo_base64 = get_logo_base64()
    current_year = datetime.utcnow().year

    # In der Vorschau Base64 verwenden (CID funktioniert nicht ohne echte E-Mail)
    # Beim Versenden CID verwenden (funktioniert mit Anhang)
    use_base64_for_preview = is_preview or logo_cid is None

    rendered_html = render_template(
        'emails/custom_mail.html',
        app_name=app_name,
        logo_base64=logo_base64 if use_base64_for_preview else None,
        logo_cid=logo_cid if not use_base64_for_preview else None,
        subject=subject,
        body_html=Markup(combined_html),
        current_year=current_year
    )

    plain_body = html_to_plain_text(combined_html)
    disclaimer_plain = ("Diese E-Mail enthält sensible Inhalte und ist nur für den genannten Empfänger bestimmt. "
                        "Sollten Sie nicht der adressierte Nutzer sein, wenden Sie sich bitte an den Versender und löschen Sie diese E-Mail.")
    copyright_plain = f"© {current_year} {app_name}. Alle Rechte vorbehalten."

    plain_sections = [section for section in [plain_body, disclaimer_plain, copyright_plain] if section]
    rendered_plain = '\n\n'.join(plain_sections)

    return rendered_html, rendered_plain


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


def connect_imap():
    """Connect to IMAP server with robust error handling."""
    try:
        imap_server = current_app.config.get('IMAP_SERVER')
        imap_port = current_app.config.get('IMAP_PORT', 993)
        imap_use_ssl = current_app.config.get('IMAP_USE_SSL', True)
        username = current_app.config.get('MAIL_USERNAME')
        password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([imap_server, username, password]):
            raise Exception("IMAP configuration missing - check .env file")
        
        if imap_use_ssl:
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        else:
            mail = imaplib.IMAP4(imap_server, imap_port)
        
        mail.login(username, password)
        mail.select('INBOX')
        
        return mail
    except Exception as e:
        error_msg = str(e).encode('ascii', errors='replace').decode('ascii')
        logging.error(f"IMAP connection failed: {error_msg}")
        return None


def find_sent_folder(mail_conn):
    """Find the Sent folder name on IMAP server (auto-detect)."""
    try:
        status, folders = mail_conn.list()
        if status != 'OK':
            return None
        
        # Mögliche Namen für den Sent-Ordner
        sent_folder_names = ['Sent', 'Sent Messages', 'Gesendet', 'Gesendete Nachrichten']
        
        for folder_info in folders:
            try:
                folder_str = folder_info.decode('utf-8')
                parts = folder_str.split('"')
                if len(parts) >= 3:
                    folder_name = parts[-2]
                    if folder_name in sent_folder_names:
                        return folder_name
            except:
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
    """Save sent email to IMAP Sent folder."""
    try:
        imap_server = current_app.config.get('IMAP_SERVER')
        imap_port = current_app.config.get('IMAP_PORT', 993)
        imap_use_ssl = current_app.config.get('IMAP_USE_SSL', True)
        username = current_app.config.get('MAIL_USERNAME')
        password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([imap_server, username, password]):
            logging.warning("IMAP configuration missing, cannot save to Sent folder")
            return False
        
        # Verbindung herstellen
        if imap_use_ssl:
            mail_conn = imaplib.IMAP4_SSL(imap_server, imap_port)
        else:
            mail_conn = imaplib.IMAP4(imap_server, imap_port)
        
        mail_conn.login(username, password)
        
        # Sent-Ordner finden
        sent_folder = find_sent_folder(mail_conn)
        if not sent_folder:
            logging.warning("Sent folder not found on IMAP server, cannot save email")
            mail_conn.close()
            mail_conn.logout()
            return False
        
        # E-Mail als RFC822-String konvertieren
        email_string = msg.as_string()
        email_bytes = email_string.encode('utf-8')
        
        # E-Mail im Sent-Ordner speichern
        try:
            mail_conn.select(sent_folder)
            result = mail_conn.append(sent_folder, None, None, email_bytes)
            
            if result[0] == 'OK':
                logging.info(f"Email saved to IMAP Sent folder '{sent_folder}'")
                mail_conn.close()
                mail_conn.logout()
                return True
            else:
                logging.warning(f"Failed to save email to IMAP Sent folder: {result}")
                mail_conn.close()
                mail_conn.logout()
                return False
        except Exception as e:
            logging.error(f"Error saving email to IMAP Sent folder: {e}")
            try:
                mail_conn.close()
                mail_conn.logout()
            except:
                pass
            return False
            
    except Exception as e:
        logging.error(f"Error connecting to IMAP to save sent email: {e}")
        return False


def sync_imap_folders():
    """Sync IMAP folders from server to database."""
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    try:
        status, folders = mail_conn.list()
        if status != 'OK':
            return False, "Ordner-Liste konnte nicht abgerufen werden"
        
        synced_folders = []
        skipped_folders = []
        
        logging.info(f"Processing {len(folders)} folders from IMAP server")
        
        for folder_info in folders:
            try:
                folder_str = folder_info.decode('utf-8')
                parts = folder_str.split('"')
                if len(parts) >= 3:
                    folder_name = parts[-2]
                    logging.debug(f"Found folder: '{folder_name}'")
                    
                    if not folder_name or folder_name.strip() == '' or folder_name == '/' or folder_name.strip() == '/':
                        logging.debug(f"Skipping invalid folder name: '{folder_name}'")
                        continue
                    
                    skip_folders = ['[Gmail]', '[Google Mail]', '&XfJT0ZAB-', '&XfJSI-']
                    if any(skip in folder_name for skip in skip_folders):
                        logging.debug(f"Skipping system folder: '{folder_name}'")
                        continue
                    
                    is_system = folder_name in ['INBOX', 'Sent', 'Sent Messages', 'Drafts', 'Trash', 'Deleted Messages', 'Spam', 'Junk', 'Archive', 'Archives']
                    display_name = EmailFolder.get_folder_display_name(folder_name)

                    separator = parts[1] if len(parts) >= 3 and parts[1] else '/'
                    separator = separator.strip() or '/'

                    parent_folder = None
                    if separator in folder_name:
                        parent_candidate = folder_name.rsplit(separator, 1)[0]
                        parent_folder = parent_candidate if parent_candidate and parent_candidate != folder_name else None

                    now = datetime.utcnow()
                    folder_type = 'standard' if is_system else 'custom'
                    folder_payload = {
                        'name': folder_name,
                        'display_name': display_name,
                        'folder_type': folder_type,
                        'is_system': is_system,
                        'parent_folder': parent_folder,
                        'separator': separator,
                        'last_synced': now,
                        'created_at': now,
                    }

                    dialect_name = db.session.bind.dialect.name if db.session.bind else ''

                    try:
                        if dialect_name in ('mysql', 'mariadb'):
                            insert_stmt = mysql_insert(EmailFolder.__table__).values(**folder_payload)
                            update_stmt = {
                                'display_name': insert_stmt.inserted.display_name,
                                'folder_type': insert_stmt.inserted.folder_type,
                                'is_system': insert_stmt.inserted.is_system,
                                'parent_folder': insert_stmt.inserted.parent_folder,
                                'separator': insert_stmt.inserted.separator,
                                'last_synced': insert_stmt.inserted.last_synced,
                            }
                            db.session.execute(insert_stmt.on_duplicate_key_update(**update_stmt))
                            synced_folders.append(folder_name)
                            if folder_type == 'standard':
                                logging.debug(f"Upserted system folder: '{folder_name}' ({display_name})")
                            else:
                                logging.info(f"Upserted folder: '{folder_name}' ({display_name})")
                        else:
                            existing_folder = EmailFolder.query.filter_by(name=folder_name).first()
                            if existing_folder:
                                existing_folder.display_name = display_name
                                existing_folder.folder_type = folder_type
                                existing_folder.is_system = is_system
                                existing_folder.parent_folder = parent_folder
                                existing_folder.separator = separator
                                existing_folder.last_synced = now
                                logging.debug(f"Updated existing folder: '{folder_name}'")
                            else:
                                folder_payload_for_insert = folder_payload.copy()
                                db.session.add(EmailFolder(**folder_payload_for_insert))
                                logging.info(f"Added new folder: '{folder_name}' ({display_name})")
                            synced_folders.append(folder_name)
                    except IntegrityError:
                        db.session.rollback()
                        existing_folder = EmailFolder.query.filter_by(name=folder_name).first()
                        if existing_folder:
                            existing_folder.last_synced = datetime.utcnow()
                            synced_folders.append(folder_name)
                            logging.debug(f"Recovered folder after IntegrityError: '{folder_name}'")
                        else:
                            logging.warning(f"IntegrityError without existing folder for '{folder_name}' – retrying insert")
                            try:
                                db.session.add(EmailFolder(
                                    name=folder_name,
                                    display_name=display_name,
                                    folder_type=folder_type,
                                    is_system=is_system,
                                    parent_folder=parent_folder,
                                    separator=separator,
                                    last_synced=datetime.utcnow()
                                ))
                                db.session.flush()
                                synced_folders.append(folder_name)
                                logging.info(f"Inserted folder after retry: '{folder_name}'")
                            except IntegrityError as retry_error:
                                db.session.rollback()
                                logging.error(f"Failed to insert folder '{folder_name}' after retry: {retry_error}")
                                continue
                else:
                    skipped_folders.append(folder_str)
                        
            except Exception as e:
                logging.error(f"Fehler beim Verarbeiten des Ordners '{folder_str if 'folder_str' in locals() else folder_info}': {e}")
                continue
        
        logging.info(f"Synced {len(synced_folders)} folders, skipped {len(skipped_folders)} invalid folders")
        
        invalid_folder_names = ['/', '']
        for invalid_name in invalid_folder_names:
            invalid_folders = EmailFolder.query.filter_by(name=invalid_name).all()
            for invalid_folder in invalid_folders:
                logging.info(f"Removing invalid folder '{invalid_name}' from database")
                db.session.delete(invalid_folder)
        
        db.session.commit()
        mail_conn.close()
        mail_conn.logout()
        
        return True, f"{len(synced_folders)} Ordner synchronisiert"
        
    except Exception as e:
        logging.error(f"Folder sync failed: {str(e)}")
        return False, f"Ordner-Sync-Fehler: {str(e)}"


def sync_emails_from_folder(folder_name):
    """Sync emails from a specific IMAP folder with bidirectional support."""
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    stats = {
        'new_emails': 0,
        'updated_emails': 0,
        'moved_emails': 0,
        'deleted_emails': 0,
        'skipped_emails': 0,
        'errors': 0
    }
    
    try:
        try:
            status, messages = mail_conn.select(folder_name)
            if status != 'OK':
                try:
                    status, messages = mail_conn.select(f'"{folder_name}"')
                except:
                    pass
                if status != 'OK':
                    # Ordner existiert nicht auf dem Server - überspringen, aber in DB behalten
                    error_msg = messages[0].decode() if messages else 'Unbekannter Fehler'
                    # Prüfe ob es sich um einen Archiv-Ordner handelt (Archive oder Archives)
                    is_archive_folder = folder_name in ['Archive', 'Archives']
                    if "doesn't exist" in error_msg or "Mailbox doesn't exist" in error_msg:
                        if is_archive_folder:
                            logging.debug(f"IMAP folder '{folder_name}' does not exist on server, skipping sync (normal for empty archive folders): {error_msg}")
                        else:
                            logging.debug(f"IMAP folder '{folder_name}' does not exist on server, skipping sync: {error_msg}")
                        try:
                            mail_conn.logout()
                        except:
                            pass
                        return True, f"Ordner '{folder_name}' existiert nicht auf dem Server, übersprungen"
                    else:
                        logging.debug(f"IMAP folder selection failed for '{folder_name}': {error_msg}")
                        try:
                            mail_conn.logout()
                        except:
                            pass
                        return True, f"Ordner '{folder_name}' konnte nicht geöffnet werden, übersprungen: {error_msg}"
        except Exception as e:
            logging.debug(f"Exception while selecting folder '{folder_name}': {e}")
            try:
                mail_conn.logout()
            except:
                pass
            return True, f"Ordner '{folder_name}' konnte nicht geöffnet werden, übersprungen: {str(e)}"
        
        # Ermittle die höchste bereits synchronisierte UID für diesen Ordner
        highest_uid = None
        try:
            highest_uid_result = db.session.query(
                func.max(cast(EmailMessage.imap_uid, Integer))
            ).filter_by(folder=folder_name).scalar()
            if highest_uid_result:
                highest_uid = int(highest_uid_result)
                logging.debug(f"Highest UID for folder '{folder_name}': {highest_uid}")
        except Exception as e:
            logging.debug(f"Could not determine highest UID for folder '{folder_name}': {e}")
        
        # Suche nur nach neuen E-Mails (UID-basiert)
        if highest_uid:
            search_criteria = f'UID {highest_uid + 1}:*'
            logging.debug(f"Searching for new emails in folder '{folder_name}' with UID > {highest_uid}")
        else:
            # Erste Synchronisation: Hole alle E-Mails, aber verarbeite nur die letzten N
            search_criteria = 'ALL'
            logging.debug(f"First sync for folder '{folder_name}', fetching all emails")
        
        status, messages = mail_conn.search(None, search_criteria)
        if status != 'OK':
            logging.error(f"IMAP search failed for folder '{folder_name}': {messages}")
            return False, f"E-Mail-Suche in Ordner '{folder_name}' fehlgeschlagen: {messages[0].decode() if messages else 'Unbekannter Fehler'}"
        
        email_ids = messages[0].split()
        logging.debug(f"Found {len(email_ids)} new email IDs in folder '{folder_name}'")
        
        if len(email_ids) == 0:
            logging.debug(f"No new emails found in folder '{folder_name}'")
            mail_conn.close()
            mail_conn.logout()
            return True, f"Ordner '{folder_name}': Keine neuen E-Mails vorhanden"
        
        # Für die Prüfung gelöschter E-Mails: Hole alle UIDs vom Server (nur wenn nicht erste Sync)
        current_imap_uids = set()
        if highest_uid:
            # Nur wenn wir schon E-Mails haben, prüfen wir auf gelöschte
            status_all, messages_all = mail_conn.search(None, 'ALL')
            if status_all == 'OK':
                all_email_ids = messages_all[0].split()
                for email_id in all_email_ids:
                    current_imap_uids.add(email_id.decode())
                
                # Optimierte Prüfung: Nur UIDs abfragen statt alle E-Mails
                existing_uids = db.session.query(EmailMessage.imap_uid).filter_by(
                    folder=folder_name
                ).filter(EmailMessage.imap_uid.isnot(None)).all()
                existing_uid_set = {uid[0] for uid in existing_uids if uid[0]}
                
                for existing_uid in existing_uid_set:
                    if existing_uid not in current_imap_uids:
                        # E-Mail existiert nicht mehr auf Server
                        email_obj = EmailMessage.query.filter_by(
                            imap_uid=existing_uid,
                            folder=folder_name
                        ).first()
                        if email_obj:
                            if email_obj.is_deleted_imap:
                                db.session.delete(email_obj)
                                stats['deleted_emails'] += 1
                            else:
                                other_folder_email = EmailMessage.query.filter_by(
                                    message_id=email_obj.message_id
                                ).filter(EmailMessage.folder != folder_name).first()
                                
                                if other_folder_email:
                                    db.session.delete(email_obj)
                                    stats['moved_emails'] += 1
                                else:
                                    email_obj.is_deleted_imap = True
                                    email_obj.last_imap_sync = datetime.utcnow()
                                    stats['deleted_emails'] += 1
        
        # Bei erster Synchronisation: Nur die letzten N E-Mails verarbeiten
        if not highest_uid:
            max_emails = 100 if folder_name not in ['INBOX', 'Sent', 'Drafts', 'Trash', 'Spam', 'Archive', 'Archives'] else 30
            emails_to_process = email_ids[-max_emails:] if len(email_ids) > max_emails else email_ids
            logging.debug(f"First sync: Processing {len(emails_to_process)} emails from folder '{folder_name}' (max: {max_emails})")
        else:
            emails_to_process = email_ids
            logging.debug(f"Processing {len(emails_to_process)} new emails from folder '{folder_name}'")
        
        for idx, email_id in enumerate(emails_to_process, 1):
            try:
                # FLAGS abrufen um Gelesen-Status zu bestimmen
                is_read_imap = False
                try:
                    flags_status, flags_result = mail_conn.fetch(email_id, '(FLAGS)')
                    if flags_status == 'OK' and flags_result and len(flags_result) > 0:
                        flags_entry = flags_result[0]
                        # FLAGS können als Tuple oder Bytes kommen
                        if isinstance(flags_entry, tuple):
                            flags_str = flags_entry[0].decode('utf-8', errors='ignore') if isinstance(flags_entry[0], bytes) else str(flags_entry[0])
                        else:
                            flags_str = flags_entry.decode('utf-8', errors='ignore') if isinstance(flags_entry, bytes) else str(flags_entry)
                        
                        # Prüfe ob \Seen Flag vorhanden ist
                        is_read_imap = '\\Seen' in flags_str or '\\SEEN' in flags_str
                except Exception as flags_error:
                    logging.debug(f"Failed to fetch FLAGS for email {email_id.decode()} from folder '{folder_name}': {flags_error}")
                    # Weiter mit is_read_imap = False
                
                # RFC822 (E-Mail-Inhalt) abrufen
                status, msg_data = mail_conn.fetch(email_id, '(RFC822)')
                if status != 'OK':
                    logging.debug(f"Failed to fetch email {email_id.decode()} from folder '{folder_name}': {msg_data}")
                    stats['errors'] += 1
                    continue
                
                raw_email = msg_data[0][1]
                email_msg = email_module.message_from_bytes(raw_email)
                
                sender_raw = email_msg.get('From', '')
                sender = decode_header_field(sender_raw)
                if not sender:
                    sender = "Unknown Sender"
                
                subject_raw = email_msg.get('Subject', '')
                subject = decode_header_field(subject_raw)
                if not subject:
                    subject = "(No Subject)"
                
                date_str = email_msg.get('Date', '')
                message_id = email_msg.get('Message-ID', '')
                
                recipients_raw = email_msg.get('To', '')
                recipients = decode_header_field(recipients_raw)
                
                cc_raw = email_msg.get('Cc', '')
                cc = decode_header_field(cc_raw)
                
                bcc_raw = email_msg.get('Bcc', '')
                bcc = decode_header_field(bcc_raw)
                
                imap_uid_str = email_id.decode()
                
                if not message_id:
                    try:
                        from email.utils import parsedate_to_datetime
                        parsed_date = parsedate_to_datetime(date_str) if date_str else datetime.utcnow()
                        date_str_clean = parsed_date.strftime('%Y%m%d%H%M%S') if parsed_date else ''
                    except:
                        date_str_clean = datetime.utcnow().strftime('%Y%m%d%H%M%S')
                    
                    message_id = f"<generated-{folder_name}-{imap_uid_str}-{date_str_clean}@local>"
                    logging.debug(f"Generated message_id for email without Message-ID: {message_id}")
                
                received_at = datetime.utcnow()
                try:
                    from email.utils import parsedate_to_datetime
                    received_at = parsedate_to_datetime(date_str)
                except:
                    pass
                
                # Bestimme is_read Status für Updates:
                # 1. E-Mails im "Sent"-Ordner sind immer als gelesen markiert
                # 2. Andere Ordner: basierend auf IMAP FLAGS (\Seen)
                is_sent_folder = folder_name in ['Sent', 'Sent Messages']
                if is_sent_folder:
                    is_read_status = True
                else:
                    is_read_status = is_read_imap
                
                existing_in_folder = EmailMessage.query.filter_by(
                    imap_uid=imap_uid_str,
                    folder=folder_name
                ).first()
                
                if existing_in_folder:
                    try:
                        existing_in_folder.last_imap_sync = datetime.utcnow()
                        existing_in_folder.is_deleted_imap = False
                        existing_in_folder.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                        existing_in_folder.is_sent = is_sent_folder  # Aktualisiere is_sent Status
                        stats['updated_emails'] += 1
                        db.session.commit()
                        continue
                    except Exception as update_error:
                        if "MySQL server has gone away" in str(update_error) or "ConnectionResetError" in str(update_error):
                            logging.debug("Database connection lost during update, attempting to reconnect...")
                            db.session.rollback()
                            db.session.close()
                            db.session = db.create_scoped_session()
                            existing_in_folder = EmailMessage.query.filter_by(
                                imap_uid=imap_uid_str,
                                folder=folder_name
                            ).first()
                            if existing_in_folder:
                                existing_in_folder.last_imap_sync = datetime.utcnow()
                                existing_in_folder.is_deleted_imap = False
                                existing_in_folder.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                                existing_in_folder.is_sent = is_sent_folder  # Aktualisiere is_sent Status
                                stats['updated_emails'] += 1
                                db.session.commit()
                                logging.debug("Database reconnection successful for update")
                            continue
                        else:
                            raise update_error
                
                existing_by_message_id = EmailMessage.query.filter_by(message_id=message_id).first()
                if existing_by_message_id:
                    if existing_by_message_id.folder == folder_name:
                        try:
                            existing_by_message_id.last_imap_sync = datetime.utcnow()
                            existing_by_message_id.is_deleted_imap = False
                            existing_by_message_id.imap_uid = imap_uid_str
                            existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                            existing_by_message_id.is_sent = is_sent_folder  # Aktualisiere is_sent Status
                            stats['updated_emails'] += 1
                            db.session.commit()
                            continue
                        except Exception as update_error:
                            if "MySQL server has gone away" in str(update_error) or "ConnectionResetError" in str(update_error):
                                logging.debug("Database connection lost during update, attempting to reconnect...")
                                db.session.rollback()
                                db.session.close()
                                db.session = db.create_scoped_session()
                                existing_by_message_id = EmailMessage.query.filter_by(message_id=message_id).first()
                                if existing_by_message_id and existing_by_message_id.folder == folder_name:
                                    existing_by_message_id.last_imap_sync = datetime.utcnow()
                                    existing_by_message_id.is_deleted_imap = False
                                    existing_by_message_id.imap_uid = imap_uid_str
                                    existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                                    existing_by_message_id.is_sent = is_sent_folder  # Aktualisiere is_sent Status
                                    stats['updated_emails'] += 1
                                    db.session.commit()
                                    logging.debug("Database reconnection successful for update")
                                continue
                            else:
                                raise update_error
                    else:
                        try:
                            existing_by_message_id.folder = folder_name
                            existing_by_message_id.imap_uid = imap_uid_str
                            existing_by_message_id.last_imap_sync = datetime.utcnow()
                            existing_by_message_id.is_deleted_imap = False
                            existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP beim Ordnerwechsel
                            existing_by_message_id.is_sent = is_sent_folder  # Aktualisiere is_sent Status
                            stats['moved_emails'] += 1
                            db.session.commit()
                            continue
                        except Exception as move_error:
                            if "MySQL server has gone away" in str(move_error) or "ConnectionResetError" in str(move_error):
                                logging.debug("Database connection lost during move, attempting to reconnect...")
                                db.session.rollback()
                                db.session.close()
                                db.session = db.create_scoped_session()
                                existing_by_message_id = EmailMessage.query.filter_by(message_id=message_id).first()
                                if existing_by_message_id:
                                    existing_by_message_id.folder = folder_name
                                    existing_by_message_id.imap_uid = imap_uid_str
                                    existing_by_message_id.last_imap_sync = datetime.utcnow()
                                    existing_by_message_id.is_deleted_imap = False
                                    existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP beim Ordnerwechsel
                                    existing_by_message_id.is_sent = is_sent_folder  # Aktualisiere is_sent Status
                                    stats['moved_emails'] += 1
                                    db.session.commit()
                                    logging.debug("Database reconnection successful for move")
                                continue
                            else:
                                raise move_error
                
                body_text = ""
                body_html = ""
                has_attachments = False
                attachments_data = []
                
                if email_msg.is_multipart():
                    for part in email_msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = part.get('Content-Disposition', '')
                        
                        if ('attachment' in content_disposition or 'inline' in content_disposition) and not content_type.startswith('text/'):
                            has_attachments = True
                            
                            try:
                                filename = part.get_filename()
                                if not filename:
                                    extension = content_type.split('/')[-1] if '/' in content_type else 'bin'
                                    filename = f"attachment_{len(attachments_data)}.{extension}"
                                
                                if filename:
                                    try:
                                        from email.header import decode_header
                                        decoded_filename = decode_header(filename)
                                        if decoded_filename and decoded_filename[0][0]:
                                            filename = decoded_filename[0][0]
                                    except:
                                        pass
                                    
                                    # Kürze Dateinamen auf maximal 500 Zeichen (Datenbanklimit)
                                    filename = truncate_filename(filename, max_length=500)
                                
                                try:
                                    payload = None
                                    try:
                                        payload = part.get_payload(decode=True)
                                    except Exception as decode_error:
                                        logging.error(f"Failed to decode attachment '{filename}': {decode_error}")
                                        has_attachments = True
                                        continue
                                    
                                    if payload:
                                        attachment_size = len(payload)
                                        
                                        max_db_size = 1 * 1024 * 1024
                                        
                                        if attachment_size > max_db_size:
                                            import os
                                            
                                            attachments_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'attachments')
                                            os.makedirs(attachments_dir, exist_ok=True)
                                            
                                            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                                            safe_filename = "".join(c for c in filename if c.isalnum() or c in '._- ')
                                            file_path = os.path.join(attachments_dir, f"{timestamp}_{safe_filename}")
                                            
                                            try:
                                                with open(file_path, 'wb') as f:
                                                    f.write(payload)
                                                logging.debug(f"Large attachment saved to disk: {file_path}")
                                                
                                                attachments_data.append({
                                                    'filename': filename,
                                                    'content_type': content_type,
                                                    'content': None,
                                                    'file_path': file_path,
                                                    'size': attachment_size,
                                                    'is_inline': 'inline' in content_disposition,
                                                    'content_id': part.get('Content-ID', '').strip('<>'),
                                                    'is_large_file': True
                                                })
                                            except Exception as file_error:
                                                logging.error(f"Error saving large file to disk: {file_error}")
                                                attachments_data.append({
                                                    'filename': filename,
                                                    'content_type': content_type,
                                                    'content': payload,
                                                    'file_path': None,
                                                    'size': attachment_size,
                                                    'is_inline': 'inline' in content_disposition,
                                                    'content_id': part.get('Content-ID', '').strip('<>'),
                                                    'is_large_file': False
                                                })
                                        else:
                                            attachments_data.append({
                                                'filename': filename,
                                                'content_type': content_type,
                                                'content': payload,
                                                'file_path': None,
                                                'size': attachment_size,
                                                'is_inline': 'inline' in content_disposition,
                                                'content_id': part.get('Content-ID', '').strip('<>'),
                                                'is_large_file': False
                                            })
                                        
                                        logging.debug(f"Added attachment: '{filename}' ({attachment_size / (1024*1024):.2f} MB) - {'disk' if attachment_size > max_db_size else 'database'}")
                                except MemoryError as mem_error:
                                    logging.error(f"Memory error processing attachment '{filename}': {mem_error}. Email will be saved without this attachment.")
                                    has_attachments = True
                                    continue
                                except Exception as payload_error:
                                    logging.error(f"Error getting payload for attachment '{filename}': {payload_error}. Email will be saved without this attachment.")
                                    has_attachments = True
                                    continue
                            except Exception as e:
                                logging.error(f"Error processing attachment '{filename if 'filename' in locals() else 'unknown'}': {e}. Email will be saved without this attachment.")
                                has_attachments = True
                                continue
                        
                        if content_type == "text/plain":
                            try:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    import chardet
                                    detected = chardet.detect(payload)
                                    encoding = detected.get('encoding', 'utf-8')
                                    decoded_text = payload.decode(encoding, errors='ignore')
                                    if decoded_text.strip():
                                        body_text = decoded_text
                            except:
                                pass
                        elif content_type == "text/html":
                            try:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    import chardet
                                    detected = chardet.detect(payload)
                                    encoding = detected.get('encoding', 'utf-8')
                                    decoded_html = payload.decode(encoding, errors='ignore')
                                    if decoded_html.strip():
                                        if body_html:
                                            body_html += "\n" + decoded_html
                                        else:
                                            body_html = decoded_html
                            except Exception as e:
                                logging.error(f"Error processing HTML part: {e}")
                                pass
                else:
                    content_type = email_msg.get_content_type()
                    try:
                        payload = email_msg.get_payload(decode=True)
                        if payload:
                            import chardet
                            detected = chardet.detect(payload)
                            encoding = detected.get('encoding', 'utf-8')
                            decoded_content = payload.decode(encoding, errors='ignore')
                            
                            if content_type == "text/html":
                                if decoded_content.strip():
                                    body_html = decoded_content
                            else:
                                if decoded_content.strip():
                                    body_text = decoded_content
                    except Exception as e:
                        logging.error(f"Error processing single part email: {e}")
                        pass
                
                
                html_max_length = current_app.config.get('EMAIL_HTML_MAX_LENGTH', 0)
                text_max_length = current_app.config.get('EMAIL_TEXT_MAX_LENGTH', 10000)
                
                if html_max_length > 0 and body_html and len(body_html) > html_max_length:
                    body_html = body_html[:html_max_length]
                
                if text_max_length > 0 and body_text and len(body_text) > text_max_length:
                    body_text = body_text[:text_max_length]
                
                # Bestimme is_read Status:
                # 1. E-Mails im "Sent"-Ordner sind immer als gelesen markiert (man hat sie selbst versendet)
                # 2. Andere Ordner: basierend auf IMAP FLAGS (\Seen)
                is_sent_folder = folder_name in ['Sent', 'Sent Messages']
                if is_sent_folder:
                    is_read_status = True
                else:
                    is_read_status = is_read_imap
                
                email_entry = EmailMessage(
                    message_id=message_id,
                    sender=sender,
                    subject=subject,
                    recipients=recipients or 'Unknown',
                    cc=cc,
                    bcc=bcc,
                    body_text=body_text if body_text else '',
                    body_html=body_html if body_html else '',
                    has_attachments=has_attachments,
                    folder=folder_name,
                    imap_uid=email_id.decode(),
                    last_imap_sync=datetime.utcnow(),
                    is_deleted_imap=False,
                    received_at=received_at,
                    is_read=is_read_status,
                    is_sent=is_sent_folder
                )
                
                try:
                    db.session.add(email_entry)
                    db.session.flush()
                except IntegrityError as integrity_error:
                    if "Duplicate entry" in str(integrity_error) or "1062" in str(integrity_error):
                        logging.debug(f"Email with message_id '{message_id}' already exists in another folder, skipping")
                        stats['skipped_emails'] += 1
                        db.session.rollback()
                        continue
                    else:
                        raise
                
                for attachment_data in attachments_data:
                    try:
                        attachment_size = attachment_data['size']
                        filename = truncate_filename(attachment_data['filename'], max_length=500)
                        
                        if attachment_size > 1 * 1024 * 1024:
                            logging.info(f"Processing large attachment: '{filename}' ({attachment_size / (1024*1024):.2f} MB) - from disk")
                        
                        attachment = EmailAttachment(
                            email_id=email_entry.id,
                            filename=filename,
                            content_type=attachment_data['content_type'],
                            size=attachment_size,
                            content=attachment_data.get('content'),
                            file_path=attachment_data.get('file_path'),
                            is_inline=attachment_data['is_inline'],
                            content_id=attachment_data['content_id'] if attachment_data['content_id'] else None,
                            is_large_file=attachment_data.get('is_large_file', False)
                        )
                        
                        db.session.add(attachment)
                        
                        if attachment_size > 1 * 1024 * 1024:
                            try:
                                db.session.flush()
                                logging.debug(f"Successfully flushed attachment '{filename}' ({attachment_size / (1024*1024):.2f} MB) to database")
                            except Exception as flush_error:
                                logging.debug(f"Flush failed for '{filename}', will commit with email: {flush_error}")
                    except Exception as e:
                        logging.error(f"Error saving attachment '{attachment_data['filename']}' ({attachment_data['size'] / (1024*1024):.2f} MB): {e}")
                        import traceback
                        logging.error(f"Traceback: {traceback.format_exc()}")
                        continue
                
                try:
                    db.session.commit()
                    stats['new_emails'] += 1
                except Exception as commit_error:
                    if "Duplicate entry" in str(commit_error) or "1062" in str(commit_error):
                        logging.debug(f"Email with message_id '{message_id}' already exists, skipping duplicate")
                        stats['skipped_emails'] += 1
                        db.session.rollback()
                        continue
                    if "MySQL server has gone away" in str(commit_error) or "ConnectionResetError" in str(commit_error):
                        logging.debug("Database connection lost, attempting to reconnect...")
                        db.session.rollback()
                        db.session.close()
                        db.session = db.create_scoped_session()
                        db.session.add(email_entry)
                        db.session.flush()
                        for attachment_data in attachments_data:
                            try:
                                attachment = EmailAttachment(
                                    email_id=email_entry.id,
                                    filename=attachment_data['filename'],
                                    content_type=attachment_data['content_type'],
                                    size=attachment_data['size'],
                                    content=attachment_data.get('content'),
                                    file_path=attachment_data.get('file_path'),
                                    is_inline=attachment_data['is_inline'],
                                    content_id=attachment_data['content_id'] if attachment_data['content_id'] else None,
                                    is_large_file=attachment_data.get('is_large_file', False)
                                )
                                db.session.add(attachment)
                            except Exception as e:
                                logging.error(f"Error saving attachment {attachment_data['filename']}: {e}")
                                continue
                        db.session.commit()
                        stats['new_emails'] += 1
                        logging.debug("Database reconnection successful")
                    else:
                        raise commit_error
            except Exception as e:
                stats['errors'] += 1
                logging.error(f"Error saving email '{subject}': {e}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                db.session.rollback()
                continue
                
            except MemoryError as mem_error:
                stats['errors'] += 1
                logging.error(f"Memory error syncing email from folder '{folder_name}': {mem_error}")
                db.session.rollback()
                continue
            except Exception as e:
                stats['errors'] += 1
                logging.error(f"Error syncing email from folder '{folder_name}': {e}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                db.session.rollback()
                continue
        
        db.session.commit()
        mail_conn.close()
        mail_conn.logout()
        
        # Sende Dashboard-Updates an alle Benutzer mit E-Mail-Berechtigungen (nur wenn neue E-Mails)
        if stats['new_emails'] > 0:
            try:
                from app.utils.dashboard_events import emit_dashboard_update
                from app.models.user import User
                
                # Hole alle Benutzer mit E-Mail-Leseberechtigung
                users_with_email_access = db.session.query(User.id).join(
                    EmailPermission, User.id == EmailPermission.user_id
                ).filter(EmailPermission.can_read == True).all()
                
                for (user_id,) in users_with_email_access:
                    # Berechne unread_count für diesen Benutzer
                    unread_count = EmailMessage.query.filter_by(
                        is_read=False
                    ).count()
                    
                    # Emittiere Dashboard-Update
                    emit_dashboard_update(user_id, 'email_update', {'count': unread_count})
            except Exception as e:
                logging.error(f"Fehler beim Senden der Dashboard-Updates für E-Mails: {e}")
        
        sync_details = []
        if stats['new_emails'] > 0:
            sync_details.append(f"{stats['new_emails']} neu")
        if stats['updated_emails'] > 0:
            sync_details.append(f"{stats['updated_emails']} übersprungen")
        if stats['moved_emails'] > 0:
            sync_details.append(f"{stats['moved_emails']} verschoben")
        if stats['deleted_emails'] > 0:
            sync_details.append(f"{stats['deleted_emails']} gelöscht")
        
        if sync_details:
            return True, f"Ordner '{folder_name}': {', '.join(sync_details)}"
        else:
            return True, f"Ordner '{folder_name}': Keine Änderungen"
        
    except Exception as e:
        logging.error(f"Email sync from folder failed: {str(e)}")
        return False, f"E-Mail-Sync-Fehler für Ordner '{folder_name}': {str(e)}"


def cleanup_old_emails():
    """Lösche alte E-Mails basierend auf der konfigurierten Speicherdauer."""
    try:
        # Hole Speicherdauer aus Einstellungen
        storage_setting = SystemSettings.query.filter_by(key='email_storage_days').first()
        storage_days = 0
        if storage_setting and storage_setting.value:
            try:
                storage_days = int(storage_setting.value)
            except ValueError:
                storage_days = 0
        
        # Wenn Speicherdauer 0 ist, keine Bereinigung
        if storage_days <= 0:
            logging.debug("E-Mail-Bereinigung deaktiviert (Speicherdauer = 0)")
            return 0
        
        # Berechne das Datum, ab dem E-Mails gelöscht werden sollen
        cutoff_date = datetime.utcnow() - timedelta(days=storage_days)
        
        # Finde E-Mails, die älter als die Speicherdauer sind
        old_emails = EmailMessage.query.filter(
            EmailMessage.created_at < cutoff_date
        ).all()
        
        deleted_count = 0
        for email in old_emails:
            try:
                # Lösche auch alle Anhänge (wird durch cascade automatisch gemacht)
                db.session.delete(email)
                deleted_count += 1
            except Exception as e:
                logging.error(f"Fehler beim Löschen der E-Mail {email.id}: {e}")
                continue
        
        if deleted_count > 0:
            db.session.commit()
            logging.info(f"E-Mail-Bereinigung: {deleted_count} E-Mails gelöscht (älter als {storage_days} Tage)")
        else:
            logging.debug(f"E-Mail-Bereinigung: Keine E-Mails zum Löschen gefunden (älter als {storage_days} Tage)")
        
        return deleted_count
        
    except Exception as e:
        logging.error(f"Fehler bei der E-Mail-Bereinigung: {e}", exc_info=True)
        db.session.rollback()
        return 0


def sync_emails_from_server():
    """Sync emails from IMAP server to database with folder support."""
    print("E-Mail-Synchronisation wird gestartet")
    logging.info("E-Mail-Synchronisation wird gestartet")
    
    try:
        folder_success, folder_message = sync_imap_folders()
        if not folder_success:
            logging.debug(f"Ordner-Sync-Warnung: {folder_message}")
        
        folder_rows = db.session.query(EmailFolder.name, EmailFolder.display_name).all()
        if not folder_rows:
            folder_rows = [('INBOX', 'Posteingang')]
        
        logging.debug(f"Syncing emails from {len(folder_rows)} folders: {[name for (name, _) in folder_rows]}")
        
        total_synced = 0
        folder_results = []
        
        for (folder_name, display_name) in folder_rows:
            try:
                logging.debug(f"Syncing folder: '{folder_name}' ({display_name})")
                success, message = sync_emails_from_folder(folder_name)
                if success:
                    import re
                    match = re.search(r'(\d+) E-Mails', message)
                    if match:
                        count = int(match.group(1))
                        total_synced += count
                    folder_results.append(f"{display_name}: {message}")
                else:
                    logging.debug(f"Failed to sync folder '{folder_name}': {message}")
                    folder_results.append(f"{display_name}: Fehler - {message}")
            except Exception as folder_error:
                logging.error(f"Fehler beim Synchronisieren des Ordners '{folder_name}': {folder_error}")
                folder_results.append(f"{display_name}: Fehler - {str(folder_error)}")
                continue
        
        print("E-Mail-Synchronisation wurde beendet")
        logging.info("E-Mail-Synchronisation wurde beendet")
        
        if total_synced > 0:
            return True, f"{total_synced} E-Mails aus {len(folder_rows)} Ordnern synchronisiert"
        else:
            return True, "Keine E-Mails synchronisiert"
    except Exception as e:
        logging.error(f"Kritischer Fehler in sync_emails_from_server: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        print(f"E-Mail-Synchronisation Fehler: {e}")
        return False, f"Fehler: {str(e)}"


def check_email_permission(permission_type='read'):
    """Check if current user has email permissions."""
    # Gast-Accounts haben keinen Zugriff auf E-Mail-Modul
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return False
    
    perm = EmailPermission.query.filter_by(user_id=current_user.id).first()
    if not perm:
        return False
    return perm.can_read if permission_type == 'read' else perm.can_send


def generate_email_idempotency_key(user_id, subject, recipients, body_hash, timestamp_second):
    """
    Generiere einen eindeutigen Idempotenz-Key für eine E-Mail.
    
    Args:
        user_id: ID des Benutzers
        subject: Betreff der E-Mail
        recipients: Empfänger (normalisiert)
        body_hash: Hash des E-Mail-Bodys
        timestamp_second: Timestamp auf Sekunde gerundet
    
    Returns:
        Idempotenz-Key als Hex-String
    """
    key_string = f"{user_id}:{subject}:{recipients}:{body_hash}:{timestamp_second}"
    return hashlib.sha256(key_string.encode('utf-8')).hexdigest()[:32]


def check_duplicate_email(user_id, subject, recipients, body_hash, time_window_seconds=60):
    """
    Prüfe, ob eine identische E-Mail in den letzten time_window_seconds Sekunden
    vom gleichen Benutzer versendet wurde.
    
    Args:
        user_id: ID des Benutzers
        subject: Betreff der E-Mail
        recipients: Empfänger (normalisiert, sortiert)
        body_hash: Hash des E-Mail-Bodys (MD5)
        time_window_seconds: Zeitfenster in Sekunden (Standard: 60)
    
    Returns:
        True wenn Duplikat gefunden wurde, False sonst
    """
    try:
        # Normalisiere Empfänger: sortiere und lowerc
        normalized_recipients = ','.join(sorted([r.strip().lower() for r in recipients.split(',') if r.strip()]))
        
        # Zeitfenster berechnen
        now = datetime.utcnow()
        time_threshold = now - timedelta(seconds=time_window_seconds)
        
        # Prüfe in der Datenbank nach identischen E-Mails
        # Wir prüfen auf: gleicher User, gleicher Betreff, gleiche Empfänger, innerhalb des Zeitfensters
        duplicate_query = EmailMessage.query.filter(
            EmailMessage.sent_by_user_id == user_id,
            EmailMessage.subject == subject,
            EmailMessage.recipients == normalized_recipients,
            EmailMessage.sent_at >= time_threshold,
            EmailMessage.is_sent == True
        )
        
        # Prüfe Body-Ähnlichkeit durch Vergleich des Body-Hash
        for email in duplicate_query.all():
            if email.body_html:
                # Generiere Hash des gespeicherten Body-Inhalts
                email_body_hash = hashlib.md5(email.body_html.encode('utf-8')).hexdigest()
                # Vergleiche mit dem aktuellen Body-Hash
                if email_body_hash == body_hash:
                    return True
        
        return False
        
    except Exception as e:
        logging.error(f"Fehler bei Idempotenz-Prüfung: {e}")
        # Bei Fehler: erlaube Versand (Fail-Open), aber logge Warnung
        return False


@email_bp.route('/')
@login_required
@check_module_access('module_email')
def index():
    """Email inbox with folder support."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))
    
    current_folder = request.args.get('folder', 'INBOX')
    emails = EmailMessage.query.filter_by(folder=current_folder).order_by(EmailMessage.received_at.desc()).all()
    folder_obj = EmailFolder.query.filter_by(name=current_folder).first()
    folder_display_name = folder_obj.display_name if folder_obj else current_folder
    
    all_folders = EmailFolder.query.all()
    
    # Define standard folder order
    standard_folder_order = ['INBOX', 'Drafts', 'Sent', 'Archive', 'Archives', 'Trash', 'Spam']
    standard_folder_names = ['Posteingang', 'Entwürfe', 'Gesendet', 'Archiv', 'Archiv', 'Papierkorb', 'Spam']
    
    # Separate standard and custom folders
    standard_folders = []
    custom_folders = []
    
    for folder in all_folders:
        if folder.folder_type == 'standard' and folder.display_name in standard_folder_names:
            standard_folders.append(folder)
        else:
            custom_folders.append(folder)
    
    # Sort standard folders by predefined order
    standard_folders.sort(key=lambda x: standard_folder_order.index(x.name) if x.name in standard_folder_order else 999)
    
    # Sort custom folders alphabetically
    custom_folders.sort(key=lambda x: x.display_name)
    
    # Combine: standard folders first, then custom folders
    folders = standard_folders + custom_folders
    
    for email_obj in emails:
        if email_obj.attachments:
            email_obj.has_attachments = True
        else:
            email_obj.has_attachments = False
    db.session.commit()
    
    return render_template(
        'email/index.html',
        emails=emails,
        folders=folders,
        current_folder=current_folder,
        folder_display_name=folder_display_name
    )


@email_bp.route('/folder/<folder_name>')
@login_required
@check_module_access('module_email')
def folder_view(folder_name):
    """View emails in a specific folder."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))
    
    # URL-decode folder name in case it's encoded
    from urllib.parse import unquote
    folder_name = unquote(folder_name)
    
    # Reject invalid folder names
    if not folder_name or folder_name.strip() == '' or folder_name == '/':
        flash(translate('email.flash.invalid_folder_name'), 'danger')
        return redirect(url_for('email.index'))
    
    # Check if folder exists, if not redirect to index
    folder_obj = EmailFolder.query.filter_by(name=folder_name).first()
    if not folder_obj:
        existing_emails = EmailMessage.query.filter_by(folder=folder_name).count()
        if existing_emails > 0:
            logging.warning(f"Folder '{folder_name}' exists in emails but not in folders table")
        flash(f'Ordner "{folder_name}" nicht gefunden.', 'warning')
        return redirect(url_for('email.index'))
    
    emails = EmailMessage.query.filter_by(folder=folder_name).order_by(EmailMessage.received_at.desc()).all()
    
    logging.info(f"Viewing folder '{folder_name}' with {len(emails)} emails")
    
    all_folders = EmailFolder.query.all()
    
    standard_folder_order = ['INBOX', 'Drafts', 'Sent', 'Archive', 'Archives', 'Trash', 'Spam']
    standard_folder_names = ['Posteingang', 'Entwürfe', 'Gesendet', 'Archiv', 'Archiv', 'Papierkorb', 'Spam']
    
    # Separate standard and custom folders
    standard_folders = []
    custom_folders = []
    
    for folder in all_folders:
        if folder.folder_type == 'standard' and folder.display_name in standard_folder_names:
            standard_folders.append(folder)
        else:
            custom_folders.append(folder)
    
    # Sort standard folders by predefined order
    standard_folders.sort(key=lambda x: standard_folder_order.index(x.name) if x.name in standard_folder_order else 999)
    
    # Sort custom folders alphabetically
    custom_folders.sort(key=lambda x: x.display_name)
    
    # Combine: standard folders first, then custom folders
    folders = standard_folders + custom_folders
    folder_display_name = folder_obj.display_name if folder_obj else folder_name
    
    return render_template('email/index.html', emails=emails, folders=folders, current_folder=folder_name, folder_display_name=folder_display_name)


@email_bp.route('/view/<int:email_id>')
@login_required
@check_module_access('module_email')
def view_email(email_id):
    """View a specific email."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))
    
    email_msg = EmailMessage.query.get_or_404(email_id)
    
    if not email_msg.is_read:
        email_msg.is_read = True
        db.session.commit()
    
    
    html_content = None
    if email_msg.body_html:
        try:
            if isinstance(email_msg.body_html, bytes):
                html_content = email_msg.body_html.decode('utf-8', errors='replace')
            else:
                html_content = str(email_msg.body_html)
            
            
            import re
            
            html_content = html_content.replace('\u2011', '-')
            html_content = html_content.replace('\u2013', '-')
            html_content = html_content.replace('\u2014', '--')
            html_content = html_content.replace('\u2018', "'")
            html_content = html_content.replace('\u2019', "'")
            html_content = html_content.replace('\u201c', '"')
            html_content = html_content.replace('\u201d', '"')
            html_content = html_content.replace('\u2026', '...')
            html_content = html_content.replace('\ufffc', '')
            
            html_content = re.sub(r'<o:p\s*/>', '', html_content)
            html_content = re.sub(r'<o:p>.*?</o:p>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<w:.*?>.*?</w:.*?>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<m:.*?>.*?</m:.*?>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<v:.*?>.*?</v:.*?>', '', html_content, flags=re.DOTALL)
            
            html_content = re.sub(r'<a([^>]*)href="([^"]*)"([^>]*)>', r'<a\1href="\2" target="_blank" rel="noopener noreferrer"\3>', html_content)
            
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, flags=re.IGNORECASE | re.DOTALL)
            if body_match:
                body_content = body_match.group(1)
                html_content = re.sub(r'<body[^>]*>.*?</body>', '<div class="email-body-wrapper">' + body_content + '</div>', html_content, flags=re.IGNORECASE | re.DOTALL)
            else:
                if not html_content.strip().startswith('<div'):
                    html_content = '<div class="email-body-wrapper">' + html_content + '</div>'
            
            # Remove html tags
            html_content = re.sub(r'<html[^>]*>', '', html_content, flags=re.IGNORECASE)
            html_content = re.sub(r'</html>', '', html_content, flags=re.IGNORECASE)
            
            def scope_style_tags(match):
                style_content = match.group(1) if match.group(1) else ''
                if not style_content.strip():
                    return ''
                
                lines = style_content.split('\n')
                scoped_lines = []
                in_media = False
                media_prefix = ''
                
                for line in lines:
                    line_stripped = line.strip()
                    if line_stripped.startswith('@'):
                        if '@media' in line_stripped:
                            in_media = True
                            media_prefix = line_stripped
                            scoped_lines.append(line)
                            continue
                        elif line_stripped == '}' and in_media:
                            in_media = False
                            media_prefix = ''
                            scoped_lines.append(line)
                            continue
                    
                    if in_media:
                        if '{' in line and not line_stripped.startswith('@'):
                            scoped_line = re.sub(
                                r'([^{}]+)\{',
                                r'.email-content-isolated-inner \1{',
                                line
                            )
                            scoped_lines.append(scoped_line)
                        else:
                            scoped_lines.append(line)
                    else:
                        if '{' in line:
                            scoped_line = re.sub(
                                r'([^{}]+)\{',
                                r'.email-content-isolated-inner \1{',
                                line
                            )
                            scoped_lines.append(scoped_line)
                        else:
                            scoped_lines.append(line)
                
                scoped_css = '\n'.join(scoped_lines)
                scoped_css = re.sub(r'\.email-content-isolated-inner\s+\.email-content-isolated-inner', '.email-content-isolated-inner', scoped_css)
                scoped_css = re.sub(r'\.email-content-isolated-inner\s+body\s*\{', '.email-content-isolated-inner {', scoped_css, flags=re.IGNORECASE)
                scoped_css = re.sub(r'\.email-content-isolated-inner\s+html\s*\{', '.email-content-isolated-inner {', scoped_css, flags=re.IGNORECASE)
                
                return f'<style type="text/css">{scoped_css}</style>'
            
            html_content = re.sub(r'<style[^>]*>(.*?)</style>', scope_style_tags, html_content, flags=re.IGNORECASE | re.DOTALL)
            
            if not html_content.strip().startswith('<'):
                html_content = f'<div class="email-body-wrapper">{html_content}</div>'
            
            if not html_content.strip().startswith('<div class="email-content-isolated-inner">'):
                html_content = f'<div class="email-content-isolated-inner">{html_content}</div>'
            
            for attachment in email_msg.attachments:
                if attachment.is_inline and attachment.content_type.startswith('image/'):
                    data_url = attachment.get_data_url()
                    if data_url:
                        cid_pattern = f'cid:{attachment.filename}'
                        html_content = html_content.replace(f'src="{cid_pattern}"', f'src="{data_url}"')
                        html_content = html_content.replace(f"src='{cid_pattern}'", f"src='{data_url}'")
                        content_id = attachment.content_id
                        if content_id:
                            html_content = html_content.replace(f'src="cid:{content_id}"', f'src="{data_url}"')
                            html_content = html_content.replace(f"src='cid:{content_id}'", f"src='{data_url}'")
            
            html_content = re.sub(r'src="cid:([^"]+)"', r'src="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y4ZjlmYSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjE0IiBmaWxsPSIjNmM3NTdkIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+SW1hZ2U8L3RleHQ+PC9zdmc+"', html_content)
            
            
        except Exception as e:
            logging.error(f"HTML processing error: {e}")
            html_content = None
    
    return render_template('email/view.html', email=email_msg, html_content=html_content)


def prefix_subject(subject: str, prefix: str) -> str:
    clean = subject or ''
    if not clean.lower().startswith(f"{prefix.lower()}: "):
        return f"{prefix}: {clean}"
    return clean


def normalize_addresses(addresses):
    if not addresses:
        return []
    if isinstance(addresses, str):
        parts = [p.strip() for p in addresses.split(',') if p.strip()]
    else:
        parts = [str(p).strip() for p in addresses if str(p).strip()]
    seen = set()
    result = []
    for a in parts:
        key = a.lower()
        if key not in seen:
            seen.add(key)
            result.append(a)
    return result


def build_plain_quote_header(email_msg: EmailMessage) -> str:
    sent_at = email_msg.received_at or email_msg.sent_at or datetime.utcnow()
    header = (
        f"Von: {email_msg.sender}\n"
        f"An: {email_msg.recipients or ''}\n"
        f"{'CC: ' + email_msg.cc + '\n' if email_msg.cc else ''}"
        f"Datum: {sent_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"Betreff: {email_msg.subject}\n\n"
    )
    return header


def quote_plain(email_msg: EmailMessage) -> str:
    body = email_msg.body_text or ''
    if not body and email_msg.body_html:
        import re
        body = re.sub(r'<[^>]+>', '', email_msg.body_html)
        body = body.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    
    header = build_plain_quote_header(email_msg)
    
    quoted_lines = []
    quoted_lines.append(header)
    for line in body.split('\n'):
        quoted_lines.append(f"> {line}")
    
    return '\n'.join(quoted_lines)


def build_reply_context(email_msg: EmailMessage, mode: str):
    to_list = []
    if email_msg.sender:
        to_list += normalize_addresses(email_msg.sender)
    cc_list = []
    if mode == 'reply_all':
        to_list += normalize_addresses(email_msg.recipients)
        cc_list += normalize_addresses(email_msg.cc)
        own = (current_user.email or '').lower()
        to_list = [a for a in to_list if a.lower() != own]
        cc_list = [a for a in cc_list if a.lower() != own]
    to_list = normalize_addresses(to_list)
    cc_list = normalize_addresses(cc_list)

    subject = prefix_subject(email_msg.subject or '', 'Re')
    body_prefill = quote_plain(email_msg)
    
    # Extrahiere erste Zeile für Vorschau
    first_line = ''
    body_text = email_msg.body_text or ''
    if not body_text and email_msg.body_html:
        import re
        body_text = re.sub(r'<[^>]+>', '', email_msg.body_html)
        body_text = body_text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    
    if body_text:
        lines = body_text.strip().split('\n')
        first_line = lines[0].strip() if lines else ''
        if len(first_line) > 100:
            first_line = first_line[:100] + '...'
    
    # HTML-Inhalt für Vorschau vorbereiten (mit gleicher Formatierung wie in view_email)
    original_html = None
    if email_msg.body_html:
        try:
            if isinstance(email_msg.body_html, bytes):
                html_content = email_msg.body_html.decode('utf-8', errors='replace')
            else:
                html_content = str(email_msg.body_html)
            
            import re
            
            # Gleiche Formatierung wie in view_email
            html_content = html_content.replace('\u2011', '-')
            html_content = html_content.replace('\u2013', '-')
            html_content = html_content.replace('\u2014', '--')
            html_content = html_content.replace('\u2018', "'")
            html_content = html_content.replace('\u2019', "'")
            html_content = html_content.replace('\u201c', '"')
            html_content = html_content.replace('\u201d', '"')
            html_content = html_content.replace('\u2026', '...')
            html_content = html_content.replace('\ufffc', '')
            
            html_content = re.sub(r'<o:p\s*/>', '', html_content)
            html_content = re.sub(r'<o:p>.*?</o:p>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<w:.*?>.*?</w:.*?>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<m:.*?>.*?</m:.*?>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<v:.*?>.*?</v:.*?>', '', html_content, flags=re.DOTALL)
            
            html_content = re.sub(r'<a([^>]*)href="([^"]*)"([^>]*)>', r'<a\1href="\2" target="_blank" rel="noopener noreferrer"\3>', html_content)
            
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, flags=re.IGNORECASE | re.DOTALL)
            if body_match:
                body_content = body_match.group(1)
                html_content = re.sub(r'<body[^>]*>.*?</body>', '<div class="email-body-wrapper">' + body_content + '</div>', html_content, flags=re.IGNORECASE | re.DOTALL)
            else:
                if not html_content.strip().startswith('<div'):
                    html_content = '<div class="email-body-wrapper">' + html_content + '</div>'
            
            # Remove html tags
            html_content = re.sub(r'<html[^>]*>', '', html_content, flags=re.IGNORECASE)
            html_content = re.sub(r'</html>', '', html_content, flags=re.IGNORECASE)
            
            def scope_style_tags(match):
                style_content = match.group(1) if match.group(1) else ''
                if not style_content.strip():
                    return ''
                
                lines = style_content.split('\n')
                scoped_lines = []
                in_media = False
                media_prefix = ''
                
                for line in lines:
                    line_stripped = line.strip()
                    if line_stripped.startswith('@'):
                        if '@media' in line_stripped:
                            in_media = True
                            media_prefix = line_stripped
                            scoped_lines.append(line)
                            continue
                        elif line_stripped == '}' and in_media:
                            in_media = False
                            media_prefix = ''
                            scoped_lines.append(line)
                            continue
                    
                    if in_media:
                        if '{' in line and not line_stripped.startswith('@'):
                            scoped_line = re.sub(
                                r'([^{}]+)\{',
                                r'.email-original-content-inner \1{',
                                line
                            )
                            scoped_lines.append(scoped_line)
                        else:
                            scoped_lines.append(line)
                    else:
                        if '{' in line:
                            scoped_line = re.sub(
                                r'([^{}]+)\{',
                                r'.email-original-content-inner \1{',
                                line
                            )
                            scoped_lines.append(scoped_line)
                        else:
                            scoped_lines.append(line)
                
                scoped_css = '\n'.join(scoped_lines)
                scoped_css = re.sub(r'\.email-original-content-inner\s+\.email-original-content-inner', '.email-original-content-inner', scoped_css)
                scoped_css = re.sub(r'\.email-original-content-inner\s+body\s*\{', '.email-original-content-inner {', scoped_css, flags=re.IGNORECASE)
                scoped_css = re.sub(r'\.email-original-content-inner\s+html\s*\{', '.email-original-content-inner {', scoped_css, flags=re.IGNORECASE)
                
                return f'<style type="text/css">{scoped_css}</style>'
            
            html_content = re.sub(r'<style[^>]*>(.*?)</style>', scope_style_tags, html_content, flags=re.IGNORECASE | re.DOTALL)
            
            if not html_content.strip().startswith('<'):
                html_content = f'<div class="email-body-wrapper">{html_content}</div>'
            
            if not html_content.strip().startswith('<div class="email-original-content-inner">'):
                html_content = f'<div class="email-original-content-inner">{html_content}</div>'
            
            # Inline-Bilder ersetzen
            for attachment in email_msg.attachments:
                if attachment.is_inline and attachment.content_type.startswith('image/'):
                    data_url = attachment.get_data_url()
                    if data_url:
                        cid_pattern = f'cid:{attachment.filename}'
                        html_content = html_content.replace(f'src="{cid_pattern}"', f'src="{data_url}"')
                        html_content = html_content.replace(f"src='{cid_pattern}'", f"src='{data_url}'")
                        content_id = attachment.content_id
                        if content_id:
                            html_content = html_content.replace(f'src="cid:{content_id}"', f'src="{data_url}"')
                            html_content = html_content.replace(f"src='cid:{content_id}'", f"src='{data_url}'")
            
            html_content = re.sub(r'src="cid:([^"]+)"', r'src="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y4ZjlmYSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjE0IiBmaWxsPSIjNmM3NTdkIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+SW1hZ2U8L3RleHQ+PC9zdmc+"', html_content)
            
            original_html = html_content
        except Exception as e:
            logging.error(f"HTML processing error for original email: {e}")
            original_html = None
    
    # Anhänge-IDs für Mitnahme
    attachment_ids = [str(a.id) for a in email_msg.attachments]
    
    return {
        'to': ', '.join(to_list),
        'cc': ', '.join(cc_list),
        'subject': subject,
        'body': body_prefill,
        'in_reply_to': email_msg.message_id or '',
        'references': email_msg.message_id or '',
        'original_email': email_msg,
        'original_html': original_html,
        'original_first_line': first_line,
        'original_attachment_ids': ','.join(attachment_ids)
    }


def build_forward_context(email_msg: EmailMessage, include_attachments: bool):
    subject = prefix_subject(email_msg.subject or '', 'Fwd')
    body_prefill = quote_plain(email_msg)
    attachment_ids = []
    if include_attachments:
        attachment_ids = [str(a.id) for a in email_msg.attachments]
    return {
        'to': '',
        'cc': '',
        'subject': subject,
        'body': body_prefill,
        'forward_attachment_ids': ','.join(attachment_ids)
    }


@email_bp.route('/reply/<int:email_id>')
@login_required
@check_module_access('module_email')
def reply(email_id: int):
    if not check_email_permission('send'):
        flash(translate('email.flash.no_send_permission'), 'danger')
        return redirect(url_for('email.view_email', email_id=email_id))
    email_msg = EmailMessage.query.get_or_404(email_id)
    ctx = build_reply_context(email_msg, 'reply')
    ctx['is_reply'] = True
    return render_template('email/compose.html', **ctx)


@email_bp.route('/reply-all/<int:email_id>')
@login_required
@check_module_access('module_email')
def reply_all(email_id: int):
    if not check_email_permission('send'):
        flash(translate('email.flash.no_send_permission'), 'danger')
        return redirect(url_for('email.view_email', email_id=email_id))
    email_msg = EmailMessage.query.get_or_404(email_id)
    ctx = build_reply_context(email_msg, 'reply_all')
    ctx['is_reply'] = True
    return render_template('email/compose.html', **ctx)


@email_bp.route('/forward/<int:email_id>')
@login_required
@check_module_access('module_email')
def forward(email_id: int):
    if not check_email_permission('send'):
        flash(translate('email.flash.no_send_permission'), 'danger')
        return redirect(url_for('email.view_email', email_id=email_id))
    email_msg = EmailMessage.query.get_or_404(email_id)
    ctx = build_forward_context(email_msg, include_attachments=True)
    return render_template('email/compose.html', **ctx)


@email_bp.route('/attachment/<int:attachment_id>')
@login_required
@check_module_access('module_email')
def download_attachment(attachment_id):
    """Download an email attachment with support for large files."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('email.index'))
    
    attachment = EmailAttachment.query.get_or_404(attachment_id)
    email_msg = attachment.email
    if not email_msg:
        flash(translate('email.flash.attachment_not_found'), 'danger')
        return redirect(url_for('email.index'))
    
    try:
        if attachment.size > 1 * 1024 * 1024:
            logging.info(f"Downloading large attachment: '{attachment.filename}' ({attachment.size / (1024*1024):.2f} MB)")
        
        if attachment.is_large_file and attachment.file_path:
            import os
            if os.path.exists(attachment.file_path):
                def generate():
                    with open(attachment.file_path, 'rb') as f:
                        while True:
                            data = f.read(8192)
                            if not data:
                                break
                            yield data
                
                response = Response(generate(), mimetype=attachment.content_type)
                import urllib.parse
                encoded_filename = urllib.parse.quote(attachment.filename.encode('utf-8'))
                response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
                response.headers['Content-Length'] = str(attachment.size)
                response.headers['Accept-Ranges'] = 'bytes'
                return response
            else:
                flash(translate('email.flash.attachment_file_not_found'), 'danger')
                return redirect(url_for('email.view_email', email_id=email_msg.id))
        else:
            content = attachment.get_content()
            if not content:
                flash(translate('email.flash.attachment_corrupted'), 'danger')
                return redirect(url_for('email.index'))
            
            file_obj = io.BytesIO(content)
            
            response = send_file(
                file_obj,
                as_attachment=True,
                download_name=attachment.filename,
                mimetype=attachment.content_type
            )
            
            import urllib.parse
            encoded_filename = urllib.parse.quote(attachment.filename.encode('utf-8'))
            response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
            
            response.headers['Content-Length'] = str(attachment.size)
            response.headers['Accept-Ranges'] = 'bytes'
            
            return response
        
    except Exception as e:
        logging.error(f"Error downloading attachment {attachment_id} ({attachment.filename}): {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        flash(f'Fehler beim Herunterladen des Anhangs: {str(e)}', 'danger')
        return redirect(url_for('email.view_email', email_id=email_msg.id))


@email_bp.route('/compose', methods=['GET', 'POST'])
@login_required
@check_module_access('module_email')
def compose():
    """Compose and send an email."""
    if not check_email_permission('send'):
        flash(translate('email.flash.no_send_permission'), 'danger')
        return redirect(url_for('email.index'))
    
    if request.method == 'POST':
        # Prüfe ob AJAX-Request
        is_ajax_request = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.headers.get('Accept', '').startswith('application/json')
        )
        
        to = request.form.get('to', '').strip()
        cc = request.form.get('cc', '').strip()
        subject = request.form.get('subject', '').strip()
        body_html = request.form.get('body', '').strip()
        in_reply_to = request.form.get('in_reply_to', '').strip()
        references = request.form.get('references', '').strip()
        forward_attachment_ids = request.form.get('forward_attachment_ids', '').strip()
        original_attachment_ids = request.form.get('original_attachment_ids', '').strip()
        
        if not all([to, subject, body_html]):
            error_msg = 'Bitte füllen Sie alle Pflichtfelder aus.'
            if is_ajax_request:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'danger')
            return render_template('email/compose.html')
        
        # Generiere Body-Hash für Idempotenz-Prüfung
        body_hash = hashlib.md5(body_html.encode('utf-8')).hexdigest()
        
        # Prüfe auf Duplikat (Idempotenz)
        if check_duplicate_email(current_user.id, subject, to, body_hash, time_window_seconds=60):
            error_msg = 'Diese E-Mail wurde bereits vor kurzem versendet. Bitte warten Sie einen Moment oder ändern Sie den Inhalt.'
            logging.warning(f"Doppelversendung verhindert: User {current_user.id}, Betreff: {subject}")
            if is_ajax_request:
                return jsonify({'success': False, 'message': error_msg}), 409
            flash(error_msg, 'warning')
            return render_template('email/compose.html')
        
        # Logo als CID-Anhang vorbereiten
        logo_data, logo_mime_type, logo_filename = get_logo_data()
        # #region agent log
        try:
            import json
            with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"location":"email.py:1948","message":"Logo-Daten geholt","data":{"has_data":logo_data is not None,"data_size":len(logo_data) if logo_data else 0,"mime_type":logo_mime_type,"filename":logo_filename},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}) + '\n')
        except: pass
        # #endregion
        logo_cid = None
        if logo_data and logo_mime_type:
            logo_cid = "portal_logo"
            # #region agent log
            try:
                import json
                with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"location":"email.py:1951","message":"Logo-CID gesetzt","data":{"logo_cid":logo_cid},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}) + '\n')
            except: pass
            # #endregion
            # Logo-Bytes werden später als CID-Anhang hinzugefügt
        else:
            # #region agent log
            try:
                import json
                with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"location":"email.py:1953","message":"BEDINGUNG FEHLGESCHLAGEN - Logo wird NICHT hinzugefügt","data":{"logo_data":logo_data is not None,"logo_mime_type":logo_mime_type},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}) + '\n')
            except: pass
            # #endregion
        
        full_body_html, full_body_plain = render_custom_email(subject, body_html, logo_cid=logo_cid)
        
        # #region agent log
        # Prüfe, ob die CID-Referenz im HTML vorhanden ist
        try:
            import json
            has_cid_ref = f'cid:{logo_cid}' in full_body_html if logo_cid else False
            with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"location":"email.py:1976","message":"HTML gerendert mit CID-Referenz","data":{"logo_cid":logo_cid,"has_cid_ref":has_cid_ref,"cid_ref_pattern":f'cid:{logo_cid}' if logo_cid else None},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"D"}) + '\n')
        except: pass
        # #endregion
        
        try:
            from config import get_formatted_sender
            sender = get_formatted_sender()
            if not sender:
                error_msg = 'E-Mail-Absender ist nicht konfiguriert. Bitte kontaktieren Sie den Administrator.'
                if is_ajax_request:
                    return jsonify({'success': False, 'message': error_msg}), 500
                flash(error_msg, 'danger')
                return render_template('email/compose.html')
            
            # Erstelle normale Flask-Mail Message (Flask-Mail erstellt automatisch multipart)
            msg = Message(
                subject=subject,
                recipients=to.split(','),
                body=full_body_plain,
                html=full_body_html,
                sender=sender
            )
            
            # Thread-Header setzen
            if in_reply_to:
                if not hasattr(msg, 'extra_headers') or msg.extra_headers is None:
                    msg.extra_headers = {}
                msg.extra_headers['In-Reply-To'] = in_reply_to
            if references:
                if not hasattr(msg, 'extra_headers') or msg.extra_headers is None:
                    msg.extra_headers = {}
                msg.extra_headers['References'] = references
            
            if cc:
                msg.cc = cc.split(',')
            
            # Füge Logo als ANHANG hinzu (wie andere Anhänge) - WICHTIG: Vor anderen Anhängen
            if logo_data and logo_mime_type and logo_cid:
                image_type = logo_mime_type.split('/')[1] if '/' in logo_mime_type else 'png'
                if image_type == 'jpeg' or image_type == 'jpg':
                    attachment_filename = 'logo.jpg'
                elif image_type == 'png':
                    attachment_filename = 'logo.png'
                elif image_type == 'gif':
                    attachment_filename = 'logo.gif'
                else:
                    attachment_filename = 'logo.png'
                
                # KRITISCH: Verwende msg.attach() - dies stellt sicher, dass das Logo in der Struktur bleibt
                # Die Manipulation mit CID und inline erfolgt später in send_email_with_lock()
                msg.attach(attachment_filename, logo_mime_type, logo_data)
                
                # #region agent log
                try:
                    import json
                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"location":"email.py:2000","message":"Logo über msg.attach() hinzugefügt","data":{"filename":attachment_filename,"mime_type":logo_mime_type,"size":len(logo_data)},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"F"}) + '\n')
                except: pass
                # #endregion
                
                # KRITISCH: Manipuliere die Message-Struktur direkt, um CID und inline zu setzen
                # Flask-Mail erstellt die Struktur beim ersten Zugriff auf msg.msg
                # Wir müssen nach msg.attach() die Struktur manipulieren
                if hasattr(msg, 'msg') and msg.msg:
                    # Flask-Mail erstellt möglicherweise msg.msg erst beim ersten Zugriff
                    # Wir müssen es jetzt erzeugen, damit wir es manipulieren können
                    try:
                        _ = msg.msg.get_content_type()
                    except:
                        pass
                
                # Setze CID und inline disposition auf dem Logo-Attachment
                if hasattr(msg, 'msg') and hasattr(msg.msg, 'get_payload'):
                    # #region agent log
                    try:
                        import json
                        msg_ct = msg.msg.get_content_type() if hasattr(msg.msg, 'get_content_type') else 'N/A'
                        with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"location":"email.py:2044","message":"VOR Logo-Manipulation - Message-Struktur","data":{"content_type":msg_ct,"has_msg":hasattr(msg, 'msg'),"msg_is_none":msg.msg is None if hasattr(msg, 'msg') else True},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"A"}) + '\n')
                    except: pass
                    # #endregion
                    parts = msg.msg.get_payload()
                    if isinstance(parts, list):
                        # #region agent log
                        try:
                            import json
                            part_info = []
                            for i, p in enumerate(parts):
                                if hasattr(p, 'get_content_type'):
                                    ct = p.get_content_type()
                                    disp = p.get('Content-Disposition', '')
                                    cid = p.get('Content-ID', '')
                                    part_info.append({"index":i,"content_type":ct,"disposition":disp,"content_id":cid})
                            with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                f.write(json.dumps({"location":"email.py:2050","message":"Teile VOR Logo-Suche","data":{"total_parts":len(parts),"parts":part_info,"looking_for":{"mime_type":logo_mime_type,"filename":attachment_filename}},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"C"}) + '\n')
                        except: pass
                        # #endregion
                        logo_found = False
                        for part in parts:
                            if (hasattr(part, 'get_content_type') and 
                                part.get_content_type() == logo_mime_type and
                                hasattr(part, 'get') and 
                                part.get('Content-Disposition', '').find(attachment_filename) != -1):
                                logo_found = True
                                # Setze Content-ID und inline disposition
                                part.add_header('Content-ID', f'<{logo_cid}>')
                                # Entferne alte Content-Disposition und setze neue
                                old_disp = part.get('Content-Disposition', '')
                                if old_disp:
                                    part.replace_header('Content-Disposition', f'inline; filename="{attachment_filename}"')
                                else:
                                    part.add_header('Content-Disposition', f'inline; filename="{attachment_filename}"')
                                
                                # #region agent log
                                try:
                                    import json
                                    new_cid = part.get('Content-ID', '')
                                    new_disp = part.get('Content-Disposition', '')
                                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                        f.write(json.dumps({"location":"email.py:2065","message":"Logo-Attachment mit CID markiert","data":{"cid":new_cid,"old_disposition":old_disp,"new_disposition":new_disp,"filename":attachment_filename},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"F"}) + '\n')
                                except: pass
                                # #endregion
                                logging.info(f"Logo als inline attachment mit CID markiert: {attachment_filename}")
                                break
                        # #region agent log
                        if not logo_found:
                            try:
                                import json
                                with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                    f.write(json.dumps({"location":"email.py:2070","message":"LOGO NICHT GEFUNDEN in Teilen","data":{"looking_for_mime":logo_mime_type,"looking_for_filename":attachment_filename},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"C"}) + '\n')
                            except: pass
                        # #endregion
            
            if 'attachments' in request.files:
                attachments = request.files.getlist('attachments')
                for attachment in attachments:
                    if attachment.filename:
                        msg.attach(
                            attachment.filename,
                            attachment.content_type or 'application/octet-stream',
                            attachment.read()
                        )
                        attachment.seek(0)

            # Forward attachments
            if forward_attachment_ids:
                id_list = [i for i in forward_attachment_ids.split(',') if i]
                for aid in id_list:
                    try:
                        att = EmailAttachment.query.get(int(aid))
                        if not att:
                            continue
                        if att.is_large_file and att.file_path:
                            with open(att.file_path, 'rb') as f:
                                data = f.read()
                            msg.attach(att.filename, att.content_type or 'application/octet-stream', data)
                        else:
                            data = att.get_content()
                            if data:
                                msg.attach(att.filename, att.content_type or 'application/octet-stream', data)
                    except Exception as _:
                        continue
            
            # Original attachments (from reply)
            if original_attachment_ids:
                id_list = [i for i in original_attachment_ids.split(',') if i]
                for aid in id_list:
                    try:
                        att = EmailAttachment.query.get(int(aid))
                        if not att:
                            continue
                        if att.is_large_file and att.file_path:
                            with open(att.file_path, 'rb') as f:
                                data = f.read()
                            msg.attach(att.filename, att.content_type or 'application/octet-stream', data)
                        else:
                            data = att.get_content()
                            if data:
                                msg.attach(att.filename, att.content_type or 'application/octet-stream', data)
                    except Exception as _:
                        continue
            
            # Stelle sicher, dass Logo-Attachment nach allen anderen Anhängen mit CID markiert ist
            # (wird auch in send_email_with_lock() nochmal geprüft, aber hier sicherstellen)
            if logo_data and logo_mime_type and logo_cid:
                # Warte, bis msg.msg erstellt wurde (nach allen anderen attach()-Aufrufen)
                if hasattr(msg, 'msg') and msg.msg:
                    try:
                        _ = msg.msg.get_content_type()
                    except:
                        pass
                    
                    # Setze CID und inline disposition auf dem Logo-Attachment
                    if hasattr(msg.msg, 'get_payload'):
                        parts = msg.msg.get_payload()
                        if isinstance(parts, list):
                            image_type = logo_mime_type.split('/')[1] if '/' in logo_mime_type else 'png'
                            if image_type == 'jpeg' or image_type == 'jpg':
                                attachment_filename = 'logo.jpg'
                            elif image_type == 'png':
                                attachment_filename = 'logo.png'
                            elif image_type == 'gif':
                                attachment_filename = 'logo.gif'
                            else:
                                attachment_filename = 'logo.png'
                            
                            for part in parts:
                                if (hasattr(part, 'get_content_type') and 
                                    part.get_content_type() == logo_mime_type and
                                    hasattr(part, 'get') and 
                                    part.get('Content-Disposition', '').find(attachment_filename) != -1):
                                    # Setze Content-ID, falls noch nicht gesetzt
                                    if not part.get('Content-ID'):
                                        part.add_header('Content-ID', f'<{logo_cid}>')
                                    # Stelle sicher, dass es inline ist
                                    disp = part.get('Content-Disposition', '')
                                    if 'attachment' in disp and 'inline' not in disp:
                                        try:
                                            part.replace_header('Content-Disposition', f'inline; filename="{attachment_filename}"')
                                        except:
                                            part.add_header('Content-Disposition', f'inline; filename="{attachment_filename}"')
                                    elif not disp:
                                        part.add_header('Content-Disposition', f'inline; filename="{attachment_filename}"')
                                    
                                    # #region agent log
                                    try:
                                        import json
                                        with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                            f.write(json.dumps({"location":"email.py:2075","message":"Logo-Attachment NACH allen Anhängen mit CID markiert","data":{"cid":logo_cid,"filename":attachment_filename},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"G"}) + '\n')
                                    except: pass
                                    # #endregion
                                    logging.info(f"Logo-Attachment nach allen Anhängen mit CID markiert: {attachment_filename}")
                                    break
            
            # #region agent log
            try:
                import json
                if hasattr(msg, 'msg') and msg.msg:
                    msg_ct = msg.msg.get_content_type() if hasattr(msg.msg, 'get_content_type') else 'N/A'
                    parts_count = 0
                    logo_cid_found = None
                    logo_disp_found = None
                    if hasattr(msg.msg, 'get_payload'):
                        parts = msg.msg.get_payload()
                        if isinstance(parts, list):
                            parts_count = len(parts)
                            for p in parts:
                                if hasattr(p, 'get_content_type') and p.get_content_type().startswith('image/'):
                                    disp = p.get('Content-Disposition', '')
                                    if 'logo' in disp.lower():
                                        logo_cid_found = p.get('Content-ID', '')
                                        logo_disp_found = disp
                                        break
                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"location":"email.py:2172","message":"VOR send_email_with_lock() - Finale Message-Struktur","data":{"content_type":msg_ct,"parts_count":parts_count,"logo_cid":logo_cid_found,"logo_disposition":logo_disp_found},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}) + '\n')
                else:
                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"location":"email.py:2172","message":"VOR send_email_with_lock() - msg.msg existiert NICHT","data":{},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}) + '\n')
            except Exception as e:
                try:
                    import json
                    with open(r'c:\Users\ermat\Documents\GitHub\Prismateams_web\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"location":"email.py:2172","message":"FEHLER beim Loggen vor send_email_with_lock()","data":{"error":str(e)},"timestamp":int(__import__('time').time()*1000),"sessionId":"debug-session","runId":"run1","hypothesisId":"B"}) + '\n')
                except: pass
            # #endregion
            
            send_email_with_lock(msg)
            
            # E-Mail im IMAP Sent-Ordner speichern
            try:
                save_email_to_imap_sent(msg)
            except Exception as save_error:
                logging.warning(f"Failed to save email to IMAP Sent folder: {save_error}")
                # Nicht kritisch - E-Mail wurde bereits versendet
            
            email_record = EmailMessage(
                subject=subject,
                sender=sender,
                recipients=to,
                cc=cc,
                body_text=full_body_plain,
                body_html=full_body_html,
                folder='Sent',
                is_sent=True,
                is_read=True,  # E-Mails im "Sent"-Ordner sind immer als gelesen markiert
                sent_by_user_id=current_user.id,
                sent_at=datetime.utcnow(),
                has_attachments=bool(request.files.getlist('attachments')) or bool(forward_attachment_ids) or bool(original_attachment_ids)
            )
            db.session.add(email_record)
            db.session.commit()
            
            success_msg = 'E-Mail wurde erfolgreich gesendet.'
            redirect_url = url_for('email.index')
            
            if is_ajax_request:
                return jsonify({
                    'success': True,
                    'message': success_msg,
                    'redirect_url': redirect_url
                }), 200
            
            flash(success_msg, 'success')
            return redirect(redirect_url)
        
        except Exception as e:
            error_msg = f'Fehler beim Senden der E-Mail: {str(e)}'
            logging.error(f"E-Mail-Versand Fehler: {e}", exc_info=True)
            if is_ajax_request:
                return jsonify({'success': False, 'message': error_msg}), 500
            flash(error_msg, 'danger')
            return render_template('email/compose.html')
    
    return render_template('email/compose.html')


@email_bp.route('/preview/custom', methods=['POST'])
@login_required
@check_module_access('module_email')
def preview_custom_email():
    if not check_email_permission('send'):
        return jsonify({'error': translate('email.errors.unauthorized')}), 403
    
    data = request.get_json(silent=True) or request.form
    if not data:
        return jsonify({'error': translate('email.errors.invalid_data')}), 400
    
    subject = (data.get('subject') or '').strip()
    body_html = (data.get('body') or '').strip()
    
    if not body_html:
        return jsonify({'error': translate('email.errors.message_missing')}), 400
    
    try:
        # In der Vorschau Base64 verwenden, damit das Logo im Browser angezeigt wird
        rendered_html, _ = render_custom_email(subject, body_html, logo_cid=None, is_preview=True)
        return jsonify({'html': rendered_html})
    except Exception as exc:
        current_app.logger.error(f"E-Mail Vorschau Fehler: {exc}")
        return jsonify({'error': translate('email.errors.preview_failed')}), 500


@email_bp.route('/sync', methods=['POST'])
@login_required
@check_module_access('module_email')
def sync_emails():
    """Sync emails from IMAP server (runs in background)."""
    if not check_email_permission('read'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept', '').startswith('application/json'):
            return jsonify({'success': False, 'error': 'Nicht autorisiert'}), 403
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('email.index'))
    
    is_async_request = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.headers.get('Accept', '').startswith('application/json')
    )
    current_folder = request.form.get('folder') or None
    folder_label = None
    if current_folder:
        folder_obj = EmailFolder.query.filter_by(name=current_folder).first()
        folder_label = folder_obj.display_name if folder_obj else current_folder
    
    if not is_async_request:
        try:
            # Verwende Lock, um sicherzustellen, dass nur ein Worker synchronisiert
            with acquire_email_sync_lock(timeout=60) as acquired:
                if acquired:
                    if current_folder:
                        success, message = sync_emails_from_folder(current_folder)
                    else:
                        success, message = sync_emails_from_server()
                    
                    if success:
                        flash(f'✅ {message}', 'success')
                    else:
                        flash(f'❌ FEHLER: {message}', 'danger')
                else:
                    flash(translate('email.flash.sync_already_running'), 'warning')
        except Exception as exc:
            current_app.logger.error(f"E-Mail-Synchronisation Fehler (synchron): {exc}", exc_info=True)
            flash(f'❌ FEHLER bei der Synchronisation: {str(exc)}', 'danger')
        
        target_endpoint = 'email.folder_view' if current_folder else 'email.index'
        target_kwargs = {'folder_name': current_folder} if current_folder else {}
        return redirect(url_for(target_endpoint, **target_kwargs))
    
    user_id = current_user.id
    job_id = f"{user_id}-{uuid4().hex}"
    app_instance = current_app._get_current_object()
    
    def emit_status(status: str, message: str, level: str = 'info', **extras):
        payload = {
            'jobId': job_id,
            'status': status,
            'message': message,
            'level': level,
            'folder': current_folder,
            'folderLabel': folder_label,
        }
        if extras:
            payload.update(extras)
        # SSE-Update senden (funktioniert mit mehreren Gunicorn-Workern)
        emit_email_sync_status(user_id, 'sync_status', payload)
    
    def sync_in_background():
        with app_instance.app_context():
            start_msg = 'Synchronisation gestartet.'
            if folder_label:
                start_msg = f"Synchronisation für '{folder_label}' gestartet."
            emit_status('started', start_msg, 'info', shouldRefresh=False)
            
            try:
                # Verwende Lock, um sicherzustellen, dass nur ein Worker synchronisiert
                with acquire_email_sync_lock(timeout=60) as acquired:
                    if acquired:
                        if current_folder:
                            print(f"E-Mail-Synchronisation wird gestartet (Ordner: {folder_label or current_folder})")
                            success, message = sync_emails_from_folder(current_folder)
                            print(f"E-Mail-Synchronisation wurde beendet (Ordner: {folder_label or current_folder})")
                        else:
                            # sync_emails_from_server() gibt bereits die Meldungen aus
                            success, message = sync_emails_from_server()
                        
                        if success:
                            emit_status('success', message, 'success', shouldRefresh=True)
                        else:
                            emit_status('error', message, 'danger', shouldRefresh=False)
                    else:
                        print("E-Mail-Synchronisation: Bereits in einem anderen Worker aktiv")
                        emit_status('warning', 'Synchronisation läuft bereits in einem anderen Worker. Bitte warten Sie einen Moment.', 'warning', shouldRefresh=False)
            except Exception as exc:
                print(f"E-Mail-Synchronisation Fehler: {exc}")
                app_instance.logger.error(f"E-Mail-Synchronisation Fehler: {exc}", exc_info=True)
                emit_status('error', str(exc), 'danger', shouldRefresh=False)
    
    thread = threading.Thread(target=sync_in_background, name=f"email-sync-{job_id}")
    thread.daemon = True
    thread.start()
    
    response_message = 'Synchronisation gestartet.'
    if folder_label:
        response_message = f"Synchronisation für '{folder_label}' gestartet."
    
    return jsonify({
        'success': True,
        'jobId': job_id,
        'message': response_message,
        'folder': current_folder,
        'folderLabel': folder_label
    }), 202


@email_bp.route('/delete/<int:email_id>', methods=['POST'])
@login_required
@check_module_access('module_email')
def delete_email(email_id):
    """Delete email from both portal and IMAP."""
    if not check_email_permission('read'):
        return jsonify({'error': translate('email.errors.unauthorized')}), 403
    
    email = EmailMessage.query.get_or_404(email_id)
    
    if email.imap_uid:
        success, message = delete_email_from_imap(email.imap_uid, email.folder)
        if not success:
            flash(f'WARNING: E-Mail konnte nicht in IMAP gelöscht werden: {message}', 'warning')
    
    db.session.delete(email)
    db.session.commit()
    
    flash(translate('email.flash.deleted'), 'success')
    return redirect(url_for('email.folder_view', folder_name=email.folder))


@email_bp.route('/move/<int:email_id>', methods=['POST'])
@login_required
@check_module_access('module_email')
def move_email(email_id):
    """Move email to another folder in both portal and IMAP."""
    if not check_email_permission('read'):
        return jsonify({'error': translate('email.errors.unauthorized')}), 403
    
    email = EmailMessage.query.get_or_404(email_id)
    new_folder = request.form.get('folder')
    
    if not new_folder:
        flash(translate('email.flash.target_folder_not_specified'), 'danger')
        return redirect(url_for('email.folder_view', folder_name=email.folder))
    
    if email.imap_uid:
        success, message = move_email_in_imap(email.imap_uid, email.folder, new_folder)
        if not success:
            flash(f'WARNING: E-Mail konnte nicht in IMAP verschoben werden: {message}', 'warning')
    
    old_folder = email.folder
    email.folder = new_folder
    email.last_imap_sync = datetime.utcnow()
    db.session.commit()
    
    flash(f'E-Mail wurde erfolgreich von {old_folder} nach {new_folder} verschoben.', 'success')
    return redirect(url_for('email.folder_view', folder_name=new_folder))


def delete_email_from_imap(email_id, folder_name):
    """Delete email from IMAP server."""
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    try:
        status, messages = mail_conn.select(folder_name)
        if status != 'OK':
            return False, f"Ordner '{folder_name}' konnte nicht geöffnet werden"
        
        status, response = mail_conn.store(email_id, '+FLAGS', '\\Deleted')
        if status != 'OK':
            return False, "E-Mail konnte nicht als gelöscht markiert werden"
        
        status, response = mail_conn.expunge()
        if status != 'OK':
            return False, "E-Mail konnte nicht gelöscht werden"
        
        mail_conn.close()
        mail_conn.logout()
        return True, "E-Mail erfolgreich gelöscht"
        
    except Exception as e:
        logging.error(f"IMAP delete failed: {str(e)}")
        return False, f"Lösch-Fehler: {str(e)}"


def move_email_in_imap(email_id, from_folder, to_folder):
    """Move email between IMAP folders."""
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    try:
        status, messages = mail_conn.select(from_folder)
        if status != 'OK':
            if from_folder != 'INBOX':
                status, messages = mail_conn.select('INBOX')
                if status != 'OK':
                    return False, f"Quellordner '{from_folder}' und INBOX konnten nicht geöffnet werden"
        
        status, response = mail_conn.copy(email_id, to_folder)
        if status != 'OK':
            try:
                mail_conn.create(to_folder)
                status, response = mail_conn.copy(email_id, to_folder)
                if status != 'OK':
                    return False, f"E-Mail konnte nicht nach '{to_folder}' kopiert werden (auch nach Ordner-Erstellung nicht)"
            except:
                return False, f"E-Mail konnte nicht nach '{to_folder}' kopiert werden"
        
        status, response = mail_conn.store(email_id, '+FLAGS', '\\Deleted')
        if status != 'OK':
            return False, "E-Mail konnte nicht als gelöscht markiert werden"
        
        status, response = mail_conn.expunge()
        if status != 'OK':
            return False, "E-Mail konnte nicht verschoben werden"
        
        mail_conn.close()
        mail_conn.logout()
        return True, f"E-Mail erfolgreich nach '{to_folder}' verschoben"
        
    except Exception as e:
        logging.error(f"IMAP move failed: {str(e)}")
        return False, f"Verschieb-Fehler: {str(e)}"


# SSE-basierte Live-Updates (siehe app/blueprints/sse.py)
# Socket.IO wurde durch Server-Sent Events ersetzt für bessere Multi-Worker-Kompatibilität


def email_sync_scheduler(app):
    """Background thread for automatic email synchronization every 15 minutes."""
    print("E-Mail-Sync-Scheduler Thread gestartet, warte 30 Sekunden vor erster Synchronisation...")
    # Warte 30 Sekunden nach App-Start, bevor die erste Synchronisation startet
    time.sleep(30)
    
    while True:
        lock_acquired = False
        try:
            with app.app_context():
                # Verwende Lock, um sicherzustellen, dass nur ein Worker synchronisiert
                from app.utils.lock_manager import acquire_email_sync_lock
                with acquire_email_sync_lock(timeout=10) as acquired:  # Reduziertes Timeout, damit nicht so lange gewartet wird
                    lock_acquired = acquired
                    if acquired:
                        # sync_emails_from_server() gibt bereits die Start/End-Meldungen aus
                        try:
                            success, message = sync_emails_from_server()
                            if success:
                                logging.debug(f"Auto-sync: {message}")
                            else:
                                logging.error(f"Auto-sync failed: {message}")
                        except Exception as sync_error:
                            logging.error(f"Fehler während der Synchronisation: {sync_error}")
                            import traceback
                            logging.error(f"Traceback: {traceback.format_exc()}")
                            print(f"E-Mail-Synchronisation Fehler: {sync_error}")
                    else:
                        logging.debug("E-Mail-Synchronisation wird bereits von anderem Worker durchgeführt, überspringe...")
        except Exception as e:
            logging.error(f"Auto-sync error: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            print(f"E-Mail-Sync-Scheduler Fehler: {e}")
        finally:
            # Stelle sicher, dass wir nach der Synchronisation immer warten
            if lock_acquired:
                print("E-Mail-Synchronisation abgeschlossen, warte 15 Minuten bis zur nächsten...")
        
        # Nach jeder Synchronisation 15 Minuten warten
        time.sleep(900)


sync_thread = None
_sync_started = False
_sync_lock = threading.Lock()

def start_email_sync(app):
    """Start the background email synchronization thread."""
    global sync_thread, _sync_started
    
    # Prüfe zuerst, ob bereits ein Thread mit diesem Namen läuft (auch nach Reload)
    existing_threads = [t for t in threading.enumerate() if t.name == "email-sync-scheduler" and t.is_alive()]
    if existing_threads:
        print(f"E-Mail-Sync-Thread läuft bereits (gefunden {len(existing_threads)} Thread(s)), überspringe Neustart")
        logging.debug(f"E-Mail-Sync-Thread läuft bereits (gefunden {len(existing_threads)} Thread(s)), überspringe Neustart")
        return
    
    # Prüfe auch, ob bereits eine Lock-Datei existiert (zusätzliche Sicherheit)
    try:
        from pathlib import Path
        instance_path = app.instance_path
        lock_file_path = Path(instance_path) / 'locks' / 'email_sync.lock'
        if lock_file_path.exists():
            # Prüfe, ob Lock-Datei noch aktiv ist (jünger als 5 Minuten)
            file_age = time.time() - lock_file_path.stat().st_mtime
            if file_age < 300:  # 5 Minuten
                print("E-Mail-Sync-Lock-Datei existiert bereits, überspringe Neustart")
                logging.debug("E-Mail-Sync-Lock-Datei existiert bereits, überspringe Neustart")
                return
    except Exception as e:
        logging.debug(f"Konnte Lock-Datei nicht prüfen: {e}")
    
    # Verwende Lock, um Thread-Erstellung zu synchronisieren
    with _sync_lock:
        # Doppelte Prüfung innerhalb des Locks
        existing_threads = [t for t in threading.enumerate() if t.name == "email-sync-scheduler" and t.is_alive()]
        if existing_threads:
            print(f"E-Mail-Sync-Thread läuft bereits (zweite Prüfung, {len(existing_threads)} Thread(s)), überspringe Neustart")
            logging.debug(f"E-Mail-Sync-Thread läuft bereits (zweite Prüfung, {len(existing_threads)} Thread(s)), überspringe Neustart")
            return
        
        # Prüfe auch das Flag (für den Fall, dass Thread noch nicht vollständig gestartet ist)
        if _sync_started:
            print("E-Mail-Sync-Thread wird bereits gestartet, überspringe Neustart")
            logging.debug("E-Mail-Sync-Thread wird bereits gestartet, überspringe Neustart")
            return
        
        _sync_started = True
        sync_thread = threading.Thread(target=email_sync_scheduler, args=(app,), daemon=True, name="email-sync-scheduler")
        sync_thread.start()
        print("E-Mail Auto-Sync Thread gestartet")
        logging.debug("E-Mail Auto-Sync gestartet (alle 15 Minuten)")
