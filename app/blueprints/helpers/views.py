"""Geschützte Ansichten für das Modul Helferverwaltung."""

from __future__ import annotations

from datetime import datetime

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app import db
from app.models.helpers import (
    Helper,
    HelperArea,
    HelperAreaWish,
    HelperEvent,
    HelperShift,
)
from app.services.helpers_service import (
    create_helper_event,
    export_area_team_csv,
    get_area_dashboard_data,
    get_area_detail_data,
    get_helper_overview_data,
    get_tshirt_summary,
    get_voucher_summary,
)
from app.utils.access_control import check_module_access
from app.utils.common import is_module_enabled
from app.utils.helpers_seed import ensure_helper_schema, ensure_initial_helper_event
from app.utils.i18n import translate
from . import helpers_bp
from .forms import (
    CORE_FIELD_KEYS,
    calculate_hours_from_times,
    parse_date_optional,
    parse_float_optional,
    parse_int_optional,
)

MODULE_KEY = 'module_helpers'


def _check_access():
    if not is_module_enabled(MODULE_KEY):
        abort(403)
    check_module_access(MODULE_KEY)


@helpers_bp.before_request
def before_request():
    if request.endpoint and request.endpoint.endswith('.public_register'):
        return
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    _check_access()


def _resolve_event_context(event_id=None):
    ensure_helper_schema()
    events = HelperEvent.query.filter_by(is_active=True).order_by(HelperEvent.created_at.desc()).all()

    current_event = None
    if event_id is not None:
        current_event = HelperEvent.query.filter_by(id=event_id, is_active=True).first()
        if current_event is None:
            abort(404)
    elif events:
        current_event = events[0]
    return events, current_event


@helpers_bp.route('/')
@helpers_bp.route('/event/<int:event_id>')
def index(event_id=None):
    """Zentrale Helfer-Übersicht (Stammdaten & Soll-Ist-Abgleich)."""
    events, current_event = _resolve_event_context(event_id)

    search_query = request.args.get('q', '').strip()
    area_filter = parse_int_optional(request.args.get('area_id'))
    status_filter = request.args.get('status', '').strip()
    assignment_filter = request.args.get('assignment', '').strip()

    if current_event is None:
        return render_template(
            'helpers/index.html',
            events=events,
            current_event=None,
            active_nav='index',
            rows=[],
            overview_fields=[],
            all_active_fields=[],
            areas=[],
            search_query=search_query,
            area_filter=area_filter,
            status_filter=status_filter,
            assignment_filter=assignment_filter,
        )

    rows, overview_fields = get_helper_overview_data(
        current_event,
        search_query=search_query,
        area_filter=area_filter,
        status_filter=status_filter,
        assignment_filter=assignment_filter,
    )

    all_active_fields = [fc for fc in current_event.field_configs if fc.is_active]

    return render_template(
        'helpers/index.html',
        events=events,
        current_event=current_event,
        active_nav='index',
        rows=rows,
        overview_fields=overview_fields,
        all_active_fields=all_active_fields,
        areas=current_event.areas,
        search_query=search_query,
        area_filter=area_filter,
        status_filter=status_filter,
        assignment_filter=assignment_filter,
    )


@helpers_bp.route('/events/create', methods=['POST'])
def create_event():
    """Neue Veranstaltung in der Sidebar anlegen."""
    name = (request.form.get('name') or '').strip()
    if not name:
        flash(translate('helpers.flash.event_name_required'), 'danger')
        return redirect(url_for('helpers.index'))

    start_date = parse_date_optional(request.form.get('start_date'))
    end_date = parse_date_optional(request.form.get('end_date'))
    description = request.form.get('description') or ''
    clone_from_id = parse_int_optional(request.form.get('clone_from_event_id'))

    ev = create_helper_event(
        name=name,
        description=description,
        start_date=start_date,
        end_date=end_date,
        clone_from_event_id=clone_from_id,
    )
    flash(translate('helpers.flash.event_created'), 'success')
    return redirect(url_for('helpers.index', event_id=ev.id))


