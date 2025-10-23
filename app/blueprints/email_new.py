from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file, Response
from flask_login import login_required, current_user
from app import db, mail
from app.models.email import EmailMessage, EmailPermission, EmailAttachment, EmailFolder
from app.models.settings import SystemSettings
from app.utils.notifications import send_email_notification
from flask_mail import Message
from datetime import datetime, timedelta
import imaplib
import email
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
                    # Try the detected encoding first
                    try:
                        decoded_string += part.decode(encoding, errors='ignore')
                        continue
                    except (UnicodeDecodeError, LookupError):
                        pass
                
                # Fallback strategies for bytes
                for fallback_encoding in ['utf-8', 'latin-1', 'cp1252', 'ascii']:
                    try:
                        decoded_string += part.decode(fallback_encoding, errors='ignore')
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                else:
                    # If all encodings fail, use ascii with replacement
                    decoded_string += part.decode('ascii', errors='replace')
            else:
                decoded_string += str(part)
        
        # Clean up the result
        result = decoded_string.strip()
        if not result:
            return str(field) if field else ''
        return result
        
    except Exception as e:
        # Ultimate fallback
        try:
            return str(field) if field else ''
        except:
            return 'Unknown'


def connect_imap():
    """Connect to IMAP server and return connection."""
    try:
        imap_server = current_app.config.get('IMAP_SERVER')
        imap_port = current_app.config.get('IMAP_PORT', 993)
        imap_use_ssl = current_app.config.get('IMAP_USE_SSL', True)
        username = current_app.config.get('MAIL_USERNAME')
        password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([imap_server, username, password]):
            raise Exception("IMAP configuration missing")
        
        # Connect to IMAP server
        if imap_use_ssl:
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        else:
            mail = imaplib.IMAP4(imap_server, imap_port)
        
        # Login
        mail.login(username, password)
        mail.select('INBOX')
        
        return mail
    except Exception as e:
        logging.error(f"IMAP connection failed: {str(e)}")
        return None


