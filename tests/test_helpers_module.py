"""Tests für das Modul Helferverwaltung (Models, Services, Public, Admin, Events-Link)."""

from datetime import date

from app import db
from app.models.event import Event, EventHelperLink
from app.models.helpers import (
    Helper,
    HelperArea,
    HelperAreaWish,
    HelperEvent,
    HelperFieldConfig,
    HelperShift,
    HelperVoucherRule,
)
from app.models.settings import SystemSettings
from app.models.user import User
from app.services.helpers_service import (
    calculate_event_vouchers,
    create_helper_event,
    export_area_team_csv,
    get_area_dashboard_data,
    get_helper_overview_data,
    get_prioritized_helpers_for_area,
    get_tshirt_summary,
)
from app.utils.helpers_seed import ensure_initial_helper_event


def _enable_helpers_module():
    setting = SystemSettings.query.filter_by(key='module_helpers').first()
    if setting is None:
        setting = SystemSettings(key='module_helpers', value='true')
        db.session.add(setting)
    else:
        setting.value = 'true'
    db.session.commit()


def _create_user(email_prefix='orga', is_admin=True):
    user = User(
        email=f'{email_prefix}@example.com',
        first_name='Orga',
        last_name='Team',
        is_admin=is_admin,
        is_email_confirmed=True,
        has_full_access=True,
        is_active=True,
    )
    user.set_password('secret123')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user):
    client.post('/logout', follow_redirects=True)
    resp = client.post(
        '/login',
        data={'email': user.email, 'password': 'secret123'},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_seed_and_multi_event_creation(app):
    ev1 = ensure_initial_helper_event()
    assert ev1.id is not None
    assert ev1.apply_token

    area_names = {a.name: a for a in ev1.areas}
    assert len(area_names) == 12
    assert 'VA-Leitung' in area_names
    assert area_names['VA-Leitung'].is_public_selectable is False
    assert area_names['Technik'].is_public_selectable is True

    field_keys = {f.field_key for f in ev1.field_configs}
    assert {'first_name', 'last_name', 'email', 'phone', 'tshirt_size', 'allergies'}.issubset(field_keys)
    assert len(ev1.voucher_rules) == 3

    ev2 = create_helper_event(name='Sommerfest 2026', clone_from_event_id=ev1.id)
    assert ev2.id != ev1.id
    assert len(ev2.areas) == 12
    assert len(ev2.voucher_rules) == 3


def test_public_registration_validation_and_duplicate_check(client, app):
    _enable_helpers_module()
    ev = ensure_initial_helper_event()
    technik = HelperArea.query.filter_by(event_id=ev.id, name='Technik').first()

    # GET ohne Login erreichbar
    resp = client.get(f'/helfer/anmeldung/{ev.apply_token}')
    assert resp.status_code == 200
    assert b'VA-Leitung' not in resp.data
    assert b'Technik' in resp.data

    # Fehlende DSGVO-Zustimmung
    resp = client.post(
        f'/helfer/anmeldung/{ev.apply_token}',
        data={
            'first_name': 'Max',
            'last_name': 'Mustermann',
            'email': 'max@example.com',
            'tshirt_size': 'L',
            'area_ids': [str(technik.id)],
            'available_days': ['Freitag', 'Samstag'],
        },
    )
    assert resp.status_code == 200
    assert Helper.query.filter_by(event_id=ev.id).count() == 0

    # Erfolgreiche Anmeldung
    resp = client.post(
        f'/helfer/anmeldung/{ev.apply_token}',
        data={
            'first_name': 'Max',
            'last_name': 'Mustermann',
            'email': 'Max@Example.com',
            'phone': '0176123456',
            'tshirt_size': 'L',
            'allergies': 'vegan',
            'area_ids': [str(technik.id)],
            'available_days': ['Freitag', 'Samstag'],
            'dsgvo_accepted': '1',
        },
    )
    assert resp.status_code == 200
    helper = Helper.query.filter_by(event_id=ev.id, email='max@example.com').first()
    assert helper is not None
    assert helper.tshirt_size == 'L'
    assert len(helper.wishes) == 1
    assert helper.wishes[0].area_id == technik.id

    # Duplikat-E-Mail im selben Event wird abgewiesen
    resp2 = client.post(
        f'/helfer/anmeldung/{ev.apply_token}',
        data={
            'first_name': 'Max',
            'last_name': 'Mustermann',
            'email': 'max@example.com',
            'tshirt_size': 'M',
            'dsgvo_accepted': '1',
        },
    )
    assert resp2.status_code == 200
    assert Helper.query.filter_by(event_id=ev.id).count() == 1

    # Im zweiten Event darf sich dieselbe E-Mail erneut anmelden
    ev2 = create_helper_event(name='Zweites Event')
    resp3 = client.post(
        f'/helfer/anmeldung/{ev2.apply_token}',
        data={
            'first_name': 'Max',
            'last_name': 'Mustermann',
            'email': 'max@example.com',
            'tshirt_size': 'M',
            'dsgvo_accepted': '1',
        },
    )
    assert resp3.status_code == 200
    assert Helper.query.filter_by(event_id=ev2.id).count() == 1


def test_voucher_calculation_modes_bulk_and_overrides(app):
    ev = ensure_initial_helper_event()
    technik = HelperArea.query.filter_by(event_id=ev.id, name='Technik').first()
    secu = HelperArea.query.filter_by(event_id=ev.id, name='Sani/Secu/Awareness').first()

    h1 = Helper(event_id=ev.id, first_name='Lea', last_name='Head', email='lea@example.com', tshirt_size='S')
    db.session.add(h1)
    db.session.flush()

    # Zwei Schichten am selben Tag: jeweils 4 Std. (per_shift -> 2x Kurzschicht, cumulative -> 1x Mittelschicht 8 Std.)
    s1 = HelperShift(event_id=ev.id, area_id=technik.id, helper_id=h1.id, day_label='Freitag', hours=4.0, is_head=True)
    s2 = HelperShift(event_id=ev.id, area_id=technik.id, helper_id=h1.id, day_label='Freitag', hours=4.0, is_head=False)
    # Anonymer Sammelposten: 25x Secu für 12 Std. (Langschicht: 2 Essen, 6 Getränke * 25 = 50 / 150)
    s_bulk = HelperShift(event_id=ev.id, area_id=secu.id, helper_id=None, group_count=25, role_label='Secu', day_label='Freitag', hours=12.0)
    # Override-Schicht
    s_ovr = HelperShift(event_id=ev.id, area_id=technik.id, helper_id=None, group_count=1, role_label='Special', day_label='Samstag', hours=2.0, food_override=0, drinks_override=2)
    db.session.add_all([s1, s2, s_bulk, s_ovr])
    db.session.commit()

    # Modus 1: per_shift
    ev.voucher_calc_mode = 'per_shift'
    shift_v, helper_v = calculate_event_vouchers(ev)
    # s1: 1 Essen, 3+1=4 Getränke; s2: 1 Essen, 3 Getränke => Summe h1: 2 Essen, 7 Getränke
    assert helper_v[h1.id]['food'] == 2
    assert helper_v[h1.id]['drinks'] == 7
    assert shift_v[s_bulk.id] == {'food': 50, 'drinks': 150}
    assert shift_v[s_ovr.id] == {'food': 0, 'drinks': 2}

    # Modus 2: cumulative_per_person_day (4+4 = 8 Std. -> Mittelschicht: 2 Essen, 5 Getränke + 1 HEAD-Bonus = 6 Getränke)
    ev.voucher_calc_mode = 'cumulative_per_person_day'
    _, helper_v_cum = calculate_event_vouchers(ev)
    assert helper_v_cum[h1.id]['food'] == 2
    assert helper_v_cum[h1.id]['drinks'] == 6


def test_tshirt_filter_prioritized_helpers_and_csv_export(app):
    ev = ensure_initial_helper_event()
    kasse = HelperArea.query.filter_by(event_id=ev.id, name='Kasse').first()
    doku = HelperArea.query.filter_by(event_id=ev.id, name='Doku').first()

    h_wish = Helper(event_id=ev.id, first_name='Anna', last_name='Wunsch', email='anna@example.com', tshirt_size='M', allergies='Laktose')
    h_other = Helper(event_id=ev.id, first_name='Ben', last_name='Andere', email='ben@example.com', tshirt_size='XL', status='registered')
    db.session.add_all([h_wish, h_other])
    db.session.flush()
    db.session.add(HelperAreaWish(helper_id=h_wish.id, area_id=kasse.id, priority=1, available_days=['Samstag']))
    db.session.add(HelperAreaWish(helper_id=h_other.id, area_id=doku.id, priority=1, available_days=['Samstag']))
    db.session.add(HelperShift(event_id=ev.id, area_id=kasse.id, helper_id=h_wish.id, day_label='Samstag', hours=5.0, role_label='Kasse'))
    db.session.commit()

    prioritized = get_prioritized_helpers_for_area(ev, kasse.id)
    assert prioritized[0][0].id == h_wish.id
    assert prioritized[0][1] is True
    assert prioritized[1][0].id == h_other.id
    assert prioritized[1][1] is False

    t_all = get_tshirt_summary(ev, only_assigned=False)
    assert t_all['total_count'] == 2
    t_assigned = get_tshirt_summary(ev, only_assigned=True)
    assert t_assigned['total_count'] == 1
    assert t_assigned['totals'] == {'M': 1}

    rows, _ = get_helper_overview_data(ev)
    row_anna = next(r for r in rows if r['helper'].id == h_wish.id)
    row_ben = next(r for r in rows if r['helper'].id == h_other.id)
    assert row_anna['is_unassigned'] is False
    assert row_ben['is_unassigned'] is True

    csv_bytes = export_area_team_csv(ev, kasse)
    csv_text = csv_bytes.decode('utf-8-sig')
    assert 'Anna' in csv_text
    assert 'Laktose' in csv_text


def test_protected_routes_and_event_link(client, app):
    _enable_helpers_module()
    non_admin = _create_user(email_prefix='helfer_user', is_admin=False)
    admin = _create_user(email_prefix='helfer_admin', is_admin=True)

    # Ohne bestehendes Event darf /helfer/ KEIN Event automatisch anlegen
    _login(client, non_admin)
    assert HelperEvent.query.count() == 0
    assert client.get('/helfer/').status_code == 200
    assert HelperEvent.query.count() == 0

    ev = ensure_initial_helper_event()

    # Nicht-Admin darf /helfer/ aufrufen, aber nicht /settings
    _login(client, non_admin)
    assert client.get(f'/helfer/event/{ev.id}').status_code == 200
    assert client.get(f'/helfer/event/{ev.id}/settings').status_code == 403

    # Admin darf /settings und Portal-Einstellungen /settings/admin/helpers aufrufen
    _login(client, admin)
    assert client.get(f'/helfer/event/{ev.id}/settings').status_code == 200
    assert client.get(f'/settings/admin/helpers?event_id={ev.id}').status_code == 200

    # PDF-Druckansicht für Bereich prüfen
    technik = HelperArea.query.filter_by(event_id=ev.id, name='Technik').first()
    pdf_resp = client.get(f'/helfer/event/{ev.id}/areas/{technik.id}/export.pdf')
    assert pdf_resp.status_code == 200
    assert pdf_resp.mimetype == 'application/pdf'
    assert pdf_resp.data.startswith(b'%PDF-')

    # Modul-Sidebar enthält keinen Link zu /helfer/event/.../settings mehr, aber Ausgabe-Check
    idx_resp = client.get(f'/helfer/event/{ev.id}')
    assert f'/helfer/event/{ev.id}/settings'.encode('utf-8') not in idx_resp.data
    assert client.get(f'/helfer/event/{ev.id}/ausgabe').status_code == 200

    # Automatische Stundenberechnung aus Start- und Endzeit (inkl. Nachtschicht)
    from app.blueprints.helpers.forms import calculate_hours_from_times
    assert calculate_hours_from_times('11:00', '17:00') == 6.0
    assert calculate_hours_from_times('15:30', '02:00') == 10.5
    assert calculate_hours_from_times('16.30', '22:30') == 6.0

    # 4 offene Positionen ohne is_bulk_post legen 4 einzelne Schichten an
    before_count = HelperShift.query.filter_by(area_id=technik.id).count()
    client.post(
        f'/helfer/event/{ev.id}/shifts/create',
        data={'area_id': str(technik.id), 'group_count': '4', 'role_label': 'Stagehand', 'day_label': 'Samstag', 'hours': '6'},
        follow_redirects=True,
    )
    assert HelperShift.query.filter_by(area_id=technik.id).count() == before_count + 4

    # Sammelposten + Zuweisung eines Helfers spaltet 1 Position ab statt alle zu überschreiben
    bulk_s = HelperShift(event_id=ev.id, area_id=technik.id, helper_id=None, group_count=4, role_label='Secu', day_label='Freitag', hours=6.0)
    h_assign = Helper(event_id=ev.id, first_name='Test', last_name='Helper', email='assign@example.com')
    db.session.add_all([bulk_s, h_assign])
    db.session.commit()
    client.post(
        f'/helfer/shifts/{bulk_s.id}/update',
        data={'helper_id': str(h_assign.id), 'role_label': 'Secu', 'day_label': 'Freitag', 'hours': '6'},
        follow_redirects=True,
    )
    db.session.refresh(bulk_s)
    assert bulk_s.helper_id is None
    assert bulk_s.group_count == 3
    assigned = HelperShift.query.filter_by(area_id=technik.id, helper_id=h_assign.id).first()
    assert assigned is not None
    assert assigned.group_count == 1

    # E-Mail-Vorlage in den Einstellungen anpassen und Schichtplan-Mail senden
    client.post(
        f'/helfer/event/{ev.id}/settings/general',
        data={
            'name': ev.name,
            'voucher_calc_mode': 'per_shift',
            'mail_template_subject': 'Schichtplan {{ event_name }} für {{ first_name }}',
            'mail_template_body': 'Hallo {{ full_name }}\n{{ shifts_list }}\nMarken: {{ food_vouchers }}/{{ drinks_vouchers }}',
            'next': 'settings',
        },
        follow_redirects=True,
    )
    from unittest.mock import patch
    with patch('app.mail.send') as mock_send:
        mail_resp = client.post(f'/helfer/helper/{h_assign.id}/send-mail', follow_redirects=True)
        assert mail_resp.status_code == 200
        assert mock_send.called
        sent_msg = mock_send.call_args[0][0]
        assert 'Test' in sent_msg.subject
        assert 'Secu' in sent_msg.body
    resp = client.post(
        f'/helfer/event/{ev.id}/settings/fields/create',
        data={
            'label': 'Führerschein',
            'field_type': 'checkbox',
            'is_public': '1',
            'show_in_overview': '1',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert HelperFieldConfig.query.filter_by(event_id=ev.id, label='Führerschein').first() is not None

    # Verknüpfung mit dem Veranstaltungsmodul (EventHelperLink)
    portal_ev = Event(
        name='Festival 2026',
        start_date=date(2026, 6, 12),
        end_date=date(2026, 6, 14),
        created_by=admin.id,
        owner_id=admin.id,
    )
    db.session.add(portal_ev)
    db.session.commit()

    # Modul Events aktivieren
    ev_mod = SystemSettings.query.filter_by(key='module_events').first()
    if ev_mod is None:
        db.session.add(SystemSettings(key='module_events', value='true'))
    else:
        ev_mod.value = 'true'
    db.session.commit()

    resp_link = client.post(
        f'/events/{portal_ev.id}/link/helpers',
        data={'action': 'add', 'helper_event_id': str(ev.id)},
        follow_redirects=True,
    )
    assert resp_link.status_code == 200
    assert EventHelperLink.query.filter_by(event_id=portal_ev.id, helper_event_id=ev.id).first() is not None
