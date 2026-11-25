"""Tests für Google Calendar OAuth Sync (inkl. geteilter Kalender ohne iCal-Link)."""

import os
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app import create_app, db
from app.models.calendar import CalendarEvent, CalendarSyncSource
from app.models.user import User
from app.utils.google_calendar_sync import (
    GOOGLE_CALENDAR_SCOPE,
    list_google_calendars,
    save_google_calendar_connection,
)
from app.utils.google_login import GOOGLE_LOGIN_SCOPES
from app.utils.ical import sync_calendar_source


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


def _create_user(prefix='gcal_user'):
    user = User(
        email=f'{prefix}@example.com',
        password_hash='test',
        first_name='Test',
        last_name='User',
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_google_login_scopes_include_calendar_readonly():
    assert GOOGLE_CALENDAR_SCOPE in GOOGLE_LOGIN_SCOPES


def test_list_google_calendars_includes_shared_reader_calendar(app):
    user = _create_user('reader_user')
    save_google_calendar_connection(user, {
        'access_token': 'valid-token',
        'refresh_token': 'refresh-123',
        'expires_at': (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        'email': 'reader@example.com',
    })
    db.session.commit()

    api_response = MagicMock()
    api_response.status_code = 200
    api_response.json.return_value = {
        'items': [
            {
                'id': 'shared_team@group.calendar.google.com',
                'summary': 'Vereinskalender (Mitglied)',
                'accessRole': 'reader',
                'primary': False,
                'backgroundColor': '#16a765',
            },
            {
                'id': 'primary',
                'summary': 'Persönlich',
                'accessRole': 'owner',
                'primary': True,
                'backgroundColor': '#4986e7',
            },
        ]
    }

    with patch('app.utils.google_calendar_sync.requests.get', return_value=api_response) as mock_get:
        calendars = list_google_calendars(user.id)

    assert len(calendars) == 2
    assert calendars[0]['primary'] is True
    shared = next(c for c in calendars if c['id'] == 'shared_team@group.calendar.google.com')
    assert shared['summary'] == 'Vereinskalender (Mitglied)'
    assert shared['access_role'] == 'reader'
    assert mock_get.call_args.kwargs['headers']['Authorization'] == 'Bearer valid-token'


def test_sync_google_calendar_source_upsert_and_delete(app):
    user = _create_user('sync_user')
    save_google_calendar_connection(user, {
        'access_token': 'valid-token',
        'refresh_token': 'refresh-123',
        'expires_at': (datetime.utcnow() + timedelta(hours=1)).isoformat(),
    })
    source = CalendarSyncSource(
        name='Shared Google Calendar',
        url='google-calendar://shared_team@group.calendar.google.com',
        created_by=user.id,
        is_active=True,
    )
    db.session.add(source)
    db.session.commit()

    first_payload = MagicMock()
    first_payload.status_code = 200
    first_payload.json.return_value = {
        'items': [
            {
                'id': 'ev1',
                'iCalUID': 'ev1@google.com',
                'summary': 'Vorstandssitzung',
                'description': 'Monatliches Treffen',
                'location': 'Raum 1',
                'start': {'dateTime': '2026-06-10T18:00:00Z'},
                'end': {'dateTime': '2026-06-10T19:30:00Z'},
                'recurrence': ['RRULE:FREQ=MONTHLY;INTERVAL=1'],
            },
            {
                'id': 'ev2',
                'iCalUID': 'ev2@google.com',
                'summary': 'Sommerfest',
                'start': {'date': '2026-07-04'},
                'end': {'date': '2026-07-05'},
            },
        ]
    }

    with patch('app.utils.google_calendar_sync.requests.get', return_value=first_payload):
        ok, msg, created, updated, deleted = sync_calendar_source(source)

    assert ok is True
    assert (created, updated, deleted) == (2, 0, 0)
    events = CalendarEvent.query.filter_by(sync_source_id=source.id).order_by(CalendarEvent.ical_uid.asc()).all()
    assert len(events) == 2
    assert events[0].title == 'Vorstandssitzung'
    assert events[0].recurrence_type == 'monthly'
    assert events[1].title == 'Sommerfest'
    assert events[1].start_time.date().isoformat() == '2026-07-04'
    assert events[1].end_time.date().isoformat() == '2026-07-04'

    # Zweiter Sync: ev1 aktualisiert, ev2 gelöscht
    second_payload = MagicMock()
    second_payload.status_code = 200
    second_payload.json.return_value = {
        'items': [
            {
                'id': 'ev1',
                'iCalUID': 'ev1@google.com',
                'summary': 'Vorstandssitzung (verschoben)',
                'start': {'dateTime': '2026-06-11T18:00:00Z'},
                'end': {'dateTime': '2026-06-11T19:30:00Z'},
            },
        ]
    }

    with patch('app.utils.google_calendar_sync.requests.get', return_value=second_payload):
        ok, msg, created, updated, deleted = sync_calendar_source(source)

    assert ok is True
    assert (created, updated, deleted) == (0, 1, 1)
    remaining = CalendarEvent.query.filter_by(sync_source_id=source.id).all()
    assert len(remaining) == 1
    assert remaining[0].title == 'Vorstandssitzung (verschoben)'
