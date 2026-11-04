"""Tests for team calendar deduplication and single team calendar enforcement."""

import os
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

from datetime import datetime, timedelta
import pytest

from app import create_app, db
from app.models.user import User
from app.models.team import Team, TeamMember
from app.models.calendar import Calendar, CalendarEvent
from app.models.settings import SystemSettings
from app.utils.multi_calendars import (
    get_or_create_team_calendar,
    list_team_calendars_for_user,
    create_extra_calendar,
    can_delete_calendar_row,
)


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


def test_get_or_create_team_calendar_deduplicates(app):
    """When a team has multiple calendars, get_or_create_team_calendar consolidates them into one."""
    user = User(email='test@example.com', first_name='Test', last_name='User')
    user.set_password('password123')
    db.session.add(user)
    team = Team(name='Sommerfestkomitee', color='#123456')
    db.session.add(team)
    db.session.commit()

    # Manually create 3 calendars for this team (simulating the bug/duplicates)
    cal1 = Calendar(name='Sommerfestkomitee', calendar_type='team', team_id=team.id, is_default=True)
    cal2 = Calendar(name='Sommerfestkomitee', calendar_type='team', team_id=team.id, is_default=False)
    cal3 = Calendar(name='Sommerfestkomitee', calendar_type='team', team_id=team.id, is_default=False)
    db.session.add_all([cal1, cal2, cal3])
    db.session.commit()

    # Add events to cal2 and cal3
    now = datetime.utcnow()
    ev1 = CalendarEvent(title='Event on cal2', start_time=now, end_time=now + timedelta(hours=1), created_by=user.id, calendar_id=cal2.id)
    ev2 = CalendarEvent(title='Event on cal3', start_time=now, end_time=now + timedelta(hours=2), created_by=user.id, calendar_id=cal3.id)
    db.session.add_all([ev1, ev2])
    db.session.commit()

    # Now call get_or_create_team_calendar
    single_cal = get_or_create_team_calendar(team)
    db.session.commit()

    assert single_cal is not None
    assert single_cal.id == cal1.id
    assert single_cal.name == 'Sommerfestkomitee'
    assert single_cal.is_default is True

    # Check only 1 calendar remains for this team
    remaining_cals = Calendar.query.filter_by(calendar_type='team', team_id=team.id).all()
    assert len(remaining_cals) == 1

    # Check events were moved to the primary calendar
    assert CalendarEvent.query.filter_by(calendar_id=single_cal.id).count() == 2


def test_list_team_calendars_for_user_returns_exactly_one_per_team(app):
    """list_team_calendars_for_user returns at most one calendar per team."""
    _set_setting('calendar_team_enabled', 'true')
    _set_setting('module_calendar_enabled', 'true')

    user = User(email='member@example.com', first_name='Team', last_name='Member')
    user.set_password('password123')
    db.session.add(user)
    team = Team(name='Sommerfestkomitee', color='#654321')
    db.session.add(team)
    db.session.flush()

    member = TeamMember(team_id=team.id, user_id=user.id)
    db.session.add(member)

    # 3 duplicate calendars in DB
    cal1 = Calendar(name='Sommerfestkomitee', calendar_type='team', team_id=team.id, is_default=True)
    cal2 = Calendar(name='Sommerfestkomitee', calendar_type='team', team_id=team.id, is_default=False)
    cal3 = Calendar(name='Sommerfestkomitee', calendar_type='team', team_id=team.id, is_default=False)
    db.session.add_all([cal1, cal2, cal3])
    db.session.commit()

    team_cals = list_team_calendars_for_user(user)
    assert len(team_cals) == 1
    assert team_cals[0].id == cal1.id


def test_create_extra_calendar_disallows_team(app):
    """Users cannot create extra calendars for teams."""
    user = User(email='creator@example.com', first_name='Creator', last_name='User')
    user.set_password('password123')
    db.session.add(user)
    team = Team(name='Sommerfestkomitee')
    db.session.add(team)
    db.session.commit()

    cal, err = create_extra_calendar(user, 'Another Calendar', 'team', team_id=team.id)
    assert cal is None
    assert err == 'invalid_type'


def test_can_delete_calendar_row_prevents_team_calendar_deletion(app):
    """Team calendars cannot be deleted from the calendar interface."""
    user = User(email='admin@example.com', first_name='Admin', last_name='User', is_admin=True)
    user.set_password('password123')
    db.session.add(user)
    team = Team(name='Sommerfestkomitee')
    db.session.add(team)
    db.session.flush()
    cal = Calendar(name='Sommerfestkomitee', calendar_type='team', team_id=team.id, is_default=True)
    db.session.add(cal)
    db.session.commit()

    assert can_delete_calendar_row(user, cal) is False


def test_migration_3_4_13_handles_duplicate_teams_and_calendars(app):
    """Test that migration 3.4.13 merges duplicate teams and deduplicates calendars."""
    from migrations.migrate_to_3_4_13 import run as run_migration

    user = User(email='test_mig@example.com', first_name='Mig', last_name='User')
    user.set_password('password123')
    db.session.add(user)

    # 2 teams with the exact same name (simulating user accidentally creating team multiple times)
    t1 = Team(name='Sommerfestkomitee', leader_id=user.id)
    t2 = Team(name='Sommerfestkomitee ')
    db.session.add_all([t1, t2])
    db.session.flush()

    c1 = Calendar(name='Sommerfestkomitee', calendar_type='team', team_id=t1.id, is_default=True)
    c2 = Calendar(name='Sommerfestkomitee', calendar_type='team', team_id=t1.id, is_default=False)
    c3 = Calendar(name='Sommerfestkomitee', calendar_type='team', team_id=t2.id, is_default=True)
    db.session.add_all([c1, c2, c3])
    db.session.commit()

    now = datetime.utcnow()
    ev1 = CalendarEvent(title='Event 1', start_time=now, end_time=now + timedelta(hours=1), created_by=user.id, calendar_id=c1.id)
    ev2 = CalendarEvent(title='Event 2', start_time=now, end_time=now + timedelta(hours=1), created_by=user.id, calendar_id=c2.id)
    ev3 = CalendarEvent(title='Event 3', start_time=now, end_time=now + timedelta(hours=1), created_by=user.id, calendar_id=c3.id)
    db.session.add_all([ev1, ev2, ev3])
    db.session.commit()

    # Run the migration
    run_migration(db)

    # Exactly 1 team named Sommerfestkomitee should remain
    teams = Team.query.filter_by(name='Sommerfestkomitee').all()
    assert len(teams) == 1
    canonical = teams[0]

    # Exactly 1 calendar should exist for this team
    cals = Calendar.query.filter_by(calendar_type='team', team_id=canonical.id).all()
    assert len(cals) == 1
    assert cals[0].is_default is True

    # All 3 events should now belong to this single calendar
    assert CalendarEvent.query.filter_by(calendar_id=cals[0].id).count() == 3
