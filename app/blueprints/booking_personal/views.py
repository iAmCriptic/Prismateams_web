import io
import csv
import os
import re
import secrets
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
    # Öffentliche Routen für Formular, Bewerbung und Zusage-Übersicht sind ohne Login zugänglich
    if request.endpoint and (
        request.endpoint.endswith('.public_form') or
        request.endpoint.endswith('.public_form_submit') or
        request.endpoint.endswith('.public_overview') or
        request.endpoint.endswith('.public_apply') or
        request.endpoint.endswith('.public_apply_submit')
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


@booking_personal_bp.route('/event/<int:event_id>/act/<int:entry_id>')
def act_detail(event_id, entry_id):
    """Detailansicht eines Acts / Künstlers als strukturierte Profilseite."""
    current_event = BookingPersonalEvent.query.get_or_404(event_id)
    entry = BookingPersonalEntry.query.get_or_404(entry_id)
    if entry.event_id != current_event.id:
        abort(404)

    events = BookingPersonalEvent.query.filter_by(is_active=True).order_by(
        BookingPersonalEvent.created_at.desc()
    ).all()

    entry.compute_formula_values(current_event.fields)
    custom_data = entry.get_custom_data()
    templates = BookingPersonalTemplate.query.order_by(
        BookingPersonalTemplate.is_system_default.desc(),
        BookingPersonalTemplate.name.asc()
    ).all()
    mailboxes = Mailbox.query.filter_by(is_active=True).order_by(Mailbox.name.asc()).all()

    return render_template(
        'booking_personal/act_detail.html',
        events=events,
        current_event=current_event,
        entry=entry,
        fields=current_event.fields,
        custom_data=custom_data,
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

@booking_personal_bp.route('/api/event/<int:event_id>/field/add', methods=['POST'])
def api_add_field(event_id):
    """Fügt einer Veranstaltung eine neue Spalte / Custom Field hinzu."""
    event = BookingPersonalEvent.query.get_or_404(event_id)
    data = request.get_json() or {}

    label = (data.get('label') or '').strip()
    if not label:
        return jsonify({'success': False, 'error': 'Bitte einen Spaltennamen angeben.'}), 400

    field_type = data.get('field_type') or 'text'
    # Generiere eindeutigen field_key
    import re
    base_key = re.sub(r'[^a-z0-9_]', '', label.lower().replace(' ', '_').replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss'))
    if not base_key:
        base_key = 'custom_col'

    existing_keys = {f.field_key for f in event.fields}
    field_key = base_key
    counter = 1
    while field_key in existing_keys:
        field_key = f"{base_key}_{counter}"
        counter += 1

    max_order = db.session.query(db.func.max(BookingPersonalField.field_order)).filter_by(event_id=event_id).scalar() or 0

    field = BookingPersonalField(
        event_id=event.id,
        field_key=field_key,
        label=label,
        label_en=data.get('label_en') or label,
        field_type=field_type,
        field_order=max_order + 1,
        width=int(data.get('width', 160)),
        is_required=bool(data.get('is_required', False)),
        is_external=bool(data.get('is_external', False)),
        is_internal=bool(data.get('is_internal', True)),
        visible_in_overview=bool(data.get('visible_in_overview', True)),
        formula_definition=data.get('formula_definition') or '',
        help_text=data.get('help_text') or '',
    )
    if data.get('options'):
        field.set_options(data.get('options'))

    db.session.add(field)
    db.session.commit()

    return jsonify({
        'success': True,
        'field': field.to_dict(),
        'fields': [f.to_dict() for f in event.fields]
    })


@booking_personal_bp.route('/api/field/<int:field_id>/update', methods=['POST'])
def api_update_field(field_id):
    """Aktualisiert die Einstellungen einer Spalte."""
    field = BookingPersonalField.query.get_or_404(field_id)
    data = request.get_json() or {}

    if 'label' in data and data['label'].strip():
        field.label = data['label'].strip()
    if 'label_en' in data:
        field.label_en = data['label_en'].strip() or field.label
    if 'field_type' in data:
        field.field_type = data['field_type']
    if 'width' in data:
        try:
            field.width = max(60, min(600, int(data['width'])))
        except (ValueError, TypeError):
            pass
    if 'is_required' in data:
        field.is_required = bool(data['is_required'])
    if 'is_external' in data:
        field.is_external = bool(data['is_external'])
    if 'is_internal' in data:
        field.is_internal = bool(data['is_internal'])
    if 'visible_in_overview' in data:
        field.visible_in_overview = bool(data['visible_in_overview'])
    if 'formula_definition' in data:
        field.formula_definition = data['formula_definition'] or ''
    if 'help_text' in data:
        field.help_text = data['help_text'] or ''
    if 'options' in data:
        field.set_options(data['options'])

    db.session.commit()

    return jsonify({
        'success': True,
        'field': field.to_dict()
    })


@booking_personal_bp.route('/api/field/<int:field_id>/delete', methods=['POST'])
def api_delete_field(field_id):
    """Löscht eine Spalte aus einer Veranstaltung."""
    field = BookingPersonalField.query.get_or_404(field_id)
    event = field.event
    db.session.delete(field)
    db.session.commit()

    return jsonify({
        'success': True,
        'fields': [f.to_dict() for f in event.fields]
    })


@booking_personal_bp.route('/api/event/<int:event_id>/fields/reorder', methods=['POST'])
def api_reorder_fields(event_id):
    """Sortiert die Spalten einer Veranstaltung anhand einer übergebenen ID-Reihenfolge."""
    event = BookingPersonalEvent.query.get_or_404(event_id)
    data = request.get_json() or {}
    order_ids = data.get('order', [])

    field_map = {f.id: f for f in event.fields}
    for idx, fid in enumerate(order_ids):
        if fid in field_map:
            field_map[fid].field_order = idx

    db.session.commit()

    return jsonify({
        'success': True,
        'fields': [f.to_dict() for f in event.fields]
    })


@booking_personal_bp.route('/api/templates', methods=['GET'])
def api_list_templates():
    """Gibt alle gespeicherten Vorlagen zurück."""
    templates = BookingPersonalTemplate.query.order_by(
        BookingPersonalTemplate.is_system_default.desc(),
        BookingPersonalTemplate.name.asc()
    ).all()
    return jsonify({
        'success': True,
        'templates': [t.to_dict() for t in templates]
    })


@booking_personal_bp.route('/api/template/<int:template_id>/delete', methods=['POST'])
def api_delete_template(template_id):
    """Löscht eine benutzerdefinierte Vorlage."""
    template = BookingPersonalTemplate.query.get_or_404(template_id)
    if template.is_system_default:
        return jsonify({'success': False, 'error': 'Standard-Systemvorlagen können nicht gelöscht werden.'}), 400

    db.session.delete(template)
    db.session.commit()

    return jsonify({'success': True})


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
# Vorlagenverwaltung (Dedizierte Seite & Vollständige Verwaltung)
# -------------------------------------------------------------

@booking_personal_bp.route('/templates')
def templates_view():
    """Dedizierte Seite zur vollständigen Vorlagenverwaltung."""
    ensure_default_template(db.session, current_user.id)

    templates = BookingPersonalTemplate.query.order_by(
        BookingPersonalTemplate.is_system_default.desc(),
        BookingPersonalTemplate.name.asc()
    ).all()

    events = BookingPersonalEvent.query.filter_by(is_active=True).order_by(
        BookingPersonalEvent.created_at.desc()
    ).all()

    template_id = request.args.get('template_id', type=int)
    selected_template = None
    if template_id:
        selected_template = BookingPersonalTemplate.query.get(template_id)
    if not selected_template and templates:
        selected_template = templates[0]

    return render_template(
        'booking_personal/templates.html',
        templates=templates,
        selected_template=selected_template,
        events=events,
        is_templates_view=True
    )


@booking_personal_bp.route('/templates/create', methods=['POST'])
def template_create():
    """Erstellt eine neue Vorlage (leer, aus Preset oder aus Event)."""
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    source_type = request.form.get('source_type', 'standard')
    source_event_id = request.form.get('source_event_id', type=int)

    if not name:
        flash('Bitte einen Namen für die Vorlage angeben.', 'warning')
        return redirect(url_for('booking_personal.templates_view'))

    existing = BookingPersonalTemplate.query.filter_by(name=name).first()
    if existing:
        flash(f'Eine Vorlage mit dem Namen „{name}“ existiert bereits.', 'danger')
        return redirect(url_for('booking_personal.templates_view', template_id=existing.id))

    fields = []
    if source_type == 'event' and source_event_id:
        ev = BookingPersonalEvent.query.get(source_event_id)
        if ev:
            fields = [f.to_dict() for f in ev.fields]
    elif source_type == 'standard':
        default_tmpl = BookingPersonalTemplate.query.filter_by(is_system_default=True).first()
        if default_tmpl:
            fields = default_tmpl.get_fields()
        else:
            fields = FESTIVAL_STANDARD_FIELDS
    elif source_type == 'copy':
        copy_tmpl_id = request.form.get('copy_template_id', type=int)
        copy_tmpl = BookingPersonalTemplate.query.get(copy_tmpl_id)
        if copy_tmpl:
            fields = copy_tmpl.get_fields()

    new_tmpl = BookingPersonalTemplate(
        name=name,
        description=description,
        is_system_default=False,
        created_by=current_user.id
    )
    new_tmpl.set_fields(fields)
    db.session.add(new_tmpl)
    db.session.commit()

    flash(f'Vorlage „{name}“ erfolgreich mit {len(fields)} Spalten angelegt.', 'success')
    return redirect(url_for('booking_personal.templates_view', template_id=new_tmpl.id))


@booking_personal_bp.route('/templates/<int:template_id>/update', methods=['POST'])
def template_update(template_id):
    """Aktualisiert Name und Beschreibung der Vorlage."""
    template = BookingPersonalTemplate.query.get_or_404(template_id)
    if template.is_system_default:
        flash('System-Standardvorlagen können in den Grundeigenschaften nicht geändert werden.', 'warning')
        return redirect(url_for('booking_personal.templates_view', template_id=template.id))

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()

    if name and name != template.name:
        existing = BookingPersonalTemplate.query.filter_by(name=name).first()
        if existing and existing.id != template.id:
            flash(f'Eine Vorlage mit dem Namen „{name}“ existiert bereits.', 'danger')
            return redirect(url_for('booking_personal.templates_view', template_id=template.id))
        template.name = name

    template.description = description
    db.session.commit()

    flash('Vorlagen-Eigenschaften erfolgreich aktualisiert.', 'success')
    return redirect(url_for('booking_personal.templates_view', template_id=template.id))


@booking_personal_bp.route('/templates/<int:template_id>/field/add', methods=['POST'])
def template_field_add(template_id):
    """Fügt ein neues Feld zur Vorlage hinzu."""
    template = BookingPersonalTemplate.query.get_or_404(template_id)
    if template.is_system_default:
        flash('System-Standardvorlagen können nicht direkt modifiziert werden. Bitte dupliziere die Vorlage.', 'warning')
        return redirect(url_for('booking_personal.templates_view', template_id=template.id))

    label = request.form.get('label', '').strip()
    label_en = request.form.get('label_en', '').strip() or label
    field_type = request.form.get('field_type', 'text')
    field_key = request.form.get('field_key', '').strip()
    is_external = request.form.get('is_external') == '1'
    visible_in_overview = request.form.get('visible_in_overview') == '1'
    width = int(request.form.get('width', 160) or 160)
    options_raw = request.form.get('options', '').strip()

    if not label:
        flash('Bitte eine Feldbezeichnung angeben.', 'warning')
        return redirect(url_for('booking_personal.templates_view', template_id=template.id))

    if not field_key:
        field_key = re.sub(r'[^a-z0-9_]', '', label.lower().replace(' ', '_'))
        if not field_key:
            field_key = f'field_{secrets.token_hex(4)}'

    options = []
    if options_raw and field_type == 'badge_select':
        for line in options_raw.splitlines():
            line = line.strip()
            if line:
                parts = [p.strip() for p in line.split('|')]
                options.append({
                    'value': parts[0],
                    'color': parts[1] if len(parts) > 1 else 'secondary'
                })

    fields = template.get_fields()
    # Eindeutigen Key garantieren
    existing_keys = {f.get('field_key') for f in fields}
    base_key = field_key
    counter = 1
    while field_key in existing_keys:
        field_key = f"{base_key}_{counter}"
        counter += 1

    new_field_def = {
        'field_key': field_key,
        'label': label,
        'label_en': label_en,
        'field_type': field_type,
        'is_external': is_external,
        'is_internal': not is_external,
        'visible_in_overview': visible_in_overview,
        'width': width,
        'options': options,
        'formula_definition': '',
        'help_text': '',
        'is_required': False,
    }
    fields.append(new_field_def)
    template.set_fields(fields)
    db.session.commit()

    flash(f'Spalte „{label}“ erfolgreich zur Vorlage hinzugefügt.', 'success')
    return redirect(url_for('booking_personal.templates_view', template_id=template.id))


@booking_personal_bp.route('/templates/<int:template_id>/field/<int:index>/delete', methods=['POST'])
def template_field_delete(template_id, index):
    """Entfernt ein Feld aus der Vorlage per Index."""
    template = BookingPersonalTemplate.query.get_or_404(template_id)
    if template.is_system_default:
        flash('System-Standardvorlagen können nicht verändert werden.', 'warning')
        return redirect(url_for('booking_personal.templates_view', template_id=template.id))

    fields = template.get_fields()
    if 0 <= index < len(fields):
        removed = fields.pop(index)
        template.set_fields(fields)
        db.session.commit()
        flash(f'Spalte „{removed.get("label", "Spalte")}“ aus Vorlage entfernt.', 'info')
    else:
        flash('Ungültiger Spalten-Index.', 'danger')

    return redirect(url_for('booking_personal.templates_view', template_id=template.id))


@booking_personal_bp.route('/templates/<int:template_id>/delete', methods=['POST'])
def template_delete(template_id):
    """Löscht eine benutzerdefinierte Vorlage."""
    template = BookingPersonalTemplate.query.get_or_404(template_id)
    if template.is_system_default:
        flash('System-Standardvorlagen können nicht gelöscht werden.', 'danger')
        return redirect(url_for('booking_personal.templates_view'))

    name = template.name
    db.session.delete(template)
    db.session.commit()

    flash(f'Vorlage „{name}“ erfolgreich gelöscht.', 'info')
    return redirect(url_for('booking_personal.templates_view'))


@booking_personal_bp.route('/templates/<int:template_id>/apply', methods=['POST'])
def template_apply(template_id):
    """Wendet die Vorlage auf eine ausgewählte Veranstaltung an."""
    template = BookingPersonalTemplate.query.get_or_404(template_id)
    event_id = request.form.get('event_id', type=int)
    if not event_id:
        flash('Bitte eine Veranstaltung auswählen.', 'warning')
        return redirect(url_for('booking_personal.templates_view', template_id=template.id))

    event = BookingPersonalEvent.query.get_or_404(event_id)
    fields_def = template.get_fields()
    if not fields_def:
        flash('Diese Vorlage enthält keine Felder.', 'warning')
        return redirect(url_for('booking_personal.templates_view', template_id=template.id))

    apply_template_to_event(event, fields_def, db.session)
    db.session.commit()

    flash(f'Vorlage „{template.name}“ erfolgreich auf „{event.name}“ angewendet!', 'success')
    return redirect(url_for('booking_personal.index', event_id=event.id))


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
