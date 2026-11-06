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
        entry_id = entry.id

    # 1. Deutsche Ansicht (Standard: Angefragt)
    res = client.get(f'/booking-personal/overview/{overview_token}?lang=de')
    assert res.status_code == 200
    content_de = res.data.decode('utf-8')
    assert 'Summer Closing' in content_de
    assert 'Luna Love' in content_de
    assert 'Status: Angefragt' in content_de
    assert '€450.00' in content_de

    # 2. Englische Ansicht (Requested)
    res = client.get(f'/booking-personal/overview/{overview_token}?lang=en')
    assert res.status_code == 200
    content_en = res.data.decode('utf-8')
    assert 'Status: Requested' in content_en
    assert 'Artist / Project Name' in content_en
    assert 'Fee / Gage' in content_en
    assert '€450.00' in content_en

    # 3. Wenn Status auf 'Zusage gesendet' wechselt -> 'Bestätigte Buchung' / 'Confirmed Booking'
    with app.app_context():
        e = BookingPersonalEntry.query.get(entry_id)
        e.status = 'Zusage gesendet'
        db.session.commit()

    res_confirmed_de = client.get(f'/booking-personal/overview/{overview_token}?lang=de')
    assert 'Bestätigte Buchung' in res_confirmed_de.data.decode('utf-8')
    res_confirmed_en = client.get(f'/booking-personal/overview/{overview_token}?lang=en')
    assert 'Confirmed Booking' in res_confirmed_en.data.decode('utf-8')


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


def test_public_custom_design_intro_and_multiselect(client, app):
    from app.models.booking_personal import BookingPersonalField
    with app.app_context():
        event = BookingPersonalEvent(
            name='Aurora Nights 2026',
            header_image_path='/uploads/branding/aurora_banner.png',
            apply_intro_text='Willkommen beim Bewerbungsportal von Aurora Nights!',
            apply_intro_text_en='Welcome to the Aurora Nights application portal!',
            form_intro_text='Bitte trage alle Hospitality-Wünsche für Aurora Nights ein.',
            form_intro_text_en='Please submit all hospitality details for Aurora Nights.',
            overview_intro_text='Offizielle Bestätigung deiner Buchung bei Aurora Nights.',
            overview_intro_text_en='Official confirmation of your booking at Aurora Nights.',
        )
        db.session.add(event)
        db.session.flush()

        # Multi-select field hinzufügen
        multi_field = BookingPersonalField(
            event_id=event.id,
            field_key='tasks',
            label='Aufgaben',
            label_en='Tasks',
            field_type='multi_select',
            category='Allgemein',
            field_order=1,
            width=180,
            is_external=True,
            visible_in_overview=True
        )
        multi_field.set_options([
            {'value': 'Soundcheck', 'color': 'primary'},
            {'value': 'Hotel gebucht', 'color': 'info'},
            {'value': 'Catering', 'color': 'success'}
        ])
        db.session.add(multi_field)

        entry = BookingPersonalEntry(event_id=event.id, name='Aurora Ensemble')
        entry.set_value('tasks', ['Soundcheck', 'Catering'])
        db.session.add(entry)
        db.session.commit()

        apply_token = event.get_apply_token()
        form_token = entry.form_token
        overview_token = entry.overview_token

    # 1. Apply: DE Ansicht mit Custom Intro Text & Banner
    res = client.get(f'/booking-personal/apply/{apply_token}?lang=de')
    assert res.status_code == 200
    html_de = res.data.decode('utf-8')
    assert 'Willkommen beim Bewerbungsportal von Aurora Nights!' in html_de
    assert '/uploads/branding/aurora_banner.png' in html_de
    assert 'Aufgaben' in html_de

    # 2. Apply: EN Ansicht
    res_en = client.get(f'/booking-personal/apply/{apply_token}?lang=en')
    assert res_en.status_code == 200
    html_en = res_en.data.decode('utf-8')
    assert 'Welcome to the Aurora Nights application portal!' in html_en
    assert 'Tasks' in html_en
    assert 'Submit Application' in html_en

    # 3. Form: EN Ansicht mit Custom Intro Text und Multi-Select
    res_form = client.get(f'/booking-personal/form/{form_token}?lang=en')
    assert res_form.status_code == 200
    form_html = res_form.data.decode('utf-8')
    assert 'Please submit all hospitality details for Aurora Nights.' in form_html
    assert 'Soundcheck' in form_html
    assert 'Catering' in form_html

    # 4. Overview: EN Ansicht
    res_ov = client.get(f'/booking-personal/overview/{overview_token}?lang=en')
    assert res_ov.status_code == 200
    ov_html = res_ov.data.decode('utf-8')
    assert 'Official confirmation of your booking at Aurora Nights.' in ov_html
    assert 'Soundcheck' in ov_html
    assert 'Catering' in ov_html



