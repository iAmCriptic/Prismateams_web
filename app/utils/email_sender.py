import os
import secrets
import string
import logging
import base64
from datetime import datetime, timedelta
from flask import render_template, current_app
from flask_mail import Message
from app import mail
from app.models.user import User


def generate_confirmation_code():
    """Generiert einen 6-stelligen Bestätigungscode."""
    return ''.join(secrets.choice(string.digits) for _ in range(6))


def get_logo_base64():
    """Holt das Portal-Logo aus SystemSettings oder Konfiguration und gibt es als Base64-String zurück."""
    try:
        from app.models.settings import SystemSettings
        
        # Versuche Portal-Logo aus SystemSettings zu laden
        portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
        if portal_logo_setting and portal_logo_setting.value:
            # Portal-Logo ist in uploads/system/ gespeichert
            project_root = os.path.dirname(current_app.root_path)
            logo_path = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system', portal_logo_setting.value)
            if os.path.exists(logo_path):
                try:
                    with open(logo_path, 'rb') as f:
                        logo_data = f.read()
                    # Bestimme MIME-Type basierend auf Dateierweiterung
                    ext = os.path.splitext(portal_logo_setting.value)[1].lower()
                    mime_types = {
                        '.png': 'image/png',
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.gif': 'image/gif',
                        '.svg': 'image/svg+xml'
                    }
                    mime_type = mime_types.get(ext, 'image/png')
                    logo_base64 = base64.b64encode(logo_data).decode('utf-8')
                    return f"data:{mime_type};base64,{logo_base64}"
                except Exception as e:
                    logging.warning(f"Fehler beim Laden des Portal-Logos: {e}")
    except Exception as e:
        logging.warning(f"Fehler beim Zugriff auf SystemSettings: {e}")
    
    # Fallback zu Standard-Logo
    try:
        logo_path = current_app.config.get('APP_LOGO', 'static/img/logo.png')
        
        # Wenn der Pfad mit 'static/' beginnt, entferne es
        if logo_path.startswith('static/'):
            logo_path = logo_path[7:]
        
        # Konvertiere zu absolutem Pfad
        static_folder = current_app.static_folder
        full_path = os.path.join(static_folder, logo_path)
        
        if os.path.exists(full_path):
            with open(full_path, 'rb') as f:
                logo_data = f.read()
            # Bestimme MIME-Type basierend auf Dateierweiterung
            ext = os.path.splitext(full_path)[1].lower()
            mime_types = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.svg': 'image/svg+xml'
            }
            mime_type = mime_types.get(ext, 'image/png')
            logo_base64 = base64.b64encode(logo_data).decode('utf-8')
            return f"data:{mime_type};base64,{logo_base64}"
    except Exception as e:
        logging.warning(f"Fehler beim Laden des Standard-Logos: {e}")
    
    # Wenn kein Logo gefunden wurde, gib None zurück
    return None


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
        
        # Get portal name from SystemSettings
        try:
            from app.models.settings import SystemSettings
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
        except:
            portal_name = current_app.config.get('APP_NAME', 'Prismateams')
        
        # Erstelle E-Mail
        msg = Message(
            subject=f'E-Mail-Bestätigung - {portal_name}',
            recipients=[user.email],
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', mail_username)
        )
        
        # Logo als Base64 laden
        logo_base64 = get_logo_base64()
        
        # HTML-Template rendern
        html_content = render_template(
            'emails/confirmation_code.html',
            user=user,
            confirmation_code=confirmation_code,
            app_name=portal_name,
            current_year=datetime.utcnow().year,
            logo_base64=logo_base64
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
                
                # Get portal name from SystemSettings (bereits oben definiert, aber zur Sicherheit nochmal)
                try:
                    from app.models.settings import SystemSettings
                    portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
                    portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
                except:
                    portal_name = current_app.config.get('APP_NAME', 'Prismateams')
                
                # Erstelle neue Message mit korrigierter Konfiguration
                msg_alt = Message(
                    subject=f'E-Mail-Bestätigung - {portal_name}',
                    recipients=[user.email],
                    sender=current_app.config.get('MAIL_DEFAULT_SENDER', mail_username)
                )
                
                # Logo als Base64 laden
                logo_base64 = get_logo_base64()
                
                # HTML-Template rendern
                html_content = render_template(
                    'emails/confirmation_code.html',
                    user=user,
                    confirmation_code=confirmation_code,
                    app_name=portal_name,
                    current_year=datetime.utcnow().year,
                    logo_base64=logo_base64
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


def send_borrow_receipt_email(borrow_transactions):
    """Sendet eine E-Mail mit Ausleihschein-PDF nach erfolgreicher Ausleihe."""
    try:
        from app.models.inventory import BorrowTransaction, Product
        from app.utils.pdf_generator import generate_borrow_receipt_pdf
        from io import BytesIO
        
        # Normalisiere zu Liste
        if not isinstance(borrow_transactions, list):
            borrow_transactions = [borrow_transactions]
        
        if not borrow_transactions:
            logging.error("Keine Transaktionen zum Versenden vorhanden.")
            return False
        
        first_transaction = borrow_transactions[0]
        borrower = first_transaction.borrower
        
        # Prüfe E-Mail-Konfiguration
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        
        if not all([mail_server, mail_username, mail_password]):
            logging.warning(f"E-Mail-Konfiguration unvollständig. Ausleihschein für {first_transaction.transaction_number} nicht gesendet.")
            return False
        
        if not borrower.email:
            logging.warning(f"Benutzer {borrower.id} hat keine E-Mail-Adresse. Ausleihschein nicht gesendet.")
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
            subject=f'Ausleihschein - {portal_name}',
            recipients=[borrower.email],
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', mail_username)
        )
        
        # Logo als Base64 laden
        logo_base64 = get_logo_base64()
        
        # HTML-Template für Ausleihschein
        borrow_date = first_transaction.borrow_date.strftime('%d.%m.%Y %H:%M')
        expected_return_date = first_transaction.expected_return_date.strftime('%d.%m.%Y')
        
        html_content = render_template(
            'emails/borrow_receipt.html',
            app_name=portal_name,
            borrower=borrower,
            transactions=borrow_transactions,
            borrow_date=borrow_date,
            expected_return_date=expected_return_date,
            transaction_number=first_transaction.transaction_number,
            current_year=datetime.utcnow().year,
            logo_base64=logo_base64
        )
        
        msg.html = html_content
        
        # PDF-Anhang generieren
        pdf_buffer = BytesIO()
        generate_borrow_receipt_pdf(borrow_transactions, pdf_buffer)
        pdf_buffer.seek(0)
        
        # PDF als Anhang hinzufügen
        filename = f"Ausleihschein_{first_transaction.transaction_number}.pdf"
        msg.attach(filename, "application/pdf", pdf_buffer.read())
        
        # E-Mail senden
        try:
            mail.send(msg)
            logging.info(f"Borrow receipt email sent to {borrower.email} for transaction {first_transaction.transaction_number}")
            return True
        except Exception as send_error:
            logging.error(f"Failed to send borrow receipt email to {borrower.email}: {str(send_error)}")
            return False
        
    except Exception as e:
        logging.error(f"Failed to send borrow receipt email: {str(e)}")
        return False


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
        
        # Logo als Base64 laden
        logo_base64 = get_logo_base64()
        
        # HTML-Template für Rückgabe-Bestätigung
        return_date = borrow_transaction.actual_return_date.strftime('%d.%m.%Y') if borrow_transaction.actual_return_date else datetime.utcnow().strftime('%d.%m.%Y')
        
        html_content = render_template(
            'emails/return_confirmation.html',
            app_name=portal_name,
            borrower=borrower,
            product=product,
            transaction=borrow_transaction,
            return_date=return_date,
            current_year=datetime.utcnow().year,
            logo_base64=logo_base64
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
