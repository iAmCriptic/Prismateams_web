"""Tests für die Deduplizierung von Mehrfach-Raumbuchungen in der Kalenderansicht."""

import os
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

from datetime import date, datetime, time

import pytest

from app import create_app, db
from app.blueprints.calendar.helpers import deduplicate_multi_room_events, event_to_api_dict
from app.models.booking import BookingRequest, BookingRoom
from app.models.calendar import Calendar, CalendarEvent
from app.models.event import Event
from app.models.user import User


@pytest.fixture(scope='session')
def app_instance():
    app = create_app('testing')
    app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'RATELIMIT_ENABLED': False,
    })
    return app


@pytest.fixture
def app(app_instance):
    with app_instance.app_context():
        db.create_all()
        yield app_instance
        db.session.remove()
        db.drop_all()


def test_deduplicate_multi_room_events_combines_rooms_when_all_selected(app):
    user = User(
        email='dedup@example.com',
        password_hash='test',
        first_name='Max',
        last_name='Mustermann',
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()

    ev = Event(
        name='Sommerkonzert',
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 10),
        owner_id=user.id,
        created_by=user.id,
    )
    db.session.add(ev)
    db.session.flush()

    start_dt = datetime(2026, 7, 10, 18, 0)
    end_dt = datetime(2026, 7, 10, 21, 0)
    room_events = []

    for room_name in ('Saal', 'Foyer', 'Studio'):
        cal = Calendar(name=f'Raum: {room_name}', calendar_type='room', owner_id=user.id)
        db.session.add(cal)
        db.session.flush()

        room = BookingRoom(name=room_name, calendar_id=cal.id)
        db.session.add(room)
        db.session.flush()

        req = BookingRequest(
            room_id=room.id,
            event_id=ev.id,
            event_name='Sommerkonzert',
            email='dedup@example.com',
            event_date=date(2026, 7, 10),
            event_start_time=time(18, 0),
            event_end_time=time(21, 0),
            status='accepted',
            booking_type='internal',
        )
        db.session.add(req)
        db.session.flush()

        ce = CalendarEvent(
            title='Sommerkonzert',
            start_time=start_dt,
            end_time=end_dt,
            location=room_name,
            created_by=user.id,
            calendar_id=cal.id,
            booking_request_id=req.id,
        )
        db.session.add(ce)
        db.session.flush()
        req.calendar_event_id = ce.id
        room_events.append(ce)

    db.session.commit()

    # Alle 3 Raum-Kalender ausgewählt -> genau 1 Eintrag mit allen Räumen
    with app.test_request_context():
        deduped = deduplicate_multi_room_events(room_events)
        assert len(deduped) == 1
        api = event_to_api_dict(deduped[0], user=user)
        assert api['location'] == 'Saal, Foyer, Studio'

        # Einzelner Raum-Kalender ausgewählt -> genau 1 Eintrag mit nur diesem Raum
        single = deduplicate_multi_room_events([room_events[1]])
        assert len(single) == 1
        assert event_to_api_dict(single[0], user=user)['location'] == 'Foyer'
