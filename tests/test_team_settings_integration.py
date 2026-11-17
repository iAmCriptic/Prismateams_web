import os
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

import pytest
from app import create_app, db
from app.models.user import User
from app.models.team import Team, TeamMember
from app.models.settings import SystemSettings
from app.utils.team_module_settings import is_team_section_enabled, set_team_section_enabled

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

@pytest.fixture
def client(app):
    return app.test_client()

def _enable_global_team_module():
    s = SystemSettings.query.filter_by(key='global_team_enabled').first()
    if s:
        s.value = 'true'
    else:
        db.session.add(SystemSettings(key='global_team_enabled', value='true'))
    # ensure module_wiki and module_credentials are on
    for m in ('module_wiki', 'module_credentials'):
        ms = SystemSettings.query.filter_by(key=m).first()
        if ms:
            ms.value = 'true'
        else:
            db.session.add(SystemSettings(key=m, value='true'))
    db.session.commit()

def _login(client, email='admin@test.local', password='Password123!@#'):
    return client.post('/login', data={
        'email': email,
        'password': password,
    }, follow_redirects=True)

def test_team_detail_page_loads_with_modules(client, app):
    with app.app_context():
        _enable_global_team_module()
        user = User(
            first_name='Admin',
            last_name='User',
            email='admin@test.local',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True,
        )
        user.set_password('Password123!@#')
        db.session.add(user)
        db.session.commit()

        team = Team(
            name='Test Portal Team',
            description='Testing portal design',
            color='#3498db',
            leader_id=user.id
        )
        db.session.add(team)
        db.session.commit()
        db.session.add(TeamMember(team_id=team.id, user_id=user.id))
        db.session.commit()
        team_id = team.id

    _login(client, 'admin@test.local', 'Password123!@#')

    response = client.get(f'/settings/admin/teams/{team_id}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Test Portal Team' in html
    assert 'sp-page' in html and 'settings-admin-teams' in html
    assert 'team-modules' in html
    assert 'team_module_wiki' in html
    assert 'sp-group' in html

def test_team_modules_update_post(client, app):
    with app.app_context():
        _enable_global_team_module()
        user = User(
            first_name='Admin',
            last_name='User',
            email='admin@test.local',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True,
        )
        user.set_password('Password123!@#')
        db.session.add(user)
        db.session.commit()

        team = Team(
            name='Test Portal Team',
            description='Testing portal design',
            color='#3498db',
            leader_id=user.id
        )
        db.session.add(team)
        db.session.commit()
        team_id = team.id

    _login(client, 'admin@test.local', 'Password123!@#')

    # Disable wiki, enable credentials
    post_data = {
        'action': 'update_team_modules',
        'team_module_credentials': 'on',
    }
    response = client.post(
        f'/settings/admin/teams/{team_id}',
        data=post_data,
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['ok'] is True

    # Verify state in database
    with app.app_context():
        assert is_team_section_enabled(team_id, 'wiki') is False
        assert is_team_section_enabled(team_id, 'credentials') is True

def test_legacy_team_settings_route_redirects(client, app):
    with app.app_context():
        user = User(
            first_name='Admin',
            last_name='User',
            email='admin@test.local',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True,
        )
        user.set_password('Password123!@#')
        db.session.add(user)
        db.session.commit()

        team = Team(
            name='Test Portal Team',
            description='Testing portal design',
            color='#3498db',
            leader_id=user.id
        )
        db.session.add(team)
        db.session.commit()
        team_id = team.id

    _login(client, 'admin@test.local', 'Password123!@#')

    response = client.get(f'/settings/team-settings?team_id={team_id}')
    assert response.status_code in (301, 302)
    assert f'/settings/admin/teams/{team_id}' in response.location

def test_member_profile_picture_rendered(client, app):
    with app.app_context():
        _enable_global_team_module()
        user = User(
            first_name='Photo',
            last_name='User',
            email='photo@test.local',
            profile_picture='avatar_test.png',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True,
        )
        user.set_password('Password123!@#')
        db.session.add(user)
        db.session.commit()

        team = Team(name='Photo Team', leader_id=user.id)
        db.session.add(team)
        db.session.commit()
        db.session.add(TeamMember(team_id=team.id, user_id=user.id))
        db.session.commit()
        team_id = team.id

    _login(client, 'photo@test.local', 'Password123!@#')

    res = client.get(f'/settings/admin/teams/{team_id}')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'avatar_test.png' in html
    assert 'sp-dir-card__avatar--img' in html


def test_system_settings_toggle_team_invite_portal_user(client, app):
    with app.app_context():
        user = User(
            first_name='Admin',
            last_name='System',
            email='admin@test.local',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True,
        )
        user.set_password('Password123!@#')
        db.session.add(user)
        db.session.commit()

    _login(client, 'admin@test.local', 'Password123!@#')

    # GET admin_system
    res = client.get('/settings/admin/system')
    assert res.status_code == 200
    assert 'team_invite_allow_portal_user' in res.get_data(as_text=True)

    # POST admin_system with team_invite_allow_portal_user=on
    res_post = client.post('/settings/admin/system', data={
        'portal_name': 'TestPortal',
        'guest_email_domain': 'guest.local',
        'team_invite_allow_portal_user': 'on',
    }, follow_redirects=True)
    assert res_post.status_code == 200

    with app.app_context():
        from app.models.team import is_team_invite_portal_user_allowed
        assert is_team_invite_portal_user_allowed() is True


def test_team_invite_portal_user_vs_team_only_registration(client, app):
    from app.models.team import TeamInviteCode

    with app.app_context():
        _enable_global_team_module()
        # Enable setting
        from app.utils.system_settings_cache import invalidate_system_settings_cache
        s = SystemSettings.query.filter_by(key='team_invite_allow_portal_user').first()
        if s:
            s.value = 'True'
        else:
            db.session.add(SystemSettings(key='team_invite_allow_portal_user', value='True'))
        db.session.commit()
        invalidate_system_settings_cache()

        admin = User(
            first_name='Admin',
            last_name='Boss',
            email='admin@test.local',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True,
        )
        admin.set_password('Password123!@#')
        db.session.add(admin)
        db.session.commit()

        team = Team(name='Invite Test Team', leader_id=admin.id)
        db.session.add(team)
        db.session.commit()
        team_id = team.id

        # Code 1: portal_user
        invite_portal = TeamInviteCode(
            code='PORTAL123',
            team_id=team.id,
            created_by_id=admin.id,
            role='portal_user',
            is_active=True,
        )
        # Code 2: team_only
        invite_team_only = TeamInviteCode(
            code='TEAMONLY1',
            team_id=team.id,
            created_by_id=admin.id,
            role='team_only',
            is_active=True,
        )
        db.session.add(invite_portal)
        db.session.add(invite_team_only)
        db.session.commit()

    # 1. Register with portal_user invite
    res_reg1 = client.post('/coderegister', data={
        'invite_code': 'PORTAL123',
        'email': 'portaluser@test.local',
        'first_name': 'New',
        'last_name': 'Colleague',
        'password': 'Password123!@#',
        'password_confirm': 'Password123!@#',
    }, follow_redirects=True)
    assert res_reg1.status_code == 200

    # 2. Register with team_only invite
    res_reg2 = client.post('/coderegister', data={
        'invite_code': 'TEAMONLY1',
        'email': 'teamonly@test.local',
        'first_name': 'Guest',
        'last_name': 'Worker',
        'password': 'Password123!@#',
        'password_confirm': 'Password123!@#',
    }, follow_redirects=True)
    assert res_reg2.status_code == 200

    with app.app_context():
        u_portal = User.query.filter_by(email='portaluser@test.local').first()
        assert u_portal is not None
        assert u_portal.can_access_public is True
        assert u_portal.can_access_private is True
        assert u_portal.can_access_team is True
        assert u_portal.is_guest is False
        assert any(m.team_id == team_id for m in u_portal.team_memberships)

        u_team = User.query.filter_by(email='teamonly@test.local').first()
        assert u_team is not None
        assert u_team.can_access_public is False
        assert u_team.can_access_private is False
        assert u_team.can_access_team is True
        assert any(m.team_id == team_id for m in u_team.team_memberships)
