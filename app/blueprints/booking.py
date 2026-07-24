from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, current_app, session
from flask_login import login_required, current_user
from app import db
from app.models.booking import (
    BookingForm, BookingFormField, BookingFormImage,
    BookingRequest, BookingRequestField, BookingRequestFile,
    BookingFormRole, BookingFormRoleUser, BookingRequestApproval,
    BookingRequestMessage,
)
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.file import Folder
from app.models.user import User
from app.utils.email_sender import send_booking_confirmation_email, send_booking_accepted_email, send_booking_rejected_email
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from app.utils.common import is_module_enabled
from app.tasks.booking_archiver import archive_old_booking_requests
from datetime import datetime, timedelta, date, time
from werkzeug.utils import secure_filename
from sqlalchemy import func
import os
import secrets
import json

booking_bp = Blueprint('booking', __name__)

BOOKING_VIEWS = ('overview', 'neu', 'accepted', 'rejected', 'archived')
VIEW_TO_STATUS = {
    'neu': 'pending',
    'accepted': 'accepted',
    'rejected': 'rejected',
    'archived': 'archived',
}
STATUS_TO_VIEW = {
    'pending': 'neu',
    'accepted': 'accepted',
    'rejected': 'rejected',
    'archived': 'archived',
}


def _booking_sidebar_context(form_id=None, view='overview'):
    """Gemeinsamer Sidebar-Kontext für Team-Buchungsseiten."""
    forms = BookingForm.query.order_by(
        BookingForm.is_active.desc(),
        BookingForm.created_at.desc()
    ).all()

    view = view if view in BOOKING_VIEWS else 'overview'
    current_form = None
    if form_id is not None:
        try:
            form_id = int(form_id)
        except (TypeError, ValueError):
            form_id = None
    if form_id:
        current_form = next((f for f in forms if f.id == form_id), None)
    if current_form is None and forms:
        current_form = next((f for f in forms if f.is_active), None) or forms[0]
        form_id = current_form.id
    elif current_form is None:
        form_id = None

    pending_counts = {}
    if forms:
        rows = (
            db.session.query(BookingRequest.form_id, func.count(BookingRequest.id))
            .filter(BookingRequest.status == 'pending')
            .group_by(BookingRequest.form_id)
            .all()
        )
        pending_counts = {fid: count for fid, count in rows}

    return {
        'booking_forms': forms,
        'current_form_id': form_id,
        'current_form': current_form,
        'current_view': view,
        'pending_counts': pending_counts,
    }


