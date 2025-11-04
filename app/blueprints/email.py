from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file, Response
from flask_login import login_required, current_user
from app import db, mail
from app.models.email import EmailMessage, EmailPermission, EmailAttachment, EmailFolder
from app.models.settings import SystemSettings
from app.utils.notifications import send_email_notification
from flask_mail import Message
from datetime import datetime, timedelta
import imaplib
import email as email_module
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import threading
import time
import logging
import io
import sqlalchemy
from markupsafe import Markup

email_bp = Blueprint('email', __name__)


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
                    
                    # Filter out invalid folder names
                    if not folder_name or folder_name.strip() == '' or folder_name == '/' or folder_name.strip() == '/':
                        logging.debug(f"Skipping invalid folder name: '{folder_name}'")
                        continue
                    
                    # Skip system/metadata folders
                    skip_folders = ['[Gmail]', '[Google Mail]', '&XfJT0ZAB-', '&XfJSI-']
                    if any(skip in folder_name for skip in skip_folders):
                        logging.debug(f"Skipping system folder: '{folder_name}'")
                        continue
                    
                    is_system = folder_name in ['INBOX', 'Sent', 'Sent Messages', 'Drafts', 'Trash', 'Deleted Messages', 'Spam', 'Junk', 'Archive']
                    display_name = EmailFolder.get_folder_display_name(folder_name)
                    
                    existing_folder = EmailFolder.query.filter_by(name=folder_name).first()
                    if not existing_folder:
                        folder = EmailFolder(
                            name=folder_name,
                            display_name=display_name,
                            folder_type='standard' if is_system else 'custom',
                            is_system=is_system,
                            last_synced=datetime.utcnow()
                        )
                        db.session.add(folder)
                        synced_folders.append(folder_name)
                        logging.info(f"Added new folder: '{folder_name}' ({display_name})")
                    else:
                        existing_folder.last_synced = datetime.utcnow()
                        synced_folders.append(folder_name)
                        logging.debug(f"Updated existing folder: '{folder_name}'")
                else:
                    skipped_folders.append(folder_str)
                        
            except Exception as e:
                logging.error(f"Fehler beim Verarbeiten des Ordners '{folder_str if 'folder_str' in locals() else folder_info}': {e}")
                continue
        
        logging.info(f"Synced {len(synced_folders)} folders, skipped {len(skipped_folders)} invalid folders")
        
        # Remove invalid folders from database (e.g., "/")
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
    
    # Statistiken für strukturierte Ausgabe
    stats = {
        'new_emails': 0,
        'updated_emails': 0,
        'moved_emails': 0,
        'deleted_emails': 0,
        'skipped_emails': 0,
        'errors': 0
    }
    
    try:
        # Select the folder - use quoted folder name for folders with special characters
        try:
            status, messages = mail_conn.select(folder_name)
            if status != 'OK':
                # Try with quoted folder name
                try:
                    status, messages = mail_conn.select(f'"{folder_name}"')
                except:
                    pass
                if status != 'OK':
                    logging.error(f"IMAP folder selection failed for '{folder_name}': {messages}")
                    # Entferne lokal nicht vorhandenen Ordner, um künftige Fehlversuche zu vermeiden
                    try:
                        db_folder = EmailFolder.query.filter_by(name=folder_name).first()
                        if db_folder:
                            db.session.delete(db_folder)
                            db.session.commit()
                            logging.info(f"Removed non-existent folder '{folder_name}' from local database")
                    except Exception as _cleanup_err:
                        db.session.rollback()
                    return False, f"Ordner '{folder_name}' konnte nicht geöffnet werden: {messages[0].decode() if messages else 'Unbekannter Fehler'}"
        except Exception as e:
            logging.error(f"Exception while selecting folder '{folder_name}': {e}")
            return False, f"Fehler beim Öffnen des Ordners '{folder_name}': {str(e)}"
        
        # Get message count
        try:
            message_count = int(messages[0].decode().split()[1])
            logging.info(f"Folder '{folder_name}' contains {message_count} messages")
        except:
            message_count = 0
        
        status, messages = mail_conn.search(None, 'ALL')
        if status != 'OK':
            logging.error(f"IMAP search failed for folder '{folder_name}': {messages}")
            return False, f"E-Mail-Suche in Ordner '{folder_name}' fehlgeschlagen: {messages[0].decode() if messages else 'Unbekannter Fehler'}"
        
        email_ids = messages[0].split()
        logging.info(f"Found {len(email_ids)} email IDs in folder '{folder_name}'")
        
        if len(email_ids) == 0:
            logging.info(f"No emails found in folder '{folder_name}'")
            mail_conn.close()
            mail_conn.logout()
            return True, f"Ordner '{folder_name}': Keine E-Mails vorhanden"
        
        synced_count = 0
        moved_count = 0
        deleted_count = 0
        
        current_imap_uids = set()
        for email_id in email_ids:
            current_imap_uids.add(email_id.decode())
        
        existing_emails = EmailMessage.query.filter_by(folder=folder_name).all()
        for email_obj in existing_emails:
            if email_obj.imap_uid and email_obj.imap_uid not in current_imap_uids:
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
        
        max_emails = 100 if folder_name not in ['INBOX', 'Sent', 'Drafts', 'Trash', 'Spam', 'Archive'] else 30
        emails_to_process = email_ids[-max_emails:] if len(email_ids) > max_emails else email_ids
        logging.info(f"Processing {len(emails_to_process)} emails from folder '{folder_name}' (max: {max_emails})")
        
        for idx, email_id in enumerate(emails_to_process, 1):
            try:
                if idx % 10 == 0:
                    logging.debug(f"Processing email {idx}/{len(emails_to_process)} from folder '{folder_name}'")
                
                status, msg_data = mail_conn.fetch(email_id, '(RFC822)')
                if status != 'OK':
                    logging.warning(f"Failed to fetch email {email_id.decode()} from folder '{folder_name}': {msg_data}")
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
                
                # Decode imap_uid first (needed for both message_id generation and lookup)
                imap_uid_str = email_id.decode()
                
                # Generate a fallback message_id if not present
                # Use a combination of folder, imap_uid, and date for uniqueness
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
                
                # Check if email already exists in THIS specific folder (using imap_uid and folder)
                existing_in_folder = EmailMessage.query.filter_by(
                    imap_uid=imap_uid_str,
                    folder=folder_name
                ).first()
                
                if existing_in_folder:
                    # Email already exists in this folder, just update sync timestamp
                    try:
                        existing_in_folder.last_imap_sync = datetime.utcnow()
                        existing_in_folder.is_deleted_imap = False
                        stats['updated_emails'] += 1
                        db.session.commit()
                        continue
                    except Exception as update_error:
                        # If update fails due to connection issues, try to reconnect
                        if "MySQL server has gone away" in str(update_error) or "ConnectionResetError" in str(update_error):
                            logging.warning("Database connection lost during update, attempting to reconnect...")
                            db.session.rollback()
                            db.session.close()
                            db.session = db.create_scoped_session()
                            # Retry the update
                            existing_in_folder = EmailMessage.query.filter_by(
                                imap_uid=imap_uid_str,
                                folder=folder_name
                            ).first()
                            if existing_in_folder:
                                existing_in_folder.last_imap_sync = datetime.utcnow()
                                existing_in_folder.is_deleted_imap = False
                                stats['updated_emails'] += 1
                                db.session.commit()
                                logging.info("Database reconnection successful for update")
                            continue
                        else:
                            raise update_error
                
                # Prüfe global nach message_id und bewege ggf. in den aktuellen Ordner
                existing_by_message_id = EmailMessage.query.filter_by(message_id=message_id).first()
                if existing_by_message_id:
                    if existing_by_message_id.folder == folder_name:
                        try:
                            existing_by_message_id.last_imap_sync = datetime.utcnow()
                            existing_by_message_id.is_deleted_imap = False
                            existing_by_message_id.imap_uid = imap_uid_str
                            stats['updated_emails'] += 1
                            db.session.commit()
                            continue
                        except Exception as update_error:
                            if "MySQL server has gone away" in str(update_error) or "ConnectionResetError" in str(update_error):
                                logging.warning("Database connection lost during update, attempting to reconnect...")
                                db.session.rollback()
                                db.session.close()
                                db.session = db.create_scoped_session()
                                existing_by_message_id = EmailMessage.query.filter_by(message_id=message_id).first()
                                if existing_by_message_id and existing_by_message_id.folder == folder_name:
                                    existing_by_message_id.last_imap_sync = datetime.utcnow()
                                    existing_by_message_id.is_deleted_imap = False
                                    existing_by_message_id.imap_uid = imap_uid_str
                                    stats['updated_emails'] += 1
                                    db.session.commit()
                                    logging.info("Database reconnection successful for update")
                                continue
                            else:
                                raise update_error
                    else:
                        # Mail wurde verschoben – ordne sie diesem Ordner zu
                        try:
                            existing_by_message_id.folder = folder_name
                            existing_by_message_id.imap_uid = imap_uid_str
                            existing_by_message_id.last_imap_sync = datetime.utcnow()
                            existing_by_message_id.is_deleted_imap = False
                            stats['moved_emails'] += 1
                            db.session.commit()
                            continue
                        except Exception as move_error:
                            if "MySQL server has gone away" in str(move_error) or "ConnectionResetError" in str(move_error):
                                logging.warning("Database connection lost during move, attempting to reconnect...")
                                db.session.rollback()
                                db.session.close()
                                db.session = db.create_scoped_session()
                                existing_by_message_id = EmailMessage.query.filter_by(message_id=message_id).first()
                                if existing_by_message_id:
                                    existing_by_message_id.folder = folder_name
                                    existing_by_message_id.imap_uid = imap_uid_str
                                    existing_by_message_id.last_imap_sync = datetime.utcnow()
                                    existing_by_message_id.is_deleted_imap = False
                                    stats['moved_emails'] += 1
                                    db.session.commit()
                                    logging.info("Database reconnection successful for move")
                                continue
                            else:
                                raise move_error
                
                # If we reach here, the email doesn't exist in the database yet
                
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
                            
                            # Process attachment - wrap in try-except to ensure email is still saved if attachment fails
                            try:
                                filename = part.get_filename()
                                if not filename:
                                    # Generate filename from content type
                                    extension = content_type.split('/')[-1] if '/' in content_type else 'bin'
                                    filename = f"attachment_{len(attachments_data)}.{extension}"
                                
                                # Decode filename if needed
                                if filename:
                                    try:
                                        from email.header import decode_header
                                        decoded_filename = decode_header(filename)
                                        if decoded_filename and decoded_filename[0][0]:
                                            filename = decoded_filename[0][0]
                                    except:
                                        pass  # Use original filename if decoding fails
                                
                                # Try to get content - handle large files gracefully
                                try:
                                    # For very large files, check size first if possible
                                    payload = None
                                    try:
                                        payload = part.get_payload(decode=True)
                                    except Exception as decode_error:
                                        # If decoding fails (e.g., memory error), log and continue
                                        logging.error(f"Failed to decode attachment '{filename}': {decode_error}")
                                        has_attachments = True  # Mark as having attachments even if we can't process it
                                        continue
                                    
                                    if payload:
                                        attachment_size = len(payload)
                                        
                                        # Log all attachments, especially large ones
                                        if attachment_size > 1 * 1024 * 1024:  # > 1MB
                                            logging.info(f"Processing large attachment: '{filename}' ({attachment_size / (1024*1024):.2f} MB) - saving to disk")
                                        else:
                                            logging.debug(f"Processing attachment: '{filename}' ({attachment_size / (1024*1024):.2f} MB) - saving to database")
                                        
                                        # Check if file should be stored on disk (>1MB) or in database (≤1MB)
                                        # Using 1MB to avoid MySQL max_allowed_packet errors
                                        max_db_size = 1 * 1024 * 1024  # 1MB limit for database storage
                                        
                                        logging.info(f"Attachment '{filename}': {attachment_size / (1024*1024):.2f} MB, max_db_size: {max_db_size / (1024*1024):.2f} MB, will store on: {'disk' if attachment_size > max_db_size else 'database'}")
                                        
                                        if attachment_size > max_db_size:
                                            # Store large file on disk
                                            import os
                                            
                                            # Create attachments directory if it doesn't exist
                                            attachments_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'attachments')
                                            os.makedirs(attachments_dir, exist_ok=True)
                                            
                                            # Generate unique filename
                                            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                                            safe_filename = "".join(c for c in filename if c.isalnum() or c in '._- ')
                                            file_path = os.path.join(attachments_dir, f"{timestamp}_{safe_filename}")
                                            
                                            # Write file to disk
                                            try:
                                                with open(file_path, 'wb') as f:
                                                    f.write(payload)
                                                logging.info(f"Large attachment saved to disk: {file_path}")
                                                
                                                attachments_data.append({
                                                    'filename': filename,
                                                    'content_type': content_type,
                                                    'content': None,  # Not stored in database
                                                    'file_path': file_path,
                                                    'size': attachment_size,
                                                    'is_inline': 'inline' in content_disposition,
                                                    'content_id': part.get('Content-ID', '').strip('<>'),
                                                    'is_large_file': True
                                                })
                                            except Exception as file_error:
                                                logging.error(f"Error saving large file to disk: {file_error}")
                                                # Fallback: try to save in database anyway
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
                                            # Store in database for smaller files
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
                                    has_attachments = True  # Mark as having attachments even if we skip it
                                    continue
                                except Exception as payload_error:
                                    logging.error(f"Error getting payload for attachment '{filename}': {payload_error}. Email will be saved without this attachment.")
                                    has_attachments = True  # Mark as having attachments even if we skip it
                                    continue
                            except Exception as e:
                                logging.error(f"Error processing attachment '{filename if 'filename' in locals() else 'unknown'}': {e}. Email will be saved without this attachment.")
                                has_attachments = True  # Mark as having attachments even if we skip it
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
                                        # Append to existing HTML content if multipart
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
                
                
                # Apply configuration limits
                html_max_length = current_app.config.get('EMAIL_HTML_MAX_LENGTH', 0)
                text_max_length = current_app.config.get('EMAIL_TEXT_MAX_LENGTH', 10000)
                
                # Truncate if limits are set
                if html_max_length > 0 and body_html and len(body_html) > html_max_length:
                    body_html = body_html[:html_max_length]
                
                if text_max_length > 0 and body_text and len(body_text) > text_max_length:
                    body_text = body_text[:text_max_length]
                
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
                    is_read=False,
                    is_sent=False
                )
                
                try:
                    db.session.add(email_entry)
                    db.session.flush()  # Get the email ID
                except sqlalchemy.exc.IntegrityError as integrity_error:
                    # Handle duplicate message_id (email exists in another folder)
                    if "Duplicate entry" in str(integrity_error) or "1062" in str(integrity_error):
                        logging.debug(f"Email with message_id '{message_id}' already exists in another folder, skipping")
                        stats['skipped_emails'] += 1
                        db.session.rollback()
                        continue
                    else:
                        raise  # Re-raise if it's a different integrity error
                
                # Process attachments with improved error handling for large files
                for attachment_data in attachments_data:
                    try:
                        attachment_size = attachment_data['size']
                        filename = attachment_data['filename']
                        
                        # Log large attachments during save
                        if attachment_size > 1 * 1024 * 1024:
                            logging.info(f"Processing large attachment: '{filename}' ({attachment_size / (1024*1024):.2f} MB) - from disk")
                        
                        # Create attachment object based on storage type
                        attachment = EmailAttachment(
                            email_id=email_entry.id,
                            filename=filename,
                            content_type=attachment_data['content_type'],
                            size=attachment_size,
                            content=attachment_data.get('content'),  # May be None for large files
                            file_path=attachment_data.get('file_path'),  # May be None for small files
                            is_inline=attachment_data['is_inline'],
                            content_id=attachment_data['content_id'] if attachment_data['content_id'] else None,
                            is_large_file=attachment_data.get('is_large_file', False)
                        )
                        
                        db.session.add(attachment)
                        
                        # For large attachments, flush immediately to ensure they're saved
                        if attachment_size > 1 * 1024 * 1024:  # > 1MB - flush for all large attachments
                            try:
                                db.session.flush()
                                logging.info(f"Successfully flushed attachment '{filename}' ({attachment_size / (1024*1024):.2f} MB) to database")
                            except Exception as flush_error:
                                logging.warning(f"Flush failed for '{filename}', will commit with email: {flush_error}")
                                # Don't fail, will commit together with email
                    except Exception as e:
                        logging.error(f"Error saving attachment '{attachment_data['filename']}' ({attachment_data['size'] / (1024*1024):.2f} MB): {e}")
                        import traceback
                        logging.error(f"Traceback: {traceback.format_exc()}")
                        # Don't skip - try to save even if there's an error
                        # The user wants all attachments saved
                        continue
                
                # Commit with retry logic for MySQL connection issues
                try:
                    db.session.commit()
                    stats['new_emails'] += 1
                except Exception as commit_error:
                    # Handle duplicate entry errors gracefully
                    if "Duplicate entry" in str(commit_error) or "1062" in str(commit_error):
                        logging.debug(f"Email with message_id '{message_id}' already exists, skipping duplicate")
                        stats['skipped_emails'] += 1
                        db.session.rollback()
                        continue
                    # If commit fails due to connection issues, try to reconnect
                    if "MySQL server has gone away" in str(commit_error) or "ConnectionResetError" in str(commit_error):
                        logging.warning("Database connection lost, attempting to reconnect...")
                        db.session.rollback()
                        db.session.close()
                        db.session = db.create_scoped_session()
                        # Retry the commit
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
                        logging.info("Database reconnection successful")
                    else:
                        raise commit_error
            except Exception as e:
                stats['errors'] += 1
                logging.error(f"Error saving email '{subject}': {e}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                db.session.rollback()
                # Continue to next email instead of breaking the entire sync
                continue
                
            except MemoryError as mem_error:
                stats['errors'] += 1
                logging.error(f"Memory error syncing email from folder '{folder_name}': {mem_error}")
                db.session.rollback()
                # Skip this email and continue with others
                continue
            except Exception as e:
                stats['errors'] += 1
                logging.error(f"Error syncing email from folder '{folder_name}': {e}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                db.session.rollback()
                # Continue to next email instead of breaking the entire sync
                continue
        
        db.session.commit()
        mail_conn.close()
        mail_conn.logout()
        
        # Strukturierte Ausgabe der Synchronisationsstatistiken
        print(f"\n--- E-Mail Synchronisation ---")
        print(f"Ordner: {folder_name}")
        print(f"Neue E-Mails: {stats['new_emails']}")
        print(f"Übersprungene E-Mails: {stats['updated_emails']}")
        print(f"Geänderte E-Mails: {stats['moved_emails']}")
        print(f"Gelöschte E-Mails: {stats['deleted_emails']}")
        if stats['errors'] > 0:
            print(f"Fehler: {stats['errors']}")
        print(f"--- --- ---\n")
        
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


def sync_emails_from_server():
    """Sync emails from IMAP server to database with folder support."""
    folder_success, folder_message = sync_imap_folders()
    if not folder_success:
        logging.warning(f"Ordner-Sync-Warnung: {folder_message}")
    
    folder_rows = db.session.query(EmailFolder.name, EmailFolder.display_name).all()
    if not folder_rows:
        folder_rows = [('INBOX', 'Posteingang')]
    
    logging.info(f"Syncing emails from {len(folder_rows)} folders: {[name for (name, _) in folder_rows]}")
    
    total_synced = 0
    folder_results = []
    
    for (folder_name, display_name) in folder_rows:
        logging.info(f"Syncing folder: '{folder_name}' ({display_name})")
        success, message = sync_emails_from_folder(folder_name)
        if success:
            import re
            match = re.search(r'(\d+) E-Mails', message)
            if match:
                count = int(match.group(1))
                total_synced += count
            folder_results.append(f"{display_name}: {message}")
        else:
            logging.warning(f"Failed to sync folder '{folder_name}': {message}")
            folder_results.append(f"{display_name}: Fehler - {message}")
    
    if total_synced > 0:
        return True, f"{total_synced} E-Mails aus {len(folder_rows)} Ordnern synchronisiert"
    else:
        # Kein Fehlerzustand – nur keine Änderungen
        return True, "Keine E-Mails synchronisiert"


def check_email_permission(permission_type='read'):
    """Check if current user has email permissions."""
    perm = EmailPermission.query.filter_by(user_id=current_user.id).first()
    if not perm:
        return False
    return perm.can_read if permission_type == 'read' else perm.can_send


@email_bp.route('/')
@login_required
def index():
    """Email inbox with folder support."""
    if not check_email_permission('read'):
        flash('Sie haben keine Berechtigung, E-Mails zu lesen.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    current_folder = request.args.get('folder', 'INBOX')
    emails = EmailMessage.query.filter_by(folder=current_folder).order_by(EmailMessage.received_at.desc()).all()
    
    # Custom folder ordering: Standard folders first, then custom folders
    all_folders = EmailFolder.query.all()
    
    # Define standard folder order
    standard_folder_order = ['INBOX', 'Drafts', 'Sent', 'Archive', 'Trash', 'Spam']
    standard_folder_names = ['Posteingang', 'Entwürfe', 'Gesendet', 'Archiv', 'Papierkorb', 'Spam']
    
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
    
    return render_template('email/index.html', emails=emails, folders=folders, current_folder=current_folder)


@email_bp.route('/folder/<folder_name>')
@login_required
def folder_view(folder_name):
    """View emails in a specific folder."""
    if not check_email_permission('read'):
        flash('Sie haben keine Berechtigung, E-Mails zu lesen.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    # URL-decode folder name in case it's encoded
    from urllib.parse import unquote
    folder_name = unquote(folder_name)
    
    # Reject invalid folder names
    if not folder_name or folder_name.strip() == '' or folder_name == '/':
        flash('Ungültiger Ordnername.', 'danger')
        return redirect(url_for('email.index'))
    
    # Check if folder exists, if not redirect to index
    folder_obj = EmailFolder.query.filter_by(name=folder_name).first()
    if not folder_obj:
        # Remove invalid folder from database if it exists in email_messages
        existing_emails = EmailMessage.query.filter_by(folder=folder_name).count()
        if existing_emails > 0:
            logging.warning(f"Folder '{folder_name}' exists in emails but not in folders table")
        flash(f'Ordner "{folder_name}" nicht gefunden.', 'warning')
        return redirect(url_for('email.index'))
    
    # Get emails from this folder
    emails = EmailMessage.query.filter_by(folder=folder_name).order_by(EmailMessage.received_at.desc()).all()
    
    # Log for debugging
    logging.info(f"Viewing folder '{folder_name}' with {len(emails)} emails")
    
    # Custom folder ordering: Standard folders first, then custom folders
    all_folders = EmailFolder.query.all()
    
    # Define standard folder order
    standard_folder_order = ['INBOX', 'Drafts', 'Sent', 'Archive', 'Trash', 'Spam']
    standard_folder_names = ['Posteingang', 'Entwürfe', 'Gesendet', 'Archiv', 'Papierkorb', 'Spam']
    
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
def view_email(email_id):
    """View a specific email."""
    if not check_email_permission('read'):
        flash('Sie haben keine Berechtigung, E-Mails zu lesen.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    email_msg = EmailMessage.query.get_or_404(email_id)
    
    if not email_msg.is_read:
        email_msg.is_read = True
        db.session.commit()
    
    
    html_content = None
    if email_msg.body_html:
        try:
            # Decode HTML content properly
            if isinstance(email_msg.body_html, bytes):
                html_content = email_msg.body_html.decode('utf-8', errors='replace')
            else:
                html_content = str(email_msg.body_html)
            
            
            # Clean up problematic characters that break display
            import re
            
            # Replace problematic Unicode characters
            html_content = html_content.replace('\u2011', '-')
            html_content = html_content.replace('\u2013', '-')
            html_content = html_content.replace('\u2014', '--')
            html_content = html_content.replace('\u2018', "'")
            html_content = html_content.replace('\u2019', "'")
            html_content = html_content.replace('\u201c', '"')
            html_content = html_content.replace('\u201d', '"')
            html_content = html_content.replace('\u2026', '...')
            html_content = html_content.replace('\ufffc', '')
            
            # Remove Microsoft Word artifacts
            html_content = re.sub(r'<o:p\s*/>', '', html_content)
            html_content = re.sub(r'<o:p>.*?</o:p>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<w:.*?>.*?</w:.*?>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<m:.*?>.*?</m:.*?>', '', html_content, flags=re.DOTALL)
            html_content = re.sub(r'<v:.*?>.*?</v:.*?>', '', html_content, flags=re.DOTALL)
            
            # Make links secure but preserve original styling
            html_content = re.sub(r'<a([^>]*)href="([^"]*)"([^>]*)>', r'<a\1href="\2" target="_blank" rel="noopener noreferrer"\3>', html_content)
            
            # Remove body/html tags that might affect the page background
            html_content = re.sub(r'<body[^>]*>', '<div class="email-body-wrapper">', html_content, flags=re.IGNORECASE)
            html_content = re.sub(r'</body>', '</div>', html_content, flags=re.IGNORECASE)
            html_content = re.sub(r'<html[^>]*>', '', html_content, flags=re.IGNORECASE)
            html_content = re.sub(r'</html>', '', html_content, flags=re.IGNORECASE)
            
            # Remove style tags that might affect the page
            html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.IGNORECASE | re.DOTALL)
            
            # Remove inline styles from body/html tags
            html_content = re.sub(r'<body[^>]*style="[^"]*"[^>]*>', '<div class="email-body-wrapper">', html_content, flags=re.IGNORECASE)
            
            # Ensure proper HTML structure if missing
            if not html_content.strip().startswith('<'):
                html_content = f'<div class="email-body-wrapper">{html_content}</div>'
            
            # Wrap in a container to isolate styles
            html_content = f'<div class="email-content-isolated-inner">{html_content}</div>'
            
            # Handle inline images
            for attachment in email_msg.attachments:
                if attachment.is_inline and attachment.content_type.startswith('image/'):
                    data_url = attachment.get_data_url()
                    if data_url:
                        cid_pattern = f'cid:{attachment.filename}'
                        html_content = html_content.replace(f'src="{cid_pattern}"', f'src="{data_url}"')
                        html_content = html_content.replace(f"src='{cid_pattern}'", f"src='{data_url}'")
                        # Also handle content-id references
                        content_id = attachment.content_id
                        if content_id:
                            html_content = html_content.replace(f'src="cid:{content_id}"', f'src="{data_url}"')
                            html_content = html_content.replace(f"src='cid:{content_id}'", f"src='{data_url}'")
            
            # Fix remaining cid: references with placeholder
            html_content = re.sub(r'src="cid:([^"]+)"', r'src="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y4ZjlmYSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjE0IiBmaWxsPSIjNmM3NTdkIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+SW1hZ2U8L3RleHQ+PC9zdmc+"', html_content)
            
            
        except Exception as e:
            logging.error(f"HTML processing error: {e}")
            html_content = None
    
    return render_template('email/view.html', email=email_msg, html_content=html_content)


# -------- Reply/Forward helpers --------
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
    # de-duplicate case-insensitively
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
    # Use text content if available, otherwise convert HTML to plain text
    body = email_msg.body_text or ''
    if not body and email_msg.body_html:
        # Simple HTML to text conversion
        import re
        body = re.sub(r'<[^>]+>', '', email_msg.body_html)
        body = body.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    
    header = build_plain_quote_header(email_msg)
    
    # Quote each line with >
    quoted_lines = []
    quoted_lines.append(header)
    for line in body.split('\n'):
        quoted_lines.append(f"> {line}")
    
    return '\n'.join(quoted_lines)


def build_reply_context(email_msg: EmailMessage, mode: str):
    # recipients
    to_list = []
    # Absender der Originalmail als primärer Empfänger
    if email_msg.sender:
        to_list += normalize_addresses(email_msg.sender)
    cc_list = []
    if mode == 'reply_all':
        to_list += normalize_addresses(email_msg.recipients)
        cc_list += normalize_addresses(email_msg.cc)
        # Eigene Adresse entfernen
        own = (current_user.email or '').lower()
        to_list = [a for a in to_list if a.lower() != own]
        cc_list = [a for a in cc_list if a.lower() != own]
    # unique again
    to_list = normalize_addresses(to_list)
    cc_list = normalize_addresses(cc_list)

    subject = prefix_subject(email_msg.subject or '', 'Re')
    body_prefill = quote_plain(email_msg)
    return {
        'to': ', '.join(to_list),
        'cc': ', '.join(cc_list),
        'subject': subject,
        'body': body_prefill,
        'in_reply_to': email_msg.message_id or '',
        'references': email_msg.message_id or ''
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
def reply(email_id: int):
    if not check_email_permission('send'):
        flash('Sie haben keine Berechtigung, E-Mails zu senden.', 'danger')
        return redirect(url_for('email.view_email', email_id=email_id))
    email_msg = EmailMessage.query.get_or_404(email_id)
    ctx = build_reply_context(email_msg, 'reply')
    return render_template('email/compose.html', **ctx)


@email_bp.route('/reply-all/<int:email_id>')
@login_required
def reply_all(email_id: int):
    if not check_email_permission('send'):
        flash('Sie haben keine Berechtigung, E-Mails zu senden.', 'danger')
        return redirect(url_for('email.view_email', email_id=email_id))
    email_msg = EmailMessage.query.get_or_404(email_id)
    ctx = build_reply_context(email_msg, 'reply_all')
    return render_template('email/compose.html', **ctx)


@email_bp.route('/forward/<int:email_id>')
@login_required
def forward(email_id: int):
    if not check_email_permission('send'):
        flash('Sie haben keine Berechtigung, E-Mails zu senden.', 'danger')
        return redirect(url_for('email.view_email', email_id=email_id))
    email_msg = EmailMessage.query.get_or_404(email_id)
    ctx = build_forward_context(email_msg, include_attachments=True)
    return render_template('email/compose.html', **ctx)


@email_bp.route('/attachment/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    """Download an email attachment with support for large files."""
    if not check_email_permission('read'):
        flash('Sie haben keine Berechtigung, E-Mails zu lesen.', 'danger')
        return redirect(url_for('email.index'))
    
    attachment = EmailAttachment.query.get_or_404(attachment_id)
    email_msg = attachment.email
    if not email_msg:
        flash('Anhang nicht gefunden.', 'danger')
        return redirect(url_for('email.index'))
    
    try:
        # Log large file downloads
        if attachment.size > 1 * 1024 * 1024:  # > 1MB
            logging.info(f"Downloading large attachment: '{attachment.filename}' ({attachment.size / (1024*1024):.2f} MB)")
        
        # Handle large files stored on disk
        if attachment.is_large_file and attachment.file_path:
            import os
            if os.path.exists(attachment.file_path):
                def generate():
                    with open(attachment.file_path, 'rb') as f:
                        while True:
                            data = f.read(8192)  # Read in chunks
                            if not data:
                                break
                            yield data
                
                response = Response(generate(), mimetype=attachment.content_type)
                # Properly encode filename for HTTP headers to handle Unicode characters
                import urllib.parse
                encoded_filename = urllib.parse.quote(attachment.filename.encode('utf-8'))
                response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
                response.headers['Content-Length'] = str(attachment.size)
                response.headers['Accept-Ranges'] = 'bytes'
                return response
            else:
                flash('Anhang-Datei nicht gefunden.', 'danger')
                return redirect(url_for('email.view_email', email_id=email_msg.id))
        else:
            # Handle files stored in database
            content = attachment.get_content()
            if not content:
                flash('Anhang nicht gefunden oder beschädigt.', 'danger')
                return redirect(url_for('email.index'))
            
            file_obj = io.BytesIO(content)
            
            # For very large files, set appropriate headers for streaming
            response = send_file(
                file_obj,
                as_attachment=True,
                download_name=attachment.filename,
                mimetype=attachment.content_type
            )
            
            # Properly encode filename for HTTP headers to handle Unicode characters
            import urllib.parse
            encoded_filename = urllib.parse.quote(attachment.filename.encode('utf-8'))
            response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
            
            # Set content length header for proper progress indication
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
def compose():
    """Compose and send an email."""
    if not check_email_permission('send'):
        flash('Sie haben keine Berechtigung, E-Mails zu senden.', 'danger')
        return redirect(url_for('email.index'))
    
    if request.method == 'POST':
        to = request.form.get('to', '').strip()
        cc = request.form.get('cc', '').strip()
        subject = request.form.get('subject', '').strip()
        # Get HTML body from Rich Text Editor
        body_html = request.form.get('body', '').strip()
        in_reply_to = request.form.get('in_reply_to', '').strip()
        references = request.form.get('references', '').strip()
        forward_attachment_ids = request.form.get('forward_attachment_ids', '').strip()
        
        if not all([to, subject, body_html]):
            flash('Bitte füllen Sie alle Pflichtfelder aus.', 'danger')
            return render_template('email/compose.html')
        
        # Get configurable email footer
        footer_template = SystemSettings.query.filter_by(key='email_footer_template').first()
        
        # Convert HTML body to plain text for email body
        import re
        from html import unescape
        body_plain = re.sub(r'<[^>]+>', '', body_html)
        body_plain = unescape(body_plain).strip()
        
        if footer_template and footer_template.value:
            # Use configurable template with variables
            footer = footer_template.value
            # Replace variables
            footer = footer.replace('<user>', current_user.full_name)
            footer = footer.replace('<email>', current_user.email)
            footer = footer.replace('<app_name>', current_app.config.get('APP_NAME', 'Prismateams'))
            footer = footer.replace('<date>', datetime.utcnow().strftime('%d.%m.%Y'))
            footer = footer.replace('<time>', datetime.utcnow().strftime('%H:%M'))
        else:
            # Fallback to old system
            footer_text_setting = SystemSettings.query.filter_by(key='email_footer_text').first()
            footer_img = SystemSettings.query.filter_by(key='email_footer_image').first()
            
            footer = f"\n\n---\n{footer_text_setting.value if footer_text_setting else ''}\n"
            footer += f"Gesendet von {current_user.full_name}"
        
        full_body_plain = body_plain + footer
        full_body_html = body_html + footer
        
        try:
            # Get sender from config or use MAIL_USERNAME as fallback
            sender = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('MAIL_USERNAME')
            if not sender:
                flash('E-Mail-Absender ist nicht konfiguriert. Bitte kontaktieren Sie den Administrator.', 'danger')
                return render_template('email/compose.html')
            
            # Create multipart message with HTML and plain text
            msg = Message(
                subject=subject,
                recipients=to.split(','),
                body=full_body_plain,
                html=full_body_html,
                sender=sender
            )

            # Threading headers (Flask-Mail: use extra_headers)
            thread_headers = {}
            if in_reply_to:
                thread_headers['In-Reply-To'] = in_reply_to
            if references:
                thread_headers['References'] = references
            if thread_headers:
                # merge with any existing extra headers
                existing = getattr(msg, 'extra_headers', None)
                if existing and isinstance(existing, dict):
                    existing.update(thread_headers)
                    msg.extra_headers = existing
                else:
                    msg.extra_headers = thread_headers
            
            if cc:
                msg.cc = cc.split(',')
            
            # Attach uploaded files
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

            # Attach forwarded attachments
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
            
            mail.send(msg)
            
            email_record = EmailMessage(
                subject=subject,
                sender=sender,
                recipients=to,
                cc=cc,
                body_text=full_body_plain,
                body_html=full_body_html,
                folder='Sent',
                is_sent=True,
                sent_by_user_id=current_user.id,
                sent_at=datetime.utcnow(),
                has_attachments=bool(request.files.getlist('attachments')) or bool(forward_attachment_ids)
            )
            db.session.add(email_record)
            db.session.commit()
            
            flash('E-Mail wurde erfolgreich gesendet.', 'success')
            return redirect(url_for('email.index'))
        
        except Exception as e:
            flash(f'Fehler beim Senden der E-Mail: {str(e)}', 'danger')
            return render_template('email/compose.html')
    
    return render_template('email/compose.html')


@email_bp.route('/sync', methods=['POST'])
@login_required
def sync_emails():
    """Sync emails from IMAP server."""
    if not check_email_permission('read'):
        return jsonify({'error': 'Nicht autorisiert'}), 403

    
    current_folder = request.form.get('folder', None)
    
    if current_folder:
        success, message = sync_emails_from_folder(current_folder)
    else:
        success, message = sync_emails_from_server()
    
    if success:
        flash(f'✅ {message} - E-Mails wurden mit bidirektionaler Synchronisation aktualisiert!', 'success')
    else:
        flash(f'❌ FEHLER: {message} - Bitte IMAP-Konfiguration prüfen!', 'danger')

    return redirect(url_for('email.index'))


@email_bp.route('/delete/<int:email_id>', methods=['POST'])
@login_required
def delete_email(email_id):
    """Delete email from both portal and IMAP."""
    if not check_email_permission('read'):
        return jsonify({'error': 'Nicht autorisiert'}), 403
    
    email = EmailMessage.query.get_or_404(email_id)
    
    if email.imap_uid:
        success, message = delete_email_from_imap(email.imap_uid, email.folder)
        if not success:
            flash(f'WARNING: E-Mail konnte nicht in IMAP gelöscht werden: {message}', 'warning')
    
    db.session.delete(email)
    db.session.commit()
    
    flash('E-Mail wurde erfolgreich gelöscht.', 'success')
    return redirect(url_for('email.folder_view', folder_name=email.folder))


@email_bp.route('/move/<int:email_id>', methods=['POST'])
@login_required
def move_email(email_id):
    """Move email to another folder in both portal and IMAP."""
    if not check_email_permission('read'):
        return jsonify({'error': 'Nicht autorisiert'}), 403
    
    email = EmailMessage.query.get_or_404(email_id)
    new_folder = request.form.get('folder')
    
    if not new_folder:
        flash('Zielordner nicht angegeben.', 'danger')
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
        # First, try to select the source folder
        status, messages = mail_conn.select(from_folder)
        if status != 'OK':
            # If source folder doesn't exist, try to create it or use INBOX
            if from_folder != 'INBOX':
                status, messages = mail_conn.select('INBOX')
                if status != 'OK':
                    return False, f"Quellordner '{from_folder}' und INBOX konnten nicht geöffnet werden"
        
        # Try to copy the email
        status, response = mail_conn.copy(email_id, to_folder)
        if status != 'OK':
            # If target folder doesn't exist, try to create it
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


def email_sync_scheduler(app):
    """Background thread for automatic email synchronization every 15 minutes."""
    while True:
        try:
            with app.app_context():
                success, message = sync_emails_from_server()
                if success:
                    logging.info(f"Auto-sync: {message}")
                else:
                    logging.error(f"Auto-sync failed: {message}")
        except Exception as e:
            logging.error(f"Auto-sync error: {e}")
        
        time.sleep(900)


sync_thread = None

def start_email_sync(app):
    """Start the background email synchronization thread."""
    global sync_thread
    if sync_thread is None or not sync_thread.is_alive():
        sync_thread = threading.Thread(target=email_sync_scheduler, args=(app,), daemon=True)
        sync_thread.start()
        logging.info("E-Mail Auto-Sync gestartet (alle 15 Minuten)")
