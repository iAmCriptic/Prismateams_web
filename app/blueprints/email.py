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
        
        for folder_info in folders:
            try:
                folder_str = folder_info.decode('utf-8')
                parts = folder_str.split('"')
                if len(parts) >= 3:
                    folder_name = parts[-2]
                    
                    skip_folders = ['[Gmail]', '[Google Mail]', '&XfJT0ZAB-', '&XfJSI-']
                    if any(skip in folder_name for skip in skip_folders):
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
                    else:
                        existing_folder.last_synced = datetime.utcnow()
                        synced_folders.append(folder_name)
                        
            except Exception as e:
                logging.error(f"Fehler beim Verarbeiten des Ordners: {e}")
                continue
        
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
        status, messages = mail_conn.select(folder_name)
        if status != 'OK':
            return False, f"Ordner '{folder_name}' konnte nicht geöffnet werden"
        
        status, messages = mail_conn.search(None, 'ALL')
        if status != 'OK':
            return False, f"E-Mail-Suche in Ordner '{folder_name}' fehlgeschlagen"
        
        email_ids = messages[0].split()
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
        
        max_emails = 200 if folder_name not in ['INBOX', 'Sent', 'Drafts', 'Trash', 'Spam', 'Archive'] else 50
        for email_id in email_ids[-max_emails:]:
            try:
                status, msg_data = mail_conn.fetch(email_id, '(RFC822)')
                if status != 'OK':
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
                
                if not message_id:
                    continue
                
                received_at = datetime.utcnow()
                try:
                    from email.utils import parsedate_to_datetime
                    received_at = parsedate_to_datetime(date_str)
                except:
                    pass
                
                # Check if email already exists anywhere in the database
                existing = EmailMessage.query.filter_by(message_id=message_id).first()
                if existing:
                    # Update sync timestamp and folder if moved
                    try:
                        existing.last_imap_sync = datetime.utcnow()
                        existing.is_deleted_imap = False
                        if existing.folder != folder_name:
                            existing.folder = folder_name
                            stats['moved_emails'] += 1
                        else:
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
                            existing = EmailMessage.query.filter_by(message_id=message_id).first()
                            if existing:
                                existing.last_imap_sync = datetime.utcnow()
                                existing.is_deleted_imap = False
                                if existing.folder != folder_name:
                                    existing.folder = folder_name
                                    stats['moved_emails'] += 1
                                else:
                                    stats['updated_emails'] += 1
                                db.session.commit()
                                logging.info("Database reconnection successful for update")
                            continue
                        else:
                            raise update_error
                
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
                            
                            # Process attachment
                            try:
                                filename = part.get_filename()
                                if not filename:
                                    # Generate filename from content type
                                    extension = content_type.split('/')[-1] if '/' in content_type else 'bin'
                                    filename = f"attachment_{len(attachments_data)}.{extension}"
                                
                                # Decode filename if needed
                                if filename:
                                    from email.header import decode_header
                                    decoded_filename = decode_header(filename)
                                    if decoded_filename and decoded_filename[0][0]:
                                        filename = decoded_filename[0][0]
                                
                                # Get content
                                payload = part.get_payload(decode=True)
                                if payload:
                                    attachments_data.append({
                                        'filename': filename,
                                        'content_type': content_type,
                                        'content': payload,
                                        'size': len(payload),
                                        'is_inline': 'inline' in content_disposition,
                                        'content_id': part.get('Content-ID', '').strip('<>')
                                    })
                            except Exception as e:
                                logging.error(f"Error processing attachment: {e}")
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
                    
                    # Process attachments
                    for attachment_data in attachments_data:
                        try:
                            attachment = EmailAttachment(
                                email_id=email_entry.id,
                                filename=attachment_data['filename'],
                                content_type=attachment_data['content_type'],
                                size=attachment_data['size'],
                                content=attachment_data['content'],
                                is_inline=attachment_data['is_inline'],
                                content_id=attachment_data['content_id'] if attachment_data['content_id'] else None
                            )
                            db.session.add(attachment)
                        except Exception as e:
                            logging.error(f"Error saving attachment {attachment_data['filename']}: {e}")
                            continue
                    
                    # Commit with retry logic for MySQL connection issues
                    try:
                        db.session.commit()
                        stats['new_emails'] += 1
                    except Exception as commit_error:
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
                                        content=attachment_data['content'],
                                        is_inline=attachment_data['is_inline'],
                                        content_id=attachment_data['content_id'] if attachment_data['content_id'] else None
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
                    logging.error(f"Error saving email {subject}: {e}")
                    db.session.rollback()
                    continue
                
            except Exception as e:
                stats['errors'] += 1
                logging.error(f"Error syncing email from folder '{folder_name}': {e}")
                db.session.rollback()
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
    
    folders = EmailFolder.query.all()
    if not folders:
        folders = [EmailFolder(name='INBOX', display_name='Posteingang', folder_type='standard', is_system=True)]
    
    total_synced = 0
    folder_results = []
    
    for folder in folders:
        success, message = sync_emails_from_folder(folder.name)
        if success:
            import re
            match = re.search(r'(\d+) E-Mails', message)
            if match:
                count = int(match.group(1))
                total_synced += count
            folder_results.append(f"{folder.display_name}: {message}")
        else:
            folder_results.append(f"{folder.display_name}: Fehler - {message}")
    
    if total_synced > 0:
        return True, f"{total_synced} E-Mails aus {len(folders)} Ordnern synchronisiert"
    else:
        return False, "Keine E-Mails synchronisiert"


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
    folders = EmailFolder.query.order_by(EmailFolder.folder_type, EmailFolder.display_name).all()
    
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
    
    emails = EmailMessage.query.filter_by(folder=folder_name).order_by(EmailMessage.received_at.desc()).all()
    
    
    folders = EmailFolder.query.order_by(EmailFolder.folder_type, EmailFolder.display_name).all()
    folder_obj = EmailFolder.query.filter_by(name=folder_name).first()
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
            
            # Ensure proper HTML structure if missing
            if not html_content.strip().startswith('<'):
                html_content = f'<div>{html_content}</div>'
            
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