@helpers_bp.route('/event/<int:event_id>/helper/create', methods=['POST'])
def create_helper(event_id):
    """Helfer intern durch Orga-Team anlegen."""
    _, current_event = _resolve_event_context(event_id)

    first_name = (request.form.get('first_name') or '').strip()
    last_name = (request.form.get('last_name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    if not first_name or not last_name or not email:
        flash(translate('helpers.flash.helper_required_fields'), 'danger')
        return redirect(url_for('helpers.index', event_id=current_event.id))

    existing = Helper.query.filter_by(event_id=current_event.id, email=email).first()
    if existing:
        flash(translate('helpers.flash.duplicate_email'), 'danger')
        return redirect(url_for('helpers.index', event_id=current_event.id))

    custom_data = _extract_custom_fields(current_event, request.form)
    helper = Helper(
        event_id=current_event.id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=(request.form.get('phone') or '').strip() or None,
        tshirt_size=(request.form.get('tshirt_size') or '').strip() or None,
        allergies=(request.form.get('allergies') or '').strip() or None,
        status=(request.form.get('status') or 'confirmed').strip(),
        custom_fields=custom_data,
        dsgvo_accepted=True,
        dsgvo_accepted_at=datetime.utcnow(),
    )
    db.session.add(helper)
    db.session.flush()

    available_days = [d.strip() for d in request.form.getlist('available_days') if d.strip()]
    for idx, raw_aid in enumerate(request.form.getlist('area_ids'), start=1):
        aid = parse_int_optional(raw_aid)
        if aid:
            db.session.add(
                HelperAreaWish(
                    helper_id=helper.id,
                    area_id=aid,
                    priority=idx,
                    available_days=available_days,
                )
            )

    db.session.commit()
    flash(translate('helpers.flash.helper_created'), 'success')
    return redirect(url_for('helpers.index', event_id=current_event.id))


@helpers_bp.route('/helper/<int:helper_id>/update', methods=['POST'])
def update_helper(helper_id):
    """Stammdaten & admin_only-Felder eines Helfers aktualisieren."""
    helper = Helper.query.get_or_404(helper_id)
    event = helper.event

    first_name = (request.form.get('first_name') or '').strip()
    last_name = (request.form.get('last_name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    if not first_name or not last_name or not email:
        flash(translate('helpers.flash.helper_required_fields'), 'danger')
        return redirect(url_for('helpers.index', event_id=event.id))

    duplicate = Helper.query.filter(
        Helper.event_id == event.id,
        Helper.email == email,
        Helper.id != helper.id,
    ).first()
    if duplicate:
        flash(translate('helpers.flash.duplicate_email'), 'danger')
        return redirect(url_for('helpers.index', event_id=event.id))

    helper.first_name = first_name
    helper.last_name = last_name
    helper.email = email
    helper.phone = (request.form.get('phone') or '').strip() or None
    helper.tshirt_size = (request.form.get('tshirt_size') or '').strip() or None
    helper.allergies = (request.form.get('allergies') or '').strip() or None
    helper.status = (request.form.get('status') or helper.status).strip()
    helper.custom_fields = _extract_custom_fields(event, request.form, existing=helper.get_custom_fields())

    # Wunschbereiche & Verfügbarkeiten aktualisieren (falls im Formular mitgesendet)
    if 'update_wishes' in request.form:
        HelperAreaWish.query.filter_by(helper_id=helper.id).delete()
        available_days = [d.strip() for d in request.form.getlist('available_days') if d.strip()]
        seen_aids = set()
        for idx, raw_aid in enumerate(request.form.getlist('area_ids'), start=1):
            aid = parse_int_optional(raw_aid)
            if aid and aid not in seen_aids:
                seen_aids.add(aid)
                db.session.add(
                    HelperAreaWish(
                        helper_id=helper.id,
                        area_id=aid,
                        priority=idx,
                        available_days=available_days,
                    )
                )

    db.session.commit()
    flash(translate('helpers.flash.helper_updated'), 'success')
    return redirect(url_for('helpers.index', event_id=event.id))


@helpers_bp.route('/helper/<int:helper_id>/delete', methods=['POST'])
def delete_helper(helper_id):
    helper = Helper.query.get_or_404(helper_id)
    event_id = helper.event_id
    db.session.delete(helper)
    db.session.commit()
    flash(translate('helpers.flash.helper_deleted'), 'success')
    return redirect(url_for('helpers.index', event_id=event_id))


@helpers_bp.route('/helper/<int:helper_id>/send-mail', methods=['POST'])
def send_helper_mail(helper_id):
    """Sendet dem Helfer seinen aktuellen Schichtplan & Details per E-Mail."""
    from .mail import send_helper_schedule_mail

    helper = Helper.query.get_or_404(helper_id)
    try:
        send_helper_schedule_mail(helper.event, helper)
        flash(translate('helpers.flash.mail_sent'), 'success')
    except Exception as exc:
        current_app.logger.warning('Helfer-Mail konnte nicht gesendet werden: %s', exc)
        flash(translate('helpers.flash.mail_failed'), 'danger')
    return redirect(url_for('helpers.index', event_id=helper.event_id))


def _extract_custom_fields(event, form_data, existing=None):
    data = dict(existing or {})
    for fc in event.field_configs:
        if not fc.is_active or fc.field_key in CORE_FIELD_KEYS:
            continue
        key = fc.field_key
        if fc.field_type == 'multiselect':
            data[key] = [v.strip() for v in form_data.getlist(f'custom_{key}') if v.strip()]
        elif fc.field_type == 'checkbox':
            data[key] = form_data.get(f'custom_{key}') in ('1', 'true', 'on', 'yes')
        else:
            data[key] = (form_data.get(f'custom_{key}') or '').strip()
    return data


@helpers_bp.route('/event/<int:event_id>/areas')
def areas(event_id):
    """Bereichs-Übersicht mit Kennzahlen je Bereich."""
    events, current_event = _resolve_event_context(event_id)
    cards = get_area_dashboard_data(current_event)
    return render_template(
        'helpers/areas.html',
        events=events,
        current_event=current_event,
        active_nav='areas',
        cards=cards,
    )


@helpers_bp.route('/event/<int:event_id>/areas/<int:area_id>')
def area_detail(event_id, area_id):
    """Detailansicht eines Bereichs mit Schichtplan, Zuweisung & Team-Liste."""
    events, current_event = _resolve_event_context(event_id)
    area = HelperArea.query.filter_by(id=area_id, event_id=current_event.id).first_or_404()
    detail = get_area_detail_data(current_event, area)
    return render_template(
        'helpers/area_detail.html',
        events=events,
        current_event=current_event,
        active_nav='areas',
        area=area,
        detail=detail,
    )


@helpers_bp.route('/event/<int:event_id>/areas/<int:area_id>/export.csv')
def area_export_csv(event_id, area_id):
    """CSV-Export der eingeteilten Helfer eines Bereichs inkl. Kontakt & Allergien."""
    _, current_event = _resolve_event_context(event_id)
    area = HelperArea.query.filter_by(id=area_id, event_id=current_event.id).first_or_404()
    csv_bytes = export_area_team_csv(current_event, area)
    filename = f'helfer_{area.name.lower().replace("/", "_")}.csv'
    return Response(
        csv_bytes,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@helpers_bp.route('/event/<int:event_id>/areas/<int:area_id>/export.pdf')
def area_export_pdf(event_id, area_id):
    """PDF-Export (Druckansicht) für einen Bereich inkl. Schichtplan & Team-Liste."""
    from app.utils.helpers_pdf import generate_area_team_pdf

    _, current_event = _resolve_event_context(event_id)
    area = HelperArea.query.filter_by(id=area_id, event_id=current_event.id).first_or_404()
    detail = get_area_detail_data(current_event, area)
    pdf_bytes = generate_area_team_pdf(current_event, area, detail)
    filename = f'helfer_{area.name.lower().replace("/", "_")}.pdf'
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'inline; filename="{filename}"'},
    )


@helpers_bp.route('/event/<int:event_id>/shifts/create', methods=['POST'])
def create_shift(event_id):
    _, current_event = _resolve_event_context(event_id)
    area_id = parse_int_optional(request.form.get('area_id'))
    area = HelperArea.query.filter_by(id=area_id, event_id=current_event.id).first_or_404()

    helper_id = parse_int_optional(request.form.get('helper_id'))
    if helper_id:
        helper = Helper.query.filter_by(id=helper_id, event_id=current_event.id).first()
        if helper is None:
            helper_id = None

    group_count = max(parse_int_optional(request.form.get('group_count'), 1) or 1, 1)
    start_time = (request.form.get('start_time') or '').strip() or None
    end_time = (request.form.get('end_time') or '').strip() or None
    hours = parse_float_optional(request.form.get('hours'))
    if hours is None and start_time and end_time:
        hours = calculate_hours_from_times(start_time, end_time)
    hours = max(hours or 0.0, 0.0)
    role_label = (request.form.get('role_label') or '').strip() or None
    is_head = (request.form.get('is_head') in ('1', 'true', 'on', 'yes')) or (
        'head' in (role_label or '').lower()
    )

    is_bulk = request.form.get('is_bulk_post') in ('1', 'true', 'on', 'yes')
    if helper_id is None and group_count > 1 and not is_bulk:
        for _ in range(group_count):
            db.session.add(
                HelperShift(
                    event_id=current_event.id,
                    area_id=area.id,
                    helper_id=None,
                    group_count=1,
                    role_label=role_label,
                    day_label=(request.form.get('day_label') or 'Freitag').strip(),
                    date=parse_date_optional(request.form.get('date')),
                    start_time=start_time,
                    end_time=end_time,
                    hours=hours,
                    is_head=is_head,
                    food_override=parse_int_optional(request.form.get('food_override')),
                    drinks_override=parse_int_optional(request.form.get('drinks_override')),
                    notes=(request.form.get('notes') or '').strip() or None,
                )
            )
    else:
        shift = HelperShift(
            event_id=current_event.id,
            area_id=area.id,
            helper_id=helper_id,
            group_count=1 if helper_id is not None else group_count,
            role_label=role_label,
            day_label=(request.form.get('day_label') or 'Freitag').strip(),
            date=parse_date_optional(request.form.get('date')),
            start_time=start_time,
            end_time=end_time,
            hours=hours,
            is_head=is_head,
            food_override=parse_int_optional(request.form.get('food_override')),
            drinks_override=parse_int_optional(request.form.get('drinks_override')),
            notes=(request.form.get('notes') or '').strip() or None,
        )
        db.session.add(shift)
    db.session.commit()
    flash(translate('helpers.flash.shift_created'), 'success')
    return redirect(url_for('helpers.area_detail', event_id=current_event.id, area_id=area.id))


@helpers_bp.route('/shifts/<int:shift_id>/update', methods=['POST'])
def update_shift(shift_id):
    shift = HelperShift.query.get_or_404(shift_id)
    new_helper_id = parse_int_optional(request.form.get('helper_id'))
    if new_helper_id:
        helper = Helper.query.filter_by(id=new_helper_id, event_id=shift.event_id).first()
        new_helper_id = helper.id if helper else None

    new_role = (request.form.get('role_label') or '').strip() or None
    new_day = (request.form.get('day_label') or shift.day_label).strip()
    new_date = parse_date_optional(request.form.get('date'))
    new_start = (request.form.get('start_time') or '').strip() or None
    new_end = (request.form.get('end_time') or '').strip() or None
    hours_val = parse_float_optional(request.form.get('hours'))
    if hours_val is None and new_start and new_end:
        hours_val = calculate_hours_from_times(new_start, new_end)
    new_hours = max(hours_val if hours_val is not None else 0.0, 0.0)
    new_is_head = (request.form.get('is_head') in ('1', 'true', 'on', 'yes')) or (
        'head' in (new_role or '').lower()
    )
    new_food_ovr = parse_int_optional(request.form.get('food_override'))
    new_drinks_ovr = parse_int_optional(request.form.get('drinks_override'))
    new_notes = (request.form.get('notes') or '').strip() or None

    # Wenn einem Sammelposten (group_count > 1) ein einzelner Helfer zugewiesen wird:
    # 1 Position abspalten statt den gesamten Sammelposten zu überschreiben.
    if new_helper_id is not None and shift.helper_id is None and (shift.group_count or 1) > 1:
        shift.group_count = int(shift.group_count) - 1
        assigned_shift = HelperShift(
            event_id=shift.event_id,
            area_id=shift.area_id,
            helper_id=new_helper_id,
            group_count=1,
            role_label=new_role,
            day_label=new_day,
            date=new_date,
            start_time=new_start,
            end_time=new_end,
            hours=new_hours,
            is_head=new_is_head,
            food_override=new_food_ovr,
            drinks_override=new_drinks_ovr,
            notes=new_notes,
        )
        db.session.add(assigned_shift)
    else:
        shift.helper_id = new_helper_id
        if new_helper_id is not None:
            shift.group_count = 1
        else:
            shift.group_count = max(parse_int_optional(request.form.get('group_count'), 1) or 1, 1)
        shift.role_label = new_role
        shift.day_label = new_day
        shift.date = new_date
        shift.start_time = new_start
        shift.end_time = new_end
        shift.hours = new_hours
        shift.is_head = new_is_head
        shift.food_override = new_food_ovr
        shift.drinks_override = new_drinks_ovr
        shift.notes = new_notes

    db.session.commit()
    flash(translate('helpers.flash.shift_updated'), 'success')
    return redirect(url_for('helpers.area_detail', event_id=shift.event_id, area_id=shift.area_id))


@helpers_bp.route('/shifts/<int:shift_id>/delete', methods=['POST'])
def delete_shift(shift_id):
    shift = HelperShift.query.get_or_404(shift_id)
    event_id = shift.event_id
    area_id = shift.area_id
    db.session.delete(shift)
    db.session.commit()
    flash(translate('helpers.flash.shift_deleted'), 'success')
    return redirect(url_for('helpers.area_detail', event_id=event_id, area_id=area_id))


@helpers_bp.route('/event/<int:event_id>/bedarf')
def bedarf(event_id):
    """T-Shirt- & Marken-Dashboard (Bedarfsermittlung & Ausgabe-Checkliste)."""
    events, current_event = _resolve_event_context(event_id)
    only_assigned = request.args.get('filter', 'all') == 'assigned'
    tshirt_summary = get_tshirt_summary(current_event, only_assigned=only_assigned)
    voucher_summary = get_voucher_summary(current_event)

    return render_template(
        'helpers/bedarf.html',
        events=events,
        current_event=current_event,
        active_nav='bedarf',
        only_assigned=only_assigned,
        tshirt_summary=tshirt_summary,
        voucher_summary=voucher_summary,
    )


@helpers_bp.route('/event/<int:event_id>/ausgabe')
def ausgabe(event_id):
    """Eigene Ansicht für den Ausgabe-Check (Marken, Tage, T-Shirt-Größe, Suche)."""
    events, current_event = _resolve_event_context(event_id)
    voucher_summary = get_voucher_summary(current_event)
    status_filter = request.args.get('status', 'all').strip()

    items = voucher_summary['checklist']
    if status_filter == 'open':
        items = [i for i in items if not i['helper'].vouchers_issued]
    elif status_filter == 'issued':
        items = [i for i in items if i['helper'].vouchers_issued]

    return render_template(
        'helpers/ausgabe.html',
        events=events,
        current_event=current_event,
        active_nav='ausgabe',
        checklist=items,
        status_filter=status_filter,
    )


@helpers_bp.route('/helper/<int:helper_id>/toggle-vouchers', methods=['POST'])
def toggle_vouchers_issued(helper_id):
    """Marken-Ausgabe-Checkliste für einen Helfer umschalten."""
    helper = Helper.query.get_or_404(helper_id)
    helper.vouchers_issued = not helper.vouchers_issued
    helper.vouchers_issued_at = datetime.utcnow() if helper.vouchers_issued else None
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'ok': True,
            'helper_id': helper.id,
            'vouchers_issued': helper.vouchers_issued,
        })
    return redirect(url_for('helpers.bedarf', event_id=helper.event_id))