def sync_imap_folders():
    """Sync IMAP folders from server to database."""
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    try:
        # List all folders
        status, folders = mail_conn.list()
        if status != 'OK':
            return False, "Ordner-Liste konnte nicht abgerufen werden"
        
        synced_folders = []
        
        for folder_info in folders:
            try:
                # Parse folder information
                folder_str = folder_info.decode('utf-8')
                # Extract folder name from IMAP response
                # Format: (\\HasNoChildren) "/" "INBOX"
                parts = folder_str.split('"')
                if len(parts) >= 3:
                    folder_name = parts[-2]  # Get folder name between quotes
                    
                    # Skip system folders that we don't want to display
                    skip_folders = ['[Gmail]', '[Google Mail]', '&XfJT0ZAB-', '&XfJSI-']
                    if any(skip in folder_name for skip in skip_folders):
                        continue
                    
                    # Determine folder type and display name
                    is_system = folder_name in ['INBOX', 'Sent', 'Sent Messages', 'Drafts', 'Trash', 'Deleted Messages', 'Spam', 'Junk', 'Archive']
                    display_name = EmailFolder.get_folder_display_name(folder_name)
                    
                    # Check if folder already exists
                    existing_folder = EmailFolder.query.filter_by(name=folder_name).first()
                    if not existing_folder:
                        # Create new folder
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
                        # Update existing folder
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
    """Sync emails from a specific IMAP folder."""
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    try:
        # Select the specific folder
        status, messages = mail_conn.select(folder_name)
        if status != 'OK':
            return False, f"Ordner '{folder_name}' konnte nicht geöffnet werden"
        
        # Search for all emails in this folder
        status, messages = mail_conn.search(None, 'ALL')
        if status != 'OK':
            return False, f"E-Mail-Suche in Ordner '{folder_name}' fehlgeschlagen"
        
        email_ids = messages[0].split()
        synced_count = 0
        
        for email_id in email_ids[-50:]:  # Only process last 50 emails per folder
            try:
                # Fetch email
                status, msg_data = mail_conn.fetch(email_id, '(RFC822)')
                if status != 'OK':
                    continue
                
                # Parse email
                raw_email = msg_data[0][1]
                email_message = email.message_from_bytes(raw_email)
                
                # Extract data with proper decoding
                from email.header import decode_header
                
                # Decode sender with error handling
                sender_raw = email_message.get('From', '')
                sender = decode_header_field(sender_raw)
                if not sender:
                    sender = "Unknown Sender"
                
                # Decode subject with error handling
                subject_raw = email_message.get('Subject', '')
                subject = decode_header_field(subject_raw)
                if not subject:
                    subject = "(No Subject)"
                
                # Decode other fields
                date_str = email_message.get('Date', '')
                message_id = email_message.get('Message-ID', '')
                
                recipients_raw = email_message.get('To', '')
                recipients = decode_header_field(recipients_raw)
                
                cc_raw = email_message.get('Cc', '')
                cc = decode_header_field(cc_raw)
                
                bcc_raw = email_message.get('Bcc', '')
                bcc = decode_header_field(bcc_raw)
                
                # Skip if no message ID (required for uniqueness)
                if not message_id:
                    continue
                
                # Parse date
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
                                db.session.commit()
                                logging.info("Database reconnection successful for update")
                            continue
                        else:
                            raise update_error
                
                # Parse body content (simplified for folder sync)
                body_text = ""
                body_html = ""
                has_attachments = False
                
                if email_message.is_multipart():
                    for part in email_message.walk():
                        content_type = part.get_content_type()
                        content_disposition = part.get('Content-Disposition', '')
                        
                        # Check for attachments
                        if ('attachment' in content_disposition or 'inline' in content_disposition) and not content_type.startswith('text/'):
                            has_attachments = True
                            continue
                        
                        # Handle text content
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
                                        body_html = decoded_html
                            except:
                                pass
                else:
                    # Single-part email
                    content_type = email_message.get_content_type()
                    try:
                        payload = email_message.get_payload(decode=True)
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
                    except:
                        pass
                
                # Create database entry with folder information
                email_entry = EmailMessage(
                    message_id=message_id,
                    sender=sender,
                    subject=subject,
                    recipients=recipients or 'Unknown',
                    cc=cc,
                    bcc=bcc,
                    body_text=body_text[:1000] if body_text else '',
                    body_html=body_html[:5000] if body_html else '',
                    has_attachments=has_attachments,
                    folder=folder_name,
                    received_at=received_at,
                    is_read=False,
                    is_sent=False
                )
                
                try:
                    db.session.add(email_entry)
                    db.session.commit()
                    synced_count += 1
                except Exception as save_error:
                    # If save fails due to connection issues, try to reconnect
                    if "MySQL server has gone away" in str(save_error) or "ConnectionResetError" in str(save_error):
                        logging.warning("Database connection lost during save, attempting to reconnect...")
                        db.session.rollback()
                        db.session.close()
                        db.session = db.create_scoped_session()
                        # Retry the save
                        db.session.add(email_entry)
                        db.session.commit()
                        synced_count += 1
                        logging.info("Database reconnection successful for save")
                    else:
                        raise save_error
                
            except Exception as e:
                logging.error(f"Fehler beim Synchronisieren der E-Mail aus Ordner '{folder_name}': {e}")
                db.session.rollback()
                continue
        
        db.session.commit()
        mail_conn.close()
        mail_conn.logout()
        
        return True, f"{synced_count} E-Mails aus Ordner '{folder_name}' synchronisiert"
        
    except Exception as e:
        logging.error(f"Email sync from folder failed: {str(e)}")
        return False, f"E-Mail-Sync-Fehler für Ordner '{folder_name}': {str(e)}"


def sync_emails_from_server():
    """Sync emails from IMAP server to database with folder support."""
    # First sync folders
    folder_success, folder_message = sync_imap_folders()
    if not folder_success:
        logging.warning(f"Ordner-Sync-Warnung: {folder_message}")
    
    # Get all folders from database
    folders = EmailFolder.query.all()
    if not folders:
        # Fallback to INBOX only if no folders found
        folders = [EmailFolder(name='INBOX', display_name='Posteingang', folder_type='standard', is_system=True)]
    
    total_synced = 0
    folder_results = []
    
    for folder in folders:
        success, message = sync_emails_from_folder(folder.name)
        if success:
            # Extract number from message
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
    
    # Get current folder from request
    current_folder = request.args.get('folder', 'INBOX')
    
    # Get emails from database for current folder
    emails = EmailMessage.query.filter_by(folder=current_folder).order_by(EmailMessage.received_at.desc()).all()
    
    # Get all folders for dropdown
    folders = EmailFolder.query.order_by(EmailFolder.folder_type, EmailFolder.display_name).all()
    
    # Debug: Update has_attachments for existing emails
    for email in emails:
        if email.attachments:
            email.has_attachments = True
        else:
            email.has_attachments = False
    db.session.commit()
    
    return render_template('email/index.html', emails=emails, folders=folders, current_folder=current_folder)


