"""IMAP folder listing and message sync into the local DB."""

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

from app.blueprints.email.imap_client import (
    _imap_logout,
    _is_placeholder_imap_config,
    _parse_imap_list_line,
    _select_imap_folder,
    connect_imap,
    decode_header_field,
    decode_imap_modutf7,
    gmail_folder_role,
    is_gmail_namespace_root,
    is_sent_folder,
    is_standard_mail_folder,
    truncate_filename,
)
from app.blueprints.email.mailbox import (
    _cleanup_main_mailbox_folder_pollution,
    _find_email_folder,
    _folder_mailbox_filter,
    _is_provider_namespace_folder,
)

def sync_imap_folders(mailbox=None):
    """Sync IMAP folders from server to database."""
    mailbox_id = mailbox.id if mailbox is not None else None
    mail_conn = None
    try:
        mail_conn = connect_imap('INBOX', mailbox=mailbox)
        if not mail_conn:
            logging.error("IMAP-Verbindung fehlgeschlagen beim Synchronisieren der Ordner")
            return False, "IMAP-Verbindung fehlgeschlagen"
    except Exception as conn_error:
        logging.error(f"Fehler beim Verbinden mit IMAP für Ordner-Sync: {conn_error}")
        return False, f"IMAP-Verbindungsfehler: {str(conn_error)}"
    
    try:
        list_rows = []
        status, folders = mail_conn.list()
        if status == 'OK' and folders:
            list_rows.extend(folders)
        else:
            logging.warning("IMAP LIST (root) fehlgeschlagen oder leer: %s", status)

        # Gmail: Sonderordner liegen unter [Gmail] / [Google Mail] – explizit nachlisten
        for ns in ('[Gmail]', '[Google Mail]'):
            try:
                st, more = mail_conn.list(f'"{ns}"', '*')
                if st == 'OK' and more:
                    list_rows.extend(more)
                    logging.info("IMAP LIST unter %s: %s Einträge", ns, len(more))
            except Exception as ns_err:
                logging.debug("IMAP LIST %s übersprungen: %s", ns, ns_err)

        if not list_rows:
            return False, "Ordner-Liste konnte nicht abgerufen werden"

        # Deduplizieren nach Rohzeile
        seen_raw = set()
        unique_rows = []
        for row in list_rows:
            key = row if isinstance(row, (bytes, str)) else repr(row)
            if key in seen_raw:
                continue
            seen_raw.add(key)
            unique_rows.append(row)
        
        synced_folders = []
        skipped_folders = []
        
        logging.info(f"Processing {len(unique_rows)} folders from IMAP server (mailbox_id={mailbox_id})")
        skip_gmail_on_main = False
        if mailbox_id is None:
            try:
                from app.utils.multi_mailboxes import is_email_multi_enabled
                skip_gmail_on_main = bool(is_email_multi_enabled())
            except Exception:
                skip_gmail_on_main = False
        
        for folder_info in unique_rows:
            try:
                folder_name, separator = _parse_imap_list_line(folder_info)
                folder_str = folder_info.decode('utf-8', errors='ignore') if isinstance(folder_info, bytes) else str(folder_info)
                if not folder_name:
                    skipped_folders.append(folder_str)
                    logging.debug(f"Skipping unparsable/invalid folder line: '{folder_str}'")
                    continue

                logging.info(f"Found folder: '{folder_name}'")

                # Nur den Gmail-Root überspringen, nicht [Gmail]/Trash usw.
                if is_gmail_namespace_root(folder_name):
                    logging.debug(f"Skipping Gmail namespace root: '{folder_name}'")
                    continue

                # Bei Multi-Postfach: Gmail-/Google-Mail-Namespaces nicht ins Hauptpostfach
                if skip_gmail_on_main and _is_provider_namespace_folder(folder_name):
                    logging.debug(
                        "Skipping provider namespace folder on Hauptpostfach: %s",
                        folder_name,
                    )
                    continue
                
                is_system = is_standard_mail_folder(folder_name)
                display_name = EmailFolder.get_folder_display_name(folder_name)

                parent_folder = None
                if separator in folder_name:
                    parent_candidate = folder_name.rsplit(separator, 1)[0]
                    # Gmail-Root nicht als Parent speichern (sonst hängen Kinder an fehlendem Knoten)
                    if parent_candidate and parent_candidate != folder_name and not is_gmail_namespace_root(parent_candidate):
                        parent_folder = parent_candidate
                    else:
                        parent_folder = None

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
                    'mailbox_id': mailbox_id,
                }

                try:
                    existing_folder = _find_email_folder(folder_name, mailbox_id)
                    if existing_folder:
                        existing_folder.display_name = display_name
                        existing_folder.folder_type = folder_type
                        existing_folder.is_system = is_system
                        existing_folder.parent_folder = parent_folder
                        existing_folder.separator = separator
                        existing_folder.last_synced = now
                        logging.debug(f"Updated existing folder: '{folder_name}'")
                    else:
                        db.session.add(EmailFolder(**folder_payload))
                        logging.info(f"Added new folder: '{folder_name}' ({display_name})")
                    synced_folders.append(folder_name)
                except IntegrityError:
                    db.session.rollback()
                    existing_folder = _find_email_folder(folder_name, mailbox_id)
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
                                last_synced=datetime.utcnow(),
                                mailbox_id=mailbox_id,
                            ))
                            db.session.flush()
                            synced_folders.append(folder_name)
                            logging.info(f"Inserted folder after retry: '{folder_name}'")
                        except IntegrityError as retry_error:
                            db.session.rollback()
                            logging.error(f"Failed to insert folder '{folder_name}' after retry: {retry_error}")
                            continue
                        
            except Exception as e:
                logging.error(f"Fehler beim Verarbeiten des Ordners '{folder_str if 'folder_str' in locals() else folder_info}': {e}")
                continue
        
        logging.info(f"Synced {len(synced_folders)} folders, skipped {len(skipped_folders)} invalid folders")
        
        invalid_folder_names = ['/', '']
        for invalid_name in invalid_folder_names:
            invalid_folders = (
                EmailFolder.query.filter_by(name=invalid_name)
                .filter(_folder_mailbox_filter(mailbox_id))
                .all()
            )
            for invalid_folder in invalid_folders:
                logging.info(f"Removing invalid folder '{invalid_name}' from database")
                db.session.delete(invalid_folder)
        
        db.session.commit()
        if mailbox_id is None:
            _cleanup_main_mailbox_folder_pollution()
        
        # Schließe IMAP-Verbindung sicher
        if mail_conn:
            try:
                mail_conn.close()
            except Exception as close_error:
                logging.debug(f"Fehler beim Schließen der IMAP-Verbindung: {close_error}")
            try:
                mail_conn.logout()
            except Exception as logout_error:
                logging.debug(f"Fehler beim Logout von IMAP: {logout_error}")
        
        return True, f"{len(synced_folders)} Ordner synchronisiert"
        
    except Exception as e:
        logging.error(f"Folder sync failed: {str(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        
        # Stelle sicher, dass IMAP-Verbindung geschlossen wird
        if mail_conn:
            try:
                mail_conn.close()
            except:
                pass
            try:
                mail_conn.logout()
            except:
                pass
        
        return False, f"Ordner-Sync-Fehler: {str(e)}"


def sync_emails_from_folder(folder_name, mail_conn=None, mailbox=None):
    """Sync emails from a specific IMAP folder with bidirectional support.

    Args:
        folder_name: IMAP-Ordnername
        mail_conn: Optionale bestehende IMAP-Verbindung (wird nicht geschlossen).
                   Wenn None, wird eine neue Verbindung geöffnet und am Ende geschlossen.
        mailbox: Optional Mailbox model (None = Hauptpostfach)
    """
    mailbox_id = mailbox.id if mailbox is not None else None
    owns_connection = mail_conn is None
    try:
        if owns_connection:
            mail_conn = connect_imap(folder_name, mailbox=mailbox)
            if not mail_conn:
                logging.error(f"IMAP-Verbindung fehlgeschlagen für Ordner '{folder_name}'")
                return False, f"IMAP-Verbindung fehlgeschlagen für Ordner '{folder_name}'"
        else:
            ok, messages = _select_imap_folder(mail_conn, folder_name)
            if not ok:
                error_msg = ''
                try:
                    if messages and len(messages) > 0:
                        if isinstance(messages[0], bytes):
                            error_msg = messages[0].decode('utf-8', errors='ignore')
                        else:
                            error_msg = str(messages[0])
                except Exception:
                    error_msg = 'Unbekannter Fehler'
                is_archive_folder = folder_name in ['Archive', 'Archives']
                if "doesn't exist" in error_msg or "Mailbox doesn't exist" in error_msg or "NONEXISTENT" in error_msg:
                    if is_archive_folder:
                        logging.debug(
                            "IMAP folder '%s' does not exist on server, skipping sync: %s",
                            folder_name, error_msg,
                        )
                    else:
                        logging.info(
                            "IMAP folder '%s' does not exist on server, skipping sync: %s",
                            folder_name, error_msg,
                        )
                    return True, f"Ordner '{folder_name}' existiert nicht auf dem Server, übersprungen"
                logging.warning("IMAP folder selection failed for '%s': %s", folder_name, error_msg)
                return True, f"Ordner '{folder_name}' konnte nicht geöffnet werden, übersprungen: {error_msg}"
    except Exception as conn_error:
        logging.error(f"Fehler beim Verbinden mit IMAP für Ordner '{folder_name}': {conn_error}")
        if owns_connection:
            _imap_logout(mail_conn)
        return False, f"IMAP-Verbindungsfehler: {str(conn_error)}"
    
    stats = {
        'new_emails': 0,
        'updated_emails': 0,
        'moved_emails': 0,
        'deleted_emails': 0,
        'skipped_emails': 0,
        'errors': 0
    }
    
    try:
        # Haupt-Synchronisations-Logik
        # Versuche Ordner zu öffnen (bei owns_connection bereits selected; nochmals absichern)
        status, messages = mail_conn.select(folder_name)
        if status != 'OK':
            # Versuche mit Anführungszeichen (für Ordner mit Leerzeichen)
            try:
                status, messages = mail_conn.select(f'"{folder_name}"')
            except Exception as quote_error:
                logging.debug(f"Could not select folder '{folder_name}' with quotes: {quote_error}")
            
            if status != 'OK':
                # Ordner existiert nicht auf dem Server - überspringen, aber in DB behalten
                error_msg = ''
                try:
                    if messages and len(messages) > 0:
                        if isinstance(messages[0], bytes):
                            error_msg = messages[0].decode('utf-8', errors='ignore')
                        else:
                            error_msg = str(messages[0])
                except Exception:
                    error_msg = 'Unbekannter Fehler'
                
                # Prüfe ob es sich um einen Archiv-Ordner handelt (Archive oder Archives)
                is_archive_folder = folder_name in ['Archive', 'Archives']
                if "doesn't exist" in error_msg or "Mailbox doesn't exist" in error_msg or "NONEXISTENT" in error_msg:
                    if is_archive_folder:
                        logging.debug(f"IMAP folder '{folder_name}' does not exist on server, skipping sync (normal for empty archive folders): {error_msg}")
                    else:
                        logging.info(f"IMAP folder '{folder_name}' does not exist on server, skipping sync: {error_msg}")
                    if owns_connection:
                        _imap_logout(mail_conn)
                    return True, f"Ordner '{folder_name}' existiert nicht auf dem Server, übersprungen"
                else:
                    logging.warning(f"IMAP folder selection failed for '{folder_name}': {error_msg}")
                    if owns_connection:
                        _imap_logout(mail_conn)
                    return True, f"Ordner '{folder_name}' konnte nicht geöffnet werden, übersprungen: {error_msg}"
    except Exception as e:
        logging.error(f"Exception while selecting folder '{folder_name}': {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        if owns_connection:
            _imap_logout(mail_conn)
        return True, f"Ordner '{folder_name}' konnte nicht geöffnet werden, übersprungen: {str(e)}"
    
    # Haupt-Synchronisations-Logik
    try:
        # Ermittle die höchste bereits synchronisierte UID für diesen Ordner + Postfach
        highest_uid = None
        try:
            highest_uid_result = db.session.query(
                func.max(cast(EmailMessage.imap_uid, Integer))
            ).filter_by(folder=folder_name, mailbox_id=mailbox_id).scalar()
            if highest_uid_result:
                highest_uid = int(highest_uid_result)
                logging.debug(f"Highest UID for folder '{folder_name}' mailbox={mailbox_id}: {highest_uid}")
        except Exception as e:
            logging.debug(f"Could not determine highest UID for folder '{folder_name}': {e}")
        
        # Initialisiere Variablen
        all_seq_numbers = []
        seq_to_uid = {}
        
        # Verwende search() für Sequenznummern (zuverlässiger als uid_search)
        status, messages = mail_conn.search(None, 'ALL')
        if status != 'OK':
            logging.error(f"IMAP search failed for folder '{folder_name}': {messages}")
            if owns_connection:
                _imap_logout(mail_conn)
            return False, f"E-Mail-Suche in Ordner '{folder_name}' fehlgeschlagen: {messages[0].decode() if messages else 'Unbekannter Fehler'}"
        
        all_seq_numbers = messages[0].split() if messages[0] else []
        logging.info(f"Found {len(all_seq_numbers)} total emails in folder '{folder_name}'")
        
        if len(all_seq_numbers) == 0:
            logging.info(f"No emails found in folder '{folder_name}' on server")
            if owns_connection:
                _imap_logout(mail_conn)
            return True, f"Ordner '{folder_name}': Keine E-Mails vorhanden"
        
        # Hole UIDs für alle E-Mails
        # Verwende FETCH mit UID für alle Sequenznummern auf einmal
        if len(all_seq_numbers) > 0:
            try:
                first_seq = all_seq_numbers[0].decode() if isinstance(all_seq_numbers[0], bytes) else str(all_seq_numbers[0])
                last_seq = all_seq_numbers[-1].decode() if isinstance(all_seq_numbers[-1], bytes) else str(all_seq_numbers[-1])
                seq_range = f"{first_seq}:{last_seq}" if len(all_seq_numbers) > 1 else first_seq
                status, uid_data = mail_conn.fetch(seq_range, '(UID)')
                
                # Erstelle Mapping von Sequenznummer zu UID
                if status == 'OK' and uid_data:
                    import re
                    for item in uid_data:
                        uid_info = None
                        # Handle both tuple and bytes formats
                        if isinstance(item, tuple) and len(item) > 0:
                            # Format: (b'1 (UID 123)', b'...')
                            uid_info = item[0].decode('utf-8', errors='ignore') if isinstance(item[0], bytes) else str(item[0])
                        elif isinstance(item, bytes):
                            # Format: b'1 (UID 123)' - direct bytes object
                            uid_info = item.decode('utf-8', errors='ignore')
                        elif isinstance(item, str):
                            # Format: '1 (UID 123)' - direct string
                            uid_info = item
                        
                        if uid_info:
                            # Parse: "1 (UID 123)" -> seq=1, uid=123
                            match = re.search(r'(\d+)\s+\(UID\s+(\d+)\)', uid_info)
                            if match:
                                seq_num = match.group(1)
                                uid_num = match.group(2)
                                seq_to_uid[seq_num] = uid_num
                
                # Falls Batch-Abfrage nicht alle UIDs zurückgegeben hat, hole sie einzeln
                if len(seq_to_uid) < len(all_seq_numbers):
                    logging.debug(f"Batch UID fetch returned {len(seq_to_uid)} UIDs, but {len(all_seq_numbers)} emails exist. Fetching remaining UIDs individually...")
                    for seq_bytes in all_seq_numbers:
                        seq_str = seq_bytes.decode() if isinstance(seq_bytes, bytes) else str(seq_bytes)
                        if seq_str not in seq_to_uid:
                            try:
                                status_single, uid_data_single = mail_conn.fetch(seq_str, '(UID)')
                                if status_single == 'OK' and uid_data_single:
                                    import re
                                    for item in uid_data_single:
                                        uid_info = None
                                        # Handle both tuple and bytes formats
                                        if isinstance(item, tuple) and len(item) > 0:
                                            uid_info = item[0].decode('utf-8', errors='ignore') if isinstance(item[0], bytes) else str(item[0])
                                        elif isinstance(item, bytes):
                                            uid_info = item.decode('utf-8', errors='ignore')
                                        elif isinstance(item, str):
                                            uid_info = item
                                        
                                        if uid_info:
                                            match = re.search(r'\(UID\s+(\d+)\)', uid_info)
                                            if match:
                                                seq_to_uid[seq_str] = match.group(1)
                                                break
                            except Exception as single_fetch_error:
                                logging.debug(f"Failed to fetch UID for sequence {seq_str}: {single_fetch_error}")
                                # Fallback: Verwende Sequenznummer als UID
                                seq_to_uid[seq_str] = seq_str
                
                logging.debug(f"Created UID mapping for {len(seq_to_uid)} emails in folder '{folder_name}'")
            except Exception as uid_fetch_error:
                logging.warning(f"Failed to fetch UIDs for folder '{folder_name}': {uid_fetch_error}")
                # Falls UID-Abfrage komplett fehlschlägt, verwende Sequenznummern als Fallback
                for seq_bytes in all_seq_numbers:
                    seq_str = seq_bytes.decode() if isinstance(seq_bytes, bytes) else str(seq_bytes)
                    seq_to_uid[seq_str] = seq_str
                logging.debug(f"Using sequence numbers as UID fallback for {len(seq_to_uid)} emails")
        
        from app.utils.email_sync_index import FolderSyncIndex, mark_missing_server_uids
        sync_index = FolderSyncIndex(folder_name, mailbox_id)

        # Filtere nach neuen E-Mails (UID > highest_uid)
        logging.info(f"Filtering emails for folder '{folder_name}': highest_uid={highest_uid}, seq_to_uid mapping has {len(seq_to_uid)} entries")
        
        if highest_uid:
            email_seqs = []
            emails_without_uid = []
            
            for seq_bytes in all_seq_numbers:
                seq_str = seq_bytes.decode() if isinstance(seq_bytes, bytes) else str(seq_bytes)
                uid_str = seq_to_uid.get(seq_str)
                if uid_str:
                    try:
                        email_uid = int(uid_str)
                        if email_uid > highest_uid:
                            email_seqs.append(seq_bytes)
                    except (ValueError, AttributeError):
                        # Falls UID nicht als Integer geparst werden kann, prüfe ob E-Mail existiert
                        emails_without_uid.append(seq_bytes)
                else:
                    # Falls keine UID im Mapping, prüfe ob E-Mail bereits in DB existiert
                    emails_without_uid.append(seq_bytes)
            
            # Für E-Mails ohne UID: Prüfe ob sie bereits in DB existieren
            if emails_without_uid:
                logging.info(f"Checking {len(emails_without_uid)} emails without UID mapping in folder '{folder_name}'")
                for seq_bytes in emails_without_uid:
                    seq_str = seq_bytes.decode() if isinstance(seq_bytes, bytes) else str(seq_bytes)
                    try:
                        status_test, msg_data_test = mail_conn.fetch(seq_str, '(RFC822)')
                        if status_test == 'OK' and msg_data_test:
                            raw_email_test = msg_data_test[0][1]
                            email_msg_test = email_module.message_from_bytes(raw_email_test)
                            message_id_test = email_msg_test.get('Message-ID', '')
                            if message_id_test:
                                existing = sync_index.get_by_mid(message_id_test)
                                if not existing:
                                    email_seqs.append(seq_bytes)
                                    logging.info(f"Email with sequence {seq_str} (Message-ID: {message_id_test[:50]}) not in database, adding to sync list")
                            else:
                                # Keine Message-ID - füge zur Sicherheit hinzu
                                email_seqs.append(seq_bytes)
                                logging.info(f"Email with sequence {seq_str} has no Message-ID, adding to sync list")
                    except Exception as e:
                        logging.debug(f"Error checking email with sequence {seq_str}: {e}")
                        # Bei Fehler, füge zur Sicherheit hinzu (besser zu viel als zu wenig)
                        email_seqs.append(seq_bytes)
            
            logging.info(f"Found {len(email_seqs)} new emails in folder '{folder_name}' with UID > {highest_uid} (or without UID mapping)")
            email_ids = email_seqs
        else:
            # Erste Synchronisation: Verwende alle Sequenznummern
            email_ids = all_seq_numbers
            logging.info(f"First sync for folder '{folder_name}', processing all {len(email_ids)} emails")
        
        # Für die Prüfung gelöschter E-Mails: Hole alle UIDs vom Server (nur wenn nicht erste Sync)
        # WICHTIG: Nur prüfen, wenn seq_to_uid vollständig ist (alle E-Mails haben UIDs)
        if highest_uid and len(seq_to_uid) > 0 and len(seq_to_uid) == len(all_seq_numbers):
            # Nur wenn wir schon E-Mails haben UND das UID-Mapping vollständig ist, prüfen wir auf gelöschte
            current_imap_uids = set(seq_to_uid.values())
            mark_missing_server_uids(sync_index, current_imap_uids, stats)
        else:
            # UID-Mapping ist nicht vollständig - keine Prüfung auf gelöschte E-Mails
            # (verhindert, dass E-Mails fälschlicherweise gelöscht werden)
            if highest_uid:
                logging.debug(f"Skipping deleted email check for folder '{folder_name}' - UID mapping incomplete ({len(seq_to_uid)}/{len(all_seq_numbers)})")

        if len(email_ids) == 0:
            logging.info(f"No new emails to sync in folder '{folder_name}' (all {len(all_seq_numbers)} emails already in database or filtered out)")
            emails_to_process = []
        else:
            # Bei erster Synchronisation: Nur die letzten N E-Mails verarbeiten
            if not highest_uid:
                is_special_folder = is_standard_mail_folder(folder_name)
                max_emails = 100 if not is_special_folder else 30
                emails_to_process = email_ids[-max_emails:] if len(email_ids) > max_emails else email_ids
                logging.debug(f"First sync: Processing {len(emails_to_process)} emails from folder '{folder_name}' (max: {max_emails})")
            else:
                emails_to_process = email_ids
                logging.debug(f"Processing {len(emails_to_process)} new emails from folder '{folder_name}'")
        
        for idx, email_id in enumerate(emails_to_process, 1):
            # Initialisiere Variablen für Exception-Handler
            subject = "Unknown"
            sender = "Unknown"
            imap_uid_str = None
            
            try:
                # Konvertiere email_id zu String (Sequenznummer)
                email_id_str = email_id.decode() if isinstance(email_id, bytes) else str(email_id)
                
                # Hole UID aus dem Mapping
                imap_uid_str = seq_to_uid.get(email_id_str)
                if not imap_uid_str:
                    # Falls UID nicht im Mapping, versuche sie direkt abzurufen
                    try:
                        status_uid, uid_data = mail_conn.fetch(email_id_str, '(UID)')
                        if status_uid == 'OK' and uid_data:
                            for item in uid_data:
                                uid_info = None
                                # Handle both tuple and bytes formats
                                if isinstance(item, tuple) and len(item) > 0:
                                    uid_info = item[0].decode('utf-8', errors='ignore') if isinstance(item[0], bytes) else str(item[0])
                                elif isinstance(item, bytes):
                                    uid_info = item.decode('utf-8', errors='ignore')
                                elif isinstance(item, str):
                                    uid_info = item
                                
                                if uid_info:
                                    import re
                                    match = re.search(r'\(UID\s+(\d+)\)', uid_info)
                                    if match:
                                        imap_uid_str = match.group(1)
                                        break
                    except:
                        pass
                
                if not imap_uid_str:
                    logging.debug(f"Could not determine UID for sequence {email_id_str}, skipping")
                    stats['errors'] += 1
                    continue
                
                # FLAGS abrufen um Gelesen-Status zu bestimmen
                is_read_imap = False
                try:
                    flags_status, flags_result = mail_conn.fetch(email_id_str, '(FLAGS)')
                    
                    if flags_status == 'OK' and flags_result and len(flags_result) > 0:
                        flags_entry = flags_result[0]
                        # FLAGS können als Tuple oder Bytes kommen
                        if isinstance(flags_entry, tuple) and len(flags_entry) > 1:
                            # Format: (b'1 (FLAGS (\\Seen))', b'...')
                            flags_str = flags_entry[0].decode('utf-8', errors='ignore') if isinstance(flags_entry[0], bytes) else str(flags_entry[0])
                        elif isinstance(flags_entry, tuple):
                            flags_str = flags_entry[0].decode('utf-8', errors='ignore') if isinstance(flags_entry[0], bytes) else str(flags_entry[0])
                        else:
                            flags_str = flags_entry.decode('utf-8', errors='ignore') if isinstance(flags_entry, bytes) else str(flags_entry)
                        
                        # Prüfe ob \Seen Flag vorhanden ist
                        is_read_imap = '\\Seen' in flags_str or '\\SEEN' in flags_str
                except Exception as flags_error:
                    logging.debug(f"Failed to fetch FLAGS for email {imap_uid_str} from folder '{folder_name}': {flags_error}")
                    # Weiter mit is_read_imap = False
                
                # RFC822 (E-Mail-Inhalt) abrufen
                status, msg_data = mail_conn.fetch(email_id_str, '(RFC822)')
                
                if status != 'OK' or not msg_data:
                    logging.debug(f"Failed to fetch email {imap_uid_str} from folder '{folder_name}': {msg_data}")
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
                
                # imap_uid_str wurde bereits oben bestimmt
                
                if not message_id:
                    # Wichtig für Move-Sync: Fallback-ID muss über Ordner hinweg stabil sein.
                    # Sonst wird dieselbe Mail nach Verschieben als neue Mail erkannt.
                    try:
                        stable_fingerprint = '|'.join([
                            (sender or '').strip().lower(),
                            (recipients or '').strip().lower(),
                            (subject or '').strip().lower(),
                            (date_str or '').strip().lower(),
                        ])
                        digest = hashlib.sha1(stable_fingerprint.encode('utf-8', errors='ignore')).hexdigest()
                        message_id = f"<generated-{digest}@local>"
                    except Exception:
                        message_id = f"<generated-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}@local>"
                    logging.debug(f"Generated stable message_id for email without Message-ID: {message_id}")
                
                received_at = datetime.utcnow()
                try:
                    from email.utils import parsedate_to_datetime
                    received_at = parsedate_to_datetime(date_str)
                except:
                    pass
                
                # Bestimme is_read Status für Updates:
                # 1. E-Mails im "Sent"-Ordner sind immer als gelesen markiert
                # 2. Andere Ordner: basierend auf IMAP FLAGS (\Seen)
                is_sent_folder_flag = is_sent_folder(folder_name)
                if is_sent_folder_flag:
                    is_read_status = True
                else:
                    is_read_status = is_read_imap
                
                existing_in_folder = sync_index.get_by_uid(imap_uid_str)
                
                if existing_in_folder:
                    try:
                        existing_in_folder.last_imap_sync = datetime.utcnow()
                        # Stelle sicher, dass E-Mail nicht als gelöscht markiert ist (wiederherstellen falls nötig)
                        if existing_in_folder.is_deleted_imap:
                            existing_in_folder.is_deleted_imap = False
                            logging.debug(f"Restoring email {imap_uid_str} in folder '{folder_name}' - was marked as deleted but found on server")
                        existing_in_folder.last_imap_sync = datetime.utcnow()
                        existing_in_folder.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                        existing_in_folder.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                        stats['updated_emails'] += 1
                        db.session.commit()
                        continue
                    except Exception as update_error:
                        if "MySQL server has gone away" in str(update_error) or "ConnectionResetError" in str(update_error):
                            logging.debug("Database connection lost during update, attempting to reconnect...")
                            db.session.rollback()
                            db.session.close()
                            db.session = db.create_scoped_session()
                            sync_index.reload()
                            existing_in_folder = sync_index.get_by_uid(imap_uid_str)
                            if existing_in_folder:
                                existing_in_folder.last_imap_sync = datetime.utcnow()
                                existing_in_folder.is_deleted_imap = False
                                existing_in_folder.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                                existing_in_folder.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                                stats['updated_emails'] += 1
                                db.session.commit()
                                logging.debug("Database reconnection successful for update")
                            continue
                        else:
                            raise update_error
                
                existing_by_message_id = sync_index.get_by_mid(message_id)
                if existing_by_message_id:
                    if existing_by_message_id.folder == folder_name:
                        try:
                            existing_by_message_id.last_imap_sync = datetime.utcnow()
                            existing_by_message_id.is_deleted_imap = False
                            existing_by_message_id.imap_uid = imap_uid_str
                            existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                            existing_by_message_id.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                            stats['updated_emails'] += 1
                            db.session.commit()
                            continue
                        except Exception as update_error:
                            if "MySQL server has gone away" in str(update_error) or "ConnectionResetError" in str(update_error):
                                logging.debug("Database connection lost during update, attempting to reconnect...")
                                db.session.rollback()
                                db.session.close()
                                db.session = db.create_scoped_session()
                                sync_index.reload()
                                existing_by_message_id = sync_index.get_by_mid(message_id)
                                if existing_by_message_id and existing_by_message_id.folder == folder_name:
                                    existing_by_message_id.last_imap_sync = datetime.utcnow()
                                    existing_by_message_id.is_deleted_imap = False
                                    existing_by_message_id.imap_uid = imap_uid_str
                                    existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP
                                    existing_by_message_id.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
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
                            existing_by_message_id.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                            stats['moved_emails'] += 1
                            db.session.commit()
                            continue
                        except Exception as move_error:
                            if "MySQL server has gone away" in str(move_error) or "ConnectionResetError" in str(move_error):
                                logging.debug("Database connection lost during move, attempting to reconnect...")
                                db.session.rollback()
                                db.session.close()
                                db.session = db.create_scoped_session()
                                sync_index.reload()
                                existing_by_message_id = sync_index.get_by_mid(message_id)
                                if existing_by_message_id:
                                    existing_by_message_id.folder = folder_name
                                    existing_by_message_id.imap_uid = imap_uid_str
                                    existing_by_message_id.last_imap_sync = datetime.utcnow()
                                    existing_by_message_id.is_deleted_imap = False
                                    existing_by_message_id.is_read = is_read_status  # Synchronisiere Gelesen-Status von IMAP beim Ordnerwechsel
                                    existing_by_message_id.is_sent = is_sent_folder_flag  # Aktualisiere is_sent Status
                                    stats['moved_emails'] += 1
                                    db.session.commit()
                                    logging.debug("Database reconnection successful for move")
                                continue
                            else:
                                raise move_error
                
                # Globale Message-ID existiert evtl. in anderem Postfach – für dieses Postfach neu anlegen.
                # Unique auf message_id: Suffix nur wenn Kollision mit anderem mailbox_id.
                insert_message_id = message_id
                owner_mailbox = sync_index.global_owner_mailbox(message_id)
                if owner_mailbox is not None and owner_mailbox != mailbox_id:
                    suffix = f"mb{mailbox_id if mailbox_id is not None else 0}"
                    insert_message_id = f"{message_id}#{suffix}"
                    existing_suffixed = sync_index.get_by_mid(insert_message_id)
                    if existing_suffixed:
                        existing_suffixed.folder = folder_name
                        existing_suffixed.imap_uid = imap_uid_str
                        existing_suffixed.last_imap_sync = datetime.utcnow()
                        existing_suffixed.is_deleted_imap = False
                        existing_suffixed.is_read = is_read_status
                        existing_suffixed.is_sent = is_sent_folder_flag
                        stats['updated_emails'] += 1
                        db.session.commit()
                        continue
                message_id = insert_message_id

                body_text = ""
                body_html = ""
                has_attachments = False
                attachments_data = []
                
                if email_msg.is_multipart():
                    for part in email_msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = part.get('Content-Disposition', '')
                        content_id_header = (part.get('Content-ID', '') or '').strip()

                        # Inline-Bilder aus multipart/related haben oft KEIN Content-Disposition,
                        # nur einen Content-ID-Header. Diese Parts müssen trotzdem als Attachment
                        # gespeichert werden, sonst können cid:-Referenzen im HTML nie aufgelöst werden.
                        is_related_inline = (
                            bool(content_id_header)
                            and not content_type.startswith('text/')
                            and not content_type.startswith('multipart/')
                            and 'attachment' not in content_disposition
                            and 'inline' not in content_disposition
                        )

                        if (
                            ('attachment' in content_disposition or 'inline' in content_disposition)
                            and not content_type.startswith('text/')
                        ) or is_related_inline:
                            has_attachments = True
                            if is_related_inline:
                                content_disposition = (content_disposition or '') + '; inline'
                            
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

                # Booking-Thread: Antworten auf Buchungsmails nicht in der normalen Inbox zeigen
                try:
                    from app.utils.booking_messages import try_route_inbound_email
                    routed = try_route_inbound_email(
                        email_msg,
                        message_id=message_id,
                        sender=sender,
                        subject=subject,
                        recipients=recipients or '',
                        body_text=body_text or '',
                        body_html=body_html or '',
                    )
                    if routed:
                        stats['skipped_emails'] += 1
                        logging.info(
                            f"Email {message_id} routed to booking thread, skipped inbox "
                            f"(folder={folder_name})"
                        )
                        continue
                except Exception as booking_route_error:
                    logging.error(f"Booking email routing failed: {booking_route_error}")
                
                # Bestimme is_read Status:
                # 1. E-Mails im "Sent"-Ordner sind immer als gelesen markiert (man hat sie selbst versendet)
                # 2. Andere Ordner: basierend auf IMAP FLAGS (\Seen)
                is_sent_folder_flag = is_sent_folder(folder_name)
                if is_sent_folder_flag:
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
                    imap_uid=imap_uid_str,
                    last_imap_sync=datetime.utcnow(),
                    is_deleted_imap=False,
                    received_at=received_at,
                    is_read=is_read_status,
                    is_sent=is_sent_folder_flag,
                    mailbox_id=mailbox_id,
                )
                
                try:
                    db.session.add(email_entry)
                    db.session.flush()
                    sync_index.remember(email_entry)
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
                subject_display = subject if 'subject' in locals() and subject else "Unknown"
                logging.error(f"Error saving email '{subject_display}': {e}")
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
        
        # Schließe IMAP-Verbindung sicher
        try:
            if owns_connection:
                _imap_logout(mail_conn)
        except Exception as close_error:
            logging.debug(f"Fehler beim Schließen der IMAP-Verbindung: {close_error}")
        
        # Navbar-/Dashboard-Badge: immer aktuellen Unread-Stand pushen
        try:
            from app.utils.email_counts import emit_email_unread_update
            emit_email_unread_update()
        except Exception as e:
            logging.error(f"Fehler beim Senden der Dashboard-Updates für E-Mails: {e}")

        if stats['new_emails'] > 0:
            try:
                last_email = EmailMessage.query.filter_by(is_sent=False).order_by(EmailMessage.id.desc()).first()
                if last_email:
                    send_email_notification(last_email.id)
            except Exception as e:
                logging.error(f"Fehler beim Senden der E-Mail-Benachrichtigung: {e}")

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
            result_msg = f"Ordner '{folder_name}': {', '.join(sync_details)}"
        else:
            result_msg = f"Ordner '{folder_name}': Keine Änderungen"
        
        return True, result_msg
        
    except Exception as e:
        logging.error(f"Email sync from folder failed: {str(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        
        # Stelle sicher, dass IMAP-Verbindung geschlossen wird (nur eigene)
        if owns_connection:
            _imap_logout(mail_conn)
        
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


def sync_emails_from_server(mailbox=None):
    """Sync emails from IMAP server to database with folder support.

    mailbox=None → Hauptpostfach (App-Config).
    """
    label = f"mailbox#{mailbox.id}" if mailbox is not None else "main"
    logger.info(f"E-Mail-Synchronisation wird gestartet ({label})")
    
    shared_conn = None
    try:
        from app.utils.multi_mailboxes import get_mailbox_imap_config
        cfg = get_mailbox_imap_config(mailbox)
        imap_server = cfg.get('server')
        username = cfg.get('user')
        password = cfg.get('password')
        auth_type = (getattr(mailbox, 'auth_type', None) or 'password') if mailbox is not None else 'password'
        # OAuth-Postfächer haben kein IMAP-Passwort – Platzhalter-Check nur für Passwort-Auth
        if auth_type != 'oauth' and _is_placeholder_imap_config(imap_server, username, password):
            message = "IMAP ist nicht konfiguriert (Platzhalterwerte erkannt) - Synchronisation übersprungen"
            logger.warning(message)
            return False, message
        if not imap_server or not username:
            message = "IMAP-Konfiguration unvollständig (Server/Benutzer fehlen)"
            logging.warning(message)
            return False, message

        # Synchronisiere zuerst die Ordner-Liste
        folder_success, folder_message = sync_imap_folders(mailbox=mailbox)
        if not folder_success:
            logging.warning(f"Ordner-Sync-Warnung: {folder_message}")
            # Weiter mit Standard-Ordnern, auch wenn Ordner-Sync fehlschlägt
            logging.info("Verwende Standard-Ordner als Fallback")
        
        mailbox_id = mailbox.id if mailbox is not None else None
        # Hole Ordner aus Datenbank
        folder_rows = (
            db.session.query(EmailFolder.name, EmailFolder.display_name)
            .filter(_folder_mailbox_filter(mailbox_id))
            .all()
        )
        if not folder_rows:
            # Fallback: Verwende Standard-Ordner
            folder_rows = [('INBOX', 'Posteingang')]
            logging.info("Keine Ordner in Datenbank gefunden, verwende Standard-Ordner")
        
        logging.info(f"Syncing emails from {len(folder_rows)} folders: {[name for (name, _) in folder_rows]}")
        
        # Eine IMAP-Session für alle Ordner (weniger Logins, schneller, Provider-freundlicher)
        shared_conn = connect_imap('INBOX', mailbox=mailbox)
        if not shared_conn:
            message = "IMAP-Verbindung fehlgeschlagen - Synchronisation abgebrochen"
            logging.error(message)
            return False, message

        total_synced = 0
        total_new = 0
        folder_results = []
        successful_folders = 0
        failed_folders = 0
        
        for (folder_name, display_name) in folder_rows:
            try:
                heartbeat_email_sync_lock()
                logging.info(f"Syncing folder: '{folder_name}' ({display_name})")
                success, message = sync_emails_from_folder(
                    folder_name, mail_conn=shared_conn, mailbox=mailbox
                )
                if success:
                    successful_folders += 1
                    import re
                    # Suche nach verschiedenen Mustern für Anzahl
                    match = re.search(r'(\d+)\s+(neu|new)', message, re.IGNORECASE)
                    if match:
                        count = int(match.group(1))
                        total_new += count
                    # Auch nach "E-Mails" suchen
                    match = re.search(r'(\d+)\s+E-Mails', message, re.IGNORECASE)
                    if match:
                        count = int(match.group(1))
                        total_synced += count
                    folder_results.append(f"{display_name}: {message}")
                    logging.info(f"✓ Ordner '{folder_name}' erfolgreich synchronisiert: {message}")
                else:
                    failed_folders += 1
                    logging.warning(f"✗ Ordner '{folder_name}' konnte nicht synchronisiert werden: {message}")
                    folder_results.append(f"{display_name}: Fehler - {message}")
            except Exception as folder_error:
                failed_folders += 1
                logging.error(f"Fehler beim Synchronisieren des Ordners '{folder_name}': {folder_error}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                folder_results.append(f"{display_name}: Fehler - {str(folder_error)}")
                continue
        
        logger.info(f"E-Mail-Synchronisation wurde beendet: {successful_folders} Ordner erfolgreich, {failed_folders} Ordner fehlgeschlagen")
        
        # Erstelle Ergebnis-Meldung
        if total_new > 0:
            result_msg = f"{total_new} neue E-Mails aus {successful_folders} Ordnern synchronisiert"
        elif total_synced > 0:
            result_msg = f"{total_synced} E-Mails aus {successful_folders} Ordnern synchronisiert"
        elif successful_folders > 0:
            result_msg = f"{successful_folders} Ordner synchronisiert (keine neuen E-Mails)"
        else:
            result_msg = "Keine E-Mails synchronisiert"
        
        if failed_folders > 0:
            result_msg += f" ({failed_folders} Ordner fehlgeschlagen)"
        
        return True, result_msg
    except Exception as e:
        logging.error(f"Kritischer Fehler in sync_emails_from_server: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        logger.error(f"E-Mail-Synchronisation Fehler: {e}", exc_info=True)
        return False, f"Kritischer Fehler: {str(e)}"
    finally:
        if shared_conn is not None:
            _imap_logout(shared_conn)


def sync_all_configured_mailboxes():
    """Sync Hauptpostfach + alle aktiven Multi-Postfächer (wenn Multi aktiv)."""
    results = []
    ok_main, msg_main = sync_emails_from_server(mailbox=None)
    results.append(('main', ok_main, msg_main))

    try:
        from app.utils.multi_mailboxes import get_active_sync_mailboxes, is_email_multi_enabled
        if is_email_multi_enabled():
            for mb in get_active_sync_mailboxes():
                try:
                    ok, msg = sync_emails_from_server(mailbox=mb)
                    results.append((f'mailbox#{mb.id}', ok, msg))
                except Exception as exc:
                    logging.error(f"Multi-Postfach-Sync fehlgeschlagen ({mb.id}): {exc}")
                    results.append((f'mailbox#{mb.id}', False, str(exc)))
    except Exception as exc:
        logging.error(f"Multi-Postfach-Sync Setup-Fehler: {exc}")

    any_ok = any(r[1] for r in results)
    summary = '; '.join(f'{name}: {msg}' for name, _, msg in results)
    return any_ok, summary
