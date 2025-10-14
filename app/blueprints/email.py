from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file, Response
from flask_login import login_required, current_user
from app import db, mail
from app.models.email import EmailMessage, EmailPermission, EmailAttachment
from app.models.settings import SystemSettings
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
    """Decode email header field properly."""
    if not field:
        return ''
    
    try:
        from email.header import decode_header
        decoded_parts = decode_header(field)
        decoded_string = ''
        
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                if encoding:
                    decoded_string += part.decode(encoding)
                else:
                    decoded_string += part.decode('utf-8', errors='ignore')
            else:
                decoded_string += str(part)
        
        return decoded_string.strip()
    except Exception:
        return str(field)


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


def sync_emails_from_server():
    """Sync emails from IMAP server to database."""
    mail_conn = connect_imap()
    if not mail_conn:
        return False, "IMAP-Verbindung fehlgeschlagen"
    
    try:
        # Search for all emails
        status, messages = mail_conn.search(None, 'ALL')
        if status != 'OK':
            return False, "E-Mail-Suche fehlgeschlagen"
        
        email_ids = messages[0].split()
        synced_count = 0
        
        for email_id in email_ids[-50:]:  # Only process last 50 emails
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
                
                # Decode sender
                sender_raw = email_message.get('From', '')
                sender = decode_header_field(sender_raw)
                
                # Decode subject
                subject_raw = email_message.get('Subject', '')
                subject = decode_header_field(subject_raw)
                
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
                
                # Check if email already exists
                existing = EmailMessage.query.filter_by(message_id=message_id).first()
                if existing:
                    continue
                
                # Parse body with HTML and attachments support
                body_text = ""
                body_html = ""
                has_attachments = False
                attachments_data = []
                
                if email_message.is_multipart():
                    for part in email_message.walk():
                        content_type = part.get_content_type()
                        content_disposition = part.get('Content-Disposition', '')
                        
                        # Handle attachments and inline images
                        if 'attachment' in content_disposition or 'inline' in content_disposition or content_type.startswith('image/'):
                            has_attachments = True
                            
                            # Get filename or generate one
                            filename = part.get_filename()
                            if not filename:
                                # Generate filename for inline images
                                if content_type.startswith('image/'):
                                    extension = content_type.split('/')[-1]
                                    filename = f"image_{len(attachments_data)}.{extension}"
                                else:
                                    filename = f"attachment_{len(attachments_data)}"
                            
                            # Decode filename if encoded
                            filename = decode_header_field(filename)
                            
                            # Get file content
                            file_content = part.get_payload(decode=True)
                            if file_content:
                                attachments_data.append({
                                    'filename': filename,
                                    'content_type': content_type,
                                    'size': len(file_content),
                                    'content': file_content,
                                    'is_inline': 'inline' in content_disposition or content_type.startswith('image/')
                                })
                            
                            continue
                        
                        # Handle text content
                        if content_type == "text/plain":
                            if not body_text:  # Only take the first plain text part
                                body_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        elif content_type == "text/html":
                            if not body_html:  # Only take the first HTML part
                                body_html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                else:
                    content_type = email_message.get_content_type()
                    if content_type == "text/html":
                        body_html = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
                    else:
                        body_text = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
                
                # Clean text version (remove excessive whitespace)
                if body_text:
                    import re
                    body_text = re.sub(r'\s+', ' ', body_text).strip()
                
                # Clean HTML version (basic sanitization)
                if body_html:
                    import re
                    # Remove script tags for security
                    body_html = re.sub(r'<script[^>]*>.*?</script>', '', body_html, flags=re.DOTALL | re.IGNORECASE)
                    # Remove style tags that might break layout
                    body_html = re.sub(r'<style[^>]*>.*?</style>', '', body_html, flags=re.DOTALL | re.IGNORECASE)
                    # Fix inline images - convert cid: to data URLs or placeholder
                    body_html = re.sub(r'src="cid:([^"]+)"', r'src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="', body_html)
                    # Remove problematic HTML entities that might cause "OBJ"
                    body_html = re.sub(r'<o:p\s*/>', '', body_html)
                    body_html = re.sub(r'<o:p>.*?</o:p>', '', body_html, flags=re.DOTALL)
                    # Normalize whitespace
                    body_html = re.sub(r'\s+', ' ', body_html).strip()
                
                # Parse date
                received_at = datetime.utcnow()
                try:
                    from email.utils import parsedate_to_datetime
                    received_at = parsedate_to_datetime(date_str)
                except:
                    pass
                
                # Create database entry
                email_entry = EmailMessage(
                    message_id=message_id,
                    sender=sender,
                    subject=subject,
                    recipients=recipients or 'Unknown',
                    cc=cc,
                    bcc=bcc,
                    body_text=body_text[:1000] if body_text else '',  # Limit body length
                    body_html=body_html[:5000] if body_html else '',  # Limit HTML length
                    has_attachments=has_attachments,
                    received_at=received_at,
                    is_read=False,
                    is_sent=False
                )
                
                db.session.add(email_entry)
                db.session.flush()  # Get the ID for attachments
                
                # Save attachments
                for attachment_data in attachments_data:
                    from app.models.email import EmailAttachment
                    attachment = EmailAttachment(
                        email_id=email_entry.id,
                        filename=attachment_data['filename'],
                        content_type=attachment_data['content_type'],
                        size=attachment_data['size'],
                        content=attachment_data['content'],
                        is_inline=attachment_data.get('is_inline', False)
                    )
                    db.session.add(attachment)
                
                synced_count += 1
                
            except Exception as e:
                logging.error(f"Failed to process email {email_id}: {str(e)}")
                continue
        
        db.session.commit()
        mail_conn.close()
        mail_conn.logout()
        
        return True, f"{synced_count} E-Mails synchronisiert"
        
    except Exception as e:
        logging.error(f"Email sync failed: {str(e)}")
        return False, f"Sync-Fehler: {str(e)}"


