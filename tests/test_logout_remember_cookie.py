"""Regressionstests für Logout und Remember-Me-Cookie-Löschung (kein Redirect-Loop)."""

from app import db
from app.models.user import User


def _create_user(email='logout-test@example.com', password='Password123!'):
    user = User(
        email=email,
        first_name='Logout',
        last_name='Tester',
        is_active=True,
        is_email_confirmed=True,
        is_admin=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def _has_cookie(client, name):
    return client.get_cookie(name) is not None


def test_logout_with_remember_me_deletes_cookie_and_avoids_redirect_loop(app, client):
    _create_user()

    login_resp = client.post(
        '/login',
        data={
            'email': 'logout-test@example.com',
            'password': 'Password123!',
            'remember': 'on',
        },
        follow_redirects=False,
    )
    assert login_resp.status_code in (302, 303)
    remember_cookie_name = app.config.get('REMEMBER_COOKIE_NAME', 'remember_token')
    assert _has_cookie(client, remember_cookie_name)

    logout_resp = client.post('/logout', follow_redirects=True)
    assert logout_resp.status_code == 200
    assert logout_resp.request.path == '/login'
    assert not _has_cookie(client, remember_cookie_name)


def test_api_logout_with_remember_me_deletes_cookie(app, client):
    _create_user(email='api-logout@example.com')

    login_resp = client.post(
        '/login',
        data={
            'email': 'api-logout@example.com',
            'password': 'Password123!',
            'remember': 'on',
        },
        follow_redirects=False,
    )
    assert login_resp.status_code in (302, 303)
    remember_cookie_name = app.config.get('REMEMBER_COOKIE_NAME', 'remember_token')
    assert _has_cookie(client, remember_cookie_name)

    logout_resp = client.post('/api/auth/logout')
    assert logout_resp.status_code == 200
    assert not _has_cookie(client, remember_cookie_name)

    login_page = client.get('/login', follow_redirects=False)
    assert login_page.status_code == 200


def test_missing_session_id_with_remember_cookie_clears_cookie_without_loop(app, client):
    _create_user(email='stale-remember@example.com')

    login_resp = client.post(
        '/login',
        data={
            'email': 'stale-remember@example.com',
            'password': 'Password123!',
            'remember': 'on',
        },
        follow_redirects=False,
    )
    assert login_resp.status_code in (302, 303)
    remember_cookie_name = app.config.get('REMEMBER_COOKIE_NAME', 'remember_token')
    assert _has_cookie(client, remember_cookie_name)

    # Simuliere verlorene/abgelaufene server-seitige Session bei vorhandenem Remember-Cookie
    with client.session_transaction() as sess:
        sess.pop('session_id', None)

    resp = client.get('/login', follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/login'
    assert not _has_cookie(client, remember_cookie_name)
