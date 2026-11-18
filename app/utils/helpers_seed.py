"""Seed-Hilfsfunktionen für das Helferverwaltungs-Modul."""

from __future__ import annotations

from app import db
from app.models.helpers import (
    HelperArea,
    HelperEvent,
    HelperFieldConfig,
    HelperVoucherRule,
)

_schema_verified = False


def ensure_helper_schema():
    """Ergänzt fehlende Spalten in bestehenden DBs (z. B. MySQL/SQLite ohne Neustart-Migration)."""
    global _schema_verified
    if _schema_verified:
        return
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'helper_events' in inspector.get_table_names():
            cols = {c['name'] for c in inspector.get_columns('helper_events')}
            col_defs = [
                ('mailbox_id', 'INTEGER NULL'),
                ('mail_template_subject', 'VARCHAR(255) NULL'),
                ('mail_template_body', 'TEXT NULL'),
            ]
            for col_name, col_type in col_defs:
                if col_name not in cols:
                    with db.engine.begin() as conn:
                        conn.execute(text(f'ALTER TABLE helper_events ADD COLUMN {col_name} {col_type}'))
        _schema_verified = True
    except Exception:
        pass

DEFAULT_TSHIRT_OPTIONS = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']

DEFAULT_FIELD_CONFIGS = [
    {
        'field_key': 'first_name',
        'label': 'Vorname',
        'field_type': 'text',
        'options': [],
        'is_public': True,
        'is_required': True,
        'admin_only': False,
        'show_in_overview': True,
        'is_active': True,
        'is_core': True,
        'sort_order': 10,
    },
    {
        'field_key': 'last_name',
        'label': 'Nachname',
        'field_type': 'text',
        'options': [],
        'is_public': True,
        'is_required': True,
        'admin_only': False,
        'show_in_overview': True,
        'is_active': True,
        'is_core': True,
        'sort_order': 20,
    },
    {
        'field_key': 'email',
        'label': 'E-Mail',
        'field_type': 'text',
        'options': [],
        'is_public': True,
        'is_required': True,
        'admin_only': False,
        'show_in_overview': True,
        'is_active': True,
        'is_core': True,
        'sort_order': 30,
    },
    {
        'field_key': 'phone',
        'label': 'Telefon',
        'field_type': 'text',
        'options': [],
        'is_public': True,
        'is_required': False,
        'admin_only': False,
        'show_in_overview': True,
        'is_active': True,
        'is_core': True,
        'sort_order': 40,
    },
    {
        'field_key': 'tshirt_size',
        'label': 'T-Shirt-Größe',
        'field_type': 'select',
        'options': DEFAULT_TSHIRT_OPTIONS,
        'is_public': True,
        'is_required': True,
        'admin_only': False,
        'show_in_overview': True,
        'is_active': True,
        'is_core': True,
        'sort_order': 50,
    },
    {
        'field_key': 'allergies',
        'label': 'Unverträglichkeiten / Ernährung',
        'field_type': 'textarea',
        'options': [],
        'is_public': True,
        'is_required': False,
        'admin_only': False,
        'show_in_overview': False,
        'is_active': True,
        'is_core': True,
        'sort_order': 60,
    },
    {
        'field_key': 'briefing_done',
        'label': 'Einweisung erledigt',
        'field_type': 'checkbox',
        'options': [],
        'is_public': False,
        'is_required': False,
        'admin_only': True,
        'show_in_overview': False,
        'is_active': True,
        'is_core': False,
        'sort_order': 70,
    },
    {
        'field_key': 'wristband_number',
        'label': 'Bändchen-Nr.',
        'field_type': 'text',
        'options': [],
        'is_public': False,
        'is_required': False,
        'admin_only': True,
        'show_in_overview': False,
        'is_active': True,
        'is_core': False,
        'sort_order': 80,
    },
    {
        'field_key': 'internal_notes',
        'label': 'Interne Notizen',
        'field_type': 'textarea',
        'options': [],
        'is_public': False,
        'is_required': False,
        'admin_only': True,
        'show_in_overview': False,
        'is_active': True,
        'is_core': False,
        'sort_order': 90,
    },
]

