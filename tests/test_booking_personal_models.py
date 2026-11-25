import pytest
from app import db
from app.models.user import User
from app.models.booking_personal import (
    BookingPersonalEvent,
    BookingPersonalField,
    BookingPersonalEntry,
    BookingPersonalFile,
    BookingPersonalTemplate,
)
from app.utils.booking_personal_presets import (
    FESTIVAL_STANDARD_FIELDS,
    ensure_default_template,
    apply_template_to_event,
)


def test_create_event_and_apply_default_template(app):
    with app.app_context():
        user = User(email='admin@example.com', first_name='Test', last_name='Admin')
        user.set_password('testpass123')
        db.session.add(user)
        db.session.commit()

        # Stelle Standard-Template sicher
        tmpl = ensure_default_template(db.session, user.id)
        assert tmpl is not None
        assert tmpl.name == 'Festival Standard'
        assert len(tmpl.get_fields()) >= 35

        # Erstelle Event
        event = BookingPersonalEvent(name='Sommer Open Air 2026', created_by=user.id)
        db.session.add(event)
        db.session.flush()

        # Wende Vorlage an
        apply_template_to_event(event, tmpl.get_fields(), db.session)
        db.session.commit()

        assert len(event.fields) >= 35
        field_keys = [f.field_key for f in event.fields]
        assert 'project_name' in field_keys
        assert 'status_booking' in field_keys
        assert 'gage' in field_keys
        assert 'gesamt' in field_keys
        assert 'promo_pictures' in field_keys
        assert 'techrider_djs' in field_keys
        assert 'techrider_attachments' in field_keys
        assert 'form_link' in field_keys
        assert 'action_accept_mail' in field_keys

        # Prüfe sinnvolle Einteilung aller Felder in Kategorien
        for f in event.fields:
            assert f.category in (
                'Stammdaten & Status',
                'Finanzen',
                'Hospitality & Logistik',
                'Presse & Technik',
                'Aktionen & Links'
            ), f"Feld {f.field_key} hat ungültige Kategorie: {f.category}"

        field_by_key = {f.field_key: f for f in event.fields}
        assert field_by_key['project_name'].category == 'Stammdaten & Status'
        assert field_by_key['status_booking'].category == 'Stammdaten & Status'
        assert field_by_key['gage'].category == 'Finanzen'
        assert field_by_key['gesamt'].category == 'Finanzen'
        assert field_by_key['getraenkeguthaben'].category == 'Hospitality & Logistik'
        assert field_by_key['techrider_djs'].category == 'Presse & Technik'
        assert field_by_key['form_link'].category == 'Aktionen & Links'


def test_entry_custom_data_and_formula_calculation(app):
    with app.app_context():
        event = BookingPersonalEvent(name='Clubnacht')
        db.session.add(event)
        db.session.flush()

        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS, db.session)
        db.session.commit()

        entry = BookingPersonalEntry(event_id=event.id, name='DJ Hyper')
        entry.set_value('project_name', 'DJ Hyper')
        entry.set_value('gage', '€350.00')
        entry.set_value('travel', '€50.00')
        entry.set_value('booking_fee', '€25.00')
        entry.set_value('sonst_ausgaben', '€15.00')

        # Berechne Formelfelder
        entry.compute_formula_values(event.fields)
        db.session.add(entry)
        db.session.commit()

        # Summe: 350 + 50 + 25 + 15 = 440.00
        gesamt = entry.get_value('gesamt')
        assert gesamt == '€440.00'
        assert entry.form_token is not None
        assert entry.overview_token is not None


def test_formula_parentheses_and_percentages(app):
    with app.app_context():
        event = BookingPersonalEvent(name='Formel Test Event')
        db.session.add(event)
        db.session.flush()
        apply_template_to_event(event, FESTIVAL_STANDARD_FIELDS, db.session)

        f_brutto = BookingPersonalField(
            event_id=event.id,
            field_key='brutto_summe',
            label='Brutto',
            field_type='formula',
            formula_definition='(gage + booking_fee) * (1 + 19%)',
            field_order=90,
        )
        f_mwst = BookingPersonalField(
            event_id=event.id,
            field_key='mwst_anteil',
            label='MwSt',
            field_type='formula',
            formula_definition='(gage + booking_fee) * 19%',
            field_order=91,
        )
        f_steuersatz = BookingPersonalField(
            event_id=event.id,
            field_key='mit_steuersatz',
            label='Mit Steuersatz',
            field_type='formula',
            formula_definition='(gage + booking_fee) * (1 + steuersatz)',
            field_order=92,
        )
        f_rabatt = BookingPersonalField(
            event_id=event.id,
            field_key='rabatt',
            label='Rabatt',
            field_type='formula',
            formula_definition='gage - (gage * 10%)',
            field_order=93,
        )
        f_split = BookingPersonalField(
            event_id=event.id,
            field_key='split',
            label='Split',
            field_type='formula',
            formula_definition='(gage + booking_fee) / 2',
            field_order=94,
        )
        f_div_zero = BookingPersonalField(
            event_id=event.id,
            field_key='div_zero',
            label='DivZero',
            field_type='formula',
            formula_definition='gage / 0',
            field_order=95,
        )
        db.session.add_all([f_brutto, f_mwst, f_steuersatz, f_rabatt, f_split, f_div_zero])
        db.session.commit()

        entry = BookingPersonalEntry(event_id=event.id, name='Formula Artist')
        entry.set_value('gage', '€100.00')
        entry.set_value('booking_fee', '€50.00')
        entry.set_value('steuersatz', '7%')
        entry.compute_formula_values(event.fields)

        assert entry.get_value('brutto_summe') == '€178.50'
        assert entry.get_value('mwst_anteil') == '€28.50'
        assert entry.get_value('mit_steuersatz') == '€160.50'
        assert entry.get_value('rabatt') == '€90.00'
        assert entry.get_value('split') == '€75.00'
        assert entry.get_value('div_zero') == '€0.00'
        # Abwärtskompatibilität für Standard-GESAMT (7% auf Gage = 107 + 50 = 157)
        assert entry.get_value('gesamt') == '€157.00'
