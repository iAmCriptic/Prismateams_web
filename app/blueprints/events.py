from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO
import json

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app import db
from app.models.calendar import CalendarEvent
from app.models.contact import Contact
from app.utils.module_visibility import accessible_query
from app.models.event import (
    Event,
    EventDay,
    EventAppointment,
    EventAssignment,
    EventContact,
    EventInventoryNeed,
    EventTimelineItem,
    EventTodoList,
    EventTodoItem,
    EventBookingPersonalLink,
    EventCustomField,
    EventCustomFieldValue,
)
from app.models.file import Folder
from app.utils.private_files import can_view_folder
from app.models.inventory import Product
from app.models.user import User
from app.services.event_service import EventService
from app.utils.access_control import check_module_access, has_module_access
from app.utils.common import is_module_enabled
from app.utils.event_pdf_generator import (
    generate_appointments_overview_pdf,
    generate_event_overview_pdf,
    generate_people_overview_pdf,
    generate_single_event_pdf,
)

events_bp = Blueprint('events', __name__)


def _parse_datetime(value):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        from dateutil import parser
        return parser.parse(value)
    except Exception:
        return None


def _parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ('%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _parse_time(value):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            pass
    return None


def _refresh_archive_state():
    from app.utils.common import portal_now_naive
    now = portal_now_naive()
    events = Event.query.all()
    changed = False
    for event_obj in events:
        if event_obj.appointments:
            has_future = any(appointment.end_time >= now for appointment in event_obj.appointments)
            should_archive = not has_future
        else:
            # Veranstaltungen ohne Termine sind in Planung und sollen nicht archiviert werden
            should_archive = False
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
        query = query.filter(
            or_(
                Event.id.in_(assigned_event_ids),
                Event.owner_id == assigned_user_id,
                Event.created_by == assigned_user_id,
            )
        )
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
    contacts = []
    if is_module_enabled('module_contacts') and has_module_access(current_user, 'module_contacts'):
        contacts = accessible_query(current_user, Contact, 'contacts').order_by(Contact.name).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Name ist erforderlich.', 'danger')
            return render_template('events/create.html', users=users, contacts=contacts)

        mode = request.form.get('event_mode', 'single')
        is_multiday = (mode == 'multi')
        default_location = request.form.get('default_location', '').strip() or None
        description = request.form.get('description', '').strip() or None

        owner_raw = request.form.get('owner_id')
        owner_id = int(owner_raw) if owner_raw and owner_raw.isdigit() else current_user.id

        start_time_raw = request.form.get('start_time', '').strip() or '10:00'
        end_time_raw = request.form.get('end_time', '').strip() or '18:00'

        try:
            start_t = datetime.strptime(start_time_raw, '%H:%M').time()
        except ValueError:
            start_t = datetime.strptime('10:00', '%H:%M').time()
        try:
            end_t = datetime.strptime(end_time_raw, '%H:%M').time()
        except ValueError:
            end_t = datetime.strptime('18:00', '%H:%M').time()

        if is_multiday:
            day_dates = request.form.getlist('multi_day_date[]')
            day_starts = request.form.getlist('multi_day_start[]')
            day_ends = request.form.getlist('multi_day_end[]')
            day_locations = request.form.getlist('multi_day_location[]')
            day_labels = request.form.getlist('multi_day_label[]')

            parsed_days = []
            for idx, d_str in enumerate(day_dates):
                d_val = _parse_date(d_str)
                if not d_val:
                    continue
                s_str = day_starts[idx].strip() if idx < len(day_starts) and day_starts[idx].strip() else '10:00'
                e_str = day_ends[idx].strip() if idx < len(day_ends) and day_ends[idx].strip() else '18:00'
                try:
                    s_t = datetime.strptime(s_str, '%H:%M').time()
                except ValueError:
                    s_t = datetime.strptime('10:00', '%H:%M').time()
                try:
                    e_t = datetime.strptime(e_str, '%H:%M').time()
                except ValueError:
                    e_t = datetime.strptime('18:00', '%H:%M').time()
                loc = day_locations[idx].strip() if idx < len(day_locations) and day_locations[idx].strip() else default_location
                lbl = day_labels[idx].strip() if idx < len(day_labels) and day_labels[idx].strip() else None
                parsed_days.append({
                    'date': d_val,
                    'start_time': s_t,
                    'end_time': e_t,
                    'location': loc,
                    'label': lbl,
                })

            if not parsed_days:
                # Fallback falls keine Datums-Slots angegeben wurden
                start_d_raw = request.form.get('start_date', '').strip()
                end_d_raw = request.form.get('end_date', '').strip()
                start_d = _parse_date(start_d_raw) or datetime.utcnow().date()
                end_d = _parse_date(end_d_raw) or (start_d + timedelta(days=1))
                if end_d < start_d:
                    start_d, end_d = end_d, start_d
                cur = start_d
                while cur <= end_d:
                    parsed_days.append({
                        'date': cur,
                        'start_time': start_t,
                        'end_time': end_t,
                        'location': default_location,
                        'label': None,
                    })
                    cur += timedelta(days=1)

            parsed_days.sort(key=lambda x: x['date'])
            start_d = parsed_days[0]['date']
            end_d = parsed_days[-1]['date']

            event_obj = Event(
                name=name,
                description=description,
                default_location=default_location,
                is_multiday=True,
                start_date=start_d,
                end_date=end_d,
                owner_id=owner_id,
                created_by=current_user.id,
            )
            db.session.add(event_obj)
            db.session.flush()

            for day_idx, p_day in enumerate(parsed_days, start=1):
                day_obj = EventDay(
                    event_id=event_obj.id,
                    day_number=day_idx,
                    date=p_day['date'],
                    start_time=p_day['start_time'],
                    end_time=p_day['end_time'],
                    location=p_day['location'],
                    label=p_day['label'] or f"Tag {day_idx}",
                )
                db.session.add(day_obj)
                db.session.flush()

                appt_start = datetime.combine(p_day['date'], p_day['start_time'])
                appt_end = datetime.combine(p_day['date'], p_day['end_time'])
                if appt_end <= appt_start:
                    appt_end = appt_start + timedelta(hours=2)

                appointment = EventAppointment(
                    event=event_obj,
                    day=day_obj,
                    label=f"{name} - {day_obj.label}",
                    start_time=appt_start,
                    end_time=appt_end,
                    location=p_day['location'] or default_location,
                )
                db.session.add(appointment)
        else:
            event_d_raw = request.form.get('event_date', '').strip()
            event_d = _parse_date(event_d_raw) or datetime.utcnow().date()

            event_obj = Event(
                name=name,
                description=description,
                default_location=default_location,
                is_multiday=False,
                start_date=event_d,
                end_date=event_d,
                owner_id=owner_id,
                created_by=current_user.id,
            )
            db.session.add(event_obj)
            db.session.flush()

            day_obj = EventDay(
                event_id=event_obj.id,
                day_number=1,
                date=event_d,
                start_time=start_t,
                end_time=end_t,
                location=default_location,
                label="Haupttermin",
            )
            db.session.add(day_obj)
            db.session.flush()

            appt_start = datetime.combine(event_d, start_t)
            appt_end = datetime.combine(event_d, end_t)
            if appt_end <= appt_start:
                appt_end = appt_start + timedelta(hours=2)

            appointment = EventAppointment(
                event=event_obj,
                day=day_obj,
                label=name,
                start_time=appt_start,
                end_time=appt_end,
                location=default_location,
            )
            db.session.add(appointment)

        # Ansprechpartner aus Formular erfassen (falls angegeben)
        contact_id = request.form.get('contact_id')
        if contact_id and contact_id.isdigit():
            c = Contact.query.get(int(contact_id))
            if c:
                db.session.add(EventContact(
                    event_id=event_obj.id,
                    name=c.name,
                    role=None,
                    phone=c.phone,
                    email=c.email,
                ))
        else:
            contact_name = request.form.get('contact_name', '').strip()
            if contact_name:
                db.session.add(EventContact(
                    event_id=event_obj.id,
                    name=contact_name,
                    role=None,
                    phone=request.form.get('contact_phone', '').strip() or None,
                    email=request.form.get('contact_email', '').strip() or None,
                ))

        # Standard-ToDo-Liste "Vorbereitung" anlegen
        prep_todo_list = EventTodoList(
            event_id=event_obj.id,
            day_id=None,
            title="Vorbereitung",
            created_by=current_user.id,
        )
        db.session.add(prep_todo_list)

        EventService.sync_calendar_for_event(event_obj, current_user.id)
        db.session.commit()
        flash('Veranstaltung erfolgreich erstellt.', 'success')
        return redirect(url_for('events.view_event', event_id=event_obj.id))

    return render_template('events/create.html', users=users, contacts=contacts)


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

    event_obj.appointments = []
    event_obj.assignments = []
    event_obj.contacts = []
    event_obj.timeline_items = []

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
        start_raw = (starts[index] if index < len(starts) else '').strip()
        end_raw = (ends[index] if index < len(ends) else '').strip()
        if not start_raw or not end_raw:
            continue
        start_dt = _parse_datetime(start_raw)
        end_dt = _parse_datetime(end_raw)
        if not start_dt or not end_dt:
            continue
        label = (label or '').strip() or (event_obj.name or 'Termin')
        appointment = EventAppointment(
            event=event_obj,
            label=label,
            description=(descriptions[index] if index < len(descriptions) else '').strip() or None,
            start_time=start_dt,
            end_time=end_dt,
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

    if created_appointments:
        dates_dict = {}
        for appt in created_appointments:
            d = appt.start_time.date()
            if d not in dates_dict:
                dates_dict[d] = []
            dates_dict[d].append(appt)

        sorted_dates = sorted(dates_dict.keys())
        event_obj.is_multiday = len(sorted_dates) > 1
        event_obj.start_date = sorted_dates[0]
        event_obj.end_date = sorted_dates[-1]

        existing_days = {d.date: d for d in event_obj.days}
        for idx, d in enumerate(sorted_dates, start=1):
            day_obj = existing_days.get(d)
            if not day_obj:
                day_obj = EventDay(
                    event_id=event_obj.id,
                    day_number=idx,
                    date=d,
                    label=f"Tag {idx}" if event_obj.is_multiday else "Haupttermin",
                )
                db.session.add(day_obj)
                db.session.flush()
            else:
                day_obj.day_number = idx
            for appt in dates_dict[d]:
                appt.day_id = day_obj.id

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
        for contact in accessible_query(current_user, Contact, 'contacts').filter(
            Contact.id.in_(selected_contact_ids)
        ).all():
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
    if event_obj.folder:
        Folder.prefetch_paths([event_obj.folder])
    conflicts = _serialize_conflicts(event_obj)

    active_modules = {
        'files': is_module_enabled('module_files') and has_module_access(current_user, 'module_files'),
        'booking_personal': is_module_enabled('module_booking_personal') and has_module_access(current_user, 'module_booking_personal'),
        'booking': is_module_enabled('module_booking') and has_module_access(current_user, 'module_booking'),
        'kanban': is_module_enabled('module_kanban') and has_module_access(current_user, 'module_kanban'),
        'inventory': is_module_enabled('module_inventory') and has_module_access(current_user, 'module_inventory'),
        'calendar': is_module_enabled('module_calendar') and has_module_access(current_user, 'module_calendar'),
    }

    folders = []
    if active_modules['files']:
        all_folders = Folder.query.filter(Folder.deleted_at.is_(None)).order_by(Folder.name).all()
        folders = [f for f in all_folders if can_view_folder(f, current_user)]
        Folder.prefetch_paths(folders)

    available_booking_events = []
    if active_modules['booking_personal']:
        from app.models.booking_personal import BookingPersonalEvent
        linked_bp_ids = {link.booking_personal_event_id for link in event_obj.booking_personal_links}
        bp_query = BookingPersonalEvent.query.filter_by(is_active=True)
        if linked_bp_ids:
            bp_query = bp_query.filter(~BookingPersonalEvent.id.in_(linked_bp_ids))
        available_booking_events = bp_query.order_by(BookingPersonalEvent.name).all()

    available_boards = []
    if active_modules['kanban']:
        from app.models.kanban import KanbanBoard
        from app.utils.kanban_access import accessible_boards_query
        available_boards = accessible_boards_query(current_user).filter(
            KanbanBoard.archived_at.is_(None),
            KanbanBoard.closed_at.is_(None)
        ).order_by(KanbanBoard.title).all()

    users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    users_by_id = {u.id: u for u in users}
    event_todos = [tl for tl in event_obj.todo_lists if tl.day_id is None]
    day_todos = [tl for tl in event_obj.todo_lists if tl.day_id is not None]
    has_day_todos = len(day_todos) > 0

    custom_fields = EventCustomField.query.filter_by(is_active=True).order_by(EventCustomField.position, EventCustomField.id).all()
    custom_values_dict = event_obj.custom_values_dict
    person_fields = [f for f in custom_fields if f.field_type == 'person']

    active_tab = request.args.get('tab', 'overview')

    return render_template(
        'events/view.html',
        event=event_obj,
        conflicts=conflicts,
        active_modules=active_modules,
        folders=folders,
        available_booking_events=available_booking_events,
        available_boards=available_boards,
        users=users,
        users_by_id=users_by_id,
        event_todos=event_todos,
        day_todos=day_todos,
        has_day_todos=has_day_todos,
        custom_fields=custom_fields,
        custom_values_dict=custom_values_dict,
        person_fields=person_fields,
        active_tab=active_tab,
    )


@events_bp.route('/<int:event_id>/custom-fields/save', methods=['POST'])
@login_required
@check_module_access('module_events')
def save_custom_fields(event_id):
    """Speichert benutzerdefinierte Felder für eine Veranstaltung."""
    event_obj = Event.query.get_or_404(event_id)
    if not (current_user.is_admin or current_user.has_full_access or event_obj.owner_id == current_user.id or event_obj.created_by == current_user.id):
        if request.is_json:
            return jsonify({'success': False, 'error': 'Keine Berechtigung'}), 403
        flash('Keine Berechtigung zum Bearbeiten dieser Veranstaltung.', 'danger')
        return redirect(url_for('events.view_event', event_id=event_id))

    custom_fields = EventCustomField.query.filter_by(is_active=True).all()
    is_json = request.is_json
    data = request.get_json(silent=True) or {} if is_json else request.form

    existing_vals = {v.field_id: v for v in event_obj.custom_values}

    for field in custom_fields:
        key = f'field_{field.id}'
        if not is_json and field.field_type == 'checkbox':
            # Im normalen HTML-Formular wird unchecked nicht gesendet, wenn das Formular das gesamte Custom-Fields-Form ist
            if 'custom_fields_form' in data or key in data or field.field_type == 'checkbox':
                val = '1' if request.form.get(key) in ('1', 'on', 'true') else '0'
            else:
                continue
        else:
            if key in data:
                val = str(data.get(key) or '').strip()
            elif str(field.id) in data:
                val = str(data.get(str(field.id)) or '').strip()
            else:
                continue

        record = existing_vals.get(field.id)
        if record:
            record.value = val
        else:
            new_val = EventCustomFieldValue(
                event_id=event_obj.id,
                field_id=field.id,
                value=val
            )
            db.session.add(new_val)

    db.session.commit()

    if is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Felder erfolgreich gespeichert.'})

    flash('Benutzerdefinierte Felder erfolgreich gespeichert.', 'success')
    return redirect(url_for('events.view_event', event_id=event_id, tab=request.form.get('return_tab', 'overview')))


@events_bp.route('/<int:event_id>/link/folder', methods=['POST'])
@login_required
@check_module_access('module_events')
def link_folder(event_id):
    if not (is_module_enabled('module_files') and has_module_access(current_user, 'module_files')):
        flash('Dateien-Modul ist nicht aktiv.', 'warning')
        return redirect(url_for('events.view_event', event_id=event_id))

    event_obj = Event.query.get_or_404(event_id)
    folder_id = request.form.get('folder_id')
    if folder_id:
        try:
            folder = Folder.query.get(int(folder_id))
            if folder and can_view_folder(folder, current_user):
                event_obj.folder_id = folder.id
                db.session.commit()
                flash(f'Ordner „{folder.name}“ erfolgreich verknüpft.', 'success')
            else:
                flash('Ordner nicht gefunden oder kein Zugriff.', 'danger')
        except (ValueError, TypeError):
            flash('Ungültiger Ordner.', 'danger')
    else:
        event_obj.folder_id = None
        db.session.commit()
        flash('Ordnerverknüpfung entfernt.', 'info')

    return redirect(url_for('events.view_event', event_id=event_obj.id))


@events_bp.route('/<int:event_id>/link/booking', methods=['POST'])
@login_required
@check_module_access('module_events')
def link_booking(event_id):
    if not (is_module_enabled('module_booking_personal') and has_module_access(current_user, 'module_booking_personal')):
        flash('Booking-Modul ist nicht aktiv.', 'warning')
        return redirect(url_for('events.view_event', event_id=event_id))

    event_obj = Event.query.get_or_404(event_id)
    action = request.form.get('action', 'add')
    bp_event_id = request.form.get('booking_personal_event_id')
    try:
        bp_event_id = int(bp_event_id)
    except (TypeError, ValueError):
        flash('Ungültige Booking-Liste.', 'danger')
        return redirect(url_for('events.view_event', event_id=event_obj.id))

    if action == 'add':
        existing = EventBookingPersonalLink.query.filter_by(
            event_id=event_obj.id,
            booking_personal_event_id=bp_event_id,
        ).first()
        if not existing:
            link = EventBookingPersonalLink(
                event_id=event_obj.id,
                booking_personal_event_id=bp_event_id,
            )
            db.session.add(link)
            db.session.commit()
            flash('Booking-Liste erfolgreich verknüpft.', 'success')
    elif action == 'remove':
        EventBookingPersonalLink.query.filter_by(
            event_id=event_obj.id,
            booking_personal_event_id=bp_event_id,
        ).delete()
        db.session.commit()
        flash('Booking-Verknüpfung entfernt.', 'info')

    return redirect(url_for('events.view_event', event_id=event_obj.id))


@events_bp.route('/<int:event_id>/link/kanban', methods=['POST'])
@login_required
@check_module_access('module_events')
def link_kanban(event_id):
    if not (is_module_enabled('module_kanban') and has_module_access(current_user, 'module_kanban')):
        flash('Kanban-Modul ist nicht aktiv.', 'warning')
        return redirect(url_for('events.view_event', event_id=event_id))

    from app.models.kanban import KanbanBoard, KanbanCard
    event_obj = Event.query.get_or_404(event_id)
    board_id = request.form.get('kanban_board_id')
    card_id = request.form.get('kanban_card_id')
    clear = request.form.get('clear') == '1'

    if clear:
        event_obj.kanban_board_id = None
        event_obj.kanban_card_id = None
        db.session.commit()
        flash('Kanban-Verknüpfung entfernt.', 'info')
        return redirect(url_for('events.view_event', event_id=event_obj.id))

    if card_id and card_id.strip():
        try:
            card = KanbanCard.query.get(int(card_id))
            if card:
                event_obj.kanban_card_id = card.id
                event_obj.kanban_board_id = card.list.board_id if card.list else None
                db.session.commit()
                flash(f'Kanban-Karte „{card.title}“ verknüpft.', 'success')
                return redirect(url_for('events.view_event', event_id=event_obj.id))
        except (ValueError, TypeError):
            pass

    if board_id and board_id.strip():
        try:
            board = KanbanBoard.query.get(int(board_id))
            if board:
                event_obj.kanban_board_id = board.id
                event_obj.kanban_card_id = None
                db.session.commit()
                flash(f'Kanban-Board „{board.title}“ verknüpft.', 'success')
                return redirect(url_for('events.view_event', event_id=event_obj.id))
        except (ValueError, TypeError):
            pass

    event_obj.kanban_board_id = None
    event_obj.kanban_card_id = None
    db.session.commit()
    flash('Kanban-Verknüpfung aktualisiert.', 'info')
    return redirect(url_for('events.view_event', event_id=event_obj.id))


@events_bp.route('/kanban/board/<int:board_id>/cards')
@login_required
@check_module_access('module_kanban')
def get_board_cards(board_id):
    from app.models.kanban import KanbanCard, KanbanList
    cards = (
        KanbanCard.query.join(KanbanList)
        .filter(KanbanList.board_id == board_id, KanbanCard.archived_at.is_(None))
        .order_by(KanbanList.position, KanbanCard.position)
        .all()
    )
    return jsonify([{
        'id': c.id,
        'title': c.title,
        'list_name': c.list.title if c.list else '',
    } for c in cards])


@events_bp.route('/<int:event_id>/todos/list/create', methods=['POST'])
@login_required
@check_module_access('module_events')
def create_todo_list(event_id):
    event_obj = Event.query.get_or_404(event_id)
    title = request.form.get('title', '').strip()
    if not title:
        flash('Bitte einen Titel für die ToDo-Liste angeben.', 'danger')
        return redirect(url_for('events.view_event', event_id=event_obj.id, tab='todos'))

    day_id = request.form.get('day_id')
    day = None
    if day_id and day_id.strip():
        try:
            day = EventDay.query.filter_by(id=int(day_id), event_id=event_obj.id).first()
        except (ValueError, TypeError):
            day = None

    todo_list = EventTodoList(
        event_id=event_obj.id,
        day_id=day.id if day else None,
        title=title,
        created_by=current_user.id,
    )
    db.session.add(todo_list)
    db.session.commit()
    flash('ToDo-Liste erstellt.', 'success')
    return redirect(url_for('events.view_event', event_id=event_obj.id, tab='todos'))


@events_bp.route('/<int:event_id>/todos/list/<int:list_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_events')
def delete_todo_list(event_id, list_id):
    event_obj = Event.query.get_or_404(event_id)
    todo_list = EventTodoList.query.filter_by(id=list_id, event_id=event_obj.id).first_or_404()
    db.session.delete(todo_list)
    db.session.commit()
    flash('ToDo-Liste gelöscht.', 'info')
    return redirect(url_for('events.view_event', event_id=event_obj.id, tab='todos'))


@events_bp.route('/<int:event_id>/todos/item/create', methods=['POST'])
@login_required
@check_module_access('module_events')
def create_todo_item(event_id):
    event_obj = Event.query.get_or_404(event_id)
    list_id = request.form.get('todo_list_id')
    title = request.form.get('title', '').strip()
    if not list_id or not title:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'Titel erforderlich'}), 400
        flash('Titel ist erforderlich.', 'danger')
        return redirect(url_for('events.view_event', event_id=event_obj.id, tab='todos'))

    todo_list = EventTodoList.query.filter_by(id=int(list_id), event_id=event_obj.id).first_or_404()
    assigned_user_id = request.form.get('assigned_to_user_id')
    assigned_id = int(assigned_user_id) if assigned_user_id and assigned_user_id.isdigit() else None

    due_date_raw = request.form.get('due_date', '').strip()
    due_date = _parse_date(due_date_raw) if due_date_raw else None
    due_time_raw = request.form.get('due_time', '').strip()
    due_time = _parse_time(due_time_raw) if due_time_raw else None

    item = EventTodoItem(
        todo_list_id=todo_list.id,
        title=title,
        assigned_to_user_id=assigned_id,
        due_date=due_date,
        due_time=due_time,
        position=len(todo_list.items) + 1,
    )
    db.session.add(item)
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'id': item.id,
            'title': item.title,
            'assigned_to': item.assigned_to.full_name if item.assigned_to else None,
            'due_date': item.due_date.strftime('%d.%m.%Y') if item.due_date else None,
            'due_time': item.due_time.strftime('%H:%M') if item.due_time else None,
            'progress': todo_list.progress_percent,
            'completed_count': todo_list.completed_count,
            'total_count': todo_list.total_count,
        })

    flash('Aufgabe hinzugefügt.', 'success')
    return redirect(url_for('events.view_event', event_id=event_obj.id, tab='todos'))


