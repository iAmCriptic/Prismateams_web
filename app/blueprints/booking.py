from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, current_app
from flask_login import login_required, current_user
from app import db
from app.models.booking import (
    BookingForm, BookingFormField, BookingFormImage,
    BookingRequest, BookingRequestField, BookingRequestFile
)
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.file import Folder
from app.models.user import User
from app.utils.email_sender import send_booking_confirmation_email, send_booking_accepted_email, send_booking_rejected_email
from app.utils.access_control import check_module_access
from app.tasks.booking_archiver import archive_old_booking_requests
from datetime import datetime, timedelta, date, time
from werkzeug.utils import secure_filename
import os
import secrets
import json

booking_bp = Blueprint('booking', __name__)


def allowed_image_file(filename):
    """Prüft ob die Datei ein erlaubtes Bildformat hat."""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_booking_token():
    """Generiert einen eindeutigen Token für eine Buchung."""
    token = secrets.token_urlsafe(32)
    # Stelle sicher, dass Token eindeutig ist
    while BookingRequest.query.filter_by(token=token).first():
        token = secrets.token_urlsafe(32)
    return token


# Öffentliche Routen (kein Login erforderlich)

@booking_bp.route('/')
def public_booking():
    """Öffentliche Buchungsseite - zeigt Formular oder Auswahl."""
    # Hole alle aktiven Formulare
    active_forms = BookingForm.query.filter_by(is_active=True).order_by(BookingForm.created_at.desc()).all()
    
    if not active_forms:
        return render_template('booking/no_forms.html')
    
    # Wenn nur ein Formular aktiv ist, zeige es direkt
    if len(active_forms) == 1:
        return redirect(url_for('booking.public_form', form_id=active_forms[0].id))
    
    # Wenn mehrere Formulare aktiv sind, zeige Auswahl
    return render_template('booking/public_form_select.html', forms=active_forms)


@booking_bp.route('/form/<int:form_id>', methods=['GET', 'POST'])
def public_form(form_id):
    """Öffentliches Buchungsformular anzeigen und verarbeiten."""
    form = BookingForm.query.get_or_404(form_id)
    
    if not form.is_active:
        flash('Dieses Buchungsformular ist nicht mehr aktiv.', 'warning')
        return redirect(url_for('booking.public_booking'))
    
    if request.method == 'POST':
        # Validiere Pflichtfelder
        event_name = request.form.get('event_name', '').strip()
        email = request.form.get('email', '').strip()
        
        if not event_name:
            flash('Bitte geben Sie einen Namen für die Veranstaltung ein.', 'danger')
            return render_template('booking/public_form.html', form=form)
        
        if not email or '@' not in email:
            flash('Bitte geben Sie eine gültige E-Mail-Adresse ein.', 'danger')
            return render_template('booking/public_form.html', form=form)
        
        # Validiere zusätzliche Pflichtfelder
        errors = []
        for field in form.fields:
            if field.is_required:
                value = request.form.get(f'field_{field.id}', '').strip()
                if not value:
                    errors.append(f'Das Feld "{field.field_label}" ist ein Pflichtfeld.')
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('booking/public_form.html', form=form)
        
        # Parse Event-Datum und Zeiten
        event_date = None
        event_start_time = None
        event_end_time = None
        
        event_date_str = request.form.get('event_date', '').strip()
        if event_date_str:
            try:
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        event_start_time_str = request.form.get('event_start_time', '').strip()
        if event_start_time_str:
            try:
                event_start_time = datetime.strptime(event_start_time_str, '%H:%M').time()
            except ValueError:
                pass
        
        event_end_time_str = request.form.get('event_end_time', '').strip()
        if event_end_time_str:
            try:
                event_end_time = datetime.strptime(event_end_time_str, '%H:%M').time()
            except ValueError:
                pass
        
        # Erstelle Buchungsanfrage
        token = generate_booking_token()
        booking_request = BookingRequest(
            form_id=form.id,
            event_name=event_name,
            email=email,
            token=token,
            status='pending',
            event_date=event_date,
            event_start_time=event_start_time,
            event_end_time=event_end_time
        )
        db.session.add(booking_request)
        db.session.flush()
        
        # Speichere zusätzliche Feldwerte
        for field in form.fields:
            value = request.form.get(f'field_{field.id}', '').strip()
            if value or field.field_type == 'checkbox':
                # Für Checkboxen: prüfe ob angehakt
                if field.field_type == 'checkbox':
                    value = '1' if request.form.get(f'field_{field.id}') == 'on' else '0'
                
                request_field = BookingRequestField(
                    request_id=booking_request.id,
                    field_id=field.id,
                    field_value=value
                )
                db.session.add(request_field)
        
        # Verarbeite Datei-Uploads
        for field in form.fields:
            if field.field_type in ['file', 'image']:
                if f'field_{field.id}' in request.files:
                    file = request.files[f'field_{field.id}']
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                        filename = f"{timestamp}_{filename}"
                        
                        # Erstelle Upload-Ordner
                        upload_dir = os.path.join(
                            current_app.config['UPLOAD_FOLDER'],
                            'bookings',
                            str(booking_request.id)
                        )
                        os.makedirs(upload_dir, exist_ok=True)
                        
                        file_path = os.path.join(upload_dir, filename)
                        file.save(file_path)
                        
                        # Speichere Datei-Referenz
                        request_field = BookingRequestField.query.filter_by(
                            request_id=booking_request.id,
                            field_id=field.id
                        ).first()
                        
                        if request_field:
                            request_field.file_path = file_path
                        else:
                            request_field = BookingRequestField(
                                request_id=booking_request.id,
                                field_id=field.id,
                                file_path=file_path
                            )
                            db.session.add(request_field)
        
        db.session.commit()
        
        # Sende Bestätigungs-E-Mail
        try:
            send_booking_confirmation_email(booking_request)
        except Exception as e:
            current_app.logger.error(f"Fehler beim Senden der Bestätigungs-E-Mail: {e}")
        
        # Weiterleitung zur Übersicht mit Token
        return redirect(url_for('booking.public_view', token=token))
    
    # GET: Zeige Formular
    # Sortiere Felder nach field_order
    fields = sorted(form.fields, key=lambda f: f.field_order)
    return render_template('booking/public_form.html', form=form, fields=fields)


