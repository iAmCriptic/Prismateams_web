from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db, mail
from app.models.email import EmailMessage, EmailPermission
from app.models.settings import SystemSettings
from flask_mail import Message
from datetime import datetime
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

email_bp = Blueprint('email', __name__)


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
    
    # Add some sample emails for testing if no emails exist
    existing_emails = EmailMessage.query.count()
    
    if existing_emails == 0:
        # Create sample emails for testing
        sample_emails = [
            {
                'subject': 'Willkommen im Team Portal',
                'sender': 'admin@example.com',
                'recipients': 'team@example.com',
                'body_text': 'Willkommen in Ihrem neuen Team Portal! Hier können Sie E-Mails verwalten, chatten und zusammenarbeiten.',
                'is_sent': False,
                'received_at': datetime.utcnow()
            },
            {
                'subject': 'Meeting morgen um 10:00',
                'sender': 'kollege@example.com',
                'recipients': 'team@example.com',
                'body_text': 'Hi Team,\n\nunser Meeting morgen um 10:00 Uhr findet im Konferenzraum statt.\n\nBeste Grüße',
                'is_sent': False,
                'received_at': datetime.utcnow()
            },
            {
                'subject': 'Projekt Update',
                'sender': 'manager@example.com',
                'recipients': 'team@example.com',
                'body_text': 'Das Projekt läuft gut voran. Hier ist das aktuelle Update...',
                'is_sent': False,
                'received_at': datetime.utcnow()
            }
        ]
        
        for email_data in sample_emails:
            email = EmailMessage(**email_data)
            db.session.add(email)
        
        db.session.commit()
        flash(f'{len(sample_emails)} Beispiel-E-Mails hinzugefügt.', 'success')
    else:
        flash('E-Mail-Synchronisierung ist noch nicht implementiert.', 'info')
    
    return redirect(url_for('email.index'))