@events_bp.route('/todos/item/<int:item_id>/toggle', methods=['POST'])
@login_required
@check_module_access('module_events')
def toggle_todo_item(item_id):
    item = EventTodoItem.query.get_or_404(item_id)
    item.is_completed = not item.is_completed
    if item.is_completed:
        item.completed_at = datetime.utcnow()
        item.completed_by_id = current_user.id
    else:
        item.completed_at = None
        item.completed_by_id = None
    db.session.commit()

    todo_list = item.todo_list
    return jsonify({
        'success': True,
        'item_id': item.id,
        'is_completed': item.is_completed,
        'completed_by': current_user.full_name if item.is_completed else None,
        'progress': todo_list.progress_percent,
        'completed_count': todo_list.completed_count,
        'total_count': todo_list.total_count,
    })


@events_bp.route('/todos/item/<int:item_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_events')
def delete_todo_item(item_id):
    item = EventTodoItem.query.get_or_404(item_id)
    event_id = item.todo_list.event_id
    db.session.delete(item)
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True})
    flash('Aufgabe gelöscht.', 'info')
    return redirect(url_for('events.view_event', event_id=event_id, tab='todos'))


@events_bp.route('/todos/item/<int:item_id>/update', methods=['POST'])
@login_required
@check_module_access('module_events')
def update_todo_item(item_id):
    item = EventTodoItem.query.get_or_404(item_id)
    event_id = item.todo_list.event_id

    payload = request.get_json(silent=True) if request.is_json else None
    if payload is None:
        payload = request.form

    if 'title' in payload:
        title = (payload.get('title') or '').strip()
        if title:
            item.title = title

    if 'assigned_to_user_id' in payload:
        uid = payload.get('assigned_to_user_id')
        if uid and str(uid).isdigit():
            user = User.query.get(int(uid))
            item.assigned_to_user_id = user.id if user and user.is_active else None
        else:
            item.assigned_to_user_id = None

    if str(payload.get('clear_due')).lower() in ('1', 'true'):
        item.due_date = None
        item.due_time = None
    elif 'due_datetime' in payload:
        dt_raw = (payload.get('due_datetime') or '').strip()
        if dt_raw:
            dt = _parse_datetime(dt_raw)
            if dt:
                item.due_date = dt.date()
                item.due_time = dt.time()
            else:
                item.due_date = None
                item.due_time = None
        else:
            item.due_date = None
            item.due_time = None
    else:
        if 'due_date' in payload:
            due_date_raw = (payload.get('due_date') or '').strip()
            item.due_date = _parse_date(due_date_raw) if due_date_raw else None
        if 'due_time' in payload:
            due_time_raw = (payload.get('due_time') or '').strip()
            item.due_time = _parse_time(due_time_raw) if due_time_raw else None

    db.session.commit()

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        due_iso = None
        due_display = None
        if item.due_date and item.due_time:
            due_iso = f"{item.due_date.strftime('%Y-%m-%d')}T{item.due_time.strftime('%H:%M')}"
            due_display = f"{item.due_date.strftime('%d.%m.')} {item.due_time.strftime('%H:%M')} Uhr"
        elif item.due_date:
            due_iso = f"{item.due_date.strftime('%Y-%m-%d')}T00:00"
            due_display = item.due_date.strftime('%d.%m.%Y')

        avatar_url = None
        initials = None
        assignee_name = None
        if item.assigned_to:
            assignee_name = item.assigned_to.full_name
            if item.assigned_to.profile_picture:
                avatar_url = url_for('settings.profile_picture', filename=item.assigned_to.profile_picture)
            fn = item.assigned_to.first_name or ''
            ln = item.assigned_to.last_name or ''
            initials = f"{fn[:1]}{ln[:1]}".upper()

        return jsonify({
            'success': True,
            'item_id': item.id,
            'title': item.title,
            'assigned_to_user_id': item.assigned_to_user_id,
            'assigned_name': assignee_name,
            'assigned_avatar': avatar_url,
            'assigned_initials': initials,
            'due_datetime': due_iso,
            'due_date': item.due_date.strftime('%d.%m.%Y') if item.due_date else None,
            'due_time': item.due_time.strftime('%H:%M') if item.due_time else None,
            'due_display': due_display,
        })

    flash('Aufgabe aktualisiert.', 'success')
    return redirect(url_for('events.view_event', event_id=event_id, tab='todos'))


