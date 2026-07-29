from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO
import json

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

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
from app.utils.event_pdf_generator import (
    generate_appointments_overview_pdf,
    generate_event_overview_pdf,
    generate_people_overview_pdf,
    generate_single_event_pdf,
)

events_bp = Blueprint('events', __name__)


def _parse_datetime(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M')


def _refresh_archive_state():
    from app.utils.common import portal_now_naive
    now = portal_now_naive()
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


def _query_appointments(archived=False, assigned_user_id=None, order_desc=False):
    query = (
        EventAppointment.query.options(joinedload(EventAppointment.event))
        .join(Event)
        .filter(Event.is_archived.is_(archived))
    )
    if assigned_user_id is not None:
        assigned_event_ids = (
            db.session.query(EventAssignment.event_id)
            .filter(EventAssignment.user_id == assigned_user_id)
            .distinct()
        )
        query = query.filter(Event.id.in_(assigned_event_ids))
    if order_desc:
        query = query.order_by(EventAppointment.start_time.desc())
    else:
        query = query.order_by(EventAppointment.start_time.asc())
    return query.all()


@events_bp.route('/')
@login_required
@check_module_access('module_events')
def index():
    _refresh_archive_state()
    appointments = _query_appointments(archived=False, order_desc=False)
    return render_template(
        'events/index.html',
        appointments=appointments,
        active_nav='standard',
    )


@events_bp.route('/overview')
@login_required
@check_module_access('module_events')
def overview():
    _refresh_archive_state()
    events = Event.query.filter_by(is_archived=False).order_by(Event.created_at.desc()).all()
    return render_template(
        'events/overview.html',
        events=events,
        active_nav='overview',
    )


@events_bp.route('/mine')
@login_required
@check_module_access('module_events')
def my_events():
    _refresh_archive_state()
    appointments = _query_appointments(
        archived=False,
        assigned_user_id=current_user.id,
        order_desc=False,
    )
    return render_template(
        'events/my_events.html',
        appointments=appointments,
        active_nav='mine',
    )


@events_bp.route('/archive')
@login_required
@check_module_access('module_events')
def archive():
    _refresh_archive_state()
    appointments = _query_appointments(archived=True, order_desc=True)
    return render_template(
        'events/archive.html',
        appointments=appointments,
        active_nav='archive',
    )


@events_bp.route('/people')
@login_required
@check_module_access('module_events')
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
    return render_template(
        'events/people_overview.html',
        rows=rows,
        active_nav='people',
    )


@events_bp.route('/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_events')
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
    appointment_timeline_json_values = req.form.getlist('appointment_timeline_json[]')
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

        timeline_entries = []
        timeline_json_raw = appointment_timeline_json_values[index] if index < len(appointment_timeline_json_values) else ''
        if timeline_json_raw:
            try:
                parsed_entries = json.loads(timeline_json_raw)
                if isinstance(parsed_entries, list):
                    for entry in parsed_entries:
                        if not isinstance(entry, dict):
                            continue
                        time_value = (entry.get('time') or '').strip()
                        what_value = (entry.get('what') or '').strip()
                        person_value = (entry.get('person') or '').strip()
                        if not (time_value or what_value or person_value):
                            continue
                        title_parts = [part for part in [time_value, what_value, person_value] if part]
                        timeline_entries.append({
                            'title': ' | '.join(title_parts),
                            'description': what_value or None,
                        })
            except (ValueError, TypeError, AttributeError):
                timeline_entries = []

        if not timeline_entries:
            timeline_raw = appointment_timeline_values[index] if index < len(appointment_timeline_values) else ''
            timeline_parts = [part.strip() for part in timeline_raw.split('|') if part.strip()]
            for part in timeline_parts:
                timeline_entries.append({'title': part, 'description': part})

        for t_pos, entry in enumerate(timeline_entries, start=1):
            db.session.add(EventTimelineItem(
                event_id=event_obj.id,
                appointment_id=appointment.id,
                position=t_pos,
                title=entry['title'],
                description=entry['description'],
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

    guest_names_json_raw = req.form.get('guest_names_json', '').strip()
    guest_names = []
    if guest_names_json_raw:
        try:
            parsed_guest_names = json.loads(guest_names_json_raw)
            if isinstance(parsed_guest_names, list):
                guest_names.extend(str(item).strip() for item in parsed_guest_names if str(item).strip())
        except (ValueError, TypeError):
            guest_names = []

    if not guest_names:
        guest_names_legacy = req.form.get('guest_names', '')
        guest_names.extend(line.strip() for line in guest_names_legacy.splitlines() if line.strip())
        guest_names.extend(str(value).strip() for value in req.form.getlist('guest_name[]') if str(value).strip())

    for value in guest_names:
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

    manual_contacts = []
    contacts_json_raw = req.form.get('contacts_json', '').strip()
    if contacts_json_raw:
        try:
            parsed_contacts = json.loads(contacts_json_raw)
            if isinstance(parsed_contacts, list):
                for entry in parsed_contacts:
                    if not isinstance(entry, dict):
                        continue
                    name = (entry.get('name') or '').strip()
                    if not name:
                        continue
                    manual_contacts.append({
                        'name': name,
                        'role': (entry.get('role') or '').strip() or None,
                        'phone': (entry.get('phone') or '').strip() or None,
                        'email': (entry.get('email') or '').strip() or None,
                    })
        except (ValueError, TypeError, AttributeError):
            manual_contacts = []

    if not manual_contacts:
        for contact_line in req.form.get('contacts_text', '').splitlines():
            parts = [p.strip() for p in contact_line.split('|')]
            if not parts or not parts[0]:
                continue
            manual_contacts.append({
                'name': parts[0],
                'role': parts[1] if len(parts) > 1 and parts[1] else None,
                'phone': parts[2] if len(parts) > 2 and parts[2] else None,
                'email': parts[3] if len(parts) > 3 and parts[3] else None,
            })

    for contact_entry in manual_contacts:
        manual_key = (
            contact_entry['name'].lower(),
            (contact_entry['phone'] or '').strip(),
            (contact_entry['email'] or '').strip().lower(),
        )
        if manual_key in existing_contact_keys:
            continue
        existing_contact_keys.add(manual_key)
        db.session.add(EventContact(
            event_id=event_obj.id,
            name=contact_entry['name'],
            role=contact_entry['role'],
            phone=contact_entry['phone'],
            email=contact_entry['email'],
        ))


@events_bp.route('/<int:event_id>')
@login_required
@check_module_access('module_events')
def view_event(event_id):
    _refresh_archive_state()
    event_obj = Event.query.get_or_404(event_id)
    conflicts = _serialize_conflicts(event_obj)
    return render_template('events/view.html', event=event_obj, conflicts=conflicts)


@events_bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
@check_module_access('module_events')
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
@check_module_access('module_events')
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
@check_module_access('module_events')
def overview_pdf():
    """PDF-Übersicht für den aktuellen Reiter (view=standard|overview|mine|archive|people)."""
    _refresh_archive_state()
    view = (request.args.get('view') or 'overview').strip().lower()
    from app.utils.common import portal_now_naive
    now = portal_now_naive()

    if view == 'standard':
        appointments = _query_appointments(archived=False, order_desc=False)
        pdf_buffer = generate_appointments_overview_pdf(appointments, title='Standardübersicht')
        download_name = 'Veranstaltungen_Standarduebersicht.pdf'
    elif view == 'mine':
        appointments = _query_appointments(
            archived=False,
            assigned_user_id=current_user.id,
            order_desc=False,
        )
        pdf_buffer = generate_appointments_overview_pdf(appointments, title='Meine Veranstaltungen')
        download_name = 'Veranstaltungen_Meine.pdf'
    elif view == 'archive':
        appointments = _query_appointments(archived=True, order_desc=True)
        pdf_buffer = generate_appointments_overview_pdf(appointments, title='Archiv')
        download_name = 'Veranstaltungen_Archiv.pdf'
    elif view == 'people':
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
        pdf_buffer = generate_people_overview_pdf(rows, title='Personenübersicht')
        download_name = 'Veranstaltungen_Personen.pdf'
    else:
        events = Event.query.filter_by(is_archived=False).order_by(Event.created_at.desc()).all()
        pdf_buffer = generate_event_overview_pdf(events, now=now, title='Veranstaltungsübersicht')
        download_name = 'Veranstaltungen_Uebersicht.pdf'

    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=download_name,
    )


@events_bp.route('/<int:event_id>/conflicts')
@login_required
@check_module_access('module_events')
def event_conflicts(event_id):
    event_obj = Event.query.get_or_404(event_id)
    return jsonify(_serialize_conflicts(event_obj))


@events_bp.route('/appointment/<int:appointment_id>/scanner')
@login_required
@check_module_access('module_inventory')
def appointment_scanner(appointment_id):
    """Öffnet Inventar-Ausleihe mit vorausgefülltem Projekt/Verantwortlichem."""
    appointment = EventAppointment.query.options(
        joinedload(EventAppointment.event).joinedload(Event.assignments).joinedload(EventAssignment.user),
        joinedload(EventAppointment.inventory_needs),
    ).get_or_404(appointment_id)
    event_obj = appointment.event
    if not event_obj:
        flash('Veranstaltung zum Termin nicht gefunden.', 'danger')
        return redirect(url_for('events.index'))

    project_name = f'{event_obj.name} - {appointment.label}'.strip(' -')

    borrower_id = None
    borrower_name = ''
    contact_email = ''

    assignments = list(event_obj.assignments or [])
    portal_assignments = [a for a in assignments if a.user_id and a.user]
    # Bevorzugt aktuelle Person, falls zugeteilt
    preferred = next((a for a in portal_assignments if a.user_id == current_user.id), None)
    chosen = preferred or (portal_assignments[0] if portal_assignments else None)
    if chosen and chosen.user:
        borrower_id = chosen.user.id
        borrower_name = chosen.user.full_name
        contact_email = chosen.user.email or ''
    else:
        guest = next((a for a in assignments if (a.display_name or '').strip()), None)
        if guest:
            borrower_name = guest.display_name.strip()
        elif event_obj.owner:
            borrower_id = event_obj.owner.id
            borrower_name = event_obj.owner.full_name
            contact_email = event_obj.owner.email or ''
        else:
            borrower_id = current_user.id
            borrower_name = current_user.full_name
            contact_email = current_user.email or ''

    # Materialbedarf in den Warenkorb legen (nur verfügbare Artikel)
    cart = list(session.get('borrow_cart', []) or [])
    added = 0
    for need in appointment.inventory_needs or []:
        product = Product.query.get(need.product_id)
        if not product or product.status != 'available':
            continue
        if product.id not in cart:
            cart.append(product.id)
            added += 1
    session['borrow_cart'] = cart
    session.modified = True

    if added:
        flash(f'{added} Artikel aus dem Materialbedarf in den Warenkorb gelegt.', 'info')
    flash(f'Ausleihe für „{project_name}“ vorbereitet – bitte Von/Bis setzen und Artikel scannen.', 'success')

    return redirect(url_for(
        'inventory.inventory_checkout',
        event_name=project_name,
        borrower_name=borrower_name,
        borrower_id=borrower_id or '',
        contact_email=contact_email,
        event_id=event_obj.id,
        event_appointment_id=appointment.id,
    ))
