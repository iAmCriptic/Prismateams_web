import io
import csv
import os
from datetime import datetime
from flask import (
    render_template, request, jsonify, flash, redirect, url_for,
    current_app, abort, send_file, Response
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models.email import Mailbox
from app.models.booking_personal import (
    BookingPersonalEvent,
    BookingPersonalField,
    BookingPersonalEntry,
    BookingPersonalFile,
    BookingPersonalTemplate,
)
from app.utils.access_control import check_module_access
from app.utils.common import is_module_enabled
from app.utils.booking_personal_presets import (
    FESTIVAL_STANDARD_FIELDS,
    ensure_default_template,
    apply_template_to_event,
)
from .mail import (
    get_available_placeholders,
    render_template_string,
    send_booking_personal_mail,
)
from . import booking_personal_bp


def _check_access():
    if not is_module_enabled('module_booking_personal'):
        abort(403)
    check_module_access('module_booking_personal')


@booking_personal_bp.before_request
def before_request():
    # Öffentliche Routen für Formular und Zusage-Übersicht sind ohne Login zugänglich
    if request.endpoint and (
        request.endpoint.endswith('.public_form') or
        request.endpoint.endswith('.public_form_submit') or
        request.endpoint.endswith('.public_overview')
    ):
        return
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    _check_access()


@booking_personal_bp.route('/')
@booking_personal_bp.route('/event/<int:event_id>')
def index(event_id=None):
    """Hauptansicht mit Event-Reitern und interaktiver Datentabelle."""
    ensure_default_template(db.session, current_user.id)

    events = BookingPersonalEvent.query.filter_by(is_active=True).order_by(
        BookingPersonalEvent.created_at.desc()
    ).all()

    current_event = None
    if event_id:
        current_event = BookingPersonalEvent.query.get(event_id)
    if not current_event and events:
        current_event = events[0]

    templates = BookingPersonalTemplate.query.order_by(
        BookingPersonalTemplate.is_system_default.desc(),
        BookingPersonalTemplate.name.asc()
    ).all()

    mailboxes = Mailbox.query.filter_by(is_active=True).order_by(Mailbox.name.asc()).all()

    # Felder und Einträge des aktuellen Events
    fields = []
    entries = []
    if current_event:
        fields = current_event.fields
        entries = current_event.entries
        # Stelle sicher, dass Formelwerte aktuell berechnet sind
        for entry in entries:
            entry.compute_formula_values(fields)

    return render_template(
        'booking_personal/index.html',
        events=events,
        current_event=current_event,
        fields=fields,
        entries=entries,
        templates=templates,
        mailboxes=mailboxes,
    )


@booking_personal_bp.route('/events/create', methods=['POST'])
def create_event():
    """Erstellt eine neue Veranstaltung mit optionalem Template."""
    name = request.form.get('name', '').strip()
    if not name:
        flash('Bitte einen Namen für die Veranstaltung eingeben.', 'warning')
        return redirect(url_for('booking_personal.index'))

    template_id = request.form.get('template_id')
    event = BookingPersonalEvent(
        name=name,
        created_by=current_user.id
    )
    db.session.add(event)
    db.session.flush()

    # Template anwenden
    fields_def = FESTIVAL_STANDARD_FIELDS
    if template_id:
        try:
            tmpl = BookingPersonalTemplate.query.get(int(template_id))
            if tmpl:
                fields_def = tmpl.get_fields() or FESTIVAL_STANDARD_FIELDS
        except Exception:
            pass

    apply_template_to_event(event, fields_def, db.session)
    db.session.commit()

    flash(f'Veranstaltung „{event.name}“ erfolgreich angelegt.', 'success')
    return redirect(url_for('booking_personal.index', event_id=event.id))


@booking_personal_bp.route('/events/<int:event_id>/settings', methods=['POST'])
def update_event_settings(event_id):
    """Aktualisiert allgemeine Einstellungen und E-Mail-Vorlagen eines Events."""
    event = BookingPersonalEvent.query.get_or_404(event_id)

    name = request.form.get('name', '').strip()
    if name:
        event.name = name

    mailbox_id = request.form.get('mailbox_id')
    if mailbox_id and mailbox_id.isdigit():
        event.mailbox_id = int(mailbox_id)
    else:
        event.mailbox_id = None

    event.accept_template_subject = request.form.get('accept_template_subject', event.accept_template_subject)
    event.accept_template_body = request.form.get('accept_template_body', event.accept_template_body)
    event.reject_template_subject = request.form.get('reject_template_subject', event.reject_template_subject)
    event.reject_template_body = request.form.get('reject_template_body', event.reject_template_body)
    event.invite_template_subject = request.form.get('invite_template_subject', event.invite_template_subject)
    event.invite_template_body = request.form.get('invite_template_body', event.invite_template_body)

    db.session.commit()
    flash('Einstellungen erfolgreich gespeichert.', 'success')
    return redirect(url_for('booking_personal.index', event_id=event.id))


@booking_personal_bp.route('/events/<int:event_id>/delete', methods=['POST'])
def delete_event(event_id):
    """Löscht eine Veranstaltung samt aller Einträge."""
    event = BookingPersonalEvent.query.get_or_404(event_id)
    name = event.name
    db.session.delete(event)
    db.session.commit()
    flash(f'Veranstaltung „{name}“ wurde gelöscht.', 'info')
    return redirect(url_for('booking_personal.index'))


# -------------------------------------------------------------
# REST API für Datentabelle & Inline-Editing
# -------------------------------------------------------------

@booking_personal_bp.route('/api/entry/<int:entry_id>/cell', methods=['POST'])
def api_save_cell(entry_id):
    """Speichert den Wert einer einzelnen Zelle direkt (Inline-Editing)."""
    entry = BookingPersonalEntry.query.get_or_404(entry_id)
    data = request.get_json() or {}

    field_key = data.get('field_key')
    value = data.get('value')

    if not field_key:
        return jsonify({'success': False, 'error': 'field_key fehlt'}), 400

    entry.set_value(field_key, value)
    entry.compute_formula_values(entry.event.fields)
    db.session.commit()

    return jsonify({
        'success': True,
        'entry': entry.to_dict(),
        'updated_custom_data': entry.get_custom_data()
    })


@booking_personal_bp.route('/api/event/<int:event_id>/entry', methods=['POST'])
def api_create_entry(event_id):
    """Fügt einen neuen Act/Eintrag zur Tabelle hinzu."""
    event = BookingPersonalEvent.query.get_or_404(event_id)
    data = request.get_json() or {}

    name = data.get('name') or 'Neuer Act'
    max_order = db.session.query(db.func.max(BookingPersonalEntry.order_index)).filter_by(event_id=event_id).scalar() or 0

    entry = BookingPersonalEntry(
        event_id=event.id,
        name=name,
        order_index=max_order + 1,
        status='Angefragt'
    )
    # Initiale Standard-Werte setzen
    entry.set_value('project_name', name)
    entry.set_value('status_booking', 'Angefragt')
    entry.set_value('gage', '€0.00')
    entry.compute_formula_values(event.fields)

    db.session.add(entry)
    db.session.commit()

    return jsonify({
        'success': True,
        'entry': entry.to_dict()
    })


@booking_personal_bp.route('/api/entry/<int:entry_id>/delete', methods=['POST'])
def api_delete_entry(entry_id):
    """Löscht einen Eintrag aus der Tabelle."""
    entry = BookingPersonalEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'success': True})


