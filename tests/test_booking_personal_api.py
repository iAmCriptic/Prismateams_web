import json
import pytest
from app import db
from app.models.user import User
from app.models.booking_personal import (
    BookingPersonalEvent,
    BookingPersonalEntry,
    BookingPersonalField,
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

    # Benutzerdefiniertes Template löschen
    res_del = client.post(f'/booking-personal/api/template/{tmpl_id}/delete')
    assert res_del.status_code == 200
    assert res_del.get_json()['success'] is True


def test_api_column_crud_and_reorder(client, app):
    with app.app_context():
        _login_test_user(client)

        event = BookingPersonalEvent(name='Spalten-Test-Event')
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    # 1. Spalte hinzufügen
    res_add = client.post(
        f'/booking-personal/api/event/{event_id}/field/add',
        data=json.dumps({
            'label': 'Hotelzimmer',
            'label_en': 'Hotel Room',
            'field_type': 'text',
            'width': 180,
            'is_external': True,
            'visible_in_overview': True
        }),
        content_type='application/json'
    )
    assert res_add.status_code == 200
    data_add = res_add.get_json()
    assert data_add['success'] is True
    field_id = data_add['field']['id']
    assert data_add['field']['label'] == 'Hotelzimmer'
    assert data_add['field']['label_en'] == 'Hotel Room'
    assert data_add['field']['is_external'] is True

    # 2. Zweite Spalte hinzufügen
    res_add2 = client.post(
        f'/booking-personal/api/event/{event_id}/field/add',
        data=json.dumps({
            'label': 'Shuttle benötigt',
            'field_type': 'badge_select',
            'options': [{'value': 'Ja', 'color': 'success'}, {'value': 'Nein', 'color': 'secondary'}]
        }),
        content_type='application/json'
    )
    assert res_add2.status_code == 200
    field_id2 = res_add2.get_json()['field']['id']

    # 3. Spalte bearbeiten
    res_upd = client.post(
        f'/booking-personal/api/field/{field_id}/update',
        data=json.dumps({
            'label': 'Hotelzimmer Luxus',
            'width': 220,
            'visible_in_overview': False
        }),
        content_type='application/json'
    )
    assert res_upd.status_code == 200
    assert res_upd.get_json()['field']['label'] == 'Hotelzimmer Luxus'
    assert res_upd.get_json()['field']['width'] == 220
    assert res_upd.get_json()['field']['visible_in_overview'] is False

    # 4. Spalten neu sortieren
    res_reorder = client.post(
        f'/booking-personal/api/event/{event_id}/fields/reorder',
        data=json.dumps({'order': [field_id2, field_id]}),
        content_type='application/json'
    )
    assert res_reorder.status_code == 200
    fields_order = res_reorder.get_json()['fields']
    assert fields_order[0]['id'] == field_id2
    assert fields_order[1]['id'] == field_id

    # 5. Spalte löschen
    res_del = client.post(f'/booking-personal/api/field/{field_id}/delete')
    assert res_del.status_code == 200
    remaining_fields = res_del.get_json()['fields']
    assert len(remaining_fields) == 1
    assert remaining_fields[0]['id'] == field_id2


def test_act_detail_view_renders_structured_page(client, app):
    with app.app_context():
        _login_test_user(client)

        event = BookingPersonalEvent(name='Open Air 2026')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS, db.session)

        entry = BookingPersonalEntry(
            event_id=event.id,
            name='Lunar Resonance',
            email='lunar@resonance.live',
            status='Zusage gesendet'
        )
        entry.set_custom_data({
            'gage': '€1200.00',
            'booking_fee': '€300.00',
            'bereich': 'Main Stage',
            'pronouns': 'they/them',
            'contact_name': 'Alex Nova',
            'techrider_djs': '2 x Pioneer CDJ 3000'
        })
        db.session.add(entry)
        db.session.commit()
        event_id = event.id
        entry_id = entry.id

    # 1. Detail-Seite aufrufen
    resp = client.get(f'/booking-personal/event/{event_id}/act/{entry_id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Verifizieren, dass das strukturierte Profil und die Daten gerendert werden
    assert 'Lunar Resonance' in html
    assert 'Zusage gesendet' in html
    assert 'Main Stage' in html
    assert 'they/them' in html
    assert 'Alex Nova' in html
    assert '€1500.00' in html
    assert '2 x Pioneer CDJ 3000' in html
    assert 'Zurück' in html
    assert 'mod-back-link' in html
    assert 'Angaben bearbeiten' in html


def test_act_detail_view_with_custom_categories(client, app):
    with app.app_context():
        _login_test_user(client)

        event = BookingPersonalEvent(name='Club Night Special')
        db.session.add(event)
        db.session.flush()

        # Eigene benutzerdefinierte Spalten mit Custom-Kategorien anlegen
        f1 = BookingPersonalField(
            event_id=event.id,
            field_key='artist_name',
            label='Künstler',
            category='Allgemeine Infos',
            field_type='text'
        )
        f2 = BookingPersonalField(
            event_id=event.id,
            field_key='stage_type',
            label='Bühnen-Setup',
            category='Bühne & Technik',
            field_type='badge_select'
        )
        f3 = BookingPersonalField(
            event_id=event.id,
            field_key='hotel_room',
            label='Hotelzimmer',
            category='Unterkunft & Reise',
            field_type='text'
        )
        db.session.add_all([f1, f2, f3])

        entry = BookingPersonalEntry(
            event_id=event.id,
            name='Solar Flare',
            status='Bestätigt'
        )
        entry.set_custom_data({
            'artist_name': 'Solar Flare',
            'stage_type': 'Live Modular Synth',
            'hotel_room': 'Zimmer 402 (Late Checkout)'
        })
        db.session.add(entry)
        db.session.commit()
        event_id = event.id
        entry_id = entry.id

    resp = client.get(f'/booking-personal/event/{event_id}/act/{entry_id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Prüfen, dass die benutzerdefinierten Kategorien als eigene Karten gerendert werden
    assert 'Allgemeine Infos' in html
    assert 'Bühne &amp; Technik' in html
    assert 'Unterkunft &amp; Reise' in html
    assert 'Live Modular Synth' in html
    assert 'Zimmer 402 (Late Checkout)' in html


def test_templates_management_page_and_crud(client, app):
    with app.app_context():
        _login_test_user(client)

        event = BookingPersonalEvent(name='Herbst Session')
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    # 1. Vorlagenseite aufrufen
    resp = client.get('/booking-personal/templates')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Vorlagenverwaltung' in html
    assert 'Festival Standard' in html

    # 2. Neue Vorlage erstellen
    resp_create = client.post('/booking-personal/templates/create', data={
        'name': 'Clubnacht Minimal',
        'description': 'Schlankes Template für Clubnächte',
        'source_type': 'blank',
    }, follow_redirects=True)
    assert resp_create.status_code == 200
    html_created = resp_create.get_data(as_text=True)
    assert 'Clubnacht Minimal' in html_created

    with app.app_context():
        tmpl = BookingPersonalTemplate.query.filter_by(name='Clubnacht Minimal').first()
        assert tmpl is not None
        tmpl_id = tmpl.id

    # 3. Spalte zur Vorlage hinzufügen
    resp_field = client.post(f'/booking-personal/templates/{tmpl_id}/field/add', data={
        'label': 'DJ Slot Time',
        'label_en': 'Slot Time',
        'field_type': 'text',
        'width': '180',
        'visible_in_overview': '1',
    }, follow_redirects=True)
    assert resp_field.status_code == 200
    html_field = resp_field.get_data(as_text=True)
    assert 'DJ Slot Time' in html_field

    with app.app_context():
        tmpl = BookingPersonalTemplate.query.get(tmpl_id)
        fields = tmpl.get_fields()
        assert len(fields) == 1
        assert fields[0]['label'] == 'DJ Slot Time'

    # 4. Vorlage auf Event anwenden
    resp_apply = client.post(f'/booking-personal/templates/{tmpl_id}/apply', data={
        'event_id': event_id,
    }, follow_redirects=True)
    assert resp_apply.status_code == 200

    with app.app_context():
        ev = BookingPersonalEvent.query.get(event_id)
        assert len(ev.fields) == 1
        assert ev.fields[0].label == 'DJ Slot Time'

    # 5. Spalte aus Vorlage löschen
    resp_del_field = client.post(f'/booking-personal/templates/{tmpl_id}/field/0/delete', follow_redirects=True)
    assert resp_del_field.status_code == 200

    with app.app_context():
        tmpl = BookingPersonalTemplate.query.get(tmpl_id)
        assert len(tmpl.get_fields()) == 0

    # 6. Vorlage löschen
    resp_del_tmpl = client.post(f'/booking-personal/templates/{tmpl_id}/delete', follow_redirects=True)
    assert resp_del_tmpl.status_code == 200

    with app.app_context():
        tmpl = BookingPersonalTemplate.query.get(tmpl_id)
        assert tmpl is None


def test_compact_toolbar_and_excel_export(client, app):
    with app.app_context():
        _login_test_user(client)

        event = BookingPersonalEvent(name='Summer OpenAir')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS[:5], db.session)

        entry = BookingPersonalEntry(
            event=event,
            name='Live Band Awesome',
            status='Bewerbung eingegangen'
        )
        entry.set_value('auftrittsname', 'Live Band Awesome')
        entry.set_value('bereich', 'Main Stage')
        db.session.add(entry)
        db.session.commit()
        event_id = event.id

    # 1. Test Toolbar UI elements
    resp = client.get(f'/booking-personal/?event_id={event_id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Filter button & popup dropdown
    assert 'id="bpFilterDropdownBtn"' in html
    assert 'id="bpStatusFilter"' in html
    assert 'id="bpAreaFilter"' in html
    assert 'id="bpResetFiltersBtn"' in html

    # Export dropdown with CSV & XLSX
    assert f'/booking-personal/event/{event_id}/export' in html
    assert f'/booking-personal/event/{event_id}/export/xlsx' in html

    # Act button with split dropdown for Bewerbungslink kopieren
    assert 'id="bpAddActBtn"' in html
    assert 'Bewerbungslink kopieren' in html
    assert 'Bewerbungsformular öffnen' in html

    # Settings icon button
    assert f"/booking-personal/event/{event_id}/settings" in html

    # 2. Test Excel export (.xlsx)
    resp_xlsx = client.get(f'/booking-personal/event/{event_id}/export/xlsx')
    assert resp_xlsx.status_code == 200
    assert resp_xlsx.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert 'attachment' in resp_xlsx.headers.get('Content-Disposition', '')

    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(resp_xlsx.data))
    ws = wb.active
    assert ws is not None
    # Check headers in row 1
    headers = [cell.value for cell in ws[1]]
    assert 'Auftrittsname / Projektname' in headers
    # Check row 2 has the created act
    row2_vals = [cell.value for cell in ws[2]]
    assert 'Live Band Awesome' in row2_vals






def test_dedicated_settings_page_and_bilingual_emails(client, app):
    """Testet die neue dedizierte Einstellungsseite im Pill-Style und zweisprachige E-Mails."""
    with app.app_context():
        _login_test_user(client)

        event = BookingPersonalEvent(name='Pill Style Festival')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS[:3], db.session)
        db.session.commit()
        event_id = event.id

    # 1. Dedicated Settings Page GET
    resp = client.get(f'/booking-personal/event/{event_id}/settings')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Check for Pill design tabs
    assert 'bp-pill-tabs' in html
    assert 'Spalten-Manager' in html
    assert 'E-Mail & Postfach' in html
    assert 'Formular-Texte & Bild' in html
    assert 'Allgemein & Löschen' in html

    # Check for Placeholders chip bar
    assert 'Verfügbare Platzhalter für E-Mails' in html
    assert 'bp-placeholder-btn' in html
    assert '{{ event_name }}' in html
    assert '{{ act_name }}' in html

    # Check for Bilingual Email fields
    assert 'name="accept_template_subject"' in html
    assert 'name="accept_template_subject_en"' in html
    assert 'name="reject_template_subject_en"' in html
    assert 'name="invite_template_subject_en"' in html

    # Check that "Breite" is NOT a configurable column in Spalten-Manager table
    assert '<th style="width: 90px;" class="text-center">Breite</th>' not in html
    assert 'id="bpColWidth"' not in html

    # Check horizontal action buttons
    assert 'd-inline-flex align-items-center justify-content-end gap-1.5' in html

    # 2. Save English and German email settings
    resp_post = client.post(
        f'/booking-personal/events/{event_id}/settings',
        data={
            'accept_template_subject': 'Zusage für {{ event_name }}',
            'accept_template_body': 'Hallo {{ contact_name }}, Zusage!',
            'accept_template_subject_en': 'Confirmed for {{ event_name }}',
            'accept_template_body_en': 'Hello {{ contact_name }}, you are booked!',
            'reject_template_subject': 'Absage {{ event_name }}',
            'reject_template_body': 'Leider nein.',
            'reject_template_subject_en': 'Decline {{ event_name }}',
            'reject_template_body_en': 'Unfortunately no.',
            'invite_template_subject': 'Fragebogen {{ event_name }}',
            'invite_template_body': 'Bitte ausfüllen.',
            'invite_template_subject_en': 'Form {{ event_name }}',
            'invite_template_body_en': 'Please fill.',
            'active_tab': 'emails',
        },
        follow_redirects=True
    )
    assert resp_post.status_code == 200

    with app.app_context():
        ev = BookingPersonalEvent.query.get(event_id)
        assert ev.accept_template_subject_en == 'Confirmed for {{ event_name }}'
        assert ev.accept_template_body_en == 'Hello {{ contact_name }}, you are booked!'
        assert ev.reject_template_subject_en == 'Decline {{ event_name }}'
        assert ev.invite_template_subject_en == 'Form {{ event_name }}'

