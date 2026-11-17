import os
from datetime import datetime
from flask import render_template, request, jsonify, flash, redirect, url_for, current_app, abort
from werkzeug.utils import secure_filename
from app import db
from app.models.booking_personal import (
    BookingPersonalEvent,
    BookingPersonalEntry,
    BookingPersonalField,
    BookingPersonalFile,
)
from app.utils.booking_personal_presets import infer_category
from . import booking_personal_bp
from .mail import get_available_placeholders, render_template_string


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'pdf', 'zip', 'doc', 'docx'}
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

CATEGORY_EN_MAP = {
    'Stammdaten & Status': 'Basic Information & Status',
    'Finanzen': 'Finances & Compensation',
    'Hospitality & Logistik': 'Hospitality & Logistics',
    'Presse & Technik': 'Media, Press & Technical Rider',
}

STATUS_EN_MAP = {
    'Angefragt': 'Requested',
    'Bewerbung eingegangen': 'Application Received',
    'Formular gesendet': 'Form Sent',
    'Formular ausgefüllt': 'Form Submitted',
    'Zusage gesendet': 'Confirmed Booking',
    'Abgeschlossen': 'Completed',
    'Rechnung weitergeleitet': 'Invoice Forwarded',
    'Absage': 'Declined',
}


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@booking_personal_bp.route('/form/<token>', methods=['GET'])
def public_form(token):
    """Öffentliches Künstler-Formular für einen Act."""
    entry = BookingPersonalEntry.query.filter_by(form_token=token).first_or_404()
    event = entry.event

    # Sprachauswahl (Standard: de)
    lang = request.args.get('lang', 'de').lower()
    if lang not in ('de', 'en'):
        lang = 'de'

    # Alle extern ausfüllbaren Felder
    external_fields = [f for f in event.fields if f.is_external]
    custom_data = entry.get_custom_data()

    fields_by_category = {}
    for f in external_fields:
        cat = f.category or infer_category(f.field_key)
        fields_by_category.setdefault(cat, []).append(f)

    submitted = request.args.get('submitted') == '1'

    placeholders = get_available_placeholders(event, entry)
    raw_intro = event.form_intro_text_en if lang == 'en' else event.form_intro_text
    form_intro = render_template_string(raw_intro or '', placeholders)

    return render_template(
        'booking_personal/public_form.html',
        event=event,
        entry=entry,
        external_fields=external_fields,
        fields_by_category=fields_by_category,
        category_en_map=CATEGORY_EN_MAP,
        custom_data=custom_data,
        submitted=submitted,
        lang=lang,
        form_intro=form_intro,
    )


@booking_personal_bp.route('/form/<token>/submit', methods=['POST'])
def public_form_submit(token):
    """Verarbeitet die Antworten des externen Künstler-Formulars."""
    entry = BookingPersonalEntry.query.filter_by(form_token=token).first_or_404()
    event = entry.event

    external_fields = [f for f in event.fields if f.is_external]
    custom_data = entry.get_custom_data()

    upload_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'booking_personal', str(event.id))
    os.makedirs(upload_dir, exist_ok=True)

    for field in external_fields:
        f_key = field.field_key
        f_type = field.field_type

        if f_type in ('file_upload', 'image_upload'):
            # Prüfe ob Datei hochgeladen wurde
            files = request.files.getlist(f_key)
            uploaded_paths = custom_data.get(f_key, [])
            if not isinstance(uploaded_paths, list):
                uploaded_paths = [uploaded_paths] if uploaded_paths else []

            for file_item in files:
                if file_item and file_item.filename and _allowed_file(file_item.filename):
                    filename = secure_filename(f"{entry.id}_{f_key}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file_item.filename}")
                    save_path = os.path.join(upload_dir, filename)
                    file_item.save(save_path)
                    rel_url = f"/uploads/booking_personal/{event.id}/{filename}"
                    uploaded_paths.append(rel_url)

                    is_img = file_item.filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS
                    db_file = BookingPersonalFile(
                        entry_id=entry.id,
                        field_key=f_key,
                        file_path=rel_url,
                        file_name=file_item.filename,
                        is_image=is_img,
                        mime_type=file_item.mimetype,
                    )
                    db.session.add(db_file)

            if uploaded_paths:
                custom_data[f_key] = uploaded_paths
        elif f_type == 'multi_select':
            vals = request.form.getlist(f_key)
            custom_data[f_key] = vals
        else:
            val = request.form.get(f_key)
            if val is not None:
                custom_data[f_key] = val.strip()

    # Aktualisiere Basis-Felder falls im Formular
    if 'contact_name' in custom_data and custom_data['contact_name']:
        if not entry.name:
            entry.name = custom_data['contact_name']
    if 'mail' in custom_data and custom_data['mail']:
        entry.email = custom_data['mail']
    if 'phone' in custom_data and custom_data['phone']:
        entry.phone = custom_data['phone']

    entry.set_custom_data(custom_data)
    entry.form_submitted_at = datetime.utcnow()
    # Status aktualisieren falls noch auf 'Angefragt' oder 'Formular gesendet'
    if entry.status in ('Angefragt', 'Formular gesendet'):
        entry.status = 'Formular ausgefüllt'

    # Formelfelder neu berechnen
    entry.compute_formula_values(event.fields)

    db.session.commit()

    if request.is_json:
        return jsonify({'success': True, 'message': 'Vielen Dank! Deine Angaben wurden gespeichert.'})

    lang = request.args.get('lang', 'de')
    return redirect(url_for('booking_personal.public_form', token=token, submitted='1', lang=lang))


