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


def test_plain_text_to_email_html_linkifies_urls_and_escapes():
    from app.blueprints.booking_personal.mail import plain_text_to_email_html

    raw = (
        'Hallo <Team>,\n\n'
        'Hier ist der Link: https://festival.example.org/booking-personal/overview/abc123.\n'
        'Und unsere Website: www.festival.example.org!'
    )
    rendered = plain_text_to_email_html(raw)
    assert '&lt;Team&gt;' in rendered
    assert '<a href="https://festival.example.org/booking-personal/overview/abc123"' in rendered
    assert 'https://festival.example.org/booking-personal/overview/abc123</a>.' in rendered
    assert '<a href="https://www.festival.example.org"' in rendered
    assert 'www.festival.example.org</a>!' in rendered


def test_event_email_logo_upload_and_html_mail_sending(client, app, tmp_path, monkeypatch):
    from io import BytesIO
    from app.blueprints.booking_personal.mail import send_booking_personal_mail

    app.config['UPLOAD_FOLDER'] = str(tmp_path)

    captured_messages = []

    def fake_smtp_send(msg, smtp_cfg):
        captured_messages.append((msg, smtp_cfg))

    monkeypatch.setattr(
        'app.blueprints.email.compose._send_flask_message_via_smtp',
        fake_smtp_send,
    )
    monkeypatch.setattr(
        'app.utils.multi_mailboxes.get_main_smtp_config',
        lambda: {'server': 'smtp.example.org', 'port': 587, 'user': 'booking@example.org', 'sender': 'booking@example.org'},
    )

    with app.app_context():
        _login_test_user(client)
        event = BookingPersonalEvent(name='Logo Fest 2026')
        db.session.add(event)
        db.session.flush()
        entry = BookingPersonalEntry(event_id=event.id, name='DJ Logo', email='dj@example.org')
        db.session.add(entry)
        db.session.commit()
        event_id = event.id
        entry_id = entry.id

    # 1. Event-Logo über das bestehende Veranstaltungs-Bild-Feld hochladen
    png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
    resp = client.post(
        f'/booking-personal/events/{event_id}/design',
        data={
            'header_image': (BytesIO(png_bytes), 'event_logo.png'),
        },
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        ev = db.session.get(BookingPersonalEvent, event_id)
        assert ev.header_image_path.startswith(f'/uploads/booking_personal/{event_id}/header_')

    # 2. Mail über API versenden & HTML + Event-Logo CID prüfen
    send_resp = client.post(
        f'/booking-personal/api/entry/{entry_id}/mail-send',
        data=json.dumps({
            'recipient': 'dj@example.org',
            'subject': 'Zusage Logo Fest',
            'body': 'Hallo DJ,\n\nLink: https://festival.example.org/overview/xyz',
            'type': 'accept',
        }),
        content_type='application/json',
    )
    assert send_resp.status_code == 200
    assert send_resp.get_json()['success'] is True

    assert len(captured_messages) == 1
    msg, _ = captured_messages[0]
    assert msg.html is not None
    assert 'email-container' in msg.html
    assert 'cid:event_logo' in msg.html
    assert '<a href="https://festival.example.org/overview/xyz"' in msg.html
    assert any(
        att.disposition == 'inline' and att.headers.get('Content-ID') == '<event_logo>' and att.data == png_bytes
        for att in msg.attachments
    )

    # 3. Event-Logo wieder entfernen
    resp_del = client.post(
        f'/booking-personal/events/{event_id}/design',
        data={
            'delete_header_image': '1',
        },
        follow_redirects=True,
    )
    assert resp_del.status_code == 200
    with app.app_context():
        ev = db.session.get(BookingPersonalEvent, event_id)
        assert ev.header_image_path is None
