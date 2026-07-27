import os
import secrets
import string
import logging
import base64
import threading
import smtplib
from email.utils import parseaddr
from datetime import datetime, timedelta
from flask import render_template, current_app, url_for
from flask_mail import Message
from app.models.user import User
from app.utils.common import portal_now_naive

# Flask-Mail ist nicht thread-sicher innerhalb eines Workers; Worker untereinander
# dürfen parallel SMTP nutzen (kein Cross-Process-File-Lock mit 60s-Wartezeit).
_smtp_send_lock = threading.Lock()


def _envelope_addr(addr):
    """Extrahiert die reine E-Mail-Adresse aus 'Name <mail@x>' oder 'mail@x'."""
    if addr is None:
        return ''
    if isinstance(addr, tuple):
        return (addr[1] or addr[0] or '').strip()
    parsed = parseaddr(str(addr))
    return (parsed[1] or str(addr)).strip()


def _smtp_connect(timeout=20):
    """Öffnet eine SMTP-Verbindung aus Flask-Config (mit Timeout)."""
    server = current_app.config.get('MAIL_SERVER')
    port = int(current_app.config.get('MAIL_PORT', 587) or 587)
    use_ssl = bool(current_app.config.get('MAIL_USE_SSL', False))
    use_tls = bool(current_app.config.get('MAIL_USE_TLS', True))
    username = current_app.config.get('MAIL_USERNAME')
    password = current_app.config.get('MAIL_PASSWORD')
    timeout = int(current_app.config.get('MAIL_TIMEOUT', timeout) or timeout)

    if not server:
        raise RuntimeError('MAIL_SERVER ist nicht gesetzt')

    if use_ssl:
        smtp = smtplib.SMTP_SSL(server, port, timeout=timeout)
    else:
        smtp = smtplib.SMTP(server, port, timeout=timeout)
        smtp.ehlo()
        if use_tls:
            smtp.starttls()
            smtp.ehlo()

    if username and password:
        smtp.login(username, password)
    return smtp


def _smtp_close(smtp):
    """Schließt SMTP robust — SMTPServerDisconnected nach Versand ist harmlos."""
    if smtp is None:
        return
    try:
        smtp.quit()
    except smtplib.SMTPServerDisconnected:
        # Viele Provider trennen nach DATA; Mail ist trotzdem zugestellt.
        pass
    except Exception:
        try:
            smtp.close()
        except Exception:
            pass


def send_message_via_smtplib(msg, timeout=20):
    """
    Sendet eine Flask-Mail Message direkt per smtplib.

    Umgeht Flask-Mail Connection.__exit__ → host.quit(), das nach erfolgreichem
    sendmail oft SMTPServerDisconnected wirft (False-Negative im UI).
    """
    if current_app.config.get('MAIL_SUPPRESS_SEND') or current_app.config.get('TESTING'):
        logging.info('MAIL_SUPPRESS_SEND/TESTING aktiv — Versand übersprungen')
        return True

    if not getattr(msg, 'sender', None):
        raise RuntimeError('E-Mail hat keinen Absender (MAIL_DEFAULT_SENDER / sender)')
    recipients = list(getattr(msg, 'send_to', None) or getattr(msg, 'recipients', None) or [])
    if not recipients:
        raise RuntimeError('E-Mail hat keine Empfänger')

    payload = msg.as_bytes() if hasattr(msg, 'as_bytes') else bytes(msg)
    from_addr = _envelope_addr(msg.sender)
    to_addrs = [_envelope_addr(r) for r in recipients]
    to_addrs = [a for a in to_addrs if a]
    if not from_addr or not to_addrs:
        raise RuntimeError('Ungültige Absender-/Empfänger-Adresse')

    smtp = None
    try:
        smtp = _smtp_connect(timeout=timeout)
        smtp.sendmail(from_addr, to_addrs, payload)
        return True
    finally:
        _smtp_close(smtp)

def _msg_has_nested_related(msg):
    """True if msg.msg is mixed with an inner multipart/related (CID + attachments)."""
    try:
        if not getattr(msg, 'msg', None):
            return False
        if msg.msg.get_content_type() != 'multipart/mixed':
            return False
        parts = msg.msg.get_payload()
        if not isinstance(parts, list):
            return False
        return any(
            hasattr(p, 'get_content_type') and p.get_content_type() == 'multipart/related'
            for p in parts
        )
    except Exception:
        return False


def _mark_logo_inline(msg):
    """Markiert vorhandene Logo-Bildteile als inline mit stabiler CID."""
    try:
        if not getattr(msg, 'msg', None):
            return
        if not hasattr(msg.msg, 'get_payload'):
            return
        parts = msg.msg.get_payload()
        if not isinstance(parts, list):
            return

        logo_filenames = ('logo.png', 'logo.jpg', 'logo.jpeg', 'logo.gif')
        for part in parts:
            if not (hasattr(part, 'get_content_type') and part.get_content_type().startswith('image/')):
                continue
            disp = part.get('Content-Disposition', '') or ''
            if not any(name in disp.lower() for name in logo_filenames):
                continue

            if not part.get('Content-ID'):
                part.add_header('Content-ID', '<portal_logo>')
            if 'attachment' in disp and 'inline' not in disp:
                import re
                filename_match = re.search(r'filename="?([^"]+)"?', disp)
                filename = filename_match.group(1) if filename_match else 'logo.png'
                try:
                    part.replace_header('Content-Disposition', f'inline; filename="{filename}"')
                except Exception:
                    del part['Content-Disposition']
                    part.add_header('Content-Disposition', f'inline; filename="{filename}"')
            elif not disp:
                part.add_header('Content-Disposition', 'inline; filename="logo.png"')
            break
    except Exception as e:
        logging.warning("Logo-CID-Markierung fehlgeschlagen: %s", e)


