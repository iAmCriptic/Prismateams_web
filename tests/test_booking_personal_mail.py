import json
import pytest
from app import db
from app.models.user import User
from app.models.booking_personal import (
    BookingPersonalEvent,
    BookingPersonalEntry,
)
from app.utils.booking_personal_presets import (
    FESTIVAL_STANDARD_FIELDS,
    apply_template_to_event,
)
from app.blueprints.booking_personal.mail import (
    get_available_placeholders,
    render_template_string,
)


def _login_test_user(client):
    user = User(
        email='booker@example.com',
        first_name='Head',
        last_name='Booker',
        is_active=True,
        is_admin=True,
        is_email_confirmed=True,
        has_full_access=True
    )
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()

    resp = client.post('/login', data={
        'email': 'booker@example.com',
        'password': 'password123'
    }, follow_redirects=True)
    assert resp.status_code == 200
    return user


def test_mail_placeholders_and_template_rendering(app):
    with app.test_request_context():
        event = BookingPersonalEvent(name='Sunset Festival')
        db.session.add(event)
        db.session.flush()

        entry = BookingPersonalEntry(event_id=event.id, name='Cosmic Beat')
        entry.email = 'cosmic@example.com'
        entry.set_value('contact_name', 'Alex Cosmic')
        entry.set_value('gage', '€800.00')
        db.session.add(entry)
        db.session.commit()

        placeholders = get_available_placeholders(event, entry)
        assert placeholders['act_name'] == 'Cosmic Beat'
        assert placeholders['contact_name'] == 'Alex Cosmic'
        assert placeholders['event_name'] == 'Sunset Festival'
        assert placeholders['gage'] == '€800.00'
        assert '/booking-personal/overview/' in placeholders['overview_link']
        assert '/booking-personal/form/' in placeholders['form_link']

        tmpl = 'Liebe(r) {{ contact_name }}, Zusage für {{ event_name }} mit {{ gage }}: {{ overview_link }}'
        rendered = render_template_string(tmpl, placeholders)
        assert 'Liebe(r) Alex Cosmic' in rendered
        assert 'Zusage für Sunset Festival' in rendered
        assert 'mit €800.00' in rendered
        assert placeholders['overview_link'] in rendered


def test_api_mail_preview_and_send(client, app, monkeypatch):
    sent_emails = []

    def fake_send(event, entry, recipient, subject, body):
        sent_emails.append({
            'recipient': recipient,
            'subject': subject,
            'body': body
        })

    monkeypatch.setattr(
        'app.blueprints.booking_personal.views.send_booking_personal_mail',
        fake_send
    )

    with app.app_context():
        _login_test_user(client)

        event = BookingPersonalEvent(name='Sunrise Beach 2026')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS, db.session)

        entry = BookingPersonalEntry(event_id=event.id, name='Beach Band')
        entry.email = 'band@beach.org'
        entry.set_value('gage', '€600.00')
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    # 1. Preview abrufen
    res = client.post(
        f'/booking-personal/api/entry/{entry_id}/mail-preview',
        data=json.dumps({'type': 'accept'}),
        content_type='application/json'
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['recipient'] == 'band@beach.org'
    assert 'Sunrise Beach 2026' in data['subject']
    assert '€600.00' in data['body']

    # 2. E-Mail senden
    res = client.post(
        f'/booking-personal/api/entry/{entry_id}/mail-send',
        data=json.dumps({
            'recipient': data['recipient'],
            'subject': data['subject'],
            'body': data['body'],
            'type': 'accept'
        }),
        content_type='application/json'
    )
    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert len(sent_emails) == 1
    assert sent_emails[0]['recipient'] == 'band@beach.org'

    # 3. Status in DB prüfen
    with app.app_context():
        updated = BookingPersonalEntry.query.get(entry_id)
        assert updated.acceptance_sent_at is not None
        assert updated.status == 'Zusage gesendet'