def _form_dashboard_stats(form_id):
    """Kennzahlen für die Formular-Übersicht."""
    today = date.today()
    window_end = today + timedelta(days=30)
    month_start = today.replace(day=1)

    base = BookingRequest.query.filter_by(form_id=form_id)
    count_pending = base.filter_by(status='pending').count()
    count_accepted = base.filter_by(status='accepted').count()
    count_rejected = base.filter_by(status='rejected').count()
    count_archived = base.filter_by(status='archived').count()
    total = count_pending + count_accepted + count_rejected + count_archived

    decided = count_accepted + count_rejected
    acceptance_rate = round((count_accepted / decided) * 100) if decided else None

    upcoming_q = (
        BookingRequest.query
        .filter_by(form_id=form_id, status='accepted')
        .filter(BookingRequest.event_date.isnot(None))
        .filter(BookingRequest.event_date >= today)
        .filter(BookingRequest.event_date <= window_end)
    )
    upcoming_count = upcoming_q.count()
    busy_days = (
        db.session.query(func.count(func.distinct(BookingRequest.event_date)))
        .filter(
            BookingRequest.form_id == form_id,
            BookingRequest.status == 'accepted',
            BookingRequest.event_date.isnot(None),
            BookingRequest.event_date >= today,
            BookingRequest.event_date <= window_end,
        )
        .scalar()
    ) or 0

    this_month = (
        BookingRequest.query
        .filter_by(form_id=form_id)
        .filter(BookingRequest.created_at >= datetime.combine(month_start, time.min))
        .count()
    )

    upcoming_events = (
        upcoming_q
        .order_by(BookingRequest.event_date.asc(), BookingRequest.event_start_time.asc())
        .limit(8)
        .all()
    )
    recent_requests = (
        BookingRequest.query
        .filter_by(form_id=form_id)
        .order_by(BookingRequest.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        'pending': count_pending,
        'accepted': count_accepted,
        'rejected': count_rejected,
        'archived': count_archived,
        'total': total,
        'acceptance_rate': acceptance_rate,
        'upcoming_count': upcoming_count,
        'busy_days': busy_days,
        'busy_window_days': 30,
        'this_month': this_month,
        'upcoming_events': upcoming_events,
        'recent_requests': recent_requests,
    }


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
        flash(translate('booking.flash.form_not_active'), 'warning')
        return redirect(url_for('booking.public_booking'))
    
    # GET: Formular-Kontext
    # Sortiere Felder nach field_order
    fields = sorted(form.fields, key=lambda f: f.field_order)

    # Lade Portalslogo
    from app.models.settings import SystemSettings
    portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
    portal_logo_filename = portal_logo_setting.value if portal_logo_setting and portal_logo_setting.value else None

    if request.method == 'POST':
        # Validiere Pflichtfelder
        applicant_name = request.form.get('applicant_name', '').strip()
        event_name = request.form.get('event_name', '').strip()
        email = request.form.get('email', '').strip()

        def _form_error():
            return render_template(
                'booking/public_form.html',
                form=form,
                fields=fields,
                portal_logo_filename=portal_logo_filename,
            )

        if not applicant_name:
            flash(translate('booking.flash.enter_name'), 'danger')
            return _form_error()

        if not event_name:
            flash(translate('booking.flash.enter_event_name'), 'danger')
            return _form_error()

        if not email or '@' not in email:
            flash(translate('booking.flash.enter_valid_email'), 'danger')
            return _form_error()

        # Validiere zusätzliche Pflichtfelder
        errors = []
        for field in form.fields:
            if field.is_required:
                value = request.form.get(f'field_{field.id}', '').strip()
                if not value:
                    errors.append(translate('booking.flash.field_required', field_label=field.field_label))
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return _form_error()
        
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
            applicant_name=applicant_name,
            email=email,
            token=token,
            status='pending',
            event_date=event_date,
            event_start_time=event_start_time,
            event_end_time=event_end_time
        )
        db.session.add(booking_request)
        db.session.flush()
        
        # Erstelle Zustimmungs-Einträge für alle Rollen
        for role in form.roles:
            approval = BookingRequestApproval(
                request_id=booking_request.id,
                role_id=role.id,
                status='pending'
            )
            db.session.add(approval)
        
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
        
        # Push an Rollen-User der Formular-Zustimmungen
        try:
            from app.utils.notifications import send_booking_request_notification
            send_booking_request_notification(booking_request)
        except Exception as e:
            current_app.logger.error(f"Fehler beim Senden der Buchungs-Push: {e}")

        # Sende Bestätigungs-E-Mail
        try:
            send_booking_confirmation_email(booking_request)
        except Exception as e:
            current_app.logger.error(f"Fehler beim Senden der Bestätigungs-E-Mail: {e}")
        
        # Weiterleitung zur Übersicht mit Token
        return redirect(url_for('booking.public_view', token=token))

    return render_template(
        'booking/public_form.html',
        form=form,
        fields=fields,
        portal_logo_filename=portal_logo_filename,
    )