@email_bp.route('/folder/<folder_name>')
@login_required
def folder_view(folder_name):
    """View emails in a specific folder."""
    if not check_email_permission('read'):
        flash('Sie haben keine Berechtigung, E-Mails zu lesen.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    # Get emails from database for this folder
    emails = EmailMessage.query.filter_by(folder=folder_name).order_by(EmailMessage.received_at.desc()).all()
    
    # Get all folders for dropdown
    folders = EmailFolder.query.order_by(EmailFolder.folder_type, EmailFolder.display_name).all()
    
    # Get folder display name
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
    
    # Mark as read
    if not email_msg.is_read:
        email_msg.is_read = True
        db.session.commit()
    
    # Debug email content
    
    # Clean and prepare HTML content for display with clickable links
    html_content = None
    if email_msg.body_html:
        import re
        # Basic HTML sanitization for safe display
        html_content = email_msg.body_html
        
        # Remove Microsoft Word artifacts that cause "OBJ" placeholders
        html_content = re.sub(r'<o:p\s*/>', '', html_content)
        html_content = re.sub(r'<o:p>.*?</o:p>', '', html_content, flags=re.DOTALL)
        html_content = re.sub(r'<w:.*?>.*?</w:.*?>', '', html_content, flags=re.DOTALL)
        html_content = re.sub(r'<m:.*?>.*?</m:.*?>', '', html_content, flags=re.DOTALL)
        html_content = re.sub(r'<v:.*?>.*?</v:.*?>', '', html_content, flags=re.DOTALL)
        html_content = re.sub(r'<![^>]*>', '', html_content)  # Remove comments
        
        # Make sure links are clickable and secure
        html_content = re.sub(r'<a([^>]*)href="([^"]*)"([^>]*)>', r'<a\1href="\2" target="_blank" rel="noopener noreferrer"\3>', html_content)
        
        # Replace cid: references with actual inline images
        for attachment in email_msg.attachments:
            if attachment.is_inline and attachment.content_type.startswith('image/'):
                data_url = attachment.get_data_url()
                if data_url:
                    # Replace cid references with data URLs
                    cid_pattern = f'cid:{attachment.filename}'
                    html_content = html_content.replace(f'src="{cid_pattern}"', f'src="{data_url}"')
                    html_content = html_content.replace(f"src='{cid_pattern}'", f"src='{data_url}'")
        
        # Fix remaining cid: references with placeholder
        html_content = re.sub(r'src="cid:([^"]+)"', r'src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="', html_content)
    
    return render_template('email/view.html', email=email_msg, html_content=html_content)


@email_bp.route('/attachment/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    """Download an email attachment."""
    if not check_email_permission('read'):
        flash('Sie haben keine Berechtigung, E-Mails zu lesen.', 'danger')
        return redirect(url_for('email.index'))
    
    attachment = EmailAttachment.query.get_or_404(attachment_id)
    
    # Check if user has permission to view this email
    email_msg = attachment.email
    if not email_msg:
        flash('Anhang nicht gefunden.', 'danger')
        return redirect(url_for('email.index'))
    
    # Get content from database or file system
    content = attachment.get_content()
    if not content:
        flash('Anhang nicht gefunden oder beschädigt.', 'danger')
        return redirect(url_for('email.index'))
    
    # Create file-like object from content
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
        
        # Get email footer from settings
        footer_text = SystemSettings.query.filter_by(key='email_footer_text').first()
        footer_img = SystemSettings.query.filter_by(key='email_footer_image').first()
        
        # Build footer
        footer = f"\n\n---\n{footer_text.value if footer_text else ''}\n"
        footer += f"Gesendet von {current_user.full_name}"
        
        full_body = body + footer
        
        try:
            # Send email using Flask-Mail
            msg = Message(
                subject=subject,
                recipients=to.split(','),
                body=full_body,
                sender=mail.default_sender
            )
            
            if cc:
                msg.cc = cc.split(',')
            
            # Handle attachments
            if 'attachments' in request.files:
                attachments = request.files.getlist('attachments')
                for attachment in attachments:
                    if attachment.filename:
                        msg.attach(
                            attachment.filename,
                            attachment.content_type or 'application/octet-stream',
                            attachment.read()
                        )
                        attachment.seek(0)  # Reset file pointer
            
            mail.send(msg)
            
            # Save to database
            email_record = EmailMessage(
                subject=subject,
                sender=mail.default_sender,
                recipients=to,
                cc=cc,
                body_text=full_body,
                folder='Sent',  # Mark as sent folder
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

    # Test IMAP connection first
    
    # Try to sync from IMAP server
    success, message = sync_emails_from_server()
    
    if success:
        flash(f'✅ {message} - E-Mails wurden mit Ordner-Support synchronisiert!', 'success')
        
        # Fallback: Add sample emails if IMAP fails and no emails exist
        existing_emails = EmailMessage.query.count()
        if existing_emails == 0:
            sample_emails = [
                {
                    'subject': 'Willkommen im Team Portal',
                    'sender': 'admin@example.com',
                    'recipients': 'team@example.com',
                    'body_text': 'Willkommen in Ihrem neuen Team Portal! Hier können Sie E-Mails verwalten, chatten und zusammenarbeiten.',
                    'body_html': '<p>Willkommen in Ihrem neuen <strong>Team Portal</strong>!</p><p>Hier können Sie:</p><ul><li>E-Mails verwalten</li><li>Chatten</li><li>Zusammenarbeiten</li></ul>',
                    'folder': 'INBOX',
                    'is_sent': False,
                    'received_at': datetime.utcnow(),
                    'message_id': 'sample-1',
                    'has_attachments': False
                },
                {
                    'subject': 'Meeting morgen um 10:00',
                    'sender': 'kollege@example.com',
                    'recipients': 'team@example.com',
                    'body_text': 'Hi Team,\n\nunser Meeting morgen um 10:00 Uhr findet im Konferenzraum statt.\n\nBeste Grüße',
                    'body_html': '<p>Hi Team,</p><p>unser Meeting morgen um <strong>10:00 Uhr</strong> findet im Konferenzraum statt.</p><p>Beste Grüße</p>',
                    'folder': 'INBOX',
                    'is_sent': False,
                    'received_at': datetime.utcnow(),
                    'message_id': 'sample-2',
                    'has_attachments': True
                },
                {
                    'subject': 'Projekt Update',
                    'sender': 'manager@example.com',
                    'recipients': 'team@example.com',
                    'body_text': 'Das Projekt läuft gut voran. Hier ist das aktuelle Update...',
                    'body_html': '<p>Das Projekt läuft gut voran. Hier ist das aktuelle <em>Update</em>...</p>',
                    'folder': 'INBOX',
                    'is_sent': False,
                    'received_at': datetime.utcnow(),
                    'message_id': 'sample-3'
                }
            ]

            for email_data in sample_emails:
                email = EmailMessage(**email_data)
                db.session.add(email)

            db.session.commit()
            flash(f'WARNING: IMAP-Sync fehlgeschlagen. {len(sample_emails)} Beispiel-E-Mails hinzugefügt.', 'warning')
        else:
            flash(f'WARNING: {message}', 'warning')

    return redirect(url_for('email.index'))


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
            logging.error(f"Auto-sync error: {str(e)}")
        
        # Wait 15 minutes (900 seconds)
        time.sleep(900)


# Start background sync thread
sync_thread = None

def start_email_sync(app):
    """Start the background email synchronization thread."""
    global sync_thread
    if sync_thread is None or not sync_thread.is_alive():
        sync_thread = threading.Thread(target=email_sync_scheduler, args=(app,), daemon=True)
        sync_thread.start()
        logging.info("E-Mail Auto-Sync gestartet (alle 15 Minuten)")

