"""Raumbuchungssystem: Raumkalender-Verwaltung, Belegungen und Kollisionsprüfung."""

from datetime import datetime, date, time, timedelta
import logging
from flask import url_for
from app import db
from app.models.booking import (
    BookingRoom,
    BookingForm,
    BookingRequest,
    BookingFormRole,
    BookingRequestApproval,
)
from app.models.calendar import Calendar, CalendarEvent

logger = logging.getLogger(__name__)


def ensure_room_calendar(room):
    """Erstellt oder aktualisiert den zugehörigen Raumkalender."""
    if not room:
        return None

    cal = None
    if room.calendar_id:
        cal = Calendar.query.get(room.calendar_id)

    if not cal:
        cal = Calendar(
            name=room.name,
            calendar_type='room',
            color=room.color or '#4f46e5',
            is_default=False,
            hidden_from_others=False,
        )
        db.session.add(cal)
        db.session.flush()
        room.calendar_id = cal.id
    else:
        changed = False
        if cal.name != room.name:
            cal.name = room.name
            changed = True
        if cal.color != (room.color or '#4f46e5'):
            cal.color = room.color or '#4f46e5'
            changed = True
        if cal.calendar_type != 'room':
            cal.calendar_type = 'room'
            changed = True
        if changed:
            db.session.flush()

    return cal


def check_room_availability(room_id, event_date, start_time, end_time, exclude_request_id=None):
    """Prüft, ob ein Raum in dem gewünschten Zeitfenster verfügbar ist.
    
    Gibt (is_available, conflicts_list) zurück.
    conflicts_list enthält Dictionaries mit Details zu den überschneidenden Buchungen/Terminen.
    """
    if not room_id or not event_date:
        return True, []

    room = BookingRoom.query.get(room_id)
    if not room:
        return True, []

    # Datum und Zeit kombinieren
    st_time = start_time or time(9, 0)
    et_time = end_time or time(10, 0)
    req_start = datetime.combine(event_date, st_time)
    req_end = datetime.combine(event_date, et_time)
    if req_end <= req_start:
        req_end = req_start + timedelta(hours=1)

    conflicts = []

    # 1. Bestehende akzeptierte/aktive Buchungen für diesen Raum am gleichen Tag prüfen
    q = BookingRequest.query.filter(
        BookingRequest.room_id == room_id,
        BookingRequest.status.in_(['accepted', 'pending']),
        BookingRequest.event_date == event_date,
    )
    if exclude_request_id:
        q = q.filter(BookingRequest.id != exclude_request_id)

    for br in q.all():
        b_st = br.event_start_time or time(9, 0)
        b_et = br.event_end_time or time(10, 0)
        b_start = datetime.combine(br.event_date, b_st)
        b_end = datetime.combine(br.event_date, b_et)
        if b_end <= b_start:
            b_end = b_start + timedelta(hours=1)

        # Schnittmenge prüfen: start1 < end2 and end1 > start2
        if req_start < b_end and req_end > b_start:
            conflicts.append({
                'source': 'booking',
                'id': br.id,
                'title': br.event_name,
                'applicant': br.applicant_name or br.email,
                'start': b_start,
                'end': b_end,
                'status': br.status,
                'booking_type': br.booking_type,
            })

    # 2. Kalendereinträge im Raumkalender prüfen (z. B. importierte Termine oder Blockierzeiten)
    if room.calendar_id:
        cal_events = CalendarEvent.query.filter(
            CalendarEvent.calendar_id == room.calendar_id,
            CalendarEvent.start_time < req_end,
            CalendarEvent.end_time > req_start,
        ).all()
        for ce in cal_events:
            # Überspringen, falls dieser Termin zu einer bereits erfassten Buchung gehört
            if any(c['id'] == ce.booking_request_id for c in conflicts if c.get('id')):
                continue
            if exclude_request_id and ce.booking_request_id == exclude_request_id:
                continue
            conflicts.append({
                'source': 'calendar',
                'id': ce.booking_request_id,
                'title': ce.title,
                'applicant': ce.location or room.name,
                'start': ce.start_time,
                'end': ce.end_time,
                'status': 'calendar',
                'booking_type': 'calendar',
            })

    is_available = (len(conflicts) == 0)
    return is_available, conflicts