def send_email_with_lock(msg, timeout=60):
    """
    Sendet eine E-Mail mit prozesslokalem Thread-Lock (Flask-Mail-Sicherheit).

    Nutzt smtplib direkt statt flask_mail.Connection, damit ein abgerissener
    SMTP-QUIT nach erfolgreichem Versand nicht als Fehler gilt.

    Args:
        msg: Flask-Mail Message-Objekt
        timeout: SMTP-Socket-Timeout in Sekunden (Default aus MAIL_TIMEOUT/20)

    Returns:
        True wenn erfolgreich gesendet

    Raises:
        Exception: Wenn E-Mail-Versand fehlschlägt
    """
    smtp_timeout = int(current_app.config.get('MAIL_TIMEOUT', 20) or 20)
    if timeout and timeout < 300:
        # Alte API nutzte timeout für Lock-Wartezeit; sinnvolle SMTP-Timeouts übernehmen
        smtp_timeout = min(smtp_timeout, int(timeout)) if timeout > 0 else smtp_timeout

    try:
        if hasattr(msg, '_message') and getattr(msg, 'msg', None) is None:
            # Nur vorbereiten wenn nötig; Flask-Mail 0.10 baut ohnehin via as_bytes()/_message()
            pass
    except Exception as e:
        logging.warning("Fehler bei Message-Vorbereitung: %s", e)

    _mark_logo_inline(msg)

    with _smtp_send_lock:
        try:
            return send_message_via_smtplib(msg, timeout=smtp_timeout)
        except smtplib.SMTPServerDisconnected as send_err:
            # Extrem selten: Disconnect während sendmail nach 250 — als Erfolg werten
            # nur wenn wir unsicher sind? Nein: ohne Bestätigung nicht als Erfolg.
            logging.error("SMTP-Verbindung abgebrochen: %s", send_err)
            raise
        except Exception as send_err:
            logging.error("Fehler beim Senden der E-Mail: %s", send_err)
            raise

def generate_confirmation_code():
    """Generiert einen 6-stelligen Bestätigungscode."""
    return ''.join(secrets.choice(string.digits) for _ in range(6))

def get_logo_data():
    """Holt das Portal-Logo aus SystemSettings oder Konfiguration und gibt Logo-Daten, MIME-Type und Dateiname zurück."""
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
                    filename = portal_logo_setting.value
                    return logo_data, mime_type, filename
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
            filename = os.path.basename(full_path)
            return logo_data, mime_type, filename
    except Exception as e:
        logging.warning(f"Fehler beim Laden des Standard-Logos: {e}")
    
    # Wenn kein Logo gefunden wurde, gib None zurück
    return None, None, None

def get_logo_base64():
    """Holt das Portal-Logo aus SystemSettings oder Konfiguration und gibt es als Base64-String zurück."""
    logo_data, mime_type, _ = get_logo_data()
    if logo_data and mime_type:
        logo_base64 = base64.b64encode(logo_data).decode('utf-8')
        return f"data:{mime_type};base64,{logo_base64}"
    return None