@booking_personal_bp.route('/api/entry/<int:entry_id>', methods=['GET'])
def api_get_entry(entry_id):
    """Liefert die kompletten Details eines Eintrags für das Detail-Modal."""
    entry = BookingPersonalEntry.query.get_or_404(entry_id)
    entry.compute_formula_values(entry.event.fields)
    return jsonify({
        'success': True,
        'entry': entry.to_dict(),
        'fields': [f.to_dict() for f in entry.event.fields]
    })


@booking_personal_bp.route('/api/entry/<int:entry_id>/update-all', methods=['POST'])
def api_update_entry_all(entry_id):
    """Aktualisiert alle Felder eines Eintrags aus dem Detail-Modal."""
    entry = BookingPersonalEntry.query.get_or_404(entry_id)
    data = request.get_json() or {}

    for k, v in data.items():
        entry.set_value(k, v)

    entry.compute_formula_values(entry.event.fields)
    db.session.commit()

    return jsonify({
        'success': True,
        'entry': entry.to_dict()
    })


# -------------------------------------------------------------
# Custom Fields & Templates
# -------------------------------------------------------------

@booking_personal_bp.route('/api/event/<int:event_id>/fields', methods=['POST'])
def api_save_fields(event_id):
    """Speichert Konfiguration, Sortierung und Eigenschaften der Spalten."""
    event = BookingPersonalEvent.query.get_or_404(event_id)
    data = request.get_json() or {}
    fields_list = data.get('fields', [])

    # Aktualisiere oder erstelle Felder
    existing_by_key = {f.field_key: f for f in event.fields}
    keep_keys = set()

    for idx, f_data in enumerate(fields_list):
        f_key = f_data.get('field_key') or f'col_{idx}_{int(datetime.utcnow().timestamp())}'
        keep_keys.add(f_key)

        field = existing_by_key.get(f_key)
        if not field:
            field = BookingPersonalField(event_id=event.id, field_key=f_key)
            db.session.add(field)

        field.label = f_data.get('label') or 'Spalte'
        field.label_en = f_data.get('label_en') or field.label
        field.field_type = f_data.get('field_type') or 'text'
        field.field_order = idx
        field.width = int(f_data.get('width', 160))
        field.is_required = bool(f_data.get('is_required', False))
        field.is_external = bool(f_data.get('is_external', False))
        field.is_internal = bool(f_data.get('is_internal', True))
        field.visible_in_overview = bool(f_data.get('visible_in_overview', True))
        field.formula_definition = f_data.get('formula_definition') or ''
        field.help_text = f_data.get('help_text') or ''

        if f_data.get('options'):
            field.set_options(f_data.get('options'))
        else:
            field.options_json = None

    # Entferne nicht mehr vorhandene Spalten
    for f_key, existing_f in existing_by_key.items():
        if f_key not in keep_keys:
            db.session.delete(existing_f)

    db.session.commit()

    return jsonify({
        'success': True,
        'fields': [f.to_dict() for f in event.fields]
    })