@booking_personal_bp.route('/overview/<token>', methods=['GET'])
def public_overview(token):
    """Zweisprachige (DE/EN) schreibgeschützte Zusage-Übersicht für den Künstler."""
    entry = BookingPersonalEntry.query.filter_by(overview_token=token).first_or_404()
    event = entry.event

    # Sprachauswahl (Standard: de)
    lang = request.args.get('lang', 'de').lower()
    if lang not in ('de', 'en'):
        lang = 'de'

    overview_fields = [f for f in event.fields if f.visible_in_overview]
    custom_data = entry.get_custom_data()

    # Berechne Formelwerte für korrekte Summen
    entry.compute_formula_values(event.fields)

    fields_by_category = {}
    for f in overview_fields:
        cat = f.category or infer_category(f.field_key)
        fields_by_category.setdefault(cat, []).append(f)

    placeholders = get_available_placeholders(event, entry)
    raw_intro = event.overview_intro_text_en if lang == 'en' else event.overview_intro_text
    overview_intro = render_template_string(raw_intro or '', placeholders)

    return render_template(
        'booking_personal/public_overview.html',
        event=event,
        entry=entry,
        overview_fields=overview_fields,
        fields_by_category=fields_by_category,
        category_en_map=CATEGORY_EN_MAP,
        status_en_map=STATUS_EN_MAP,
        custom_data=custom_data,
        lang=lang,
        overview_intro=overview_intro,
    )


@booking_personal_bp.route('/apply/<token>', methods=['GET'])
def public_apply(token):
    """Öffentliches Anmelde- / Bewerbungsformular für eine Veranstaltung."""
    event = BookingPersonalEvent.query.filter_by(apply_token=token).first()
    if not event or not event.is_active:
        abort(404)

    # Sprachauswahl (Standard: de)
    lang = request.args.get('lang', 'de').lower()
    if lang not in ('de', 'en'):
        lang = 'de'

    # Relevante Felder für die Bewerbung (alle externen Felder oder Basis-Felder)
    apply_fields = [f for f in event.fields if f.is_external]
    if not apply_fields:
        apply_fields = [
            f for f in event.fields
            if f.field_key in (
                'project_name', 'contact_name', 'mail', 'phone', 'pronouns',
                'promotext', 'promo_pictures', 'techrider_djs', 'techrider_other',
                'soundcloud', 'instagram'
            )
        ]

    fields_by_category = {}
    for f in apply_fields:
        cat = f.category or infer_category(f.field_key)
        fields_by_category.setdefault(cat, []).append(f)

    submitted = request.args.get('submitted') == '1'

    placeholders = {'event_name': event.name or 'Veranstaltung'}
    raw_intro = event.apply_intro_text_en if lang == 'en' else event.apply_intro_text
    apply_intro = render_template_string(raw_intro or '', placeholders)

    return render_template(
        'booking_personal/public_apply.html',
        event=event,
        apply_fields=apply_fields,
        fields_by_category=fields_by_category,
        category_en_map=CATEGORY_EN_MAP,
        submitted=submitted,
        lang=lang,
        apply_intro=apply_intro,
    )


