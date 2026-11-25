import os
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from app import create_app, db
from app.models.team import Team, TeamInviteCode
from app.models.user import User
from app.tasks.invite_account_cleanup import cleanup_expired_invite_accounts


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
        import app.models  # noqa: F401
        import app.models.passkey  # noqa: F401
        db.create_all()
        yield app_instance
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _create_admin_and_team():
    admin = User(
        email='admin@test.local',
        first_name='Admin',
        last_name='User',
        is_active=True,
        is_admin=True,
        is_super_admin=True,
        is_email_confirmed=True,
    )
    admin.set_password('Password123!@#')
    db.session.add(admin)
    team = Team(name='Invite Lifecycle Team')
    db.session.add(team)
    db.session.commit()
    return admin, team


def _login(client, email='admin@test.local', password='Password123!@#'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


def test_register_page_has_invite_code_button(client, app):
    with app.app_context():
        _create_admin_and_team()
    res = client.get('/register')
    assert res.status_code == 200
    assert b'/coderegister' in res.data
    assert b'Mit Einladungscode' in res.data


def test_invite_code_account_active_until_create_register_and_cleanup(client, app):
    with app.app_context():
        admin, team = _create_admin_and_team()
        team_id = team.id

    _login(client)
    res_create = client.post(
        f'/settings/admin/teams/{team_id}',
        data={
            'action': 'create_invite_code',
            'account_active_until': '2027-07-31',
        },
        follow_redirects=True,
    )
    assert res_create.status_code == 200

    with app.app_context():
        invite = TeamInviteCode.query.filter_by(team_id=team_id).first()
        assert invite is not None
        assert invite.account_active_until == date(2027, 7, 31)
        code = invite.code

    # Logout admin before registering via coderegister
    client.post('/logout', follow_redirects=True)

    res_reg = client.post(
        '/coderegister',
        data={
            'invite_code': code,
            'email': 'tempuser@test.local',
            'first_name': 'Temp',
            'last_name': 'User',
            'password': 'TempUserPass123!@#',
            'password_confirm': 'TempUserPass123!@#',
        },
        follow_redirects=True,
    )
    assert res_reg.status_code == 200

    with app.app_context():
        u = User.query.filter_by(email='tempuser@test.local').first()
        assert u is not None
        assert u.is_active is True
        assert u.account_active_until == date(2027, 7, 31)
        assert u.auto_deactivated_at is None

        # On 2027-07-31: still allowed to stay active
        with patch('app.tasks.invite_account_cleanup.portal_now_naive', return_value=datetime(2027, 7, 31, 23, 55)):
            cleanup_expired_invite_accounts()
        u = User.query.filter_by(email='tempuser@test.local').first()
        assert u.is_active is True
        assert u.auto_deactivated_at is None

        # On 2027-08-01: deactivated
        with patch('app.tasks.invite_account_cleanup.portal_now_naive', return_value=datetime(2027, 8, 1, 0, 5)):
            cleanup_expired_invite_accounts()
        u = User.query.filter_by(email='tempuser@test.local').first()
        assert u.is_active is False
        assert u.auto_deactivated_at is not None

        # Simulate 6 days after deactivation: NOT deleted yet
        u.auto_deactivated_at = datetime.utcnow() - timedelta(days=6)
        db.session.commit()
        with patch('app.tasks.invite_account_cleanup.portal_now_naive', return_value=datetime(2027, 8, 7, 12, 0)):
            cleanup_expired_invite_accounts()
        assert User.query.filter_by(email='tempuser@test.local').first() is not None

        # Simulate 7 days after deactivation: deleted
        u = User.query.filter_by(email='tempuser@test.local').first()
        u.auto_deactivated_at = datetime.utcnow() - timedelta(days=7, minutes=1)
        db.session.commit()
        with patch('app.tasks.invite_account_cleanup.portal_now_naive', return_value=datetime(2027, 8, 8, 0, 5)):
            cleanup_expired_invite_accounts()
        assert User.query.filter_by(email='tempuser@test.local').first() is None


def test_reactivated_user_is_not_deleted(client, app):
    with app.app_context():
        _create_admin_and_team()
        u = User(
            email='reactivate@test.local',
            first_name='React',
            last_name='User',
            is_active=False,
            is_email_confirmed=True,
            account_active_until=date(2020, 1, 1),
            auto_deactivated_at=datetime.utcnow() - timedelta(days=5),
        )
        u.set_password('Password123!@#')
        db.session.add(u)
        db.session.commit()
        uid = u.id

    _login(client)
    res = client.post(f'/settings/admin/users/{uid}/activate', follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        u = User.query.get(uid)
        assert u.is_active is True
        assert u.auto_deactivated_at is None
        assert u.account_active_until is None

        cleanup_expired_invite_accounts()
        u = User.query.get(uid)
        assert u is not None
        assert u.is_active is True