@booking_bp.route('/view/<token>')
def public_view(token):
    """Zeigt Buchungsübersicht mit Token."""
    booking_request = BookingRequest.query.filter_by(token=token).first_or_404()
    form = booking_request.form
    
    # Lade Feldwerte
    field_values = {}
    for field_value in booking_request.field_values:
        field_values[field_value.field_id] = field_value
    
    # Lade Portalslogo
    from app.models.settings import SystemSettings
    portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
    portal_logo_filename = portal_logo_setting.value if portal_logo_setting and portal_logo_setting.value else None
    
    thread_messages = (
        BookingRequestMessage.query
        .filter_by(request_id=booking_request.id)
        .order_by(BookingRequestMessage.created_at.asc())
        .all()
    )

    return render_template('booking/public_view.html',
                         booking_request=booking_request,
                         form=form,
                         field_values=field_values,
                         token=token,
                         portal_logo_filename=portal_logo_filename,
                         messages=thread_messages)


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
        flash(translate('booking.flash.mailbox_not_created'), 'warning')
        return redirect(url_for('booking.public_view', token=token))
    
    folder = booking_request.folder
    
    if request.method == 'POST':
        from app.utils.bot_protection import is_enabled_for, validate_bot_protection

        mailbox_bot_key = f'mailbox_bot_verified_{token}'
        if is_enabled_for('mailbox'):
            if not session.get(mailbox_bot_key):
                bot_ok, _ = validate_bot_protection(request, 'mailbox')
                if not bot_ok:
                    flash(translate('auth.flash.bot_protection_failed'), 'danger')
                    return redirect(url_for('booking.mailbox_upload', token=token))
                session[mailbox_bot_key] = True

        if 'file' not in request.files:
            flash(translate('booking.flash.no_file_selected'), 'danger')
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
                flash(translate('booking.flash.file_too_large', filename=file.filename), 'danger')
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
            flash(translate('booking.flash.files_uploaded', count=uploaded_count), 'success')
        else:
            flash(translate('booking.flash.no_files_uploaded'), 'warning')
        
        return redirect(url_for('booking.mailbox_upload', token=token))
    
    # GET: Zeige Upload-Formular
    # Lade bereits hochgeladene Dateien
    from app.models.file import File
    from app.utils.bot_protection import get_template_context as get_bot_template_context

    uploaded_files = File.query.filter_by(folder_id=folder.id, is_current=True).order_by(File.created_at.desc()).all()
    bot_ctx = get_bot_template_context()
    bot_ctx['bot_context'] = 'mailbox'
    bot_ctx['show_bot'] = bot_ctx.get('bot_enabled_mailbox', False) and not session.get(f'mailbox_bot_verified_{token}')

    return render_template('booking/mailbox_upload.html',
                         booking_request=booking_request,
                         token=token,
                         folder=folder,
                         uploaded_files=uploaded_files,
                         **bot_ctx)


# Admin-Routen wurden nach settings.py verschoben


# Team-Routen

@booking_bp.route('/requests')
@login_required
@check_module_access('module_booking')
def requests():
    """Übersicht aller Buchungsanfragen (Shell: Sidebar + Dashboard/Liste)."""
    try:
        archive_old_booking_requests()
    except Exception as e:
        current_app.logger.error(f"Fehler bei automatischer Archivierung: {e}")

    # Legacy ?status= → neue view-Namen
    legacy_status = request.args.get('status')
    view = request.args.get('view')
    if not view and legacy_status:
        view = STATUS_TO_VIEW.get(legacy_status, 'overview')
    if not view:
        view = 'overview'

    form_id = request.args.get('form_id', type=int)
    ctx = _booking_sidebar_context(form_id=form_id, view=view)
    view = ctx['current_view']
    current_form = ctx['current_form']

    stats = None
    requests_list = []
    unread_by_request = {}
    if current_form:
        if view == 'overview':
            stats = _form_dashboard_stats(current_form.id)
        else:
            status = VIEW_TO_STATUS.get(view)
            query = BookingRequest.query.filter_by(form_id=current_form.id)
            if status:
                query = query.filter_by(status=status)
            requests_list = query.order_by(BookingRequest.created_at.desc()).all()
            if requests_list:
                try:
                    ids = [r.id for r in requests_list]
                    rows = (
                        db.session.query(
                            BookingRequestMessage.request_id,
                            func.count(BookingRequestMessage.id),
                        )
                        .filter(
                            BookingRequestMessage.request_id.in_(ids),
                            BookingRequestMessage.direction == 'inbound',
                            BookingRequestMessage.is_read.is_(False),
                        )
                        .group_by(BookingRequestMessage.request_id)
                        .all()
                    )
                    unread_by_request = {rid: cnt for rid, cnt in rows}
                except Exception as e:
                    current_app.logger.error(f"Unread booking message counts failed: {e}")

    return render_template(
        'booking/requests.html',
        requests=requests_list,
        stats=stats,
        status_filter=VIEW_TO_STATUS.get(view, 'pending'),
        unread_by_request=unread_by_request,
        **ctx,
    )


