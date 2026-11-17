"""Tests for calendar sidebar visibility of Public, Teams, and Person calendars."""

import os
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

import pytest
from app import create_app, db
from app.models.user import User
from app.models.team import Team, TeamMember
from app.models.calendar import Calendar
from app.models.settings import SystemSettings
from app.utils.multi_calendars import (
    list_sidebar_calendars,
    is_calendar_multi_enabled,
    is_calendar_personal_enabled,
    is_calendar_team_enabled,
    is_calendar_public_enabled,
)
from app.blueprints.calendar.helpers import _sidebar_context
from app.utils.system_settings_cache import invalidate_system_settings_cache


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


def _set_setting(key, value):
    s = SystemSettings.query.filter_by(key=key).first()
    if s:
        s.value = str(value)
    else:
        db.session.add(SystemSettings(key=key, value=str(value)))
    db.session.commit()
    invalidate_system_settings_cache()


def test_calendar_sidebar_all_active(app):
    with app.test_request_context('/calendar/'):
        u1 = User(email='alice@example.com', password_hash='hash', first_name='Alice', last_name='Smith', is_active=True)
        u2 = User(email='bob@example.com', password_hash='hash', first_name='Bob', last_name='Jones', is_active=True)
        u_inactive = User(email='old@example.com', password_hash='hash', first_name='Inactive', last_name='User', is_active=False)
        db.session.add_all([u1, u2, u_inactive])
        db.session.commit()

        team = Team(name='Marketing')
        db.session.add(team)
        db.session.commit()
        db.session.add(TeamMember(team_id=team.id, user_id=u1.id))
        db.session.commit()

        _set_setting('modules_allow_public', 'true')
        _set_setting('modules_allow_private', 'true')
        _set_setting('modules_allow_team', 'true')
        _set_setting('calendar_public_enabled', 'true')
        _set_setting('calendar_personal_enabled', 'true')
        _set_setting('calendar_team_enabled', 'true')

        ctx = _sidebar_context(u1)
        sc = ctx['sidebar_calendars']

        # Public calendar is listed
        public_names = [p['name'] for p in sc['publics']]
        assert 'Public' in public_names

        # Team calendar is listed
        team_names = [t['name'] for t in sc['teams']]
        assert 'Marketing' in team_names

        # Own personal calendar is listed in personals
        personal_names = [p['name'] for p in sc['personals']]
        assert len(personal_names) >= 1

        # Other active person calendar is listed in others
        other_names = [o['name'] for o in sc['others']]
        assert 'Bob Jones' in other_names
        # Inactive user is NOT listed
        assert 'Inactive User' not in other_names


def test_calendar_sidebar_public_inactive(app):
    with app.test_request_context('/calendar/'):
        u1 = User(email='alice@example.com', password_hash='hash', first_name='Alice', last_name='Smith', is_active=True)
        u2 = User(email='bob@example.com', password_hash='hash', first_name='Bob', last_name='Jones', is_active=True)
        db.session.add_all([u1, u2])
        db.session.commit()

        team = Team(name='Sales')
        db.session.add(team)
        db.session.commit()
        db.session.add(TeamMember(team_id=team.id, user_id=u1.id))
        db.session.commit()

        _set_setting('modules_allow_public', 'false')
        _set_setting('modules_allow_private', 'true')
        _set_setting('modules_allow_team', 'true')
        _set_setting('calendar_public_enabled', 'false')
        _set_setting('calendar_personal_enabled', 'true')
        _set_setting('calendar_team_enabled', 'true')

        ctx = _sidebar_context(u1)
        sc = ctx['sidebar_calendars']

        # Public calendar is NOT listed
        assert len(sc['publics']) == 0
        assert sc['public'] is None

        # Teams and personals are still listed
        assert len(sc['teams']) == 1
        assert len(sc['personals']) >= 1
        assert 'Bob Jones' in [o['name'] for o in sc['others']]


def test_calendar_sidebar_teams_inactive(app):
    with app.test_request_context('/calendar/'):
        u1 = User(email='alice@example.com', password_hash='hash', first_name='Alice', last_name='Smith', is_active=True)
        db.session.add(u1)
        db.session.commit()

        team = Team(name='Dev')
        db.session.add(team)
        db.session.commit()
        db.session.add(TeamMember(team_id=team.id, user_id=u1.id))
        db.session.commit()

        _set_setting('modules_allow_public', 'true')
        _set_setting('modules_allow_private', 'true')
        _set_setting('modules_allow_team', 'false')
        _set_setting('calendar_public_enabled', 'true')
        _set_setting('calendar_personal_enabled', 'true')
        _set_setting('calendar_team_enabled', 'false')

        ctx = _sidebar_context(u1)
        sc = ctx['sidebar_calendars']

        # Teams are NOT listed
        assert len(sc['teams']) == 0

        # Public and personal are listed
        assert len(sc['publics']) >= 1
        assert len(sc['personals']) >= 1


def test_calendar_sidebar_private_inactive(app):
    with app.test_request_context('/calendar/'):
        u1 = User(email='alice@example.com', password_hash='hash', first_name='Alice', last_name='Smith', is_active=True)
        u2 = User(email='bob@example.com', password_hash='hash', first_name='Bob', last_name='Jones', is_active=True)
        db.session.add_all([u1, u2])
        db.session.commit()

        team = Team(name='Finance')
        db.session.add(team)
        db.session.commit()
        db.session.add(TeamMember(team_id=team.id, user_id=u1.id))
        db.session.commit()

        _set_setting('modules_allow_public', 'true')
        _set_setting('modules_allow_private', 'false')
        _set_setting('modules_allow_team', 'true')
        _set_setting('calendar_public_enabled', 'true')
        _set_setting('calendar_personal_enabled', 'false')
        _set_setting('calendar_team_enabled', 'true')

        ctx = _sidebar_context(u1)
        sc = ctx['sidebar_calendars']

        # Personal is NOT listed
        assert len(sc['personals']) == 0
        assert sc['personal'] is None

        # Other persons are NOT listed in others
        person_others = [o for o in sc['others'] if o['calendar_type'] == 'personal']
        assert len(person_others) == 0

        # Public and teams are listed
        assert len(sc['publics']) >= 1
        assert len(sc['teams']) == 1