@booking_personal_bp.route('/apply/<token>/submit', methods=['POST'])
def public_apply_submit(token):
    """Verarbeitet eine neue Bewerbung / Anmeldung und legt einen neuen Act an."""
    event = BookingPersonalEvent.query.filter_by(apply_token=token).first()
    if not event or not event.is_active:
        abort(404)

    apply_fields = [f for f in event.fields if f.is_external]
    if not apply_fields:
        apply_fields = [
            f for f in event.fields
            if f.field_key in (
                'project_name', 'contact_name', 'mail', 'phone', 'pronouns',
                'promotext', 'promo_pictures', 'techrider_djs', 'techrider_other',
                'soundcloud', 'instagram'
            )
        ]

    # Neuen Eintrag in der Veranstaltung erzeugen
    entry_name = (
        request.form.get('project_name') or
        request.form.get('auftrittsname_projektname') or
        request.form.get('contact_name') or
        'Neuer Bewerber'
    ).strip()

    email_val = (request.form.get('mail') or request.form.get('email') or '').strip()
    phone_val = (request.form.get('phone') or request.form.get('telefonnummer') or '').strip()

    entry = BookingPersonalEntry(
        event_id=event.id,
        name=entry_name,
        email=email_val,
        phone=phone_val,
        status='Bewerbung eingegangen'
    )
    db.session.add(entry)
    db.session.flush()

    custom_data = {}
    upload_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'booking_personal', str(event.id))
    os.makedirs(upload_dir, exist_ok=True)

    for field in apply_fields:
        f_key = field.field_key
        f_type = field.field_type

        if f_type in ('file_upload', 'image_upload'):
            files = request.files.getlist(f_key)
            uploaded_paths = []
            for file_item in files:
                if file_item and file_item.filename and _allowed_file(file_item.filename):
                    filename = secure_filename(f"{entry.id}_{f_key}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file_item.filename}")
                    save_path = os.path.join(upload_dir, filename)
                    file_item.save(save_path)
                    rel_url = f"/uploads/booking_personal/{event.id}/{filename}"
                    uploaded_paths.append(rel_url)

                    is_img = file_item.filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS
                    db_file = BookingPersonalFile(
                        entry_id=entry.id,
                        field_key=f_key,
                        file_path=rel_url,
                        file_name=file_item.filename,
                        is_image=is_img,
                        mime_type=file_item.mimetype,
                    )
                    db.session.add(db_file)

            if uploaded_paths:
                custom_data[f_key] = uploaded_paths
        elif f_type == 'multi_select':
            vals = request.form.getlist(f_key)
            custom_data[f_key] = vals
        else:
            val = request.form.get(f_key)
            if val is not None:
                custom_data[f_key] = val.strip()

    # Alle übermittelten Formularwerte erfassen
    for k, v in request.form.items():
        if k not in custom_data and v is not None:
            custom_data[k] = v.strip()

    if entry_name:
        custom_data['project_name'] = entry_name
        custom_data['auftrittsname_projektname'] = entry_name
    if email_val:
        custom_data['mail'] = email_val
    if phone_val:
        custom_data['phone'] = phone_val
    custom_data['status_booking'] = 'Bewerbung eingegangen'

    entry.set_custom_data(custom_data)
    entry.form_submitted_at = datetime.utcnow()
    entry.compute_formula_values(event.fields)

    db.session.commit()

    if request.is_json:
        return jsonify({'success': True, 'message': 'Vielen Dank für deine Bewerbung!'})

    lang = request.args.get('lang', 'de')
    return redirect(url_for('booking_personal.public_apply', token=token, submitted='1', lang=lang))