DEFAULT_AREAS = [
    ('Artistcare', 'Backstage, Künstlerbetreuung & Check-In AC', True, 10),
    ('Aufbau/Abbau', 'Aufbau, Abbau, Zaunbau & Zaunwache', True, 20),
    ('Check-in', 'Gäste- & Helfer-Check-in', True, 30),
    ('Doku', 'Foto-, Video- und Festivaldokumentation', True, 40),
    ('Gastro-Essen', 'Teamarea Food, Grill & Runner Food', True, 50),
    ('Gastro-Bar', 'Bars, Pavillon, Container, Bierwagen & Pfandstation', True, 60),
    ('Kasse', 'Kassen & Kassen-Container', True, 70),
    ('Team-Area', 'Team-Area Bar & Betreuung', True, 80),
    ('Sani/Secu/Awareness', 'Sanitätsdienst, Security & Awareness', True, 90),
    ('Technik', 'Bühnentechnik, Strom, Mainstage & Aftershow', True, 100),
    ('Workshops', 'Workshops, Siebdruck, Graffiti, SkateJam & Programm', True, 110),
    ('VA-Leitung', 'Produktionsbüro, ADL, Finanzen & Gesamtleitung', False, 120),
]

DEFAULT_VOUCHER_RULES = [
    {
        'name': 'Kurzschicht (0 - 5.9 Std.)',
        'min_hours': 0.0,
        'max_hours': 5.99,
        'food_count': 1,
        'drinks_count': 3,
        'head_bonus_drinks': 1,
    },
    {
        'name': 'Mittelschicht (6 - 10.9 Std.)',
        'min_hours': 6.0,
        'max_hours': 10.99,
        'food_count': 2,
        'drinks_count': 5,
        'head_bonus_drinks': 1,
    },
    {
        'name': 'Langschicht (>= 11 Std.)',
        'min_hours': 11.0,
        'max_hours': None,
        'food_count': 2,
        'drinks_count': 6,
        'head_bonus_drinks': 1,
    },
]


def seed_event_defaults(event_id, session=None):
    """Legt Standard-Felder, Bereiche und Markenregeln für eine Veranstaltung idempotent an."""
    sess = session or db.session

    existing_keys = {
        fc.field_key
        for fc in sess.query(HelperFieldConfig).filter_by(event_id=event_id).all()
    }
    for cfg in DEFAULT_FIELD_CONFIGS:
        if cfg['field_key'] not in existing_keys:
            sess.add(HelperFieldConfig(event_id=event_id, **cfg))

    existing_areas = {
        area.name
        for area in sess.query(HelperArea).filter_by(event_id=event_id).all()
    }
    for name, description, is_public_selectable, sort_order in DEFAULT_AREAS:
        if name not in existing_areas:
            sess.add(
                HelperArea(
                    event_id=event_id,
                    name=name,
                    description=description,
                    is_public_selectable=is_public_selectable,
                    sort_order=sort_order,
                )
            )

    has_rules = sess.query(HelperVoucherRule).filter_by(event_id=event_id).first() is not None
    if not has_rules:
        for rule in DEFAULT_VOUCHER_RULES:
            sess.add(HelperVoucherRule(event_id=event_id, area_id=None, **rule))

    sess.flush()


def ensure_initial_helper_event(session=None):
    """Stellt sicher, dass mindestens eine aktive Veranstaltung mit Defaults existiert."""
    sess = session or db.session
    event = sess.query(HelperEvent).filter_by(is_active=True).order_by(HelperEvent.id.asc()).first()
    if event is None:
        event = HelperEvent(
            name='Veranstaltung 2026',
            slug='veranstaltung-2026',
            description='Standard-Veranstaltung der Helferverwaltung',
            is_active=True,
            apply_enabled=True,
            voucher_calc_mode='per_shift',
        )
        event.ensure_apply_token()
        sess.add(event)
        sess.flush()
    else:
        event.ensure_apply_token()
    seed_event_defaults(event.id, session=sess)
    sess.commit()
    return event