def create_message_with_logo(subject, recipients, html_content, body_text=None, sender=None, cc=None, logo_cid='portal_logo'):
    """
    Erstellt eine Flask-Mail Message mit Logo als CID-Anhang.
    
    Args:
        subject: E-Mail-Betreff
        recipients: Liste von Empfängern oder String mit kommagetrennten Adressen
        html_content: HTML-Inhalt der E-Mail
        body_text: Plain-Text-Version (optional)
        sender: Absender (optional, wird aus Config geholt wenn None)
        cc: CC-Empfänger (optional)
        logo_cid: Content-ID für das Logo (Standard: 'portal_logo')
    
    Returns:
        Flask-Mail Message-Objekt mit Logo als CID-Anhang
    """
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage
    from email.header import Header
    from config import get_formatted_sender
    
    # Hole Absender
    if not sender:
        mail_username = current_app.config.get('MAIL_USERNAME')
        sender = get_formatted_sender() or mail_username
    
    # Normalisiere Empfänger
    if isinstance(recipients, str):
        recipients_list = [r.strip() for r in recipients.split(',')]
    else:
        recipients_list = recipients
    
    # Erstelle multipart/related Message für HTML mit inline images
    msg_multipart = MIMEMultipart('related')
    
    # Setze Header
    msg_multipart['Subject'] = Header(subject, 'utf-8')
    msg_multipart['From'] = sender
    msg_multipart['To'] = ', '.join(recipients_list)
    if cc:
        if isinstance(cc, str):
            cc_list = [c.strip() for c in cc.split(',')]
        else:
            cc_list = cc
        msg_multipart['Cc'] = ', '.join(cc_list)
    
    # Erstelle multipart/alternative für plain text und HTML
    msg_alternative = MIMEMultipart('alternative')
    msg_multipart.attach(msg_alternative)
    
    # Füge plain text hinzu (falls vorhanden)
    if body_text:
        msg_alternative.attach(MIMEText(body_text, 'plain', 'utf-8'))
    else:
        # Fallback: HTML zu Text konvertieren (einfach)
        import re
        from html import unescape
        text_content = re.sub(r'<[^>]+>', '', html_content)
        text_content = unescape(text_content).strip()
        msg_alternative.attach(MIMEText(text_content, 'plain', 'utf-8'))
    
    # Füge HTML hinzu
    msg_alternative.attach(MIMEText(html_content, 'html', 'utf-8'))
    
    # Füge Logo als inline attachment mit CID hinzu
    logo_data, logo_mime_type, logo_filename = get_logo_data()
    if logo_data and logo_mime_type:
        image_type = logo_mime_type.split('/')[1] if '/' in logo_mime_type else 'png'
        
        # Standardisiere Dateiname basierend auf MIME-Type
        if image_type == 'jpeg' or image_type == 'jpg':
            attachment_filename = 'logo.jpg'
        elif image_type == 'png':
            attachment_filename = 'logo.png'
        elif image_type == 'gif':
            attachment_filename = 'logo.gif'
        else:
            attachment_filename = 'logo.png'  # Default
        
        img_attachment = MIMEImage(logo_data, image_type)
        img_attachment.add_header('Content-ID', f'<{logo_cid}>')
        img_attachment.add_header('Content-Disposition', 'inline', filename=attachment_filename)
        # Stelle sicher, dass Content-Type korrekt gesetzt ist
        img_attachment.add_header('Content-Type', logo_mime_type)
        msg_multipart.attach(img_attachment)
        logging.info(f"Logo als Anhang hinzugefügt: {attachment_filename} ({logo_mime_type}), CID: {logo_cid}, Größe: {len(logo_data)} bytes")
    else:
        logging.warning("Logo konnte nicht geladen werden - kein Logo als Anhang hinzugefügt")
    
    # Erstelle Flask-Mail Message Objekt und kopiere die konstruierte Message
    msg = Message(
        subject=subject,
        recipients=recipients_list,
        body=body_text or '',
        html=html_content,
        sender=sender
    )
    if cc:
        if isinstance(cc, str):
            msg.cc = cc.split(',')
        else:
            msg.cc = cc
    
    # Ersetze die interne Message-Struktur mit unserer multipart/related Version
    # WICHTIG: Flask-Mail verwendet msg.msg beim Senden, also müssen wir die komplette
    # multipart-Struktur hier setzen
    msg.msg = msg_multipart
    
    # Debug: Überprüfe, dass Logo-Anhang vorhanden ist
    if hasattr(msg.msg, 'get_payload'):
        parts = msg.msg.get_payload()
        if isinstance(parts, list):
            attachment_count = sum(1 for p in parts if hasattr(p, 'get_content_type') and p.get_content_type().startswith('image/'))
            logging.info(f"Message-Struktur nach msg.msg Setzen: {len(parts)} Teile, davon {attachment_count} Bild-Anhänge")
            logo_found = False
            for i, part in enumerate(parts):
                if hasattr(part, 'get_content_type') and part.get_content_type().startswith('image/'):
                    cid = part.get('Content-ID', 'N/A')
                    filename = part.get('Content-Disposition', 'N/A')
                    logging.info(f"  Logo-Anhang {i}: Content-ID={cid}, Disposition={filename}")
                    if cid != 'N/A' and logo_cid in cid:
                        logo_found = True
            
            if not logo_found and logo_data and logo_mime_type:
                logging.warning("Logo wurde nicht in Message-Struktur gefunden, obwohl es hinzugefügt wurde!")
    
    return msg

def _portal_name():
    """Portal-Anzeigename aus SystemSettings."""
    try:
        from app.models.settings import SystemSettings
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        return (
            portal_name_setting.value
            if portal_name_setting and portal_name_setting.value
            else current_app.config.get('APP_NAME', 'Prismateams')
        )
    except Exception:
        return current_app.config.get('APP_NAME', 'Prismateams')

def _mail_configured():
    return all([
        current_app.config.get('MAIL_SERVER'),
        current_app.config.get('MAIL_USERNAME'),
        current_app.config.get('MAIL_PASSWORD'),
    ])

def _attach_files_to_message(msg, attachments):
    """Hängt Dateien an (multipart/mixed um related mit CID-Logo)."""
    if not attachments:
        return
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart

    if getattr(msg, 'msg', None) is not None:
        outer = MIMEMultipart('mixed')
        for key, value in msg.msg.items():
            if key.lower() not in ('content-type', 'mime-version'):
                outer[key] = value
        outer.attach(msg.msg)
        for filename, mimetype, data in attachments:
            part = MIMEApplication(data, Name=filename)
            part.add_header('Content-Disposition', 'attachment', filename=filename)
            outer.attach(part)
        msg.msg = outer
    else:
        for filename, mimetype, data in attachments:
            msg.attach(filename, mimetype, data)

def _footer_placeholder_values(user=None, app_name=None, **ctx):
    """Werte für <user>/<email>/<app_name>/<date>/<time> im Footer-Template."""
    from app.utils.common import now_in_portal_timezone

    name = ''
    email = ''
    if user is not None:
        name = (getattr(user, 'full_name', None) or '').strip()
        email = (getattr(user, 'email', None) or '').strip()

    booking = ctx.get('booking_request')
    if booking is not None:
        if not name:
            name = (
                getattr(booking, 'contact_name', None)
                or getattr(booking, 'name', None)
                or getattr(booking, 'event_name', None)
                or ''
            )
            name = str(name).strip() if name else ''
        if not email:
            email = (getattr(booking, 'email', None) or '').strip()

    if not name:
        name = (
            ctx.get('borrower_name')
            or ctx.get('recipient_name')
            or ''
        )
        name = str(name).strip() if name else ''
    if not email:
        email = (
            ctx.get('contact_email')
            or ctx.get('recipient_email')
            or ''
        )
        email = str(email).strip() if email else ''

    now = now_in_portal_timezone()
    return {
        '<user>': name,
        '<email>': email,
        '<app_name>': app_name or _portal_name(),
        '<date>': now.strftime('%d.%m.%Y'),
        '<time>': now.strftime('%H:%M'),
    }

def _format_footer_plain_to_html(text):
    """Wandelt Plaintext-Footer (Zeilenumbrüche) in Absätze mit <br> um."""
    import re

    if not text or not str(text).strip():
        return ''
    paragraphs = re.split(r'\n\n+', str(text))
    formatted = []
    for para in paragraphs:
        if para.strip():
            formatted.append(f'<p>{para.strip().replace(chr(10), "<br>")}</p>')
    return ''.join(formatted)

def build_email_footer_html(user=None, app_name=None, *, sender_line=False, **ctx):
    """
    Baut HTML-Footer aus SystemSettings (email_footer_template / email_footer_text).
    Gleiche Platzhalter wie Admin-Footer: <user>, <email>, <app_name>, <date>, <time>.
    Gibt None zurück, wenn kein konfigurierter Footer existiert (außer sender_line).
    """
    from app.models.settings import SystemSettings

    portal_name = app_name or _portal_name()
    replacements = _footer_placeholder_values(user=user, app_name=portal_name, **ctx)

    footer_template = SystemSettings.query.filter_by(key='email_footer_template').first()
    if footer_template and footer_template.value and str(footer_template.value).strip():
        footer_html = str(footer_template.value)
        for placeholder, value in replacements.items():
            footer_html = footer_html.replace(placeholder, value)
        return _format_footer_plain_to_html(footer_html) or footer_html

    lines = []
    footer_text_setting = SystemSettings.query.filter_by(key='email_footer_text').first()
    if footer_text_setting and footer_text_setting.value and str(footer_text_setting.value).strip():
        lines.append(str(footer_text_setting.value).strip())
    if sender_line and user is not None:
        display = (getattr(user, 'full_name', None) or '').strip() or replacements['<user>']
        if display:
            lines.append(f'Gesendet von {display}')
    if not lines:
        return None
    return ''.join(f'<p>{line}</p>' for line in lines if line)

def render_portal_email(template_name, **ctx):
    """Rendert Portal-E-Mail-Template mit Standard-Kontext (CID-Logo + Admin-Footer)."""
    portal_name = ctx.pop('app_name', None) or _portal_name()
    ctx.setdefault('app_name', portal_name)
    ctx.setdefault('current_year', portal_now_naive().year)
    ctx.setdefault('logo_cid', 'portal_logo')
    if 'email_footer_html' not in ctx:
        ctx['email_footer_html'] = build_email_footer_html(
            user=ctx.get('user'),
            app_name=portal_name,
            borrower_name=ctx.get('borrower_name'),
            recipient_name=ctx.get('recipient_name'),
            contact_email=ctx.get('contact_email'),
            recipient_email=ctx.get('recipient_email'),
            booking_request=ctx.get('booking_request'),
        )
    html_content = render_template(template_name, **ctx)
    return html_content, portal_name

def build_portal_message(subject, recipients, template_name, body_text=None, attachments=None, **ctx):
    """Baut Flask-Mail Message mit Portal-Shell und CID-Logo."""
    html_content, portal_name = render_portal_email(template_name, **ctx)
    msg = create_message_with_logo(
        subject=subject,
        recipients=recipients,
        html_content=html_content,
        body_text=body_text,
    )
    _attach_files_to_message(msg, attachments)
    return msg, html_content, portal_name

def render_and_send_portal_email(subject, recipients, template_name, body_text=None, attachments=None, **ctx):
    """Rendert Template, baut CID-Message und sendet.

    Returns:
        True bei erfolgreichem Versand, False bei Config-/Send-Fehler.
    """
    if not _mail_configured():
        logging.warning(f'E-Mail-Konfiguration unvollständig. Versand übersprungen: {subject}')
        return False
    try:
        msg, _, _ = build_portal_message(
            subject, recipients, template_name,
            body_text=body_text, attachments=attachments, **ctx
        )
        ok = send_email_with_lock(msg)
        if not ok:
            logging.error(f'E-Mail-Versand fehlgeschlagen (kein Erfolg vom Sender): {subject}')
            return False
        return True
    except Exception as e:
        logging.error(f'E-Mail-Versand fehlgeschlagen: {subject}: {e}')
        return False

