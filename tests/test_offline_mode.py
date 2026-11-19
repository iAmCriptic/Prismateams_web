"""Tests für den Offline-/Wartungsmodus und den Admin-Recovery-Zugang (/recover)."""

import pyotp

from app import db
from app.models.user import User
from app.utils.offline_mode import is_offline_mode_enabled, set_offline_mode_enabled
from app.utils.system_settings_cache import invalidate_system_settings_cache


def _create_user(*, email, password='Password123!', is_admin=False, totp_secret=None):
    user = User(
        email=email,
        first_name='Test',
        last_name='User',
        is_active=True,
        is_email_confirmed=True,
        is_admin=is_admin,
        totp_enabled=bool(totp_secret),
        totp_secret=totp_secret,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def test_offline_mode_default_disabled(app):
    invalidate_system_settings_cache()
    assert is_offline_mode_enabled() is False


def test_admin_can_toggle_offline_mode_in_system_settings(app, client):
    invalidate_system_settings_cache()
    _create_user(email='admin@example.com', is_admin=True)

    resp = client.post('/login', data={
        'email': 'admin@example.com',
        'password': 'Password123!',
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)

    resp = client.post('/settings/admin/system', data={
        'portal_name': 'Prismateams',
        'guest_email_domain': 'guest.local',
        'offline_mode_enabled': 'on',
    }, follow_redirects=False)
    assert resp.status_code in (200, 302)
    assert is_offline_mode_enabled() is True

    # Admin bleibt im Portal handlungsfähig
    admin_resp = client.get('/settings/admin/system')
    assert admin_resp.status_code == 200
    assert b'offline_mode_enabled' in admin_resp.data

    # Offline-Modus wieder deaktivieren
    resp = client.post('/settings/admin/system', data={
        'portal_name': 'Prismateams',
        'guest_email_domain': 'guest.local',
    }, follow_redirects=False)
    assert resp.status_code in (200, 302)
    assert is_offline_mode_enabled() is False


def test_offline_mode_blocks_login_and_non_admins(app, client):
    invalidate_system_settings_cache()
    _create_user(email='admin@example.com', is_admin=True)
    _create_user(email='user@example.com', is_admin=False)

    # Normaler User meldet sich zuerst an
    resp = client.post('/login', data={
        'email': 'user@example.com',
        'password': 'Password123!',
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)

    # Offline-Modus aktivieren
    set_offline_mode_enabled(True)
    db.session.commit()
    invalidate_system_settings_cache()

    # Eingeloggter Nicht-Admin wird blockiert
    resp = client.get('/dashboard')
    assert resp.status_code == 503
    assert 'Wartungsarbeiten'.encode('utf-8') in resp.data

    # API-Endpunkt liefert 503 JSON
    api_resp = client.get('/api/ping')
    assert api_resp.status_code == 503
    assert api_resp.get_json()['offline_mode'] is True

    # Ausloggen -> Login-Seite zeigt Wartungsseite statt Login-Formular
    client.post('/logout', follow_redirects=False)
    login_resp = client.get('/login')
    assert login_resp.status_code == 503
    assert 'Wartungsarbeiten'.encode('utf-8') in login_resp.data
    assert b'id="loginForm"' not in login_resp.data


def test_recover_rejects_non_admin_and_allows_admin_to_end_lockdown(app, client):
    invalidate_system_settings_cache()
    _create_user(email='admin@example.com', is_admin=True)
    _create_user(email='user@example.com', is_admin=False)

    set_offline_mode_enabled(True)
    db.session.commit()
    invalidate_system_settings_cache()

    # /recover ist erreichbar
    rec_get = client.get('/recover')
    assert rec_get.status_code == 200
    assert b'id="recoverForm"' in rec_get.data

    # Nicht-Admin wird auf /recover abgewiesen
    non_admin_post = client.post('/recover', data={
        'email': 'user@example.com',
        'password': 'Password123!',
    }, follow_redirects=True)
    assert non_admin_post.status_code == 200
    assert 'Nur Administratoren'.encode('utf-8') in non_admin_post.data
    assert b'id="recoverForm"' in non_admin_post.data

    # Admin meldet sich über /recover an
    admin_post = client.post('/recover', data={
        'email': 'admin@example.com',
        'password': 'Password123!',
    }, follow_redirects=True)
    assert admin_post.status_code == 200
    assert 'Lockdown beenden'.encode('utf-8') in admin_post.data

    # Admin beendet den Lockdown über /recover/disable
    disable_resp = client.post('/recover/disable', follow_redirects=False)
    assert disable_resp.status_code in (302, 303)
    assert is_offline_mode_enabled() is False

    # Nach Ausloggen ist /login wieder normal erreichbar
    client.post('/logout', follow_redirects=False)
    login_resp = client.get('/login')
    assert login_resp.status_code == 200
    assert b'id="loginForm"' in login_resp.data


def test_recover_supports_admin_with_2fa(app, client):
    from app.models.passkey import UserPasskey
    UserPasskey.__table__.create(db.engine, checkfirst=True)
    invalidate_system_settings_cache()
    secret = pyotp.random_base32()
    _create_user(email='admin2fa@example.com', is_admin=True, totp_secret=secret)

    set_offline_mode_enabled(True)
    db.session.commit()
    invalidate_system_settings_cache()

    resp = client.post('/recover', data={
        'email': 'admin2fa@example.com',
        'password': 'Password123!',
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert '/login/2fa' in resp.location

    # /login/2fa ist im Offline-Modus für den Recovery-Flow erreichbar
    twofa_get = client.get('/login/2fa')
    assert twofa_get.status_code == 200

    code = pyotp.TOTP(secret).now()
    twofa_post = client.post('/login/2fa', data={'totp_code': code}, follow_redirects=True)
    assert twofa_post.status_code == 200
    assert 'Lockdown beenden'.encode('utf-8') in twofa_post.data