def test_booking_personal_pdf_export_and_table_hover_actions(client, app):
    """Prüft den PDF-Export der Booking-Tabelle und die Hover-Aktionen im Table-Template."""
    with app.app_context():
        _login_test_user(client)
        event = BookingPersonalEvent(name='PDF Export Festival')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS, db.session)
        entry = BookingPersonalEntry(event_id=event.id, name='Headliner Act')
        db.session.add(entry)
        db.session.commit()
        event_id = event.id

    # 1. PDF-Export Route aufrufen
    resp_pdf = client.get(f'/booking-personal/event/{event_id}/export/pdf')
    assert resp_pdf.status_code == 200
    assert resp_pdf.content_type == 'application/pdf'
    assert resp_pdf.data.startswith(b'%PDF')

    # 2. Übersicht rendern und prüfen
    resp_view = client.get(f'/booking-personal/event/{event_id}')
    assert resp_view.status_code == 200
    html = resp_view.data.decode('utf-8')

    # Mod-list hover actions & class vorhanden
    assert 'mod-list-row' in html
    assert 'mod-list-hover-actions' in html
    assert f'/booking-personal/event/{event_id}/export/pdf' in html

    # Spalte 01 MAIL FÜR ZUSAGE wurde aus thead/tbody eliminiert
    assert '01 MAIL FÜR ZUSAGE' not in html