def send_confirmation_email(user):
    """Sendet eine Bestätigungs-E-Mail an den Benutzer (nur bei aktivem Konto)."""
    try:
        if not user or getattr(user, 'is_guest', False):
            return False
        if not getattr(user, 'is_active', False):
            logging.info(
                'Bestätigungs-E-Mail für %s übersprungen — Konto noch nicht freigeschaltet.',
                getattr(user, 'email', '?'),
            )
            return False

        confirmation_code = generate_confirmation_code()
        expires_at = portal_now_naive() + timedelta(hours=24)
        user.confirmation_code = confirmation_code
        user.confirmation_code_expires = expires_at
        user.is_email_confirmed = False
        from app import db
        db.session.commit()

        if not _mail_configured():
            logging.warning(
                'E-Mail-Konfiguration unvollständig. Bestätigungs-E-Mail an %s nicht gesendet '
                '(Code nur in der Datenbank gespeichert).',
                user.email,
            )
            return False

        portal_name = _portal_name()
        plain_text = (
            'Ihr Konto wurde nun aktiviert.\n\n'
            'Zur Identitätsbestätigung müssen Sie sich innerhalb von 24 Stunden '
            'anmelden und den unten stehenden Code angeben.\n\n'
            f'Bestätigungscode: {confirmation_code}\n\n'
            'Der Code ist 24 Stunden gültig und darf nicht an Dritte weitergegeben werden.'
        )
        try:
            ok = render_and_send_portal_email(
                subject=f'E-Mail-Bestätigung - {portal_name}',
                recipients=[user.email],
                template_name='emails/confirmation_code.html',
                body_text=plain_text,
                user=user,
                confirmation_code=confirmation_code,
            )
            if ok:
                logging.info('Confirmation email sent to %s', user.email)
                return True
            logging.error('Confirmation email send returned False for %s — retrying once', user.email)
            ok = render_and_send_portal_email(
                subject=f'E-Mail-Bestätigung - {portal_name}',
                recipients=[user.email],
                template_name='emails/confirmation_code.html',
                body_text=plain_text,
                user=user,
                confirmation_code=confirmation_code,
            )
            if ok:
                logging.info(f'Alternative E-Mail erfolgreich gesendet an {user.email}')
                return True
            logging.error(f'Alternative E-Mail-Versand auch fehlgeschlagen für {user.email}')
            return False
        except Exception as send_error:
            logging.error(f'Failed to send confirmation email to {user.email}: {str(send_error)}')
            return False
    except Exception as e:
        logging.error(f'Failed to send confirmation email to {user.email}: {str(e)}')
        return False

def verify_confirmation_code(user, code):
    """Überprüft den Bestätigungscode."""
    if not user.confirmation_code or not user.confirmation_code_expires:
        return False
    if portal_now_naive() > user.confirmation_code_expires:
        return False
    if user.confirmation_code != code:
        return False
    user.is_email_confirmed = True
    user.confirmation_code = None
    user.confirmation_code_expires = None
    from app import db
    db.session.commit()
    return True

def resend_confirmation_email(user):
    """Sendet eine neue Bestätigungs-E-Mail."""
    return send_confirmation_email(user)

def send_password_reset_email(user):
    """Sendet eine Passwort-Reset-E-Mail an den Benutzer."""
    try:
        reset_code = generate_confirmation_code()
        expires_at = portal_now_naive() + timedelta(hours=1)
        user.password_reset_code = reset_code
        user.password_reset_code_expires = expires_at
        from app import db
        db.session.commit()

        if not _mail_configured():
            logging.warning(
                'E-Mail-Konfiguration unvollständig. Passwort-Reset-E-Mail an %s nicht gesendet '
                '(Code nur in der Datenbank gespeichert).',
                user.email,
            )
            return False

        portal_name = _portal_name()
        plain_text = (
            f'Passwort-Reset-Code: {reset_code}\n\n'
            'Bitte geben Sie diesen Code ein, um Ihr Passwort zurückzusetzen. Der Code ist 1 Stunde gültig.'
        )
        try:
            ok = render_and_send_portal_email(
                subject=f'Passwort zurücksetzen - {portal_name}',
                recipients=[user.email],
                template_name='emails/password_reset.html',
                body_text=plain_text,
                user=user,
                reset_code=reset_code,
            )
            if not ok:
                logging.error(f'Password reset email send returned False for {user.email}')
                return False
            logging.info('Password reset email sent to %s', user.email)
            return True
        except Exception as send_error:
            logging.error(f'Failed to send password reset email to {user.email}: {str(send_error)}')
            return False
    except Exception as e:
        logging.error(f'Failed to send password reset email to {user.email}: {str(e)}')
        return False

def verify_password_reset_code(user, code):
    """Überprüft den Passwort-Reset-Code."""
    if not user.password_reset_code or not user.password_reset_code_expires:
        return False
    if portal_now_naive() > user.password_reset_code_expires:
        return False
    if user.password_reset_code != code:
        return False
    return True

def _checkout_recipient_email(checkout):
    """Empfänger für Inventar-Mails: contact_email oder Portal-User-E-Mail."""
    email = (getattr(checkout, 'contact_email', None) or '').strip()
    if email:
        return email
    borrower = getattr(checkout, 'borrower', None)
    if borrower and getattr(borrower, 'email', None):
        return borrower.email.strip()
    return None

def _checkout_item_rows(items):
    rows = []
    for item in items or []:
        product = getattr(item, 'product', None)
        rows.append({
            'id': getattr(product, 'id', None) or getattr(item, 'product_id', '—'),
            'name': getattr(product, 'name', None) or '—',
        })
    return rows