@booking_bp.route('/view/<token>')
def public_view(token):
    """Zeigt Buchungsübersicht mit Token."""
    booking_request = BookingRequest.query.filter_by(token=token).first_or_404()
    form = booking_request.form
    
    # Lade Feldwerte
    field_values = {}
    for field_value in booking_request.field_values:
        field_values[field_value.field_id] = field_value
    
    return render_template('booking/public_view.html', 
                         request=booking_request, 
                         form=form,
                         field_values=field_values,
                         token=token)


@booking_bp.route('/mailbox/<token>', methods=['GET', 'POST'])
def mailbox_upload(token):
    """Briefkasten-Upload für Buchungskunden."""
    booking_request = BookingRequest.query.filter_by(token=token).first_or_404()
    
    # Prüfe ob Briefkasten aktiviert ist
    if not booking_request.form.enable_mailbox:
        flash('Briefkasten ist für diese Buchung nicht verfügbar.', 'danger')
        return redirect(url_for('booking.public_view', token=token))
    
    # Prüfe ob Ordner existiert
    if not booking_request.folder_id:
        flash('Briefkasten wurde noch nicht erstellt.', 'warning')
        return redirect(url_for('booking.public_view', token=token))
    
    folder = booking_request.folder
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Keine Datei ausgewählt.', 'danger')
            return redirect(url_for('booking.mailbox_upload', token=token))
        
        files = request.files.getlist('file')
        uploaded_count = 0
        
        for file in files:
            if not file.filename:
                continue
            
            # Dateigröße prüfen (max 50MB)
            file.seek(0, 2)  # Seek to end
            file_size = file.tell()
            file.seek(0)  # Reset to beginning
            
            max_size = 50 * 1024 * 1024  # 50MB
            if file_size > max_size:
                flash(f'Datei "{file.filename}" ist zu groß (max. 50MB).', 'danger')
                continue
            
            # Datei speichern
            original_name = secure_filename(file.filename)
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{original_name}"
            
            # Speichere im Veranstaltungen-Ordner
            upload_dir = os.path.join(
                current_app.config['UPLOAD_FOLDER'],
                'veranstaltungen',
                secure_filename(booking_request.event_name)
            )
            os.makedirs(upload_dir, exist_ok=True)
            
            file_path = os.path.join(upload_dir, filename)
            file.save(file_path)
            
            # Erstelle File-Eintrag in der Datenbank
            from app.models.file import File
            # Verwende einen System-User oder den Ersteller der Buchung
            uploader_id = booking_request.form.created_by if booking_request.form.created_by else 1
            new_file = File(
                name=original_name,
                original_name=original_name,
                folder_id=folder.id,
                file_path=file_path,
                uploaded_by=uploader_id,
                file_size=file_size,
                is_current=True
            )
            db.session.add(new_file)
            uploaded_count += 1
        
        if uploaded_count > 0:
            db.session.commit()
            flash(f'{uploaded_count} Datei(en) wurden erfolgreich hochgeladen.', 'success')
        else:
            flash('Keine Dateien wurden hochgeladen.', 'warning')
        
        return redirect(url_for('booking.mailbox_upload', token=token))
    
    # GET: Zeige Upload-Formular
    # Lade bereits hochgeladene Dateien
    from app.models.file import File
    uploaded_files = File.query.filter_by(folder_id=folder.id, is_current=True).order_by(File.created_at.desc()).all()
    
    return render_template('booking/mailbox_upload.html',
                         request=booking_request,
                         token=token,
                         folder=folder,
                         uploaded_files=uploaded_files)