def check_email_permission(permission_type='read'):
    """Check if current user has email permissions."""
    perm = EmailPermission.query.filter_by(user_id=current_user.id).first()
    if not perm:
        return False
    return perm.can_read if permission_type == 'read' else perm.can_send


@email_bp.route('/')
@login_required
def index():
    """Email inbox."""
    if not check_email_permission('read'):
        flash('Sie haben keine Berechtigung, E-Mails zu lesen.', 'danger')
        return redirect(url_for('dashboard.index'))
    
    # Get emails from database
    emails = EmailMessage.query.order_by(EmailMessage.received_at.desc()).all()
    
    # Debug: Update has_attachments for existing emails
    for email in emails:
        if email.attachments:
            email.has_attachments = True
        else:
            email.has_attachments = False
    db.session.commit()
    
    return render_template('email/index.html', emails=emails)


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
    
    # Clean and prepare HTML content for display
    html_content = None
    if email_msg.body_html:
        import re
        # Basic HTML sanitization for safe display
        html_content = email_msg.body_html
        
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
        return redirect(url_for('dashboard.index'))
    
    attachment = EmailAttachment.query.get_or_404(attachment_id)
    
    # Check if user has permission to view this email
    email_msg = attachment.email
    if not email_msg:
        flash('Anhang nicht gefunden.', 'danger')
        return redirect(url_for('email.index'))
    
    # Create file-like object from binary data
    file_obj = io.BytesIO(attachment.content)
    
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
            
            mail.send(msg)
            
            # Save to database
            email_record = EmailMessage(
                subject=subject,
                sender=mail.default_sender,
                recipients=to,
                cc=cc,
                body_text=full_body,
                is_sent=True,
                sent_by_user_id=current_user.id,
                sent_at=datetime.utcnow()
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
    print(f"🔍 Testing IMAP connection...")
    print(f"   Server: {current_app.config.get('IMAP_SERVER')}")
    print(f"   Port: {current_app.config.get('IMAP_PORT', 993)}")
    print(f"   Username: {current_app.config.get('MAIL_USERNAME')}")
    print(f"   SSL: {current_app.config.get('IMAP_USE_SSL', True)}")
    
    # Clear existing emails to force re-sync with new attachment handling
    EmailMessage.query.delete()
    db.session.commit()
    
    # Try to sync from IMAP server
    success, message = sync_emails_from_server()
    
    if success:
        flash(f'✅ {message} - E-Mails wurden neu synchronisiert mit Attachment-Support!', 'success')
        print(f"✅ {message}")
    else:
        print(f"❌ {message}")
        
        # Fallback: Add sample emails if IMAP fails and no emails exist
        existing_emails = EmailMessage.query.count()
        if existing_emails == 0:
            sample_emails = [
                {
                    'subject': 'Willkommen im Team Portal',
                    'sender': 'admin@example.com',
                    'recipients': 'team@example.com',
                    'body_text': 'Willkommen in Ihrem neuen Team Portal! Hier können Sie E-Mails verwalten, chatten und zusammenarbeiten.',
                    'is_sent': False,
                    'received_at': datetime.utcnow(),
                    'message_id': 'sample-1'
                },
                {
                    'subject': 'Meeting morgen um 10:00',
                    'sender': 'kollege@example.com',
                    'recipients': 'team@example.com',
                    'body_text': 'Hi Team,\n\nunser Meeting morgen um 10:00 Uhr findet im Konferenzraum statt.\n\nBeste Grüße',
                    'is_sent': False,
                    'received_at': datetime.utcnow(),
                    'message_id': 'sample-2'
                },
                {
                    'subject': 'Projekt Update',
                    'sender': 'manager@example.com',
                    'recipients': 'team@example.com',
                    'body_text': 'Das Projekt läuft gut voran. Hier ist das aktuelle Update...',
                    'is_sent': False,
                    'received_at': datetime.utcnow(),
                    'message_id': 'sample-3'
                }
            ]

            for email_data in sample_emails:
                email = EmailMessage(**email_data)
                db.session.add(email)

            db.session.commit()
            flash(f'⚠️ IMAP-Sync fehlgeschlagen. {len(sample_emails)} Beispiel-E-Mails hinzugefügt.', 'warning')
            print(f"⚠️ Fallback: {len(sample_emails)} Beispiel-E-Mails hinzugefügt")
        else:
            flash(f'⚠️ {message}', 'warning')

    return redirect(url_for('email.index'))


def email_sync_scheduler(app):
    """Background thread for automatic email synchronization every 15 minutes."""
    while True:
        try:
            with app.app_context():
                success, message = sync_emails_from_server()
                if success:
                    print(f"🔄 Auto-sync: {message}")
                else:
                    print(f"🔄 Auto-sync failed: {message}")
        except Exception as e:
            print(f"🔄 Auto-sync error: {str(e)}")
        
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
        print("E-Mail Auto-Sync gestartet (alle 15 Minuten)")



