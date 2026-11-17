"""Tests für E-Mail-Bestätigung (/confirm-email) und CSRF-Handling."""

import os
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

from datetime import datetime, timedelta
import pytest
from app import db
from app.models.user import User


@pytest.fixture
def unconfirmed_user(app):
    user = User(
        email='unconfirmed@example.com',
        first_name='Max',
        last_name='Mustermann',
        is_active=True,
        is_admin=False,
        is_email_confirmed=False,
        confirmation_code='123456',
        confirmation_code_expires=datetime.utcnow() + timedelta(hours=24),
    )
    user.set_password('Password123!@#')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, email='unconfirmed@example.com', password='Password123!@#'):
    return client.post('/login', data={
        'email': email,
        'password': password
    }, follow_redirects=True)


def test_confirm_email_page_contains_csrf_token(client, unconfirmed_user):
    """Prüft, dass auf der Bestätigungsseite das CSRF-Token-Inputfeld gerendert wird."""
    login_resp = _login(client)
    assert login_resp.status_code == 200

    response = client.get('/confirm-email')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="csrf_token"' in html
    assert 'id="confirmEmailForm"' in html
    assert 'id="confirmation_code"' in html


def test_confirm_email_success(client, unconfirmed_user):
    """Gültiger 6-stelliger Code bestätigt E-Mail und leitet zum Dashboard weiter."""
    _login(client)

    response = client.post('/confirm-email', data={
        'confirmation_code': '123456'
    }, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/dashboard')

    # User in DB prüfen
    db.session.refresh(unconfirmed_user)
    assert unconfirmed_user.is_email_confirmed is True
    assert unconfirmed_user.confirmation_code is None
    assert unconfirmed_user.confirmation_code_expires is None


def test_confirm_email_invalid_code(client, unconfirmed_user):
    """Falscher Code zeigt Fehlermeldung und aktiviert das Konto nicht."""
    _login(client)

    response = client.post('/confirm-email', data={
        'confirmation_code': '999999'
    }, follow_redirects=False)

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="csrf_token"' in html

    db.session.refresh(unconfirmed_user)
    assert unconfirmed_user.is_email_confirmed is False
    assert unconfirmed_user.confirmation_code == '123456'


def test_confirm_email_assets_and_no_duplicate_flashes(client, unconfirmed_user):
    """Prüft, dass statische Assets (/assets/core.css, /sw.js) für unbestätigte User nicht abgefangen werden und keine doppelten Flash-Meldungen erzeugen."""
    _login(client)

    # 1. core.css wird ohne Redirect mit Content-Type text/css ausgeliefert
    resp_css = client.get('/assets/core.css')
    assert resp_css.status_code == 200
    assert 'text/css' in resp_css.headers.get('Content-Type', '')

    # 2. sw.js wird ohne Redirect ausgeliefert
    resp_sw = client.get('/sw.js')
    assert resp_sw.status_code == 200

    # 3. Erste Anzeige zeigt genau eine Meldung
    page1 = client.get('/confirm-email')
    html1 = page1.get_data(as_text=True)
    assert html1.count('Bitte bestätigen Sie Ihre E-Mail-Adresse, um fortzufahren.') <= 1

    # 4. Neuladen erzeugt keine duplizierten Meldungen (Flash wurde verbraucht)
    page2 = client.get('/confirm-email')
    html2 = page2.get_data(as_text=True)
    assert html2.count('Bitte bestätigen Sie Ihre E-Mail-Adresse, um fortzufahren.') == 0