def create_or_update_room_booking(
    room_id,
    event_name,
    event_date,
    start_time,
    end_time,
    user=None,
    applicant_name=None,
    email=None,
    form_id=None,
    event_id=None,
    notes=None,
    booking_type='internal',
    booking_request_id=None,
):
    """Erstellt oder aktualisiert eine Raumbuchung inklusive Kollisionsprüfung und Kalendereintrag."""
    room = BookingRoom.query.get_or_404(room_id)
    ensure_room_calendar(room)

    # Zeiten aufbereiten
    st_time = start_time or time(9, 0)
    et_time = end_time or time(10, 0)
    start_dt = datetime.combine(event_date, st_time)
    end_dt = datetime.combine(event_date, et_time)
    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(hours=1)

    # Kollisionsprüfung
    is_avail, conflicts = check_room_availability(
        room_id,
        event_date,
        st_time,
        et_time,
        exclude_request_id=booking_request_id,
    )
    has_conflict = not is_avail
    conflict_notes = None
    if has_conflict:
        conflict_lines = []
        for c in conflicts:
            conflict_lines.append(
                f"{c['title']} ({c['start'].strftime('%H:%M')} - {c['end'].strftime('%H:%M')})"
            )
        conflict_notes = "Kollision mit: " + ", ".join(conflict_lines)

    # BookingRequest anlegen oder laden
    if booking_request_id:
        req = BookingRequest.query.get(booking_request_id)
    else:
        req = None

    if not req:
        import secrets
        token = secrets.token_urlsafe(32)
        while BookingRequest.query.filter_by(token=token).first():
            token = secrets.token_urlsafe(32)

        req = BookingRequest(
            form_id=form_id or room.default_form_id,
            room_id=room.id,
            event_name=event_name,
            applicant_name=applicant_name or (user.full_name if user else 'Intern'),
            email=email or (user.email if user else 'internal@portal.local'),
            token=token,
            status='accepted' if booking_type == 'internal' else 'pending',
            booking_type=booking_type,
            booked_by_user_id=user.id if user else None,
            event_id=event_id,
            event_date=event_date,
            event_start_time=st_time,
            event_end_time=et_time,
            has_conflict=has_conflict,
            conflict_notes=conflict_notes,
        )
        if booking_type == 'internal' and user:
            req.accepted_by = user.id
            req.accepted_at = datetime.utcnow()

        db.session.add(req)
        db.session.flush()

        # Rollen-Zustimmungen vorbereiten
        target_form = req.form or room.default_form
        if target_form and target_form.roles:
            for role in target_form.roles:
                approval = BookingRequestApproval(
                    request_id=req.id,
                    role_id=role.id,
                    status='pending',
                )
                db.session.add(approval)
    else:
        req.room_id = room.id
        req.event_name = event_name
        req.event_date = event_date
        req.event_start_time = st_time
        req.event_end_time = et_time
        req.has_conflict = has_conflict
        req.conflict_notes = conflict_notes
        if event_id:
            req.event_id = event_id
        if applicant_name:
            req.applicant_name = applicant_name
        if email:
            req.email = email
        db.session.flush()

    # Raumkalender-Termin synchronisieren
    cal_event = None
    if req.calendar_event_id:
        cal_event = CalendarEvent.query.get(req.calendar_event_id)

    loc_str = f"{room.name} ({room.location})" if room.location else room.name
    desc_str = f"Raumbuchung für {room.name}"
    if req.booked_by:
        desc_str += f" durch {req.booked_by.full_name}"
    elif req.applicant_name:
        desc_str += f" durch {req.applicant_name}"
    if conflict_notes:
        desc_str += f"\n\n[WARNUNG] {conflict_notes}"

    if not cal_event:
        cal_event = CalendarEvent(
            title=req.event_name,
            description=desc_str,
            start_time=start_dt,
            end_time=end_dt,
            location=loc_str,
            event_color=room.color or '#4f46e5',
            created_by=user.id if user else 1,
            calendar_id=room.calendar_id,
            booking_request_id=req.id,
        )
        db.session.add(cal_event)
        db.session.flush()
        req.calendar_event_id = cal_event.id
    else:
        cal_event.title = req.event_name
        cal_event.start_time = start_dt
        cal_event.end_time = end_dt
        cal_event.location = loc_str
        cal_event.event_color = room.color or '#4f46e5'
        cal_event.calendar_id = room.calendar_id
        cal_event.description = desc_str

    db.session.commit()

    # Benachrichtigung an Rollen-Inhaber senden
    if booking_type == 'internal':
        try:
            from app.utils.notifications import send_booking_request_notification
            send_booking_request_notification(req)
        except Exception as e:
            logger.warning("Push-Benachrichtigung für interne Buchung fehlgeschlagen: %s", e)

    return req, has_conflict, conflicts


def delete_room_booking(booking_request):
    """Löscht eine Raumbuchung und den zugehörigen Kalendereintrag."""
    if not booking_request:
        return
    if isinstance(booking_request, int):
        booking_request = db.session.get(BookingRequest, booking_request)
        if not booking_request:
            return
    if booking_request.calendar_event_id:
        ce = CalendarEvent.query.get(booking_request.calendar_event_id)
        if ce:
            db.session.delete(ce)
    db.session.delete(booking_request)
    db.session.commit()
