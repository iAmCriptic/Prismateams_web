"""Öffentliche Anmelderouten für das Modul Helferverwaltung (ohne Login zugänglich)."""

from __future__ import annotations

from datetime import datetime

from flask import abort, render_template, request

from app import db
from app.models.helpers import Helper, HelperArea, HelperAreaWish, HelperEvent
from app.utils.helpers_seed import ensure_initial_helper_event
from app.utils.i18n import translate
from . import helpers_bp
from .forms import validate_public_registration

DEFAULT_DAY_OPTIONS = ['Freitag', 'Samstag', 'Sonntag', 'Aufbau / Abbau']


def _resolve_public_event(token=None):
    if token:
        event = HelperEvent.query.filter_by(apply_token=token, is_active=True).first()
        if not event or not event.apply_enabled:
            abort(404)
        return event

    event = (
        HelperEvent.query.filter_by(is_active=True, apply_enabled=True)
        .order_by(HelperEvent.id.asc())
        .first()
    )
    if event is None:
        event = ensure_initial_helper_event()
        if not event.apply_enabled:
            abort(404)
    return event


@helpers_bp.route('/anmeldung', methods=['GET', 'POST'])
@helpers_bp.route('/anmeldung/<token>', methods=['GET', 'POST'])
def public_register(token=None):
    """Öffentliche Helfer-Anmeldeseite (ohne Login zugänglich)."""
    event = _resolve_public_event(token=token)

    public_fields = [
        fc for fc in event.field_configs
        if fc.is_active and fc.is_public and not fc.admin_only
    ]
    selectable_areas = [
        area for area in event.areas
        if area.is_public_selectable
    ]

    errors = []
    success = False
    submitted_data = {}

    if request.method == 'POST':
        errors, cleaned = validate_public_registration(event, request.form)
        submitted_data = request.form

        if not errors:
            core = cleaned['core']
            helper = Helper(
                event_id=event.id,
                first_name=core['first_name'],
                last_name=core['last_name'],
                email=core['email'],
                phone=core['phone'] or None,
                tshirt_size=core['tshirt_size'] or None,
                allergies=core['allergies'] or None,
                status='registered',
                custom_fields=cleaned['custom'],
                dsgvo_accepted=True,
                dsgvo_accepted_at=datetime.utcnow(),
            )
            db.session.add(helper)
            db.session.flush()

            valid_area_ids = {a.id for a in selectable_areas}
            priority = 1
            for area_id in cleaned['area_ids']:
                if area_id not in valid_area_ids:
                    continue
                db.session.add(
                    HelperAreaWish(
                        helper_id=helper.id,
                        area_id=area_id,
                        priority=priority,
                        available_days=cleaned['available_days'],
                        notes=cleaned['wish_notes'] or None,
                    )
                )
                priority += 1

            db.session.commit()
            success = True
            submitted_data = {}

    return render_template(
        'helpers/public_register.html',
        event=event,
        public_fields=public_fields,
        selectable_areas=selectable_areas,
        day_options=DEFAULT_DAY_OPTIONS,
        errors=errors,
        success=success,
        submitted_data=submitted_data,
        page_title=translate('helpers.public.title'),
    )
