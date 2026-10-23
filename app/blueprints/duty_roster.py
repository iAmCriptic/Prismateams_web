"""Dienstplan module: Public / Team / Private surfaces."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from app import db
from app.models.duty_roster import (
    ENTRY_TYPE_VACATION,
    TIME_ENTRY_OTHER,
    TIME_ENTRY_SICK,
    TIME_ENTRY_VACATION,
    TIME_ENTRY_WORK,
    WEEKDAY_NAMES_DE,
    DutyExternalPerson,
    DutyPersonConfig,
    DutyRoster,
    DutyRosterColumn,
    DutyRosterDay,
    DutyRosterEntry,
    DutyRosterPlanner,
    DutyTimeEntry,
)
from app.models.team import Team, TeamMember
from app.models.user import User
from app.utils.access_control import check_module_access
from app.utils.common import is_module_enabled
from app.utils.duty_roster import (
    adjust_vacation_days_for_entry_change,
    bootstrap_columns_from_team,
    bootstrap_roster_days,
    can_plan_team,
    can_view_published_roster,
    can_view_team_roster,
    column_active_on,
    create_monthly_roster,
    ensure_duty_schema,
    ensure_person_config,
    entry_map_for_roster,
    filter_days_by_view,
    get_or_create_person_configs,
    get_user_teams,
    parse_cell_value,
    parse_time,
    build_team_month_slots,
    partition_rosters_by_current_month,
    person_stats_for_team,
    planned_hours_by_column_week,
    planned_hours_for_column,
    pull_boundary_days_from_owners,
    push_day_to_peer_rosters,
    resolve_pager_target,
    user_team_ids,
    visible_columns,
    week_boundary_rows,
)
from app.utils.duty_roster_pdf import generate_duty_roster_pdf
from app.utils.i18n import translate
from app.utils.module_visibility_settings import (
    is_global_private_enabled,
    is_global_public_enabled,
    is_global_team_enabled,
)
from app.utils.user_content_access import user_may_access_private, user_may_access_public

duty_roster_bp = Blueprint('duty_roster', __name__, url_prefix='/duty-roster')

MODULE_KEY = 'module_duty_roster'


def _module_on():
    return is_module_enabled(MODULE_KEY)


def _denied(redirect_endpoint='duty_roster.index'):
    flash(translate('duty_roster.flash.access_denied'), 'danger')
    return redirect(url_for(redirect_endpoint))


def _team_surface_guard(*, as_json=False):
    """Modul + globale Team-Sektion — gleiche Guards für Index, View und Mutationen."""
    if not _module_on():
        if as_json:
            return jsonify({
                'ok': False,
                'error': 'module_disabled',
                'message': translate('duty_roster.flash.module_disabled'),
            }), 403
        flash(translate('duty_roster.flash.module_disabled'), 'warning')
        return redirect(url_for('dashboard.index'))
    if not is_global_team_enabled():
        if as_json:
            return jsonify({
                'ok': False,
                'error': 'no_section',
                'message': translate('duty_roster.flash.no_section'),
            }), 403
        flash(translate('duty_roster.flash.no_section'), 'warning')
        return redirect(url_for('duty_roster.index'))
    return None


def _schema_guard(fallback_endpoint='duty_roster.index', **fallback_values):
    """Ensure duty schema; on failure flash and redirect. Returns response or None."""
    if ensure_duty_schema():
        return None
    flash(translate('duty_roster.flash.schema_error'), 'danger')
    return redirect(url_for(fallback_endpoint, **fallback_values))


def _allowed_sections(user):
    sections = []
    if is_global_private_enabled() and user_may_access_private(user):
        sections.append('private')
    if is_global_team_enabled():
        sections.append('team')
    if is_global_public_enabled() and user_may_access_public(user):
        sections.append('public')
    return sections


def _nav_context(section: str = 'team', team_id: int | None = None):
    teams = get_user_teams(current_user)
    if current_user.is_admin:
        teams = Team.query.order_by(Team.name).all()
    plan_teams = [t for t in teams if can_plan_team(current_user, t.id) or can_view_team_roster(current_user, t.id)]
    return {
        'allowed_sections': _allowed_sections(current_user),
        'nav_teams': plan_teams,
        'active_section': section,
        'active_team_id': team_id,
        'module_title': translate('duty_roster.nav.title'),
    }


def _parse_int(raw, default=None):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_float(raw, default=None):
    raw = (raw or '').strip().replace(',', '.')
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_roster_or_404(roster_id: int) -> DutyRoster:
    return DutyRoster.query.get_or_404(roster_id)


def _table_context(
    roster: DutyRoster,
    view: str = 'month',
    focus: date | None = None,
    editable: bool = False,
    show_person_stats: bool = False,
):
    days = filter_days_by_view(list(roster.days), view, focus)
    cols = visible_columns(roster)
    entries = entry_map_for_roster(roster)
    rows = week_boundary_rows(days, roster=roster)
    hours_by_week = planned_hours_by_column_week(roster)
    # Monatsstunden-Pill: nur Tage im Plan-Monat (Nachbarwochen-Tage zählen nur in der KW-Zeile)
    entries_all = entries
    column_week_totals = {}
    for col in cols:
        total = 0.0
        for day in roster.days:
            if day.date.year != roster.year or day.date.month != roster.month:
                continue
            e = entries_all.get((day.id, col.id))
            if e:
                total += e.duration_hours()
        column_week_totals[col.id] = round(total, 2)
    visible_weeks = sorted({r['week'] for r in rows if 'week' in r})
    week_column_hours = {}
    for w in visible_weeks:
        week_column_hours[w] = {
            col.id: hours_by_week.get(col.id, {}).get(w, 0.0) for col in cols
        }

    person_stats = {}
    if show_person_stats:
        today = date.today()
        if (roster.year, roster.month) < (today.year, today.month):
            stats_ref = roster.month_end
        elif (roster.year, roster.month) == (today.year, today.month):
            stats_ref = today
        else:
            stats_ref = today
        for col in cols:
            if col.user_id:
                person_stats[col.id] = person_stats_for_team(
                    roster.team_id, col.user_id, stats_ref
                )

    person_configs = {
        c.user_id: c
        for c in DutyPersonConfig.query.filter_by(team_id=roster.team_id).all()
    }
    # (day_id, column_id) -> aktiv an dem Tag
    cell_active = {}
    for day in days:
        for col in cols:
            cell_active[(day.id, col.id)] = column_active_on(col, day.date, person_configs)

    return {
        'roster': roster,
        'columns': cols,
        'rows': rows,
        'entries': entries,
        'view_mode': view,
        'focus_date': focus,
        'editable': editable,
        'column_week_totals': column_week_totals,
        'week_column_hours': week_column_hours,
        'person_stats': person_stats,
        'cell_active': cell_active,
        'can_plan': can_plan_team(current_user, roster.team_id),
    }


def _pager_urls(roster, view, focus, *, mode=None, published_only=False, endpoint='duty_roster.team_view'):
    """Prev/Next-URLs für Tag/Woche/Monat (None = Button deaktiviert)."""
    result = {'nav_prev_url': None, 'nav_next_url': None}
    for key, delta in (('nav_prev_url', -1), ('nav_next_url', 1)):
        target = resolve_pager_target(
            roster, view, focus, delta, published_only=published_only
        )
        if not target:
            continue
        kwargs = {
            'roster_id': target['roster_id'],
            'view': view,
            'focus': target['focus'].isoformat(),
        }
        if mode is not None:
            kwargs['mode'] = mode
        result[key] = url_for(endpoint, **kwargs)
    return result


# ---------------------------------------------------------------------------
# Index / section router
# ---------------------------------------------------------------------------

@duty_roster_bp.route('/')
@login_required
@check_module_access(MODULE_KEY)
def index():
    if not _module_on():
        flash(translate('duty_roster.flash.module_disabled'), 'warning')
        return redirect(url_for('dashboard.index'))

    sections = _allowed_sections(current_user)
    view = (request.args.get('view') or '').strip()
    if view == 'public' and 'public' in sections:
        return redirect(url_for('duty_roster.public_index'))
    if view == 'private' and 'private' in sections:
        return redirect(url_for('duty_roster.private_index'))
    if view == 'team' or 'team' in sections:
        team_id = _parse_int(request.args.get('team_id'))
        return redirect(url_for('duty_roster.team_index', team_id=team_id) if team_id else url_for('duty_roster.team_index'))
    if 'public' in sections:
        return redirect(url_for('duty_roster.public_index'))
    if 'private' in sections:
        return redirect(url_for('duty_roster.private_index'))
    flash(translate('duty_roster.flash.no_section'), 'warning')
    return redirect(url_for('dashboard.index'))


# ---------------------------------------------------------------------------
# Team surface
# ---------------------------------------------------------------------------

@duty_roster_bp.route('/team')
@login_required
@check_module_access(MODULE_KEY)
def team_index():
    blocked = _team_surface_guard()
    if blocked:
        return blocked
    blocked = _schema_guard()
    if blocked:
        return blocked

    teams = get_user_teams(current_user)
    if current_user.is_admin:
        teams = Team.query.order_by(Team.name).all()
    teams = [t for t in teams if can_view_team_roster(current_user, t.id) or can_plan_team(current_user, t.id)]
    if not teams:
        flash(translate('duty_roster.flash.no_team'), 'info')
        return render_template(
            'duty_roster/team_index.html',
            rosters=[],
            roster_groups={'current': [], 'future': [], 'past': []},
            month_slots=None,
            teams=[],
            selected_team=None,
            can_plan=False,
            **_nav_context('team'),
        )

    team_id = _parse_int(request.args.get('team_id'), teams[0].id)
    if not any(t.id == team_id for t in teams):
        team_id = teams[0].id
    if not can_view_team_roster(current_user, team_id) and not can_plan_team(current_user, team_id):
        return _denied()

    selected = next(t for t in teams if t.id == team_id)
    can_plan = can_plan_team(current_user, team_id)
    rosters = DutyRoster.query.filter_by(team_id=team_id).all()
    roster_groups = partition_rosters_by_current_month(rosters)
    month_slots = build_team_month_slots(rosters) if can_plan else None
    return render_template(
        'duty_roster/team_index.html',
        rosters=rosters,
        roster_groups=roster_groups,
        month_slots=month_slots,
        teams=teams,
        selected_team=selected,
        can_plan=can_plan,
        **_nav_context('team', team_id),
    )


@duty_roster_bp.route('/team/create', methods=['POST'])
@login_required
@check_module_access(MODULE_KEY)
def team_create():
    blocked = _team_surface_guard()
    if blocked:
        return blocked
    team_id = _parse_int(request.form.get('team_id'))
    year = _parse_int(request.form.get('year'), date.today().year)
    month = _parse_int(request.form.get('month'), date.today().month)

    if not team_id or not can_plan_team(current_user, team_id):
        return _denied()
    blocked = _schema_guard('duty_roster.team_index', team_id=team_id)
    if blocked:
        return blocked
    if not (1 <= month <= 12) or year < 2000 or year > 2100:
        flash(translate('duty_roster.flash.invalid_month'), 'danger')
        return redirect(url_for('duty_roster.team_index', team_id=team_id))

    existing = DutyRoster.query.filter_by(team_id=team_id, year=year, month=month).first()
    if existing:
        flash(translate('duty_roster.flash.roster_exists'), 'warning')
        return redirect(url_for('duty_roster.team_view', roster_id=existing.id))

    get_or_create_person_configs(team_id)
    roster = create_monthly_roster(team_id, year, month, current_user.id)
    db.session.commit()
    flash(translate('duty_roster.flash.roster_created'), 'success')
    return redirect(url_for('duty_roster.team_view', roster_id=roster.id))


@duty_roster_bp.route('/team/<int:roster_id>')
@login_required
@check_module_access(MODULE_KEY)
def team_view(roster_id):
    blocked = _team_surface_guard()
    if blocked:
        return blocked
    blocked = _schema_guard()
    if blocked:
        return blocked
    roster = _get_roster_or_404(roster_id)
    if not can_view_team_roster(current_user, roster.team_id) and not can_plan_team(current_user, roster.team_id):
        return _denied()

    can_plan = can_plan_team(current_user, roster.team_id)
    if can_plan:
        bootstrap_roster_days(roster)
        bootstrap_columns_from_team(roster)
    if pull_boundary_days_from_owners(roster) or can_plan:
        db.session.commit()

    view = (request.args.get('view') or 'month').strip()
    if view not in ('day', 'week', 'month'):
        view = 'month'
    mode = (request.args.get('mode') or '').strip()
    if mode not in ('view', 'edit'):
        mode = 'edit' if can_plan else 'view'
    if not can_plan:
        mode = 'view'

    focus_raw = (request.args.get('focus') or '').strip()
    focus = None
    if focus_raw:
        try:
            focus = datetime.strptime(focus_raw, '%Y-%m-%d').date()
        except ValueError:
            focus = None
    if focus is None:
        today = date.today()
        if roster.year == today.year and roster.month == today.month:
            focus = today
        else:
            focus = roster.month_start

    editable = can_plan and mode == 'edit'
    ctx = _table_context(
        roster, view=view, focus=focus, editable=editable, show_person_stats=True
    )
    ctx['editor_mode'] = mode
    ctx.update(_pager_urls(roster, view, focus, mode=mode))
    ctx.update(_nav_context('team', roster.team_id))
    return render_template('duty_roster/team_view.html', **ctx)


@duty_roster_bp.route('/team/<int:roster_id>/publish', methods=['POST'])
@login_required
@check_module_access(MODULE_KEY)
def team_publish(roster_id):
    blocked = _team_surface_guard()
    if blocked:
        return blocked
    roster = _get_roster_or_404(roster_id)
    if not can_plan_team(current_user, roster.team_id):
        return _denied()
    action = (request.form.get('action') or 'publish').strip()
    roster.is_published = action != 'unpublish'
    roster.updated_at = datetime.utcnow()
    db.session.commit()
    if roster.is_published:
        flash(translate('duty_roster.flash.published'), 'success')
    else:
        flash(translate('duty_roster.flash.unpublished'), 'info')
    return redirect(url_for('duty_roster.team_view', roster_id=roster.id))


@duty_roster_bp.route('/team/<int:roster_id>/delete', methods=['POST'])
@login_required
@check_module_access(MODULE_KEY)
def team_delete(roster_id):
    blocked = _team_surface_guard()
    if blocked:
        return blocked
    roster = _get_roster_or_404(roster_id)
    if not can_plan_team(current_user, roster.team_id):
        return _denied()
    team_id = roster.team_id
    db.session.delete(roster)
    db.session.commit()
    flash(translate('duty_roster.flash.roster_deleted'), 'success')
    return redirect(url_for('duty_roster.team_index', team_id=team_id))


@duty_roster_bp.route('/team/<int:roster_id>/day/<int:day_id>', methods=['POST'])
@login_required
@check_module_access(MODULE_KEY)
def team_update_day(roster_id, day_id):
    blocked = _team_surface_guard(as_json=True)
    if blocked:
        return blocked
    roster = _get_roster_or_404(roster_id)
    if not can_plan_team(current_user, roster.team_id):
        return jsonify({
            'ok': False,
            'error': 'denied',
            'message': translate('duty_roster.flash.cell_denied'),
        }), 403
    day = DutyRosterDay.query.filter_by(id=day_id, roster_id=roster.id).first_or_404()
    if 'whats_happening' in request.form:
        day.whats_happening = (request.form.get('whats_happening') or '').strip()[:500] or None
    if 'row_color' in request.form:
        color = (request.form.get('row_color') or '').strip()
        day.row_color = color[:20] if color else None
    roster.updated_at = datetime.utcnow()
    db.session.flush()
    push_day_to_peer_rosters(roster, day.date)
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.best == 'application/json':
        return jsonify({'ok': True})
    return redirect(url_for('duty_roster.team_view', roster_id=roster.id))


@duty_roster_bp.route('/team/<int:roster_id>/cell', methods=['POST'])
@login_required
@check_module_access(MODULE_KEY)
def team_update_cell(roster_id):
    blocked = _team_surface_guard(as_json=True)
    if blocked:
        return blocked
    roster = _get_roster_or_404(roster_id)
    if not can_plan_team(current_user, roster.team_id):
        return jsonify({
            'ok': False,
            'error': 'denied',
            'message': translate('duty_roster.flash.cell_denied'),
        }), 403

    day_id = _parse_int(request.form.get('day_id'))
    column_id = _parse_int(request.form.get('column_id'))
    raw = request.form.get('value', '')

    day = DutyRosterDay.query.filter_by(id=day_id, roster_id=roster.id).first()
    col = DutyRosterColumn.query.filter_by(id=column_id, roster_id=roster.id).first()
    if not day or not col:
        return jsonify({
            'ok': False,
            'error': 'not_found',
            'message': translate('duty_roster.flash.cell_not_found'),
        }), 404
    if not column_active_on(col, day.date):
        return jsonify({
            'ok': False,
            'error': 'inactive',
            'message': translate('duty_roster.flash.cell_inactive'),
        }), 400

    parsed = parse_cell_value(raw)
    entry = DutyRosterEntry.query.filter_by(day_id=day.id, column_id=col.id).first()
    was_vacation = bool(entry and entry.entry_type == ENTRY_TYPE_VACATION)

    if parsed.get('clear'):
        is_vacation = False
        if entry:
            db.session.delete(entry)
            entry = None
        display = ''
        hours = 0.0
    else:
        is_vacation = parsed.get('entry_type') == ENTRY_TYPE_VACATION
        if not entry:
            entry = DutyRosterEntry(day_id=day.id, column_id=col.id)
            db.session.add(entry)
        entry.entry_type = parsed['entry_type']
        entry.label = parsed.get('label')
        entry.start_time = parsed.get('start_time')
        entry.end_time = parsed.get('end_time')
        entry.ends_next_day = bool(parsed.get('ends_next_day'))
        display = entry.display_text()
        hours = entry.duration_hours()

    vacation_remaining = adjust_vacation_days_for_entry_change(
        roster.team_id,
        col.user_id,
        was_vacation=was_vacation,
        is_vacation=is_vacation,
    )

    roster.updated_at = datetime.utcnow()
    db.session.flush()
    push_day_to_peer_rosters(roster, day.date)
    db.session.commit()

    week_hours = planned_hours_for_column(roster, col.id, week=day.iso_week)
    return jsonify({
        'ok': True,
        'display': display,
        'week_hours': week_hours,
        'column_id': col.id,
        'week': day.iso_week,
        'vacation_remaining': vacation_remaining,
    })


def _column_redirect(roster: DutyRoster):
    """Nach Spalten-Aktionen zurück zu Einstellungen (mit Plan) oder Plan-Ansicht."""
    if (request.form.get('return_to') or '').strip() == 'settings':
        return redirect(url_for(
            'duty_roster.team_settings',
            team_id=roster.team_id,
            roster_id=roster.id,
        ))
    return redirect(url_for('duty_roster.team_view', roster_id=roster.id))


@duty_roster_bp.route('/team/<int:roster_id>/columns', methods=['POST'])
@login_required
@check_module_access(MODULE_KEY)
def team_add_column(roster_id):
    blocked = _team_surface_guard()
    if blocked:
        return blocked
    roster = _get_roster_or_404(roster_id)
    if not can_plan_team(current_user, roster.team_id):
        return _denied()

    user_id = _parse_int(request.form.get('user_id'))
    external_name = (request.form.get('external_name') or '').strip()[:120]

    max_order = max((c.sort_order for c in roster.columns), default=-1)
    if user_id:
        if DutyRosterColumn.query.filter_by(roster_id=roster.id, user_id=user_id).first():
            flash(translate('duty_roster.flash.column_exists'), 'warning')
            return _column_redirect(roster)
        if not TeamMember.query.filter_by(team_id=roster.team_id, user_id=user_id).first():
            flash(translate('duty_roster.flash.not_member'), 'danger')
            return _column_redirect(roster)
        col = DutyRosterColumn(
            roster_id=roster.id,
            user_id=user_id,
            sort_order=max_order + 1,
            show_in_plan=True,
        )
    elif external_name:
        col = DutyRosterColumn(
            roster_id=roster.id,
            external_name=external_name,
            sort_order=max_order + 1,
            show_in_plan=True,
        )
    else:
        flash(translate('duty_roster.flash.column_required'), 'danger')
        return _column_redirect(roster)

    db.session.add(col)
    db.session.commit()
    flash(translate('duty_roster.flash.column_added'), 'success')
    return _column_redirect(roster)


@duty_roster_bp.route('/team/<int:roster_id>/columns/<int:column_id>/toggle', methods=['POST'])
@login_required
@check_module_access(MODULE_KEY)
def team_toggle_column(roster_id, column_id):
    blocked = _team_surface_guard()
    if blocked:
        return blocked
    roster = _get_roster_or_404(roster_id)
    if not can_plan_team(current_user, roster.team_id):
        return _denied()
    col = DutyRosterColumn.query.filter_by(id=column_id, roster_id=roster.id).first_or_404()
    col.show_in_plan = not col.show_in_plan
    db.session.commit()
    return _column_redirect(roster)


@duty_roster_bp.route('/team/<int:roster_id>/columns/<int:column_id>/delete', methods=['POST'])
@login_required
@check_module_access(MODULE_KEY)
def team_delete_column(roster_id, column_id):
    blocked = _team_surface_guard()
    if blocked:
        return blocked
    roster = _get_roster_or_404(roster_id)
    if not can_plan_team(current_user, roster.team_id):
        return _denied()
    col = DutyRosterColumn.query.filter_by(id=column_id, roster_id=roster.id).first_or_404()
    db.session.delete(col)
    db.session.commit()
    flash(translate('duty_roster.flash.column_deleted'), 'success')
    return _column_redirect(roster)

@duty_roster_bp.route('/team/<int:roster_id>/pdf')
@login_required
@check_module_access(MODULE_KEY)
def team_pdf(roster_id):
    blocked = _team_surface_guard()
    if blocked:
        return blocked
    roster = _get_roster_or_404(roster_id)
    if not can_view_team_roster(current_user, roster.team_id) and not can_plan_team(current_user, roster.team_id):
        return _denied()
    buf = generate_duty_roster_pdf(roster)
    filename = f'dienstplan_{roster.year}-{roster.month:02d}.pdf'
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)


# ---------------------------------------------------------------------------
# Team settings (Stammdaten + Planner)
# ---------------------------------------------------------------------------

def _parse_date_field(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


@duty_roster_bp.route('/team/<int:team_id>/settings', methods=['GET', 'POST'])
@login_required
@check_module_access(MODULE_KEY)
def team_settings(team_id):
    blocked = _team_surface_guard()
    if blocked:
        return blocked
    blocked = _schema_guard('duty_roster.team_index', team_id=team_id)
    if blocked:
        return blocked
    if not can_plan_team(current_user, team_id):
        return _denied()
    team = Team.query.get_or_404(team_id)
    members = (
        TeamMember.query.filter_by(team_id=team_id)
        .join(User, User.id == TeamMember.user_id)
        .order_by(User.first_name, User.last_name)
        .all()
    )
    get_or_create_person_configs(team_id)
    db.session.commit()

    if request.method == 'POST':
        action = (request.form.get('action') or 'save_configs').strip()
        if action == 'save_configs':
            for m in members:
                cfg = ensure_person_config(team_id, m.user_id)
                prefix = f'user_{m.user_id}_'
                soll = _parse_float(request.form.get(prefix + 'soll'))
                vac_total = _parse_float(request.form.get(prefix + 'vac_total'))
                vac_used = _parse_float(request.form.get(prefix + 'vac_used'), 0.0)
                available = request.form.get(prefix + 'available') == 'on'
                cfg.weekly_hours_soll = soll
                cfg.vacation_days_total = vac_total
                cfg.vacation_days_used = vac_used if vac_used is not None else 0.0
                cfg.available_for_roster = available
                cfg.valid_from = _parse_date_field(request.form.get(prefix + 'from'))
                cfg.valid_until = _parse_date_field(request.form.get(prefix + 'until'))
            for ext in DutyExternalPerson.query.filter_by(team_id=team_id).all():
                prefix = f'ext_{ext.id}_'
                if request.form.get(prefix + 'delete') == 'on':
                    db.session.delete(ext)
                    continue
                name = (request.form.get(prefix + 'name') or '').strip()[:120]
                if name:
                    ext.name = name
                ext.valid_from = _parse_date_field(request.form.get(prefix + 'from'))
                ext.valid_until = _parse_date_field(request.form.get(prefix + 'until'))
                ext.is_active = request.form.get(prefix + 'active') == 'on'
            db.session.commit()
            flash(translate('duty_roster.flash.settings_saved'), 'success')
        elif action == 'add_external':
            name = (request.form.get('external_name') or '').strip()[:120]
            if name:
                max_order = max(
                    (e.sort_order for e in DutyExternalPerson.query.filter_by(team_id=team_id).all()),
                    default=-1,
                )
                db.session.add(DutyExternalPerson(
                    team_id=team_id,
                    name=name,
                    valid_from=_parse_date_field(request.form.get('external_from')),
                    valid_until=_parse_date_field(request.form.get('external_until')),
                    sort_order=max_order + 1,
                    is_active=True,
                ))
                db.session.commit()
                flash(translate('duty_roster.flash.column_added'), 'success')
            else:
                flash(translate('duty_roster.flash.column_required'), 'danger')
        elif action == 'add_planner':
            uid = _parse_int(request.form.get('planner_user_id'))
            if uid and TeamMember.query.filter_by(team_id=team_id, user_id=uid).first():
                if not DutyRosterPlanner.query.filter_by(team_id=team_id, user_id=uid).first():
                    db.session.add(DutyRosterPlanner(team_id=team_id, user_id=uid))
                    db.session.commit()
                    flash(translate('duty_roster.flash.planner_added'), 'success')
        elif action == 'remove_planner':
            uid = _parse_int(request.form.get('planner_user_id'))
            row = DutyRosterPlanner.query.filter_by(team_id=team_id, user_id=uid).first()
            if row:
                db.session.delete(row)
                db.session.commit()
                flash(translate('duty_roster.flash.planner_removed'), 'info')
        return redirect(url_for('duty_roster.team_settings', team_id=team_id))

    configs = {
        c.user_id: c
        for c in DutyPersonConfig.query.filter_by(team_id=team_id).all()
    }
    externals = (
        DutyExternalPerson.query.filter_by(team_id=team_id)
        .order_by(DutyExternalPerson.sort_order, DutyExternalPerson.name)
        .all()
    )
    planners = DutyRosterPlanner.query.filter_by(team_id=team_id).all()
    planner_ids = {p.user_id for p in planners}
    stats = {m.user_id: person_stats_for_team(team_id, m.user_id) for m in members}

    return render_template(
        'duty_roster/team_settings.html',
        team=team,
        members=members,
        configs=configs,
        externals=externals,
        planners=planners,
        planner_ids=planner_ids,
        stats=stats,
        **_nav_context('team', team_id),
    )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

@duty_roster_bp.route('/public')
@login_required
@check_module_access(MODULE_KEY)
def public_index():
    if not _module_on() or not is_global_public_enabled() or not user_may_access_public(current_user):
        return _denied()

    q = DutyRoster.query.filter_by(is_published=True)
    team_id = _parse_int(request.args.get('team_id'))
    if team_id:
        q = q.filter_by(team_id=team_id)
    rosters = q.order_by(DutyRoster.year.desc(), DutyRoster.month.desc()).all()
    teams = Team.query.order_by(Team.name).all()
    return render_template(
        'duty_roster/public_index.html',
        rosters=rosters,
        teams=teams,
        filter_team_id=team_id,
        **_nav_context('public', team_id),
    )


@duty_roster_bp.route('/public/<int:roster_id>')
@login_required
@check_module_access(MODULE_KEY)
def public_view(roster_id):
    roster = _get_roster_or_404(roster_id)
    if not can_view_published_roster(current_user, roster):
        return _denied('duty_roster.public_index')

    view = (request.args.get('view') or 'month').strip()
    if view not in ('day', 'week', 'month'):
        view = 'month'
    focus_raw = (request.args.get('focus') or '').strip()
    focus = None
    if focus_raw:
        try:
            focus = datetime.strptime(focus_raw, '%Y-%m-%d').date()
        except ValueError:
            focus = roster.month_start
    else:
        focus = roster.month_start

    if pull_boundary_days_from_owners(roster):
        db.session.commit()

    ctx = _table_context(roster, view=view, focus=focus, editable=False)
    ctx.update(_pager_urls(
        roster, view, focus,
        published_only=True,
        endpoint='duty_roster.public_view',
    ))
    ctx.update(_nav_context('public', roster.team_id))
    return render_template('duty_roster/public_view.html', **ctx)


@duty_roster_bp.route('/public/<int:roster_id>/pdf')
@login_required
@check_module_access(MODULE_KEY)
def public_pdf(roster_id):
    roster = _get_roster_or_404(roster_id)
    if not can_view_published_roster(current_user, roster):
        return _denied('duty_roster.public_index')
    buf = generate_duty_roster_pdf(roster)
    filename = f'dienstplan_{roster.year}-{roster.month:02d}.pdf'
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)


# ---------------------------------------------------------------------------
# Private surface
# ---------------------------------------------------------------------------

@duty_roster_bp.route('/private')
@login_required
@check_module_access(MODULE_KEY)
def private_index():
    if not _module_on() or not is_global_private_enabled() or not user_may_access_private(current_user):
        return _denied()

    today = date.today()
    # Ist-Zeiten (genug Historie für „Vergangen“)
    time_entries = (
        DutyTimeEntry.query.filter_by(user_id=current_user.id)
        .order_by(DutyTimeEntry.date.desc(), DutyTimeEntry.id.desc())
        .limit(200)
        .all()
    )
    actual_by_date: dict[date, list] = {}
    for e in time_entries:
        actual_by_date.setdefault(e.date, []).append(e)

    # Geplante Schichten (Vergangenheit + Zukunft)
    my_cols = DutyRosterColumn.query.filter_by(user_id=current_user.id).all()
    planned_by_date: dict[date, list] = {}
    seen = set()
    for col in my_cols:
        roster = col.roster
        if not roster:
            continue
        for day in roster.days:
            e = DutyRosterEntry.query.filter_by(day_id=day.id, column_id=col.id).first()
            if not e:
                continue
            key = (day.date, col.id)
            if key in seen:
                continue
            seen.add(key)
            planned_by_date.setdefault(day.date, []).append({
                'team': roster.team,
                'roster': roster,
                'entry': e,
                'whats_happening': day.whats_happening,
            })

    def _day_row(d: date) -> dict:
        return {
            'date': d,
            'weekday': WEEKDAY_NAMES_DE[d.weekday()],
            'planned': planned_by_date.get(d, []),
            'actual': actual_by_date.get(d, []),
        }

    all_dates = set(planned_by_date) | set(actual_by_date)
    today_rows = [_day_row(today)] if today in all_dates else []

    future_dates = sorted(d for d in all_dates if d > today)
    past_dates = sorted((d for d in all_dates if d < today), reverse=True)

    future_preview = [_day_row(d) for d in future_dates[:5]]
    future_more = [_day_row(d) for d in future_dates[5:]]
    past_rows = [_day_row(d) for d in past_dates]

    team_ids = user_team_ids(current_user)
    overtime_blocks = []
    for tid in team_ids:
        cfg = DutyPersonConfig.query.filter_by(team_id=tid, user_id=current_user.id).first()
        stats = person_stats_for_team(tid, current_user.id, today)
        team = Team.query.get(tid)
        overtime_blocks.append({
            'team': team,
            'config': cfg,
            'stats': stats,
        })

    teams = get_user_teams(current_user)
    default_team_id = teams[0].id if len(teams) == 1 else None

    return render_template(
        'duty_roster/private_index.html',
        today=today,
        today_rows=today_rows,
        future_preview=future_preview,
        future_more=future_more,
        past_rows=past_rows,
        overtime_blocks=overtime_blocks,
        default_team_id=default_team_id,
        **_nav_context('private'),
    )


@duty_roster_bp.route('/private/entry', methods=['POST'])
@login_required
@check_module_access(MODULE_KEY)
def private_add_entry():
    if not user_may_access_private(current_user):
        return _denied()

    date_raw = (request.form.get('date') or '').strip()
    try:
        entry_date = datetime.strptime(date_raw, '%Y-%m-%d').date()
    except ValueError:
        flash(translate('duty_roster.flash.invalid_date'), 'danger')
        return redirect(url_for('duty_roster.private_index'))

    entry_type = (request.form.get('entry_type') or TIME_ENTRY_WORK).strip()
    if entry_type not in (TIME_ENTRY_WORK, TIME_ENTRY_SICK, TIME_ENTRY_VACATION, TIME_ENTRY_OTHER):
        entry_type = TIME_ENTRY_WORK

    start = parse_time(request.form.get('start_time', ''))
    end = parse_time(request.form.get('end_time', ''))
    # Ende vor/gleich Start → Folgetag, sonst gleicher Tag (kein Checkbox)
    ends_next = bool(start and end and end <= start)

    note = (request.form.get('note') or '').strip()[:500] or None

    team_ids = user_team_ids(current_user)
    team_id = _parse_int(request.form.get('team_id'))
    if team_id and team_id not in team_ids:
        team_id = None
    if team_id is None and len(team_ids) == 1:
        team_id = team_ids[0]

    if entry_type == TIME_ENTRY_WORK and (not start or not end):
        flash(translate('duty_roster.flash.times_required'), 'danger')
        return redirect(url_for('duty_roster.private_index'))

    entry = DutyTimeEntry(
        user_id=current_user.id,
        team_id=team_id,
        date=entry_date,
        start_time=start if entry_type == TIME_ENTRY_WORK else None,
        end_time=end if entry_type == TIME_ENTRY_WORK else None,
        ends_next_day=ends_next if entry_type == TIME_ENTRY_WORK else False,
        entry_type=entry_type,
        note=note,
    )
    db.session.add(entry)
    db.session.commit()
    flash(translate('duty_roster.flash.time_saved'), 'success')
    return redirect(url_for('duty_roster.private_index'))


@duty_roster_bp.route('/private/entry/<int:entry_id>/delete', methods=['POST'])
@login_required
@check_module_access(MODULE_KEY)
def private_delete_entry(entry_id):
    entry = DutyTimeEntry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id and not current_user.is_admin:
        return _denied('duty_roster.private_index')
    db.session.delete(entry)
    db.session.commit()
    flash(translate('duty_roster.flash.time_deleted'), 'info')
    return redirect(url_for('duty_roster.private_index'))
