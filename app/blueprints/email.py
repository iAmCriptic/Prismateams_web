from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app import db, mail
from app.models.email import EmailMessage, EmailPermission
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

email_bp = Blueprint('email', __name__)


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
            # Fetch email
            status, msg_data = mail_conn.fetch(email_id, '(RFC822)')
            if status != 'OK':
                continue
            
            # Parse email
            raw_email = msg_data[0][1]
            email_message = email.message_from_bytes(raw_email)
            
            # Extract data
            sender = email_message.get('From', '')
            subject = email_message.get('Subject', '')
            date_str = email_message.get('Date', '')
            message_id = email_message.get('Message-ID', '')
            
            # Check if email already exists
            existing = EmailMessage.query.filter_by(message_id=message_id).first()
            if existing:
                continue
            
            # Parse body
            body_text = ""
            if email_message.is_multipart():
                for part in email_message.walk():
                    if part.get_content_type() == "text/plain":
                        body_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
            else:
                body_text = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
            
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
                body_text=body_text[:1000],  # Limit body length
                received_at=received_at,
                is_read=False,
                is_sent=False
            )
            
            db.session.add(email_entry)
            synced_count += 1
        
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
    
    return render_template('email/view.html', email=email_msg)


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
    
    # Try to sync from IMAP server
    success, message = sync_emails_from_server()
    
    if success:
        flash(f'✅ {message}', 'success')
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
        print("🔄 E-Mail Auto-Sync gestartet (alle 15 Minuten)")