def send_borrow_receipt_email(checkout):
    """Sendet Ausleihschein-PDF nach Checkout (Quick Scan / Ausleihe)."""
    try:
        from app.models.inventory import Checkout
        from app.utils.pdf_generator import generate_borrow_receipt_pdf
        from io import BytesIO

        if not isinstance(checkout, Checkout):
            logging.error('send_borrow_receipt_email erwartet ein Checkout-Objekt.')
            return False

        recipient = _checkout_recipient_email(checkout)
        if not recipient:
            logging.warning(
                f'Keine E-Mail für Checkout {checkout.checkout_number}. Ausleihschein nicht gesendet.'
            )
            return False
        if not _mail_configured():
            logging.warning(
                f'E-Mail-Konfiguration unvollständig. Ausleihschein für {checkout.checkout_number} nicht gesendet.'
            )
            return False

        portal_name = _portal_name()
        borrow_date = checkout.start_date.strftime('%d.%m.%Y %H:%M') if checkout.start_date else '—'
        expected_return_date = checkout.end_date.strftime('%d.%m.%Y') if checkout.end_date else '—'
        items = _checkout_item_rows(checkout.items)

        pdf_buffer = BytesIO()
        generate_borrow_receipt_pdf(checkout, pdf_buffer)
        pdf_buffer.seek(0)
        filename = f'Ausleihschein_{checkout.checkout_number}.pdf'

        plain_text = (
            f'Ausleihschein {checkout.checkout_number}\n'
            f'Projekt: {checkout.event_name}\n'
            f'Ausleiher: {checkout.borrower_name}\n'
            f'Ausleihe: {borrow_date}\n'
            f'Rückgabe: {expected_return_date}\n'
        )
        ok = render_and_send_portal_email(
            subject=f'Ausleihschein - {portal_name}',
            recipients=[recipient],
            template_name='emails/borrow_receipt.html',
            body_text=plain_text,
            attachments=[(filename, 'application/pdf', pdf_buffer.read())],
            borrower_name=checkout.borrower_name,
            checkout_number=checkout.checkout_number,
            event_name=checkout.event_name,
            borrow_date=borrow_date,
            expected_return_date=expected_return_date,
            contact_email=recipient,
            items=items,
        )
        if not ok:
            logging.error(f'Borrow receipt email send returned False for {checkout.checkout_number}')
            return False
        logging.info(f'Borrow receipt email sent to {recipient} for {checkout.checkout_number}')
        return True
    except Exception as e:
        logging.error(f'Failed to send borrow receipt email: {str(e)}')
        return False

def send_return_confirmation_email(checkout, returned_items=None):
    """Sendet Rückgabe-Bestätigung mit PDF nach Rückgabe."""
    try:
        from app.models.inventory import Checkout
        from app.utils.pdf_generator import generate_return_confirmation_pdf
        from io import BytesIO

        if not isinstance(checkout, Checkout):
            logging.error('send_return_confirmation_email erwartet ein Checkout-Objekt.')
            return False

        recipient = _checkout_recipient_email(checkout)
        if not recipient:
            logging.warning(
                f'Keine E-Mail für Checkout {checkout.checkout_number}. Rückgabe-Mail nicht gesendet.'
            )
            return False
        if not _mail_configured():
            logging.warning(
                f'E-Mail-Konfiguration unvollständig. Rückgabe für {checkout.checkout_number} nicht gesendet.'
            )
            return False

        portal_name = _portal_name()
        items_source = returned_items if returned_items is not None else checkout.returned_items
        items = _checkout_item_rows(items_source)
        return_date = portal_now_naive().strftime('%d.%m.%Y %H:%M')
        if items_source:
            first_returned = getattr(items_source[0], 'returned_at', None)
            if first_returned:
                return_date = first_returned.strftime('%d.%m.%Y %H:%M')

        pdf_buffer = BytesIO()
        generate_return_confirmation_pdf(checkout, pdf_buffer, returned_items=items_source)
        pdf_buffer.seek(0)
        filename = f'Rueckgabe_{checkout.checkout_number}.pdf'

        plain_text = (
            f'Rückgabe-Bestätigung {checkout.checkout_number}\n'
            f'Projekt: {checkout.event_name}\n'
            f'Rückgabe: {return_date}\n'
        )
        ok = render_and_send_portal_email(
            subject=f'Rückgabe-Bestätigung - {portal_name}',
            recipients=[recipient],
            template_name='emails/return_confirmation.html',
            body_text=plain_text,
            attachments=[(filename, 'application/pdf', pdf_buffer.read())],
            borrower_name=checkout.borrower_name,
            checkout_number=checkout.checkout_number,
            event_name=checkout.event_name,
            return_date=return_date,
            items=items,
        )
        if not ok:
            logging.error(f'Return confirmation email send returned False for {checkout.checkout_number}')
            return False
        logging.info(f'Return confirmation email sent to {recipient} for {checkout.checkout_number}')
        return True
    except Exception as e:
        logging.error(f'Failed to send return confirmation email: {str(e)}')
        return False

def _persist_booking_outbound(booking_request, msg, subject, body_text, body_html=None, created_by=None):
    from app.utils.booking_messages import apply_thread_headers, save_outbound_message

    message_id = apply_thread_headers(msg, booking_request)
    in_reply_to = None
    if getattr(msg, 'extra_headers', None):
        in_reply_to = msg.extra_headers.get('In-Reply-To')
    try:
        ok = send_email_with_lock(msg)
    except Exception as send_error:
        logging.error(f'Booking outbound send failed for request {booking_request.id}: {send_error}')
        return False
    if not ok:
        logging.error(f'Booking outbound send returned False for request {booking_request.id}')
        return False
    try:
        save_outbound_message(
            booking_request,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            message_id=message_id,
            in_reply_to=in_reply_to,
            created_by=created_by,
        )
    except Exception as persist_error:
        logging.error(f'Booking outbound mail sent but thread save failed: {persist_error}')
    return True

