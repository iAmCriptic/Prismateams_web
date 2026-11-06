import json
import pytest
from app import db
from app.models.user import User
from app.models.booking_personal import (
    BookingPersonalEvent,
    BookingPersonalEntry,
    BookingPersonalTemplate,
)
from app.utils.booking_personal_presets import (
    FESTIVAL_STANDARD_FIELDS,
    apply_template_to_event,
)


def _login_test_user(client):
    user = User(
        email='coordinator@example.com',
        first_name='Booking',
        last_name='Coordinator',
        is_active=True,
        is_admin=True,
        is_email_confirmed=True,
        has_full_access=True
    )
    user.set_password('securepassword')
    db.session.add(user)
    db.session.commit()

    resp = client.post('/login', data={
        'email': 'coordinator@example.com',
        'password': 'securepassword'
    }, follow_redirects=True)
    assert resp.status_code == 200
    return user


def test_api_entry_create_and_cell_update(client, app):
    with app.app_context():
        _login_test_user(client)

        event = BookingPersonalEvent(name='Elektro Festival')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS, db.session)
        db.session.commit()
        event_id = event.id

    # 1. Neuen Act hinzufügen
    res = client.post(
        f'/booking-personal/api/event/{event_id}/entry',
        data=json.dumps({'name': 'Techno Duo'}),
        content_type='application/json'
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    entry_id = data['entry']['id']
    assert data['entry']['name'] == 'Techno Duo'

    # 2. Gage per Inline-Editing aktualisieren
    res = client.post(
        f'/booking-personal/api/entry/{entry_id}/cell',
        data=json.dumps({'field_key': 'gage', 'value': '€500.00'}),
        content_type='application/json'
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['updated_custom_data']['gage'] == '€500.00'
    # Formelfeld GESAMT sollte nun mindestens 500.00 sein
    assert '€500.00' in data['updated_custom_data']['gesamt']

    # 3. Status per Inline-Editing aktualisieren
    res = client.post(
        f'/booking-personal/api/entry/{entry_id}/cell',
        data=json.dumps({'field_key': 'status_booking', 'value': 'Abgeschlossen'}),
        content_type='application/json'
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['entry']['status'] == 'Abgeschlossen'

    # 4. Detail abfragen
    res = client.get(f'/booking-personal/api/entry/{entry_id}')
    assert res.status_code == 200
    data = res.get_json()
    assert data['entry']['name'] == 'Techno Duo'
    assert len(data['fields']) >= 35

    # 5. Löschen
    res = client.post(f'/booking-personal/api/entry/{entry_id}/delete')
    assert res.status_code == 200
    assert res.get_json()['success'] is True


def test_api_template_save_and_load(client, app):
    with app.app_context():
        _login_test_user(client)

        event = BookingPersonalEvent(name='Clubnacht')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS, db.session)
        db.session.commit()
        event_id = event.id

    # Neues Template speichern
    res = client.post(
        f'/booking-personal/api/event/{event_id}/save-template',
        data=json.dumps({'name': 'Mein Club-Setup'}),
        content_type='application/json'
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    tmpl_id = data['template']['id']
    assert data['template']['name'] == 'Mein Club-Setup'

    # Template in ein zweites Event laden
    with app.app_context():
        event2 = BookingPersonalEvent(name='Zweites Event')
        db.session.add(event2)
        db.session.commit()
        event2_id = event2.id

    res = client.post(
        f'/booking-personal/api/event/{event2_id}/load-template',
        data=json.dumps({'template_id': tmpl_id}),
        content_type='application/json'
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert len(data['fields']) >= 35