@events_bp.route('/<int:event_id>/owner', methods=['POST'])
@login_required
@check_module_access('module_events')
def update_owner(event_id):
    event_obj = Event.query.get_or_404(event_id)
    owner_id = request.form.get('owner_id')
    if owner_id and owner_id.isdigit():
        user = User.query.get(int(owner_id))
        if user and user.is_active:
            event_obj.owner_id = user.id
            db.session.commit()
            flash(f'Verantwortliche Person auf „{user.full_name}“ geändert.', 'success')
        else:
            flash('Ungültiger Benutzer.', 'danger')
    else:
        flash('Bitte eine verantwortliche Person auswählen.', 'warning')
    return redirect(url_for('events.view_event', event_id=event_obj.id))


@events_bp.route('/<int:event_id>/assignments/add', methods=['POST'])
@login_required
@check_module_access('module_events')
def add_assignment(event_id):
    event_obj = Event.query.get_or_404(event_id)
    user_id = request.form.get('user_id')
    role = request.form.get('role', '').strip() or None
    display_name = request.form.get('display_name', '').strip() or None

    if user_id and user_id.isdigit():
        user = User.query.get(int(user_id))
        if user and user.is_active:
            existing = EventAssignment.query.filter_by(event_id=event_obj.id, user_id=user.id).first()
            if not existing:
                assignment = EventAssignment(
                    event_id=event_obj.id,
                    user_id=user.id,
                    role=role,
                    display_name=user.full_name
                )
                db.session.add(assignment)
                db.session.commit()
                flash(f'„{user.full_name}“ erfolgreich zugeteilt.', 'success')
            else:
                flash(f'„{user.full_name}“ ist bereits zugeteilt.', 'info')
        else:
            flash('Benutzer nicht gefunden.', 'danger')
    elif display_name:
        assignment = EventAssignment(
            event_id=event_obj.id,
            user_id=None,
            role=role,
            display_name=display_name
        )
        db.session.add(assignment)
        db.session.commit()
        flash(f'„{display_name}“ erfolgreich hinzugefügt.', 'success')
    else:
        flash('Bitte einen Benutzer auswählen oder einen Namen angeben.', 'warning')

    return redirect(url_for('events.view_event', event_id=event_obj.id, tab='people'))