@email_bp.route('/attachment/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    """Download an email attachment."""
    if not check_email_permission('read'):
        flash('Sie haben keine Berechtigung, E-Mails zu lesen.', 'danger')
        return redirect(url_for('email.index'))
    
    attachment = EmailAttachment.query.get_or_404(attachment_id)
    email_msg = attachment.email
    if not email_msg:
        flash('Anhang nicht gefunden.', 'danger')
        return redirect(url_for('email.index'))
    
    content = attachment.get_content()
    if not content:
        flash('Anhang nicht gefunden oder beschädigt.', 'danger')
        return redirect(url_for('email.index'))
    
    file_obj = io.BytesIO(content)
    
    return send_file(
        file_obj,
        as_attachment=True,
        download_name=attachment.filename,
        mimetype=attachment.content_type
    )


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
        body = request.form.get('body', '').strip()
        
        if not all([to, subject, body]):
            flash('Bitte füllen Sie alle Pflichtfelder aus.', 'danger')
            return render_template('email/compose.html')
        
        footer_text = SystemSettings.query.filter_by(key='email_footer_text').first()
        footer_img = SystemSettings.query.filter_by(key='email_footer_image').first()
        
        footer = f"\n\n---\n{footer_text.value if footer_text else ''}\n"
        footer += f"Gesendet von {current_user.full_name}"
        
        full_body = body + footer
        
        try:
            msg = Message(
                subject=subject,
                recipients=to.split(','),
                body=full_body,
                sender=mail.default_sender
            )
            
            if cc:
                msg.cc = cc.split(',')
            
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
            
            mail.send(msg)
            
            email_record = EmailMessage(
                subject=subject,
                sender=mail.default_sender,
                recipients=to,
                cc=cc,
                body_text=full_body,
                folder='Sent',
                is_sent=True,
                sent_by_user_id=current_user.id,
                sent_at=datetime.utcnow(),
                has_attachments=bool(request.files.getlist('attachments'))
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