def send_booking_confirmation_email(booking_request):
    """Sendet Bestätigungs-E-Mail nach Buchungsanfrage."""
    try:
        from app.utils.booking_messages import ensure_booking_subject
        if not _mail_configured():
            logging.warning(
                f'E-Mail-Konfiguration unvollständig. Bestätigung für Buchung {booking_request.id} nicht gesendet.'
            )
            return False
        portal_name = _portal_name()
        subject = ensure_booking_subject(f'Buchungsbestätigung - {portal_name}', booking_request.id)
        booking_url = url_for('booking.public_view', token=booking_request.token, _external=True)
        body_text = f'Buchungsbestätigung für {booking_request.event_name}. Status: {booking_url}'
        msg, html_content, _ = build_portal_message(
            subject=subject,
            recipients=[booking_request.email],
            template_name='emails/booking_confirmation.html',
            body_text=body_text,
            booking_request=booking_request,
            booking_url=booking_url,
        )
        try:
            if not _persist_booking_outbound(booking_request, msg, subject, body_text, html_content):
                return False
            logging.info(
                f'Booking confirmation email sent to {booking_request.email} for booking {booking_request.id}'
            )
            return True
        except Exception as send_error:
            logging.error(
                f'Failed to send booking confirmation email to {booking_request.email}: {str(send_error)}'
            )
            return False
    except Exception as e:
        logging.error(f'Failed to send booking confirmation email: {str(e)}')
        return False

def send_booking_accepted_email(booking_request, calendar_event):
    """Sendet E-Mail bei Annahme einer Buchung."""
    try:
        from app.utils.booking_messages import ensure_booking_subject
        if not _mail_configured():
            logging.warning(
                f'E-Mail-Konfiguration unvollständig. Annahme für Buchung {booking_request.id} nicht gesendet.'
            )
            return False
        portal_name = _portal_name()
        subject = ensure_booking_subject(
            f'Buchung angenommen - {booking_request.event_name}', booking_request.id
        )
        booking_url = url_for('booking.public_view', token=booking_request.token, _external=True)
        calendar_url = (
            url_for('calendar.view_event', event_id=calendar_event.id, _external=True)
            if calendar_event else None
        )
        body_text = f'Ihre Buchung „{booking_request.event_name}“ wurde angenommen. Status: {booking_url}'
        msg, html_content, _ = build_portal_message(
            subject=subject,
            recipients=[booking_request.email],
            template_name='emails/booking_accepted.html',
            body_text=body_text,
            booking_request=booking_request,
            calendar_event=calendar_event,
            booking_url=booking_url,
            calendar_url=calendar_url,
        )
        try:
            if not _persist_booking_outbound(booking_request, msg, subject, body_text, html_content):
                return False
            logging.info(
                f'Booking accepted email sent to {booking_request.email} for booking {booking_request.id}'
            )
            return True
        except Exception as send_error:
            logging.error(
                f'Failed to send booking accepted email to {booking_request.email}: {str(send_error)}'
            )
            return False
    except Exception as e:
        logging.error(f'Failed to send booking accepted email: {str(e)}')
        return False

def send_booking_rejected_email(booking_request):
    """Sendet E-Mail bei Ablehnung einer Buchung."""
    try:
        from app.utils.booking_messages import ensure_booking_subject
        if not _mail_configured():
            logging.warning(
                f'E-Mail-Konfiguration unvollständig. Ablehnung für Buchung {booking_request.id} nicht gesendet.'
            )
            return False
        portal_name = _portal_name()
        subject = ensure_booking_subject(
            f'Buchung abgelehnt - {booking_request.event_name}', booking_request.id
        )
        booking_url = url_for('booking.public_view', token=booking_request.token, _external=True)
        body_text = f'Ihre Buchung „{booking_request.event_name}“ wurde abgelehnt. Status: {booking_url}'
        msg, html_content, _ = build_portal_message(
            subject=subject,
            recipients=[booking_request.email],
            template_name='emails/booking_rejected.html',
            body_text=body_text,
            booking_request=booking_request,
            booking_url=booking_url,
        )
        try:
            if not _persist_booking_outbound(booking_request, msg, subject, body_text, html_content):
                return False
            logging.info(
                f'Booking rejected email sent to {booking_request.email} for booking {booking_request.id}'
            )
            return True
        except Exception as send_error:
            logging.error(
                f'Failed to send booking rejected email to {booking_request.email}: {str(send_error)}'
            )
            return False
    except Exception as e:
        logging.error(f'Failed to send booking rejected email: {str(e)}')
        return False