@booking_bp.route('/request/<int:request_id>')
@login_required
@check_module_access('module_booking')
def request_detail(request_id):
    """Details einer Buchung anzeigen."""
    booking_request = BookingRequest.query.get_or_404(request_id)
    form = booking_request.form

    field_values = {}
    for field_value in booking_request.field_values:
        field_values[field_value.field_id] = field_value

    approvals = {}
    user_role_assignments = {}

    for role in form.roles:
        approval = BookingRequestApproval.query.filter_by(
            request_id=booking_request.id,
            role_id=role.id
        ).first()
        approvals[role.id] = approval

        role_user = BookingFormRoleUser.query.filter_by(
            role_id=role.id,
            user_id=current_user.id
        ).first()
        user_role_assignments[role.id] = role_user is not None

    detail_view = STATUS_TO_VIEW.get(booking_request.status, 'overview')
    ctx = _booking_sidebar_context(form_id=form.id, view=detail_view)

    try:
        from app.utils.booking_messages import mark_messages_read
        mark_messages_read(booking_request.id)
    except Exception as e:
        current_app.logger.error(f"Could not mark booking messages read: {e}")

    thread_messages = (
        BookingRequestMessage.query
        .filter_by(request_id=booking_request.id)
        .order_by(BookingRequestMessage.created_at.asc())
        .all()
    )

    return render_template(
        'booking/request_detail.html',
        booking_request=booking_request,
        form=form,
        field_values=field_values,
        approvals=approvals,
        user_role_assignments=user_role_assignments,
        messages=thread_messages,
        **ctx,
    )


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
        flash(translate('booking.flash.enter_event_date'), 'danger')
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
    
    # Erstelle Kalendereintrag (bei Multi-Kalender im Public-Kalender)
    calendar_id = None
    try:
        from app.utils.multi_calendars import is_calendar_multi_enabled, get_public_calendar
        if is_calendar_multi_enabled():
            calendar_id = get_public_calendar().id
    except Exception as e:
        current_app.logger.error(f"Multi-Kalender Public-Lookup fehlgeschlagen: {e}")

    calendar_event = CalendarEvent(
        title=booking_request.event_name,
        description=f"Buchungsanfrage von {booking_request.email}\n\nLink zur Buchung: {url_for('booking.request_detail', request_id=booking_request.id, _external=True)}",
        start_time=start_datetime,
        end_time=end_datetime,
        created_by=current_user.id,
        booking_request_id=booking_request.id,
        calendar_id=calendar_id,
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
        # Finde oder erstelle Veranstaltungen-Ordner (öffentlich)
        veranstaltungen_folder = Folder.query.filter_by(name='veranstaltungen', parent_id=None).first()
        if not veranstaltungen_folder:
            veranstaltungen_folder = Folder(
                name='veranstaltungen',
                parent_id=None,
                created_by=current_user.id,
                space='public',
            )
            db.session.add(veranstaltungen_folder)
            db.session.flush()
        elif getattr(veranstaltungen_folder, 'space', None) != 'public':
            veranstaltungen_folder.space = 'public'
        
        # Erstelle Ordner für diese Veranstaltung
        event_folder = Folder(
            name=booking_request.event_name,
            parent_id=veranstaltungen_folder.id,
            created_by=current_user.id,
            space='public',
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

    # Veranstaltungsmodul: Event + Appointment an denselben Kalendereintrag knüpfen (kein Doppel-Termin)
    if is_module_enabled('module_events'):
        try:
            from app.models.event import Event, EventAppointment
            event_obj = Event(
                name=booking_request.event_name,
                description=(
                    f"Aus Buchungsanfrage von {booking_request.email}\n"
                    f"Link: {url_for('booking.request_detail', request_id=booking_request.id, _external=True)}"
                ),
                folder_id=folder.id if folder else None,
                owner_id=current_user.id,
                created_by=current_user.id,
            )
            db.session.add(event_obj)
            db.session.flush()

            appointment = EventAppointment(
                event_id=event_obj.id,
                label='Termin',
                description=event_obj.description,
                start_time=start_datetime,
                end_time=end_datetime,
                calendar_event_id=calendar_event.id,
            )
            db.session.add(appointment)
        except Exception as e:
            current_app.logger.error(f"Veranstaltung aus Buchung konnte nicht erstellt werden: {e}")
    
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
    
    flash(translate('booking.flash.accepted'), 'success')
    return redirect(url_for('booking.request_detail', request_id=request_id))


@booking_bp.route('/request/<int:request_id>/reject', methods=['POST'])
@login_required
@check_module_access('module_booking')
def request_reject(request_id):
    """Buchung ablehnen."""
    booking_request = BookingRequest.query.get_or_404(request_id)
    
    if booking_request.status != 'pending':
        flash(translate('booking.flash.cannot_reject'), 'warning')
        return redirect(url_for('booking.request_detail', request_id=request_id))
    
    rejection_reason = request.form.get('rejection_reason', '').strip()
    
    if not rejection_reason:
        flash(translate('booking.flash.enter_rejection_reason'), 'danger')
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
    
    flash(translate('booking.flash.rejected'), 'success')
    return redirect(url_for('booking.request_detail', request_id=request_id))


@booking_bp.route('/request/<int:request_id>/send-email', methods=['POST'])
@login_required
@check_module_access('module_booking')
def request_send_email(request_id):
    """E-Mail-Rückfrage an Buchungskunden senden (Thread)."""
    booking_request = BookingRequest.query.get_or_404(request_id)

    email_subject = request.form.get('email_subject', '').strip()
    email_body = request.form.get('email_body', '').strip()

    if not email_subject or not email_body:
        flash(translate('booking.flash.fill_subject_message'), 'danger')
        return redirect(url_for('booking.request_detail', request_id=request_id))

    try:
        from app.utils.email_sender import send_booking_staff_message
        ok = send_booking_staff_message(
            booking_request,
            email_subject,
            email_body,
            created_by=current_user.id,
        )
        if ok:
            flash(translate('booking.flash.email_sent'), 'success')
        else:
            flash(translate('booking.flash.email_error'), 'danger')
    except Exception as e:
        current_app.logger.error(f"Fehler beim Senden der E-Mail: {e}")
        flash(translate('booking.flash.email_error'), 'danger')

    return redirect(url_for('booking.request_detail', request_id=request_id))


@booking_bp.route('/request/<int:request_id>/approve/<int:role_id>', methods=['POST'])
@login_required
@check_module_access('module_booking')
def request_approve(request_id, role_id):
    """Zustimmung für eine Rolle geben."""
    booking_request = BookingRequest.query.get_or_404(request_id)
    role = BookingFormRole.query.get_or_404(role_id)
    
    # Prüfe ob Benutzer dieser Rolle zugewiesen ist
    role_user = BookingFormRoleUser.query.filter_by(role_id=role_id, user_id=current_user.id).first()
    if not role_user:
        flash(translate('booking.flash.not_assigned_to_role'), 'danger')
        return redirect(url_for('booking.request_detail', request_id=request_id))
    
    # Finde oder erstelle Approval
    approval = BookingRequestApproval.query.filter_by(request_id=request_id, role_id=role_id).first()
    if not approval:
        approval = BookingRequestApproval(
            request_id=request_id,
            role_id=role_id,
            status='pending'
        )
        db.session.add(approval)
    
    # Setze Zustimmung
    approval.status = 'approved'
    approval.user_id = current_user.id
    approval.approved_at = datetime.utcnow()
    approval.comment = request.form.get('comment', '').strip() or None
    
    db.session.commit()
    
    # Prüfe ob alle erforderlichen Rollen zugestimmt haben
    all_required_approved = True
    for r in booking_request.form.roles:
        if r.is_required:
            appr = BookingRequestApproval.query.filter_by(request_id=request_id, role_id=r.id).first()
            if not appr or appr.status != 'approved':
                all_required_approved = False
                break
    
    # Prüfe ob jemand abgelehnt hat
    any_rejected = BookingRequestApproval.query.filter_by(request_id=request_id, status='rejected').first() is not None
    
    # Aktualisiere Status der Buchung
    if any_rejected:
        booking_request.status = 'rejected'
    elif all_required_approved:
        booking_request.status = 'accepted'
    
    db.session.commit()
    
    flash(translate('booking.flash.approval_saved', role_name=role.role_name), 'success')
    return redirect(url_for('booking.request_detail', request_id=request_id))


@booking_bp.route('/request/<int:request_id>/reject-role/<int:role_id>', methods=['POST'])
@login_required
@check_module_access('module_booking')
def request_reject_role(request_id, role_id):
    """Ablehnung für eine Rolle geben."""
    booking_request = BookingRequest.query.get_or_404(request_id)
    role = BookingFormRole.query.get_or_404(role_id)
    
    # Prüfe ob Benutzer dieser Rolle zugewiesen ist
    role_user = BookingFormRoleUser.query.filter_by(role_id=role_id, user_id=current_user.id).first()
    if not role_user:
        flash(translate('booking.flash.not_assigned_to_role'), 'danger')
        return redirect(url_for('booking.request_detail', request_id=request_id))
    
    # Finde oder erstelle Approval
    approval = BookingRequestApproval.query.filter_by(request_id=request_id, role_id=role_id).first()
    if not approval:
        approval = BookingRequestApproval(
            request_id=request_id,
            role_id=role_id,
            status='pending'
        )
        db.session.add(approval)
    
    # Setze Ablehnung
    approval.status = 'rejected'
    approval.user_id = current_user.id
    approval.rejected_at = datetime.utcnow()
    approval.comment = request.form.get('rejection_reason', '').strip() or None
    
    # Wenn eine Rolle ablehnt, ist die gesamte Buchung abgelehnt
    booking_request.status = 'rejected'
    
    db.session.commit()
    
    flash(translate('booking.flash.rejection_saved', role_name=role.role_name), 'warning')
    return redirect(url_for('booking.request_detail', request_id=request_id))


@booking_bp.route('/request/<int:request_id>/pdf')
@login_required
@check_module_access('module_booking')
def request_pdf(request_id):
    """PDF für Buchungsanfrage generieren und herunterladen."""
    booking_request = BookingRequest.query.get_or_404(request_id)
    
    from app.utils.booking_pdf_generator import generate_booking_request_pdf
    from flask import send_file
    from io import BytesIO
    
    # Generiere PDF
    pdf_buffer = generate_booking_request_pdf(booking_request)
    
    # Sende PDF als Download
    filename = f"Buchung_{booking_request.event_name}_{booking_request.id}.pdf"
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )

