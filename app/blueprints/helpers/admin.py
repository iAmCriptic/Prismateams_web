"""Admin-Einstellungen für das Modul Helferverwaltung."""

from __future__ import annotations

import re

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.models.helpers import (
    HelperArea,
    HelperEvent,
    HelperFieldConfig,
    HelperVoucherRule,
)
from app.utils.i18n import translate
from . import helpers_bp
from .forms import parse_date_optional, parse_float_optional, parse_int_optional
from .views import _resolve_event_context


def _require_admin():
    if not getattr(current_user, 'is_admin', False):
        abort(403)


def _admin_redirect(event_id):
    if (request.form.get('next') or '').strip() == 'settings':
        return redirect(url_for('settings.admin_helpers_settings', event_id=event_id))
    return redirect(url_for('helpers.settings', event_id=event_id))


def _slugify_key(raw_key):
    cleaned = re.sub(r'[^a-z0-9_]+', '_', (raw_key or '').strip().lower()).strip('_')
    return cleaned or 'custom_field'


@helpers_bp.route('/event/<int:event_id>/settings', methods=['GET'])
def settings(event_id):
    """Admin-Einstellungen für Felder, Bereiche, Markenregeln und öffentliche Anmeldung."""
    _require_admin()
    from app.models.email import Mailbox

    events, current_event = _resolve_event_context(event_id)
    public_url = url_for('helpers.public_register', token=current_event.apply_token, _external=True)
    mailboxes = Mailbox.query.filter_by(is_active=True).order_by(Mailbox.name.asc()).all()

    return render_template(
        'helpers/settings.html',
        events=events,
        current_event=current_event,
        active_nav='settings',
        public_url=public_url,
        mailboxes=mailboxes,
    )


@helpers_bp.route('/event/<int:event_id>/settings/general', methods=['POST'])
def update_event_settings(event_id):
    _require_admin()
    _, current_event = _resolve_event_context(event_id)

    name = (request.form.get('name') or '').strip()
    if name:
        current_event.name = name
    current_event.description = (request.form.get('description') or '').strip() or None
    current_event.start_date = parse_date_optional(request.form.get('start_date'))
    current_event.end_date = parse_date_optional(request.form.get('end_date'))
    current_event.apply_enabled = request.form.get('apply_enabled') in ('1', 'true', 'on', 'yes')

    calc_mode = (request.form.get('voucher_calc_mode') or 'per_shift').strip()
    if calc_mode in ('per_shift', 'cumulative_per_person_day'):
        current_event.voucher_calc_mode = calc_mode

    if 'mailbox_id' in request.form:
        current_event.mailbox_id = parse_int_optional(request.form.get('mailbox_id'))
    if 'mail_template_subject' in request.form:
        subj = (request.form.get('mail_template_subject') or '').strip()
        if subj:
            current_event.mail_template_subject = subj
    if 'mail_template_body' in request.form:
        body = (request.form.get('mail_template_body') or '').strip()
        if body:
            current_event.mail_template_body = body

    db.session.commit()
    flash(translate('helpers.flash.settings_saved'), 'success')
    return _admin_redirect(current_event.id)


@helpers_bp.route('/event/<int:event_id>/settings/fields/create', methods=['POST'])
def create_field(event_id):
    _require_admin()
    _, current_event = _resolve_event_context(event_id)

    label = (request.form.get('label') or '').strip()
    if not label:
        flash(translate('helpers.flash.field_label_required'), 'danger')
        return redirect(url_for('helpers.settings', event_id=current_event.id))

    raw_key = (request.form.get('field_key') or '').strip() or label
    field_key = _slugify_key(raw_key)

    base_key = field_key
    suffix = 1
    while HelperFieldConfig.query.filter_by(event_id=current_event.id, field_key=field_key).first():
        suffix += 1
        field_key = f'{base_key}_{suffix}'

    field_type = (request.form.get('field_type') or 'text').strip()
    if field_type not in ('text', 'textarea', 'number', 'select', 'multiselect', 'checkbox'):
        field_type = 'text'

    raw_options = request.form.get('options') or ''
    options = [o.strip() for o in raw_options.split(',') if o.strip()]

    max_order = max((fc.sort_order for fc in current_event.field_configs), default=0)
    fc = HelperFieldConfig(
        event_id=current_event.id,
        field_key=field_key,
        label=label,
        field_type=field_type,
        options=options,
        is_public=request.form.get('is_public') in ('1', 'true', 'on', 'yes'),
        is_required=request.form.get('is_required') in ('1', 'true', 'on', 'yes'),
        admin_only=request.form.get('admin_only') in ('1', 'true', 'on', 'yes'),
        show_in_overview=request.form.get('show_in_overview') in ('1', 'true', 'on', 'yes'),
        is_active=True,
        is_core=False,
        sort_order=parse_int_optional(request.form.get('sort_order'), max_order + 10) or (max_order + 10),
    )
    db.session.add(fc)
    db.session.commit()
    flash(translate('helpers.flash.field_created'), 'success')
    return _admin_redirect(current_event.id)


@helpers_bp.route('/settings/fields/<int:field_id>/update', methods=['POST'])
def update_field(field_id):
    _require_admin()
    fc = HelperFieldConfig.query.get_or_404(field_id)

    label = (request.form.get('label') or '').strip()
    if label:
        fc.label = label

    if not fc.is_core:
        field_type = (request.form.get('field_type') or fc.field_type).strip()
        if field_type in ('text', 'textarea', 'number', 'select', 'multiselect', 'checkbox'):
            fc.field_type = field_type

    raw_options = request.form.get('options')
    if raw_options is not None:
        fc.options = [o.strip() for o in raw_options.split(',') if o.strip()]

    fc.is_public = request.form.get('is_public') in ('1', 'true', 'on', 'yes')
    fc.is_required = request.form.get('is_required') in ('1', 'true', 'on', 'yes')
    fc.admin_only = request.form.get('admin_only') in ('1', 'true', 'on', 'yes')
    fc.show_in_overview = request.form.get('show_in_overview') in ('1', 'true', 'on', 'yes')
    fc.is_active = request.form.get('is_active') in ('1', 'true', 'on', 'yes')
    sort_val = parse_int_optional(request.form.get('sort_order'))
    if sort_val is not None:
        fc.sort_order = sort_val

    db.session.commit()
    flash(translate('helpers.flash.field_updated'), 'success')
    return redirect(url_for('helpers.settings', event_id=fc.event_id))


@helpers_bp.route('/settings/fields/<int:field_id>/delete', methods=['POST'])
def delete_field(field_id):
    _require_admin()
    fc = HelperFieldConfig.query.get_or_404(field_id)
    event_id = fc.event_id
    if fc.is_core:
        fc.is_active = False
    else:
        db.session.delete(fc)
    db.session.commit()
    flash(translate('helpers.flash.field_deleted'), 'success')
    return _admin_redirect(event_id)


@helpers_bp.route('/event/<int:event_id>/settings/areas/create', methods=['POST'])
def create_area(event_id):
    _require_admin()
    _, current_event = _resolve_event_context(event_id)

    name = (request.form.get('name') or '').strip()
    if not name:
        flash(translate('helpers.flash.area_name_required'), 'danger')
        return redirect(url_for('helpers.settings', event_id=current_event.id))

    existing = HelperArea.query.filter_by(event_id=current_event.id, name=name).first()
    if existing:
        flash(translate('helpers.flash.area_duplicate'), 'danger')
        return redirect(url_for('helpers.settings', event_id=current_event.id))

    max_order = max((a.sort_order for a in current_event.areas), default=0)
    area = HelperArea(
        event_id=current_event.id,
        name=name,
        description=(request.form.get('description') or '').strip() or None,
        is_public_selectable=request.form.get('is_public_selectable') in ('1', 'true', 'on', 'yes'),
        sort_order=parse_int_optional(request.form.get('sort_order'), max_order + 10) or (max_order + 10),
    )
    db.session.add(area)
    db.session.commit()
    flash(translate('helpers.flash.area_created'), 'success')
    return _admin_redirect(current_event.id)


@helpers_bp.route('/settings/areas/<int:area_id>/update', methods=['POST'])
def update_area(area_id):
    _require_admin()
    area = HelperArea.query.get_or_404(area_id)
    name = (request.form.get('name') or '').strip()
    if name:
        area.name = name
    area.description = (request.form.get('description') or '').strip() or None
    area.is_public_selectable = request.form.get('is_public_selectable') in ('1', 'true', 'on', 'yes')
    sort_val = parse_int_optional(request.form.get('sort_order'))
    if sort_val is not None:
        area.sort_order = sort_val
    db.session.commit()
    flash(translate('helpers.flash.area_updated'), 'success')
    return redirect(url_for('helpers.settings', event_id=area.event_id))


@helpers_bp.route('/settings/areas/<int:area_id>/delete', methods=['POST'])
def delete_area(area_id):
    _require_admin()
    area = HelperArea.query.get_or_404(area_id)
    event_id = area.event_id
    db.session.delete(area)
    db.session.commit()
    flash(translate('helpers.flash.area_deleted'), 'success')
    return _admin_redirect(event_id)


@helpers_bp.route('/event/<int:event_id>/settings/rules/create', methods=['POST'])
def create_voucher_rule(event_id):
    _require_admin()
    _, current_event = _resolve_event_context(event_id)

    name = (request.form.get('name') or '').strip() or 'Neue Regel'
    min_hours = parse_float_optional(request.form.get('min_hours'), 0.0) or 0.0
    max_hours = parse_float_optional(request.form.get('max_hours'))
    food_count = parse_int_optional(request.form.get('food_count'), 0) or 0
    drinks_count = parse_int_optional(request.form.get('drinks_count'), 0) or 0
    head_bonus = parse_int_optional(request.form.get('head_bonus_drinks'), 0) or 0
    area_id = parse_int_optional(request.form.get('area_id'))

    rule = HelperVoucherRule(
        event_id=current_event.id,
        name=name,
        min_hours=min_hours,
        max_hours=max_hours,
        food_count=max(food_count, 0),
        drinks_count=max(drinks_count, 0),
        head_bonus_drinks=max(head_bonus, 0),
        area_id=area_id,
    )
    db.session.add(rule)
    db.session.commit()
    flash(translate('helpers.flash.rule_created'), 'success')
    return _admin_redirect(current_event.id)


@helpers_bp.route('/settings/rules/<int:rule_id>/update', methods=['POST'])
def update_voucher_rule(rule_id):
    _require_admin()
    rule = HelperVoucherRule.query.get_or_404(rule_id)
    rule.name = (request.form.get('name') or rule.name).strip()
    rule.min_hours = parse_float_optional(request.form.get('min_hours'), rule.min_hours) or 0.0
    rule.max_hours = parse_float_optional(request.form.get('max_hours'))
    rule.food_count = max(parse_int_optional(request.form.get('food_count'), rule.food_count) or 0, 0)
    rule.drinks_count = max(parse_int_optional(request.form.get('drinks_count'), rule.drinks_count) or 0, 0)
    rule.head_bonus_drinks = max(parse_int_optional(request.form.get('head_bonus_drinks'), rule.head_bonus_drinks) or 0, 0)
    rule.area_id = parse_int_optional(request.form.get('area_id'))
    db.session.commit()
    flash(translate('helpers.flash.rule_updated'), 'success')
    return redirect(url_for('helpers.settings', event_id=rule.event_id))


@helpers_bp.route('/settings/rules/<int:rule_id>/delete', methods=['POST'])
def delete_voucher_rule(rule_id):
    _require_admin()
    rule = HelperVoucherRule.query.get_or_404(rule_id)
    event_id = rule.event_id
    db.session.delete(rule)
    db.session.commit()
    flash(translate('helpers.flash.rule_deleted'), 'success')
    return _admin_redirect(event_id)
