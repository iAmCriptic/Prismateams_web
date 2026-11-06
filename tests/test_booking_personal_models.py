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