@events_bp.route('/<int:event_id>/assignments/<int:assignment_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_events')
def delete_assignment(event_id, assignment_id):
    event_obj = Event.query.get_or_404(event_id)
    assignment = EventAssignment.query.filter_by(id=assignment_id, event_id=event_obj.id).first_or_404()
    db.session.delete(assignment)
    db.session.commit()
    flash('Zuteilung entfernt.', 'info')
    return redirect(url_for('events.view_event', event_id=event_obj.id, tab='people'))


@events_bp.route('/<int:event_id>/contacts/add', methods=['POST'])
@login_required
@check_module_access('module_events')
def add_contact(event_id):
    event_obj = Event.query.get_or_404(event_id)
    name = request.form.get('name', '').strip()
    role = request.form.get('role', '').strip() or None
    phone = request.form.get('phone', '').strip() or None
    email = request.form.get('email', '').strip() or None

    if not name:
        flash('Bitte einen Namen für den Ansprechpartner angeben.', 'danger')
        return redirect(url_for('events.view_event', event_id=event_obj.id, tab='people'))

    contact = EventContact(
        event_id=event_obj.id,
        name=name,
        role=role,
        phone=phone,
        email=email
    )
    db.session.add(contact)
    db.session.commit()
    flash(f'Ansprechpartner „{name}“ hinzugefügt.', 'success')
    return redirect(url_for('events.view_event', event_id=event_obj.id, tab='people'))