@booking_personal_bp.route('/api/event/<int:event_id>/save-template', methods=['POST'])
def api_save_template(event_id):
    """Speichert das Spalten-Set des Events als neues Template ab."""
    event = BookingPersonalEvent.query.get_or_404(event_id)
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()

    if not name:
        return jsonify({'success': False, 'error': 'Bitte einen Namen für die Vorlage angeben.'}), 400

    existing = BookingPersonalTemplate.query.filter_by(name=name).first()
    if existing and existing.is_system_default:
        return jsonify({'success': False, 'error': 'Standard-Systemvorlagen können nicht überschrieben werden.'}), 400

    template = existing or BookingPersonalTemplate(name=name, created_by=current_user.id)
    template.description = data.get('description', '')
    template.set_fields([f.to_dict() for f in event.fields])

    db.session.add(template)
    db.session.commit()

    return jsonify({
        'success': True,
        'template': template.to_dict()
    })


@booking_personal_bp.route('/api/event/<int:event_id>/load-template', methods=['POST'])
def api_load_template(event_id):
    """Wendet ein gespeichertes Template auf das Event an."""
    event = BookingPersonalEvent.query.get_or_404(event_id)
    data = request.get_json() or {}
    template_id = data.get('template_id')

    template = BookingPersonalTemplate.query.get_or_404(template_id)
    fields_def = template.get_fields()
    if not fields_def:
        return jsonify({'success': False, 'error': 'Vorlage enthält keine Felder.'}), 400

    apply_template_to_event(event, fields_def, db.session)
    db.session.commit()

    return jsonify({
        'success': True,
        'fields': [f.to_dict() for f in event.fields]
    })


