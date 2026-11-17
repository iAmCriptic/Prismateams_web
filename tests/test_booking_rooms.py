from datetime import date, time, datetime, timedelta
import pytest
from app import db
from app.models.user import User
from app.models.booking import BookingRoom, BookingForm, BookingRequest, BookingRequestApproval, BookingFormRole
from app.models.calendar import Calendar, CalendarEvent
from app.models.event import Event
from app.utils.booking_rooms import (
    ensure_room_calendar,
    check_room_availability,
    create_or_update_room_booking,
    delete_room_booking
)


def _create_user(email='organizer@example.com'):
    user = User(email=email, first_name='Max', last_name='Mustermann', is_admin=True)
    user.set_password('Secret123!')
    db.session.add(user)
    db.session.commit()
    return user


def test_booking_room_and_dedicated_calendar(app):
    with app.app_context():
        room = BookingRoom(
            name='Großer Saal',
            location='Hauptgebäude, 1. OG',
            capacity=120,
            color='#10b981',
            description='Saal mit Beamer und Bühne'
        )
        db.session.add(room)
        db.session.commit()

        # Dedicated calendar should be auto-created by ensure_room_calendar
        cal = ensure_room_calendar(room)
        assert cal is not None
        assert cal.calendar_type == 'room'
        assert cal.name == 'Großer Saal'
        assert cal.color == '#10b981'
        assert room.calendar_id == cal.id


def test_room_collision_detection_and_permanent_flag(app):
    with app.app_context():
        user = _create_user('collision_test@example.com')
        room = BookingRoom(name='Seminarraum A', capacity=30, color='#3b82f6')
        db.session.add(room)
        db.session.commit()

        d = date.today() + timedelta(days=5)
        t_start_1 = time(10, 0)
        t_end_1 = time(12, 0)

        # First booking - no collision
        avail, conflicts = check_room_availability(room.id, d, t_start_1, t_end_1)
        assert avail is True
        assert len(conflicts) == 0

        req1, has_conflict1, confs1 = create_or_update_room_booking(
            room_id=room.id,
            event_name='Projekt-Kickoff',
            event_date=d,
            start_time=t_start_1,
            end_time=t_end_1,
            user=user,
            booking_type='internal'
        )
        assert req1.id is not None
        assert req1.has_conflict is False
        assert has_conflict1 is False
        assert req1.calendar_event_id is not None

        # Second booking - overlapping time (11:00 - 13:00)
        t_start_2 = time(11, 0)
        t_end_2 = time(13, 0)

        avail2, conflicts2 = check_room_availability(room.id, d, t_start_2, t_end_2)
        assert avail2 is False
        assert len(conflicts2) == 1
        assert conflicts2[0]['id'] == req1.id

        # Booking is created anyway as per requirements, but permanently flagged with has_conflict=True
        req2, has_conflict2, confs2 = create_or_update_room_booking(
            room_id=room.id,
            event_name='Überlappendes Meeting',
            event_date=d,
            start_time=t_start_2,
            end_time=t_end_2,
            user=user,
            booking_type='internal'
        )
        assert req2.has_conflict is True
        assert has_conflict2 is True
        assert 'Kollision mit' in (req2.conflict_notes or '')
        assert 'Projekt-Kickoff' in (req2.conflict_notes or '')
        assert req2.calendar_event_id is not None


def test_internal_booking_role_acknowledgement_and_issue_reporting(app):
    with app.app_context():
        user = _create_user('role_test@example.com')
        room = BookingRoom(name='Tagungsraum B', capacity=20)
        form = BookingForm(title='Internes Formular', created_by=user.id)
        db.session.add_all([room, form])
        db.session.commit()

        role = BookingFormRole(form_id=form.id, role_name='Hausmeister')
        db.session.add(role)
        db.session.commit()

        d = date.today() + timedelta(days=3)
        req, _, _ = create_or_update_room_booking(
            room_id=room.id,
            event_name='Abteilungsmeeting',
            event_date=d,
            start_time=time(14, 0),
            end_time=time(16, 0),
            user=user,
            booking_type='internal'
        )
        req.form_id = form.id
        db.session.commit()

        approval = BookingRequestApproval(
            request_id=req.id,
            role_id=role.id,
            status='pending'
        )
        db.session.add(approval)
        db.session.commit()

        # 1. Role acknowledges (Zur Kenntnis genommen)
        approval.status = 'acknowledged'
        approval.acknowledged_at = datetime.utcnow()
        db.session.commit()
        assert approval.status == 'acknowledged'
        assert approval.acknowledged_at is not None

        # 2. Role reports an issue (Problem melden)
        req.issue_reported = True
        req.issue_comment = 'Beamer defekt, muss vorab repariert werden!'
        req.issue_reported_by = user.id
        req.issue_reported_at = datetime.utcnow()
        approval.status = 'issue_reported'
        approval.reported_at = datetime.utcnow()
        db.session.commit()

        assert req.issue_reported is True
        assert 'Beamer defekt' in req.issue_comment
        assert approval.status == 'issue_reported'


def test_event_module_coupling(app):
    with app.app_context():
        user = _create_user('event_test@example.com')
        room = BookingRoom(name='Konzertsaal', capacity=250, color='#f59e0b')
        db.session.add(room)
        db.session.commit()

        ev = Event(
            name='Jahreskonzert 2026',
            description='Großes Konzert',
            room_id=room.id,
            default_location='Konzertsaal',
            owner_id=user.id,
            created_by=user.id
        )
        db.session.add(ev)
        db.session.commit()

        d = date.today() + timedelta(days=14)
        req, _, _ = create_or_update_room_booking(
            room_id=room.id,
            event_name=ev.name,
            event_date=d,
            start_time=time(18, 0),
            end_time=time(22, 0),
            user=user,
            event_id=ev.id,
            booking_type='internal'
        )

        assert req.event_id == ev.id
        assert req.room_id == room.id
        cal_ev = CalendarEvent.query.get(req.calendar_event_id)
        assert cal_ev is not None
        assert cal_ev.title == ev.name

        # Delete booking cleans up calendar event
        cal_ev_id = cal_ev.id
        delete_room_booking(req.id)
        assert CalendarEvent.query.filter_by(id=cal_ev_id).first() is None


def test_booking_form_room_settings(app):
    with app.app_context():
        user = _create_user('form_test@example.com')
        room1 = BookingRoom(name='Raum 1')
        room2 = BookingRoom(name='Raum 2')
        room3 = BookingRoom(name='Raum 3')
        db.session.add_all([room1, room2, room3])
        db.session.commit()

        # Form with specific room selection allowed
        form = BookingForm(
            title='Raumanfrage Formular',
            created_by=user.id,
            allow_room_selection=True
        )
        form.set_allowed_rooms([room1.id, room2.id])
        db.session.add(form)
        db.session.commit()

        allowed_rooms = form.get_allowed_rooms()
        allowed_ids = [r.id for r in allowed_rooms]
        assert allowed_ids == [room1.id, room2.id]
        assert room3.id not in allowed_ids

        # Form with strict room binding
        form_strict = BookingForm(
            title='Nur Raum 3',
            created_by=user.id,
            room_id=room3.id,
            allow_room_selection=False
        )
        db.session.add(form_strict)
        db.session.commit()

        assert form_strict.room_id == room3.id
        assert form_strict.allow_room_selection is False
