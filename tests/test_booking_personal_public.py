import pytest
from app import db
from app.models.booking_personal import (
    BookingPersonalEvent,
    BookingPersonalEntry,
)
from app.utils.booking_personal_presets import (
    FESTIVAL_STANDARD_FIELDS,
    apply_template_to_event,
)


def test_public_form_and_submission(client, app):
    with app.app_context():
        event = BookingPersonalEvent(name='Herbst Festival 2026')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS, db.session)

        entry = BookingPersonalEntry(event_id=event.id, name='The Soundwaves')
        db.session.add(entry)
        db.session.commit()

        form_token = entry.form_token
        entry_id = entry.id

    # 1. Externes Formular aufrufen (ohne Login)
    res = client.get(f'/booking-personal/form/{form_token}')
    assert res.status_code == 200
    assert b'Herbst Festival 2026' in res.data
    assert b'The Soundwaves' in res.data

    # 2. Formular absenden (z. B. Pronomen, Ansprechpartner, Techrider)
    post_data = {
        'contact_name': 'Max Mustermann',
        'mail': 'max@soundwaves.band',
        'phone': '+491701234567',
        'pronouns': 'they/them',
        'techrider_djs': '2 x Pioneer CDJ 3000',
        'mitgliederanzahl': '3',
        'was_du_uns_noch_sagen': 'Wir freuen uns riesig auf das Festival!',
    }
    res = client.post(
        f'/booking-personal/form/{form_token}/submit',
        data=post_data,
        follow_redirects=True
    )
    assert res.status_code == 200
    assert 'Vielen Dank' in res.data.decode('utf-8')

    # 3. Überprüfen, ob Daten in der Datenbank synchronisiert wurden
    with app.app_context():
        updated_entry = BookingPersonalEntry.query.get(entry_id)
        assert updated_entry.form_submitted_at is not None
        assert updated_entry.status == 'Formular ausgefüllt'
        assert updated_entry.email == 'max@soundwaves.band'
        assert updated_entry.get_value('pronouns') == 'they/them'
        assert updated_entry.get_value('techrider_djs') == '2 x Pioneer CDJ 3000'
        assert updated_entry.get_value('mitgliederanzahl') == '3'


def test_public_bilingual_overview(client, app):
    with app.app_context():
        event = BookingPersonalEvent(name='Summer Closing')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS, db.session)

        entry = BookingPersonalEntry(event_id=event.id, name='Luna Love')
        entry.set_value('gage', '€450.00')
        entry.set_value('travel', '€75.00')
        entry.set_value('bereich', 'Main Stage')
        db.session.add(entry)
        db.session.commit()

        overview_token = entry.overview_token

    # 1. Deutsche Ansicht (Standard)
    res = client.get(f'/booking-personal/overview/{overview_token}?lang=de')
    assert res.status_code == 200
    content_de = res.data.decode('utf-8')
    assert 'Summer Closing' in content_de
    assert 'Luna Love' in content_de
    assert 'Bestätigte Buchung' in content_de
    assert '€450.00' in content_de

    # 2. Englische Ansicht
    res = client.get(f'/booking-personal/overview/{overview_token}?lang=en')
    assert res.status_code == 200
    content_en = res.data.decode('utf-8')
    assert 'Confirmed Booking' in content_en
    assert 'Artist / Project Name' in content_en
    assert 'Fee / Gage' in content_en
    assert '€450.00' in content_en


def test_public_apply_and_submission(client, app):
    with app.app_context():
        event = BookingPersonalEvent(name='Open Air 2026')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS, db.session)
        apply_token = event.get_apply_token()
        event_id = event.id
        db.session.commit()

    # 1. Öffentliches Bewerbungsformular aufrufen (ohne Login)
    res = client.get(f'/booking-personal/apply/{apply_token}')
    assert res.status_code == 200
    assert 'Open Air 2026' in res.data.decode('utf-8')
    assert 'Bewerbung' in res.data.decode('utf-8')

    # 2. Bewerbung absenden
    post_data = {
        'project_name': 'DJ Cosmic Pulse',
        'contact_name': 'Clara Himmel',
        'mail': 'clara@cosmicpulse.music',
        'phone': '+4915199887766',
        'pronouns': 'she/her',
        'bereich': 'Ambient',
        'soundcloud': 'https://soundcloud.com/cosmicpulse',
        'promotext': 'Sphärische Ambient Klänge zum Träumen.',
    }
    res = client.post(
        f'/booking-personal/apply/{apply_token}/submit',
        data=post_data,
        follow_redirects=True
    )
    assert res.status_code == 200
    assert 'Bewerbung erfolgreich' in res.data.decode('utf-8')

    # 3. Prüfen, dass der Act automatisch in der Veranstaltung angelegt wurde
    with app.app_context():
        new_entry = BookingPersonalEntry.query.filter_by(event_id=event_id, name='DJ Cosmic Pulse').first()
        assert new_entry is not None
        assert new_entry.email == 'clara@cosmicpulse.music'
        assert new_entry.phone == '+4915199887766'
        assert new_entry.status == 'Bewerbung eingegangen'
        assert new_entry.get_value('bereich') == 'Ambient'
        assert new_entry.get_value('soundcloud') == 'https://soundcloud.com/cosmicpulse'
        assert new_entry.get_value('promotext') == 'Sphärische Ambient Klänge zum Träumen.'