# -------------------------------------------------------------
# E-Mail Workflows (Zusage, Absage, Einladung)
# -------------------------------------------------------------

@booking_personal_bp.route('/api/entry/<int:entry_id>/mail-preview', methods=['POST'])
def api_mail_preview(entry_id):
    """Erzeugt eine vorausgefüllte Vorschau für Zusage, Absage oder Einladung."""
    entry = BookingPersonalEntry.query.get_or_404(entry_id)
    event = entry.event
    data = request.get_json() or {}
    mail_type = data.get('type', 'accept')  # accept, reject, invite

    placeholders = get_available_placeholders(event, entry)

    if mail_type == 'reject':
        subject_tmpl = event.reject_template_subject
        body_tmpl = event.reject_template_body
    elif mail_type == 'invite':
        subject_tmpl = event.invite_template_subject
        body_tmpl = event.invite_template_body
    else:
        subject_tmpl = event.accept_template_subject
        body_tmpl = event.accept_template_body

    subject = render_template_string(subject_tmpl, placeholders)
    body = render_template_string(body_tmpl, placeholders)
    recipient = entry.email or entry.get_value('mail') or ''

    return jsonify({
        'success': True,
        'type': mail_type,
        'recipient': recipient,
        'subject': subject,
        'body': body,
        'placeholders': placeholders,
        'mailbox_name': event.mailbox.display_name if event.mailbox else 'Standard-Portalabsender'
    })


@booking_personal_bp.route('/api/entry/<int:entry_id>/mail-send', methods=['POST'])
def api_mail_send(entry_id):
    """Versendet die geprüfte E-Mail an den Act/Person."""
    entry = BookingPersonalEntry.query.get_or_404(entry_id)
    event = entry.event
    data = request.get_json() or {}

    recipient = (data.get('recipient') or '').strip()
    subject = (data.get('subject') or '').strip()
    body = data.get('body') or ''
    mail_type = data.get('type', 'accept')

    if not recipient or '@' not in recipient:
        return jsonify({'success': False, 'error': 'Ungültige Empfängeradresse.'}), 400
    if not subject:
        return jsonify({'success': False, 'error': 'Betreff darf nicht leer sein.'}), 400

    try:
        send_booking_personal_mail(event, entry, recipient, subject, body)

        now = datetime.utcnow()
        if mail_type == 'accept':
            entry.acceptance_sent_at = now
            entry.set_value('status_booking', 'Zusage gesendet')
            entry.status = 'Zusage gesendet'
        elif mail_type == 'reject':
            entry.rejection_sent_at = now
            entry.set_value('status_booking', 'Absage')
            entry.status = 'Absage'
        elif mail_type == 'invite':
            entry.invite_sent_at = now
            entry.set_value('status_booking', 'Formular gesendet')
            entry.status = 'Formular gesendet'

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'E-Mail wurde erfolgreich versendet!',
            'entry': entry.to_dict()
        })
    except Exception as e:
        current_app.logger.exception('Fehler beim E-Mail-Versand (Booking / Personal):')
        return jsonify({'success': False, 'error': f'Fehler beim E-Mail-Versand: {str(e)}'}), 500


# -------------------------------------------------------------
# CSV / Excel Export
# -------------------------------------------------------------

@booking_personal_bp.route('/event/<int:event_id>/export')
def export_csv(event_id):
    """Exportiert alle Einträge der Veranstaltung als CSV."""
    event = BookingPersonalEvent.query.get_or_404(event_id)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    # Header
    header = [f.label for f in event.fields]
    writer.writerow(header)

    # Rows
    for entry in event.entries:
        entry.compute_formula_values(event.fields)
        row = []
        for f in event.fields:
            val = entry.get_value(f.field_key, '')
            if isinstance(val, list):
                val = ', '.join([str(v) for v in val])
            row.append(str(val) if val is not None else '')
        writer.writerow(row)

    output.seek(0)
    filename = f"{secure_filename(event.name)}_booking_export.csv"
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )
