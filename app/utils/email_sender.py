import os
import secrets
import string
import logging
from datetime import datetime, timedelta
from flask import render_template, current_app
from flask_mail import Message
from app import mail
from app.models.user import User


def generate_confirmation_code():
    """Generiert einen 6-stelligen Bestätigungscode."""
    return ''.join(secrets.choice(string.digits) for _ in range(6))


def send_confirmation_email(user):
    """Sendet eine Bestätigungs-E-Mail an den Benutzer."""
    try:
        # Generiere Bestätigungscode
        confirmation_code = generate_confirmation_code()
        
        # Setze Ablaufzeit (24 Stunden)
        expires_at = datetime.utcnow() + timedelta(hours=24)
        
        # Aktualisiere Benutzer-Daten
        user.confirmation_code = confirmation_code
        user.confirmation_code_expires = expires_at
        user.is_email_confirmed = False
        
        # Speichere in Datenbank
        from app import db
        db.session.commit()
        
        # Prüfe E-Mail-Konfiguration
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        mail_port = current_app.config.get('MAIL_PORT', 587)
        mail_use_tls = current_app.config.get('MAIL_USE_TLS', True)
        mail_use_ssl = current_app.config.get('MAIL_USE_SSL', False)
        
        
        if not all([mail_server, mail_username, mail_password]):
            logging.warning(f"E-Mail-Konfiguration unvollständig. Code für {user.email}: {confirmation_code}")
            return False
        
        # Erstelle E-Mail
        msg = Message(
            # Get portal name from SystemSettings
            try:
                from app.models.settings import SystemSettings
                portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
                portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
            except:
                portal_name = current_app.config.get('APP_NAME', 'Prismateams')
            
            subject=f'E-Mail-Bestätigung - {portal_name}',
            recipients=[user.email],
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', mail_username)
        )
        
        # HTML-Template rendern
        html_content = render_template(
            'emails/confirmation_code.html',
            user=user,
            confirmation_code=confirmation_code,
            app_name=portal_name,
            current_year=datetime.utcnow().year
        )
        
        msg.html = html_content
        
        # E-Mail senden mit verbesserter Fehlerbehandlung
        try:
            mail.send(msg)
            logging.info(f"Confirmation email sent to {user.email} with code: {confirmation_code}")
            return True
        except Exception as send_error:
            logging.error(f"Failed to send confirmation email to {user.email}: {str(send_error)}")
            
            # Versuche alternative Konfiguration für Infomaniak
            try:
                logging.info("Versuche alternative E-Mail-Konfiguration...")
                
                # Erstelle neue Message mit korrigierter Konfiguration
                msg_alt = Message(
                    # Get portal name from SystemSettings
            try:
                from app.models.settings import SystemSettings
                portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
                portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
            except:
                portal_name = current_app.config.get('APP_NAME', 'Prismateams')
            
            subject=f'E-Mail-Bestätigung - {portal_name}',
                    recipients=[user.email],
                    sender=current_app.config.get('MAIL_DEFAULT_SENDER', mail_username)
                )
                
                # HTML-Template rendern
                html_content = render_template(
                    'emails/confirmation_code.html',
                    user=user,
                    confirmation_code=confirmation_code,
                    app_name=portal_name,
                    current_year=datetime.utcnow().year
                )
                
                msg_alt.html = html_content
                
                # Versuche erneut zu senden
                mail.send(msg_alt)
                logging.info(f"Alternative E-Mail erfolgreich gesendet an {user.email}")
                return True
                
            except Exception as alt_error:
                logging.error(f"Alternative E-Mail-Versand auch fehlgeschlagen: {str(alt_error)}")
                return False
        
    except Exception as e:
        logging.error(f"Failed to send confirmation email to {user.email}: {str(e)}")
        # Code trotzdem in Datenbank speichern für manuelle Eingabe
        return False


def verify_confirmation_code(user, code):
    """Überprüft den Bestätigungscode."""
    if not user.confirmation_code or not user.confirmation_code_expires:
        return False
    
    # Prüfe Ablaufzeit
    if datetime.utcnow() > user.confirmation_code_expires:
        return False
    
    # Prüfe Code
    if user.confirmation_code != code:
        return False
    
    # Code ist gültig - bestätige E-Mail
    user.is_email_confirmed = True
    user.confirmation_code = None
    user.confirmation_code_expires = None
    
    from app import db
    db.session.commit()
    
    return True


def resend_confirmation_email(user):
    """Sendet eine neue Bestätigungs-E-Mail."""
    return send_confirmation_email(user)


def send_return_confirmation_email(borrow_transaction):
    """Sendet eine Bestätigungs-E-Mail nach erfolgreicher Rückgabe mit PDF-Anhang."""
    try:
        from app.models.inventory import BorrowTransaction, Product
        from app.utils.pdf_generator import generate_return_confirmation_pdf
        from io import BytesIO
        
        product = borrow_transaction.product
        borrower = borrow_transaction.borrower
        
        # Prüfe E-Mail-Konfiguration
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([mail_server, mail_username, mail_password]):
            logging.warning(f"E-Mail-Konfiguration unvollständig. Rückgabe-Bestätigung für {borrow_transaction.transaction_number} nicht gesendet.")
            return False
        
        # Get portal name from SystemSettings
        try:
            from app.models.settings import SystemSettings
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
        except:
            portal_name = current_app.config.get('APP_NAME', 'Prismateams')
        
        # Erstelle E-Mail
        msg = Message(
            subject=f'Rückgabe-Bestätigung - {portal_name}',
            recipients=[borrower.email],
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', mail_username)
        )
        
        # HTML-Template für Rückgabe-Bestätigung
        return_date = borrow_transaction.actual_return_date.strftime('%d.%m.%Y') if borrow_transaction.actual_return_date else datetime.utcnow().strftime('%d.%m.%Y')
        
        html_content = render_template(
            'emails/return_confirmation.html',
            app_name=portal_name,
            borrower=borrower,
            product=product,
            transaction=borrow_transaction,
            return_date=return_date,
            current_year=datetime.utcnow().year
        )
        
        msg.html = html_content
        
        # PDF-Anhang generieren
        pdf_buffer = BytesIO()
        generate_return_confirmation_pdf(borrow_transaction, pdf_buffer)
        pdf_buffer.seek(0)
        
        # PDF als Anhang hinzufügen
        filename = f"Rueckgabe_Bestaetigung_{borrow_transaction.transaction_number}.pdf"
        msg.attach(filename, "application/pdf", pdf_buffer.read())
        
        # E-Mail senden
        try:
            mail.send(msg)
            logging.info(f"Return confirmation email sent to {borrower.email} for transaction {borrow_transaction.transaction_number}")
            return True
        except Exception as send_error:
            logging.error(f"Failed to send return confirmation email to {borrower.email}: {str(send_error)}")
            return False
        
    except Exception as e:
        logging.error(f"Failed to send return confirmation email: {str(e)}")
        return False
