from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.models.calendar import CalendarEvent
from app.models.contact import Contact
from app.models.event import (
    Event,
    EventAppointment,
    EventAssignment,
    EventContact,
    EventInventoryNeed,
    EventTimelineItem,
)
from app.models.file import Folder
from app.models.inventory import Product
from app.models.user import User
from app.services.event_service import EventService
from app.utils.access_control import check_module_access
from app.utils.event_pdf_generator import generate_event_overview_pdf, generate_single_event_pdf

events_bp = Blueprint('events', __name__)


def _parse_datetime(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M')


def _refresh_archive_state():
    now = datetime.utcnow()
    events = Event.query.all()
    changed = False
    for event_obj in events:
        has_future = any(appointment.end_time >= now for appointment in event_obj.appointments)
        should_archive = not has_future
        if event_obj.is_archived != should_archive:
            event_obj.is_archived = should_archive
            event_obj.archived_at = now if should_archive else None
            changed = True
    if changed:
        db.session.commit()


def _serialize_conflicts(event_obj):
    person_conflicts = []
    inventory_conflicts = []

    assigned_user_ids = {a.user_id for a in event_obj.assignments if a.user_id}
    for appointment in event_obj.appointments:
        overlapping_appointments = (
            EventAppointment.query.join(Event)
            .filter(
                EventAppointment.id != appointment.id,
                EventAppointment.start_time < appointment.end_time,
                EventAppointment.end_time > appointment.start_time,
            )
            .all()
        )
        if overlapping_appointments:
            overlap_event_ids = {a.event_id for a in overlapping_appointments}
            overlap_assignments = EventAssignment.query.filter(
                EventAssignment.event_id.in_(overlap_event_ids),
                EventAssignment.user_id.in_(assigned_user_ids),
            ).all()
            for assignment in overlap_assignments:
                person_conflicts.append({
                    'appointment': appointment.label,
                    'user': assignment.user.full_name if assignment.user else assignment.display_name,
                    'other_event_id': assignment.event_id,
                })

        for need in appointment.inventory_needs:
            concurrent_needs = (
                EventInventoryNeed.query.join(EventAppointment)
                .filter(
                    EventInventoryNeed.id != need.id,
                    EventInventoryNeed.product_id == need.product_id,
                    EventAppointment.start_time < appointment.end_time,
                    EventAppointment.end_time > appointment.start_time,
                )
                .all()
            )
            if concurrent_needs:
                inventory_conflicts.append({
                    'appointment': appointment.label,
                    'product': need.product.name if need.product else f'Produkt {need.product_id}',
                    'requested_quantity': need.quantity,
                    'parallel_uses': len(concurrent_needs),
                })

    return {
        'person_conflicts': person_conflicts,
        'inventory_conflicts': inventory_conflicts,
    }


@events_bp.route('/')
@login_required
@check_module_access('module_calendar')
def index():
    _refresh_archive_state()
    events = Event.query.filter_by(is_archived=False).order_by(Event.created_at.desc()).all()
    return render_template('events/index.html', events=events)


@events_bp.route('/mine')
@login_required
@check_module_access('module_calendar')
def my_events():
    _refresh_archive_state()
    assigned_event_ids = (
        db.session.query(EventAssignment.event_id)
        .filter(EventAssignment.user_id == current_user.id)
        .distinct()
        .all()
    )
    assigned_event_ids = [row[0] for row in assigned_event_ids]
    events = (
        Event.query.filter(Event.id.in_(assigned_event_ids), Event.is_archived.is_(False)).order_by(Event.created_at.desc()).all()
        if assigned_event_ids else []
    )
    return render_template('events/my_events.html', events=events)


@events_bp.route('/archive')
@login_required
@check_module_access('module_calendar')
def archive():
    _refresh_archive_state()
    events = Event.query.filter_by(is_archived=True).order_by(Event.archived_at.desc(), Event.created_at.desc()).all()
    return render_template('events/archive.html', events=events)


@events_bp.route('/people')
@login_required
@check_module_access('module_calendar')
def people_overview():
    _refresh_archive_state()
    counts = defaultdict(int)
    users = {u.id: u for u in User.query.filter_by(is_active=True).all()}
    assignments = (
        EventAssignment.query.join(Event)
        .filter(EventAssignment.user_id.isnot(None), Event.is_archived.is_(False))
        .all()
    )
    for assignment in assignments:
        counts[assignment.user_id] += 1
    rows = [
        {'user': users[user_id], 'event_count': count}
        for user_id, count in counts.items()
        if user_id in users
    ]
    rows.sort(key=lambda x: x['event_count'], reverse=True)
    return render_template('events/people_overview.html', rows=rows)


@events_bp.route('/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_calendar')
def create_event():
    users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    contacts = Contact.query.order_by(Contact.name).all()
    folders = Folder.query.order_by(Folder.name).all()
    products = Product.query.order_by(Product.name).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Name ist erforderlich.', 'danger')
            return render_template('events/create.html', users=users, contacts=contacts, folders=folders, products=products)

        event_obj = Event(
            name=name,
            description=request.form.get('description', '').strip() or None,
            default_location=request.form.get('default_location', '').strip() or None,
            folder_id=request.form.get('folder_id') or None,
            owner_id=current_user.id,
            created_by=current_user.id,
        )
        db.session.add(event_obj)
        db.session.flush()

        _store_form_data(event_obj, request)
        EventService.sync_calendar_for_event(event_obj, current_user.id)
        db.session.commit()
        flash('Veranstaltung erstellt.', 'success')
        return redirect(url_for('events.view_event', event_id=event_obj.id))

    return render_template('events/create.html', users=users, contacts=contacts, folders=folders, products=products)


def _store_form_data(event_obj, req):
    old_calendar_event_ids = set()
    existing_appointments = EventAppointment.query.filter_by(event_id=event_obj.id).all()
    for appointment in existing_appointments:
        if appointment.calendar_event_id:
            old_calendar_event_ids.add(appointment.calendar_event_id)
        db.session.delete(appointment)

    # Verwaiste Kalendertermine aus vorherigen Ständen entfernen.
    # Danach erzeugt EventService die aktuellen Termine neu.
    if old_calendar_event_ids:
        stale_calendar_events = CalendarEvent.query.filter(CalendarEvent.id.in_(old_calendar_event_ids)).all()
        for calendar_event in stale_calendar_events:
            db.session.delete(calendar_event)

    EventAssignment.query.filter_by(event_id=event_obj.id).delete()
    EventContact.query.filter_by(event_id=event_obj.id).delete()
    EventTimelineItem.query.filter_by(event_id=event_obj.id).delete()

    labels = req.form.getlist('appointment_label[]')
    starts = req.form.getlist('appointment_start[]')
    ends = req.form.getlist('appointment_end[]')
    locations = req.form.getlist('appointment_location[]')
    descriptions = req.form.getlist('appointment_description[]')
    appointment_timeline_values = req.form.getlist('appointment_timeline[]')
    needs_products = req.form.getlist('needs_product[]')
    needs_quantities = req.form.getlist('needs_quantity[]')

    created_appointments = []
    for index, label in enumerate(labels):
        label = (label or '').strip()
        start_raw = starts[index] if index < len(starts) else ''
        end_raw = ends[index] if index < len(ends) else ''
        if not label or not start_raw or not end_raw:
            continue
        appointment = EventAppointment(
            event_id=event_obj.id,
            label=label,
            description=(descriptions[index] if index < len(descriptions) else '').strip() or None,
            start_time=_parse_datetime(start_raw),
            end_time=_parse_datetime(end_raw),
            location=(locations[index] if index < len(locations) else '').strip() or None,
        )
        db.session.add(appointment)
        db.session.flush()
        created_appointments.append(appointment)

        timeline_raw = appointment_timeline_values[index] if index < len(appointment_timeline_values) else ''
        timeline_parts = [part.strip() for part in timeline_raw.split('|') if part.strip()]
        for t_pos, title in enumerate(timeline_parts, start=1):
            db.session.add(EventTimelineItem(
                event_id=event_obj.id,
                appointment_id=appointment.id,
                position=t_pos,
                title=title,
            ))

    # Materialbedarf wird dem ersten Termin zugeordnet (warnend, nicht blockierend).
    if created_appointments:
        base_appointment = created_appointments[0]
        for p_idx, product_id in enumerate(needs_products):
            if not product_id:
                continue
            qty_raw = needs_quantities[p_idx] if p_idx < len(needs_quantities) else '1'
            try:
                qty = max(1, int(qty_raw or 1))
                parsed_product_id = int(product_id)
            except (TypeError, ValueError):
                continue
            db.session.add(EventInventoryNeed(appointment_id=base_appointment.id, product_id=parsed_product_id, quantity=qty))

    for user_id in req.form.getlist('participant_user_ids'):
        if user_id:
            db.session.add(EventAssignment(event_id=event_obj.id, user_id=int(user_id)))

    guest_names = req.form.get('guest_names', '')
    for line in guest_names.splitlines():
        value = line.strip()
        if value:
            db.session.add(EventAssignment(event_id=event_obj.id, display_name=value))

    existing_contact_keys = set()
    selected_contact_ids = req.form.getlist('contact_ids')
    if selected_contact_ids:
        for contact in Contact.query.filter(Contact.id.in_(selected_contact_ids)).all():
            contact_key = (
                (contact.name or '').strip().lower(),
                (contact.phone or '').strip(),
                (contact.email or '').strip().lower(),
            )
            existing_contact_keys.add(contact_key)
            db.session.add(EventContact(
                event_id=event_obj.id,
                name=contact.name,
                role=None,
                phone=contact.phone,
                email=contact.email,
            ))

    for contact_line in req.form.get('contacts_text', '').splitlines():
        parts = [p.strip() for p in contact_line.split('|')]
        if not parts or not parts[0]:
            continue
        manual_key = (
            parts[0].lower(),
            parts[2] if len(parts) > 2 and parts[2] else '',
            (parts[3] if len(parts) > 3 and parts[3] else '').lower(),
        )
        if manual_key in existing_contact_keys:
            continue
        existing_contact_keys.add(manual_key)
        db.session.add(EventContact(
            event_id=event_obj.id,
            name=parts[0],
            role=parts[1] if len(parts) > 1 and parts[1] else None,
            phone=parts[2] if len(parts) > 2 and parts[2] else None,
            email=parts[3] if len(parts) > 3 and parts[3] else None,
        ))

    start_pos = len(created_appointments) * 100
    for pos, line in enumerate(req.form.get('timeline_text', '').splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        db.session.add(EventTimelineItem(
            event_id=event_obj.id,
            position=start_pos + pos,
            title=line,
        ))


@events_bp.route('/<int:event_id>')
@login_required
@check_module_access('module_calendar')
def view_event(event_id):
    _refresh_archive_state()
    event_obj = Event.query.get_or_404(event_id)
    conflicts = _serialize_conflicts(event_obj)
    return render_template('events/view.html', event=event_obj, conflicts=conflicts)


@events_bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
@check_module_access('module_calendar')
def edit_event(event_id):
    _refresh_archive_state()
    event_obj = Event.query.get_or_404(event_id)
    users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    contacts = Contact.query.order_by(Contact.name).all()
    folders = Folder.query.order_by(Folder.name).all()
    products = Product.query.order_by(Product.name).all()

    if request.method == 'POST':
        event_obj.name = request.form.get('name', '').strip()
        event_obj.description = request.form.get('description', '').strip() or None
        event_obj.default_location = request.form.get('default_location', '').strip() or None
        event_obj.folder_id = request.form.get('folder_id') or None
        _store_form_data(event_obj, request)
        EventService.sync_calendar_for_event(event_obj, current_user.id)
        db.session.commit()
        flash('Veranstaltung aktualisiert.', 'success')
        return redirect(url_for('events.view_event', event_id=event_obj.id))

    return render_template('events/edit.html', event=event_obj, users=users, contacts=contacts, folders=folders, products=products)


@events_bp.route('/<int:event_id>/pdf')
@login_required
@check_module_access('module_calendar')
def event_pdf(event_id):
    event_obj = Event.query.get_or_404(event_id)
    pdf_buffer = generate_single_event_pdf(event_obj)
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Veranstaltung_{event_obj.id}.pdf',
    )


@events_bp.route('/pdf-overview')
@login_required
@check_module_access('module_calendar')
def overview_pdf():
    _refresh_archive_state()
    now = datetime.utcnow()
    events = Event.query.filter_by(is_archived=False).order_by(Event.created_at.desc()).all()
    pdf_buffer = generate_event_overview_pdf(events, now=now)
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='Veranstaltungen_Uebersicht.pdf',
    )


@events_bp.route('/<int:event_id>/conflicts')
@login_required
@check_module_access('module_calendar')
def event_conflicts(event_id):
    event_obj = Event.query.get_or_404(event_id)
    return jsonify(_serialize_conflicts(event_obj))


@events_bp.route('/appointment/<int:appointment_id>/scanner')
@login_required
@check_module_access('module_inventory')
def appointment_scanner(appointment_id):
    appointment = EventAppointment.query.get_or_404(appointment_id)
    flash(f'QR-Scanner für Termin "{appointment.label}" geöffnet.', 'info')
    return redirect(url_for('inventory.borrow_scanner'))