# Admin-Routen wurden nach settings.py verschoben


# Team-Routen

@booking_bp.route('/requests')
@login_required
@check_module_access('module_booking')
def requests():
    """Übersicht aller Buchungsanfragen."""
    # Führe Archivierung aus (kann auch als separater Task laufen)
    try:
        archive_old_booking_requests()
    except Exception as e:
        current_app.logger.error(f"Fehler bei automatischer Archivierung: {e}")
    
    status_filter = request.args.get('status', 'pending')
    
    query = BookingRequest.query
    
    if status_filter == 'pending':
        query = query.filter_by(status='pending')
    elif status_filter == 'accepted':
        query = query.filter_by(status='accepted')
    elif status_filter == 'rejected':
        query = query.filter_by(status='rejected')
    elif status_filter == 'archived':
        query = query.filter_by(status='archived')
    
    requests_list = query.order_by(BookingRequest.created_at.desc()).all()
    
    return render_template('booking/requests.html', requests=requests_list, status_filter=status_filter)


@booking_bp.route('/request/<int:request_id>')
@login_required
@check_module_access('module_booking')
def request_detail(request_id):
    """Details einer Buchung anzeigen."""
    booking_request = BookingRequest.query.get_or_404(request_id)
    form = booking_request.form
    
    # Lade Feldwerte
    field_values = {}
    for field_value in booking_request.field_values:
        field_values[field_value.field_id] = field_value
    
    return render_template('booking/request_detail.html', 
                         request=booking_request, 
                         form=form,
                         field_values=field_values)


@booking_bp.route('/request/<int:request_id>/accept', methods=['POST'])
@login_required
@check_module_access('module_booking')
def request_accept(request_id):
    """Buchung annehmen."""
    booking_request = BookingRequest.query.get_or_404(request_id)
    
    if booking_request.status != 'pending':
        flash('Diese Buchung kann nicht mehr angenommen werden.', 'warning')
        return redirect(url_for('booking.request_detail', request_id=request_id))
    
    # Parse Datum und Zeiten für Kalendereintrag
    if not booking_request.event_date:
        flash('Bitte geben Sie ein Datum für die Veranstaltung ein.', 'danger')
        return redirect(url_for('booking.request_detail', request_id=request_id))
    
    # Kombiniere Datum und Zeit
    start_datetime = None
    end_datetime = None
    
    if booking_request.event_start_time:
        start_datetime = datetime.combine(booking_request.event_date, booking_request.event_start_time)
    else:
        start_datetime = datetime.combine(booking_request.event_date, time(9, 0))  # Default: 9:00
    
    if booking_request.event_end_time:
        end_datetime = datetime.combine(booking_request.event_date, booking_request.event_end_time)
    else:
        # Default: 1 Stunde später
        end_datetime = start_datetime + timedelta(hours=1)
    
    # Erstelle Kalendereintrag
    calendar_event = CalendarEvent(
        title=booking_request.event_name,
        description=f"Buchungsanfrage von {booking_request.email}\n\nLink zur Buchung: {url_for('booking.request_detail', request_id=booking_request.id, _external=True)}",
        start_time=start_datetime,
        end_time=end_datetime,
        created_by=current_user.id,
        booking_request_id=booking_request.id
    )
    db.session.add(calendar_event)
    db.session.flush()
    
    # Füge alle aktiven Benutzer als Teilnehmer hinzu
    active_users = User.query.filter_by(is_active=True).all()
    for user in active_users:
        participant = EventParticipant(
            event_id=calendar_event.id,
            user_id=user.id,
            status='pending'
        )
        db.session.add(participant)
    
    # Erstelle Ordner/Briefkasten falls aktiviert
    folder = None
    if booking_request.form.enable_mailbox or booking_request.form.enable_shared_folder:
        # Finde oder erstelle Veranstaltungen-Ordner
        veranstaltungen_folder = Folder.query.filter_by(name='veranstaltungen', parent_id=None).first()
        if not veranstaltungen_folder:
            veranstaltungen_folder = Folder(
                name='veranstaltungen',
                parent_id=None,
                created_by=current_user.id
            )
            db.session.add(veranstaltungen_folder)
            db.session.flush()
        
        # Erstelle Ordner für diese Veranstaltung
        event_folder = Folder(
            name=booking_request.event_name,
            parent_id=veranstaltungen_folder.id,
            created_by=current_user.id
        )
        db.session.add(event_folder)
        db.session.flush()
        
        # Erstelle physischen Ordner
        upload_dir = os.path.join(
            current_app.config['UPLOAD_FOLDER'],
            'veranstaltungen',
            secure_filename(booking_request.event_name)
        )
        os.makedirs(upload_dir, exist_ok=True)
        
        folder = event_folder
    
    # Aktualisiere Buchungsanfrage
    booking_request.status = 'accepted'
    booking_request.calendar_event_id = calendar_event.id
    booking_request.folder_id = folder.id if folder else None
    booking_request.accepted_by = current_user.id
    booking_request.accepted_at = datetime.utcnow()
    
    db.session.commit()
    
    # Sende E-Mail an Buchungskunden
    try:
        send_booking_accepted_email(booking_request, calendar_event)
    except Exception as e:
        current_app.logger.error(f"Fehler beim Senden der Annahme-E-Mail: {e}")
    
    flash('Buchung wurde angenommen und Kalendereintrag wurde erstellt.', 'success')
    return redirect(url_for('booking.request_detail', request_id=request_id))


