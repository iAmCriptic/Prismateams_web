"""Validierungs- und Formular-Helfer für das Helferverwaltungs-Modul."""

from __future__ import annotations

import re
from datetime import datetime

from app.models.helpers import Helper

CORE_FIELD_KEYS = frozenset({
    'first_name',
    'last_name',
    'email',
    'phone',
    'tshirt_size',
    'allergies',
})

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def parse_date_optional(raw_value):
    val = (raw_value or '').strip()
    if not val:
        return None
    try:
        return datetime.strptime(val, '%Y-%m-%d').date()
    except ValueError:
        return None


def parse_float_optional(raw_value, default=None):
    val = str(raw_value or '').strip().replace(',', '.')
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def parse_int_optional(raw_value, default=None):
    val = str(raw_value or '').strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def calculate_hours_from_times(start_time, end_time):
    """Berechnet Stunden aus Start-/Endzeit (z. B. '15:30' - '02:00' -> 10.5)."""
    def _to_minutes(raw):
        text = (raw or '').strip().replace('.', ':')
        m = re.match(r'^(\d{1,2}):(\d{2})$', text)
        if not m:
            return None
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh == 24 and mm == 0:
            return 24 * 60
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh * 60 + mm
        return None

    s_min = _to_minutes(start_time)
    e_min = _to_minutes(end_time)
    if s_min is None or e_min is None:
        return None
    diff = e_min - s_min
    if diff <= 0:
        diff += 24 * 60
    return round(diff / 60.0, 2)


def validate_public_registration(event, form_data):
    """
    Validiert die öffentliche Helfer-Anmeldung dynamisch anhand der aktiven
    `HelperFieldConfig`-Einträge des Events sowie E-Mail-Duplikat- und DSGVO-Prüfung.
    """
    errors = []
    public_fields = [
        fc for fc in event.field_configs
        if fc.is_active and fc.is_public and not fc.admin_only
    ]
    public_field_map = {fc.field_key: fc for fc in public_fields}

    core_values = {
        'first_name': (form_data.get('first_name') or '').strip(),
        'last_name': (form_data.get('last_name') or '').strip(),
        'email': (form_data.get('email') or '').strip().lower(),
        'phone': (form_data.get('phone') or '').strip(),
        'tshirt_size': (form_data.get('tshirt_size') or '').strip(),
        'allergies': (form_data.get('allergies') or '').strip(),
    }

    # Kernfelder prüfen (Vorname, Nachname, E-Mail immer erforderlich)
    if not core_values['first_name']:
        errors.append('Vorname ist ein Pflichtfeld.')
    if not core_values['last_name']:
        errors.append('Nachname ist ein Pflichtfeld.')
    if not core_values['email'] or not EMAIL_RE.match(core_values['email']):
        errors.append('Bitte eine gültige E-Mail-Adresse angeben.')
    else:
        existing = Helper.query.filter_by(
            event_id=event.id,
            email=core_values['email'],
        ).first()
        if existing is not None:
            errors.append('Diese E-Mail-Adresse ist für diese Veranstaltung bereits registriert.')

    custom_values = {}
    for fc in public_fields:
        key = fc.field_key
        if key in CORE_FIELD_KEYS:
            val = core_values.get(key, '')
            if fc.is_required and not val:
                errors.append(f'{fc.label} ist ein Pflichtfeld.')
            continue

        if fc.field_type == 'multiselect':
            val = [v.strip() for v in form_data.getlist(f'custom_{key}') if v.strip()]
            if fc.is_required and not val:
                errors.append(f'{fc.label} ist ein Pflichtfeld.')
            custom_values[key] = val
        elif fc.field_type == 'checkbox':
            val = form_data.get(f'custom_{key}') in ('1', 'true', 'on', 'yes')
            if fc.is_required and not val:
                errors.append(f'{fc.label} muss bestätigt werden.')
            custom_values[key] = val
        else:
            val = (form_data.get(f'custom_{key}') or '').strip()
            if fc.is_required and not val:
                errors.append(f'{fc.label} ist ein Pflichtfeld.')
            if fc.field_type == 'number' and val:
                if parse_float_optional(val) is None:
                    errors.append(f'{fc.label} muss eine gültige Zahl sein.')
            custom_values[key] = val

    # Wunschbereiche & Verfügbarkeit
    selected_area_ids = []
    for raw_id in form_data.getlist('area_ids'):
        aid = parse_int_optional(raw_id)
        if aid and aid not in selected_area_ids:
            selected_area_ids.append(aid)

    available_days = [d.strip() for d in form_data.getlist('available_days') if d.strip()]
    wish_notes = (form_data.get('wish_notes') or '').strip()

    if not public_field_map.get('email'):
        # Fallback falls E-Mail in Config deaktiviert wurde: bleibt Pflicht
        pass

    dsgvo_accepted = form_data.get('dsgvo_accepted') in ('1', 'true', 'on', 'yes')
    if not dsgvo_accepted:
        errors.append('Bitte akzeptiere die Datenschutzhinweise (DSGVO).')

    return errors, {
        'core': core_values,
        'custom': custom_values,
        'area_ids': selected_area_ids,
        'available_days': available_days,
        'wish_notes': wish_notes,
        'dsgvo_accepted': dsgvo_accepted,
    }
