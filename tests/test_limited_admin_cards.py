"""Tests für limitierten Admin-Zugriff auf einzelne Einstellungs-Karten."""

from app import db
from app.models.role import UserAdminCardPermission
from app.models.settings import SystemSettings
from app.models.user import User
from app.utils.admin_cards import has_admin_card_access, has_any_admin_card_access
from app.utils.helpers_seed import ensure_initial_helper_event


def _make_user(email, is_admin=False, is_guest=False):
    user = User(
        email=email,
        first_name='Test',
        last_name='User',
        is_admin=is_admin,
        is_guest=is_guest,
        is_email_confirmed=True,
        has_full_access=True,
        is_active=True,
    )
    user.set_password('secret123')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user):
    client.post('/logout', follow_redirects=True)
    resp = client.post(
        '/login',
        data={'email': user.email, 'password': 'secret123'},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def _enable_module(key):
    s = SystemSettings.query.filter_by(key=key).first()
    if s is None:
        db.session.add(SystemSettings(key=key, value='true'))
    else:
        s.value = 'true'
    db.session.commit()


def test_limited_admin_helpers_access_and_isolation(app, client):
    _enable_module('module_helpers')
    ev = ensure_initial_helper_event()
    admin = _make_user('admin@example.com', is_admin=True)
    helper_mgr = _make_user('helper_mgr@example.com', is_admin=False)

    # Without limited admin card: denied
    assert not has_admin_card_access(helper_mgr, 'admin_helpers')
    assert not has_any_admin_card_access(helper_mgr)

    _login(client, helper_mgr)
    resp = client.get('/settings/admin/helpers', follow_redirects=False)
    assert resp.status_code == 302
    resp_sys = client.get('/settings/admin/system', follow_redirects=False)
    assert resp_sys.status_code == 302

    # Admin grants 'admin_helpers' to helper_mgr
    _login(client, admin)
    upd = client.post(
        f'/settings/admin/roles/user/{helper_mgr.id}/update',
        data={
            'has_full_access': 'on',
            'can_access_public': 'on',
            'can_access_team': 'on',
            'can_access_private': 'on',
            'admin_card': ['admin_helpers'],
        },
    )
    assert upd.status_code == 200
    assert upd.get_json()['success'] is True

    db.session.refresh(helper_mgr)
    assert has_admin_card_access(helper_mgr, 'admin_helpers')
    assert has_any_admin_card_access(helper_mgr)
    assert not has_admin_card_access(helper_mgr, 'admin_system')

    # helper_mgr can now access /settings/admin/helpers and helpers blueprint admin routes
    _login(client, helper_mgr)
    hub_resp = client.get('/settings/')
    assert hub_resp.status_code == 200
    assert b'/settings/admin/helpers' in hub_resp.data
    assert b'/settings/admin/system' not in hub_resp.data

    helpers_resp = client.get('/settings/admin/helpers')
    assert helpers_resp.status_code == 200

    # Still blocked from other admin cards
    sys_resp = client.get('/settings/admin/system', follow_redirects=False)
    assert sys_resp.status_code == 302
    users_resp = client.get('/settings/admin/users', follow_redirects=False)
    assert users_resp.status_code == 302

    # Helpers blueprint _require_admin allows helper_mgr
    ev_resp = client.get(f'/helfer/event/{ev.id}/settings')
    assert ev_resp.status_code == 200


def test_limited_admin_users_cannot_escalate_privileges(app, client):
    user_mgr = _make_user('usermgr@example.com', is_admin=False)
    target = _make_user('target@example.com', is_admin=False)
    guest = _make_user('guest@example.com', is_admin=False, is_guest=True)

    db.session.add(UserAdminCardPermission(user_id=user_mgr.id, card_key='admin_users'))
    db.session.commit()

    _login(client, user_mgr)
    # Can view user management
    assert client.get('/settings/admin/users').status_code == 200

    # Cannot make target a full admin
    client.post(f'/settings/admin/users/{target.id}/make-admin', follow_redirects=False)
    db.session.refresh(target)
    assert target.is_admin is False

    # Cannot grant admin_card permissions via admin_roles_user_update
    upd = client.post(
        f'/settings/admin/roles/user/{target.id}/update',
        data={
            'has_full_access': 'on',
            'can_access_public': 'on',
            'can_access_team': 'on',
            'can_access_private': 'on',
            'admin_card': ['admin_system', 'admin_helpers'],
        },
    )
    assert upd.status_code == 200
    assert UserAdminCardPermission.query.filter_by(user_id=target.id).count() == 0

    # Even full admin cannot grant admin cards to guest accounts
    admin = _make_user('fulladmin@example.com', is_admin=True)
    _login(client, admin)
    client.post(
        f'/settings/admin/roles/user/{guest.id}/update',
        data={'admin_card': ['admin_helpers']},
    )
    assert UserAdminCardPermission.query.filter_by(user_id=guest.id).count() == 0