@booking_bp.route('/request/<int:request_id>/reject', methods=['POST'])
@login_required
@check_module_access('module_booking')
def request_reject(request_id):
    """Buchung ablehnen."""
    booking_request = BookingRequest.query.get_or_404(request_id)
    
    if booking_request.status != 'pending':
        flash('Diese Buchung kann nicht mehr abgelehnt werden.', 'warning')
        return redirect(url_for('booking.request_detail', request_id=request_id))
    
    rejection_reason = request.form.get('rejection_reason', '').strip()
    
    if not rejection_reason:
        flash('Bitte geben Sie einen Ablehnungsgrund ein.', 'danger')
        return redirect(url_for('booking.request_detail', request_id=request_id))
    
    # Aktualisiere Buchungsanfrage
    booking_request.status = 'rejected'
    booking_request.rejection_reason = rejection_reason
    booking_request.rejected_by = current_user.id
    booking_request.rejected_at = datetime.utcnow()
    
    db.session.commit()
    
    # Sende E-Mail an Buchungskunden
    try:
        send_booking_rejected_email(booking_request)
    except Exception as e:
        current_app.logger.error(f"Fehler beim Senden der Ablehnungs-E-Mail: {e}")
    
    flash('Buchung wurde abgelehnt.', 'success')
    return redirect(url_for('booking.request_detail', request_id=request_id))


@booking_bp.route('/request/<int:request_id>/send-email', methods=['POST'])
@login_required
@check_module_access('module_booking')
def request_send_email(request_id):
    """E-Mail-Rückfrage an Buchungskunden senden."""
    booking_request = BookingRequest.query.get_or_404(request_id)
    
    email_subject = request.form.get('email_subject', '').strip()
    email_body = request.form.get('email_body', '').strip()
    
    if not email_subject or not email_body:
        flash('Bitte füllen Sie Betreff und Nachricht aus.', 'danger')
        return redirect(url_for('booking.request_detail', request_id=request_id))
    
    # Sende E-Mail
    try:
        from flask_mail import Message
        from app import mail
        from config import get_formatted_sender
        
        msg = Message(
            subject=email_subject,
            recipients=[booking_request.email],
            sender=get_formatted_sender() or current_app.config.get('MAIL_USERNAME'),
            body=email_body
        )
        mail.send(msg)
        
        flash('E-Mail wurde gesendet.', 'success')
    except Exception as e:
        current_app.logger.error(f"Fehler beim Senden der E-Mail: {e}")
        flash('Fehler beim Senden der E-Mail.', 'danger')
    
    return redirect(url_for('booking.request_detail', request_id=request_id))

