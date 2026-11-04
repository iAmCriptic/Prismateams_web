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
        is_email_confirmed=False,
        confirmation_code='123456',
        confirmation_code_expires=datetime.utcnow() + timedelta(hours=24),
    )
    user.set_password('Password123!@#')
    db.session.add(user)
    db.session.commit()
    return user


def test_confirm_email_page_contains_csrf_token(client, unconfirmed_user):
    """Prüft, dass auf der Bestätigungsseite das CSRF-Token-Inputfeld gerendert wird."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(unconfirmed_user.id)
        sess['user_scope'] = 'portal'

    response = client.get('/confirm-email')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="csrf_token"' in html
    assert 'id="confirmEmailForm"' in html
    assert 'id="confirmation_code"' in html


def test_confirm_email_success(client, unconfirmed_user):
    """Gültiger 6-stelliger Code bestätigt E-Mail und leitet zum Dashboard weiter."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(unconfirmed_user.id)
        sess['user_scope'] = 'portal'

    response = client.post('/confirm-email', data={
        'confirmation_code': '123456'
    }, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/')

    # User in DB prüfen
    db.session.refresh(unconfirmed_user)
    assert unconfirmed_user.is_email_confirmed is True
    assert unconfirmed_user.confirmation_code is None
    assert unconfirmed_user.confirmation_code_expires is None


def test_confirm_email_invalid_code(client, unconfirmed_user):
    """Falscher Code zeigt Fehlermeldung und aktiviert das Konto nicht."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(unconfirmed_user.id)
        sess['user_scope'] = 'portal'

    response = client.post('/confirm-email', data={
        'confirmation_code': '999999'
    }, follow_redirects=False)

    assert response.status_code == 200
    db.session.refresh(unconfirmed_user)
    assert unconfirmed_user.is_email_confirmed is False
    assert unconfirmed_user.confirmation_code == '123456'