def send_booking_staff_message(booking_request, subject, body_text, created_by=None):
    """Staff-Nachricht an Antragsteller im Portal-Shell."""
    try:
        from app.utils.booking_messages import ensure_booking_subject
        if not _mail_configured():
            logging.warning(
                f'E-Mail-Konfiguration unvollständig. Staff-Nachricht für Buchung {booking_request.id} nicht gesendet.'
            )
            return False
        subject = ensure_booking_subject(subject, booking_request.id)
        booking_url = url_for('booking.public_view', token=booking_request.token, _external=True)
        message_body = (body_text or '').strip()
        full_body = message_body
        if booking_url and booking_url not in full_body:
            full_body = f'{full_body}\n\n—\nStatusseite: {booking_url}'
        msg, html_content, _ = build_portal_message(
            subject=subject,
            recipients=[booking_request.email],
            template_name='emails/booking_staff_message.html',
            body_text=full_body,
            booking_request=booking_request,
            booking_url=booking_url,
            message_body=message_body,
        )
        try:
            if not _persist_booking_outbound(
                booking_request, msg, subject, full_body,
                body_html=html_content, created_by=created_by,
            ):
                return False
            logging.info(
                f'Booking staff message sent to {booking_request.email} for booking {booking_request.id}'
            )
            return True
        except Exception as send_error:
            logging.error(
                f'Failed to send booking staff message to {booking_request.email}: {str(send_error)}'
            )
            return False
    except Exception as e:
        logging.error(f'Failed to send booking staff message: {str(e)}')
        return False

def send_smtp_test_email(recipient_email):
    """Sendet HTML-Test-E-Mail im Portal-Shell."""
    try:
        if not _mail_configured():
            logging.warning('E-Mail-Konfiguration unvollständig. SMTP-Test nicht gesendet.')
            return False
        portal_name = _portal_name()
        ok = render_and_send_portal_email(
            subject=f'Test-E-Mail - {portal_name}',
            recipients=[recipient_email],
            template_name='emails/smtp_test.html',
            body_text=f'Dies ist eine Test-E-Mail von {portal_name}.',
            recipient_email=recipient_email,
        )
        if not ok:
            logging.error(f'SMTP test email send returned False for {recipient_email}')
            raise RuntimeError('SMTP test email send failed')
        logging.info(f'SMTP test email sent to {recipient_email}')
        return True
    except Exception as e:
        logging.error(f'Failed to send SMTP test email: {str(e)}')
        raise

def generate_random_password(length=8):
    """Generiert ein sicheres zufälliges Passwort."""
    alphabet = string.ascii_letters + string.digits
    excluded_chars = 'Il1O0'
    alphabet = ''.join(c for c in alphabet if c not in excluded_chars)
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def send_account_creation_email(user, password):
    """Sendet Zugangsdaten nach Admin-Account-Erstellung."""
    try:
        if not _mail_configured():
            logging.warning(
                'E-Mail-Konfiguration unvollständig. Account-E-Mail an %s nicht gesendet '
                '(Passwort wird nicht geloggt).',
                user.email,
            )
            return False
        portal_name = _portal_name()
        login_url = url_for('auth.login', _external=True)
        plain_text = (
            f'Willkommen bei {portal_name}!\n\n'
            f'Ihr Account wurde erfolgreich erstellt.\n\n'
            f'Zugangsdaten:\nBenutzername/E-Mail: {user.email}\nPasswort: {password}\n\n'
            f'Bitte melden Sie sich unter folgender Adresse an:\n{login_url}\n\n'
            f'Nach dem ersten Login sollten Sie Ihr Passwort ändern.\n'
        )
        try:
            ok = render_and_send_portal_email(
                subject=f'Zugangsdaten für {portal_name}',
                recipients=[user.email],
                template_name='emails/account_created.html',
                body_text=plain_text,
                user=user,
                password=password,
                login_url=login_url,
            )
            if not ok:
                logging.error(f'Account creation email send returned False for {user.email}')
                return False
            logging.info(f'Account creation email sent to {user.email}')
            return True
        except Exception as send_error:
            logging.error(f'Failed to send account creation email to {user.email}: {str(send_error)}')
            return False
    except Exception as e:
        logging.error(f'Failed to send account creation email to {user.email}: {str(e)}')
        return False


def send_guest_credentials_email(recipient, full_name, username, password):
    """Sendet Gast-Zugangsdaten manuell an eine angegebene Empfänger-Adresse."""
    try:
        recipient = (recipient or '').strip().lower()
        if not recipient or '@' not in recipient:
            logging.warning('Gast-Zugangsdaten-E-Mail: ungültiger Empfänger.')
            return False
        if not _mail_configured():
            logging.warning(
                'E-Mail-Konfiguration unvollständig. Gast-Zugangsdaten an %s nicht gesendet.',
                recipient,
            )
            return False

        portal_name = _portal_name()
        login_url = url_for('auth.login', _external=True)
        display_name = (full_name or '').strip() or 'Gast'
        plain_text = (
            f'Hallo!\n\n'
            f'für Sie wurde ein Gast-Zugang bei {portal_name} eingerichtet.\n\n'
            f'Zugangsdaten:\n'
            f'Benutzername/E-Mail: {username}\n'
            f'Passwort: {password}\n\n'
            f'Login: {login_url}\n\n'
            f'Bewahren Sie diese Zugangsdaten sicher auf.\n'
        )
        ok = render_and_send_portal_email(
            subject=f'Gast-Zugang für {portal_name}',
            recipients=[recipient],
            template_name='emails/guest_credentials.html',
            body_text=plain_text,
            full_name=display_name,
            username=username,
            password=password,
            login_url=login_url,
        )
        if not ok:
            logging.error('Gast-Zugangsdaten-E-Mail an %s fehlgeschlagen.', recipient)
            return False
        logging.info('Gast-Zugangsdaten-E-Mail an %s gesendet.', recipient)
        return True
    except Exception as e:
        logging.error('Gast-Zugangsdaten-E-Mail fehlgeschlagen: %s', e)
        return False