@events_bp.route('/<int:event_id>/contacts/<int:contact_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_events')
def delete_contact(event_id, contact_id):
    event_obj = Event.query.get_or_404(event_id)
    contact = EventContact.query.filter_by(id=contact_id, event_id=event_obj.id).first_or_404()
    db.session.delete(contact)
    db.session.commit()
    flash('Ansprechpartner entfernt.', 'info')
    return redirect(url_for('events.view_event', event_id=event_obj.id, tab='people'))


@events_bp.route('/<int:event_id>/days/update', methods=['POST'])
@login_required
@check_module_access('module_events')
def update_days(event_id):
    event_obj = Event.query.get_or_404(event_id)
    day_ids = request.form.getlist('day_id[]')
    labels = request.form.getlist('day_label[]')
    notes = request.form.getlist('day_notes[]')

    for idx, d_id in enumerate(day_ids):
        try:
            day = EventDay.query.filter_by(id=int(d_id), event_id=event_obj.id).first()
            if day:
                if idx < len(labels) and labels[idx].strip():
                    day.label = labels[idx].strip()
                if idx < len(notes):
                    day.notes = notes[idx].strip() or None
        except (ValueError, TypeError):
            continue

    db.session.commit()
    flash('Tagesdetails aktualisiert.', 'success')
    return redirect(url_for('events.view_event', event_id=event_obj.id, tab='days'))


@events_bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
@check_module_access('module_events')
def edit_event(event_id):
    _refresh_archive_state()
    event_obj = Event.query.get_or_404(event_id)
    users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    contacts = accessible_query(current_user, Contact, 'contacts').order_by(Contact.name).all()
    all_folders = Folder.query.filter(Folder.deleted_at.is_(None)).order_by(Folder.name).all()
    folders = [f for f in all_folders if can_view_folder(f, current_user)]
    Folder.prefetch_paths(folders)
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
