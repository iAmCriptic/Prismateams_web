"""Helpers for optional multi-calendar mode (public / personal / team)."""

from sqlalchemy import or_

from app import db
from app.models.calendar import Calendar, CalendarEvent, EventParticipant
from app.models.settings import SystemSettings
from app.models.team import Team, TeamMember
from app.models.user import User

PUBLIC_CALENDAR_NAME = 'Public'
EVENTS_CALENDAR_NAME = 'Veranstaltungen'
PERSONAL_CALENDAR_NAME = 'Mein Kalender'
TEAM_CALENDAR_NAME = 'Team-Kalender'
DEFAULT_PUBLIC_COLOR = '#198754'
DEFAULT_EVENTS_COLOR = '#e85d04'
DEFAULT_IMPORT_COLOR = '#6c757d'
DEFAULT_TEAM_COLOR = '#6f42c1'

PERSONAL_COLORS = (
    '#0d6efd', '#6610f2', '#d63384', '#fd7e14',
    '#20c997', '#0dcaf0', '#ffc107', '#dc3545',
)


def _setting_bool(key, default=False):
    setting = SystemSettings.query.filter_by(key=key).first()
    if not setting or setting.value is None or str(setting.value).strip() == '':
        return default
    return str(setting.value).lower() == 'true'


def _setting_exists(key):
    setting = SystemSettings.query.filter_by(key=key).first()
    return setting is not None and setting.value is not None and str(setting.value).strip() != ''


def is_calendar_personal_enabled():
    if _setting_exists('calendar_personal_enabled'):
        return _setting_bool('calendar_personal_enabled', False)
    return _setting_bool('calendar_multi_enabled', False)


def is_calendar_team_enabled():
    return _setting_bool('calendar_team_enabled', False)


def is_calendar_multi_enabled():
    """Sidebar / multi-calendar UI: personal, team, or extra public calendars."""
    if is_calendar_personal_enabled() or is_calendar_team_enabled():
        return True
    try:
        return Calendar.query.filter_by(calendar_type='public').count() > 1
    except Exception:
        return False


def is_calendar_export_enabled():
    return _setting_bool('calendar_export_enabled', True)


def is_calendar_import_enabled():
    return _setting_bool('calendar_import_enabled', True)


def _color_for_user(user_id):
    return PERSONAL_COLORS[int(user_id or 0) % len(PERSONAL_COLORS)]


def user_calendar_team_ids(user):
    if not user or not getattr(user, 'id', None):
        return set()
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return {tid for (tid,) in Team.query.with_entities(Team.id).all()}
    return {m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()}


def _is_team_member(user, team_id):
    if not user or not team_id:
        return False
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return True
    return TeamMember.query.filter_by(team_id=team_id, user_id=user.id).first() is not None


def _mark_default(cal):
    if cal and not cal.is_default:
        cal.is_default = True
    return cal


def get_public_calendar():
    cal = Calendar.query.filter_by(calendar_type='public', is_default=True).order_by(Calendar.id.asc()).first()
    if cal:
        return cal
    cal = Calendar.query.filter_by(calendar_type='public').order_by(Calendar.id.asc()).first()
    if cal:
        return _mark_default(cal)
    cal = Calendar(
        name=PUBLIC_CALENDAR_NAME,
        calendar_type='public',
        owner_id=None,
        color=DEFAULT_PUBLIC_COLOR,
        is_default=True,
    )
    db.session.add(cal)
    db.session.flush()
    return cal


def list_public_calendars():
    get_public_calendar()
    return (
        Calendar.query.filter_by(calendar_type='public')
        .order_by(Calendar.is_default.desc(), Calendar.name.asc(), Calendar.id.asc())
        .all()
    )


def get_or_create_events_calendar():
    """Singleton calendar for Events/Booking module entries."""
    cal = Calendar.query.filter_by(calendar_type='events').first()
    if cal:
        return _mark_default(cal)
    cal = Calendar(
        name=EVENTS_CALENDAR_NAME,
        calendar_type='events',
        owner_id=None,
        color=DEFAULT_EVENTS_COLOR,
        is_default=True,
    )
    db.session.add(cal)
    db.session.flush()
    return cal


def target_calendar_id_for_module_events():
    """Calendar for Events/Booking module entries.

    Multi on → Veranstaltungen; multi off → Public (single shared calendar).
    """
    if is_calendar_multi_enabled():
        return get_or_create_events_calendar().id
    return get_public_calendar().id


def fold_events_calendar_into_public():
    """Move Veranstaltungen events into Public (when multi-calendar is turned off)."""
    events_cal = Calendar.query.filter_by(calendar_type='events').first()
    if not events_cal:
        return 0
    public = get_public_calendar()
    if events_cal.id == public.id:
        return 0
    updated = (
        CalendarEvent.query
        .filter_by(calendar_id=events_cal.id)
        .update({CalendarEvent.calendar_id: public.id}, synchronize_session=False)
    )
    return updated or 0


def get_or_create_personal_calendar(user):
    user_id = user.id if hasattr(user, 'id') else int(user)
    cal = (
        Calendar.query.filter_by(calendar_type='personal', owner_id=user_id, is_default=True)
        .order_by(Calendar.id.asc())
        .first()
    )
    if cal:
        return cal
    cal = (
        Calendar.query.filter_by(calendar_type='personal', owner_id=user_id)
        .order_by(Calendar.id.asc())
        .first()
    )
    if cal:
        return _mark_default(cal)
    owner = user if hasattr(user, 'full_name') else User.query.get(user_id)
    name = PERSONAL_CALENDAR_NAME
    if owner and getattr(owner, 'full_name', None):
        name = owner.full_name
    cal = Calendar(
        name=name,
        calendar_type='personal',
        owner_id=user_id,
        color=_color_for_user(user_id),
        is_default=True,
    )
    db.session.add(cal)
    db.session.flush()
    return cal


def list_personal_calendars(user):
    user_id = user.id if hasattr(user, 'id') else int(user)
    get_or_create_personal_calendar(user)
    return (
        Calendar.query.filter_by(calendar_type='personal', owner_id=user_id)
        .order_by(Calendar.is_default.desc(), Calendar.name.asc(), Calendar.id.asc())
        .all()
    )


def get_or_create_team_calendar(team, created_by=None):
    if not team or not getattr(team, 'id', None):
        return None
    cal = (
        Calendar.query.filter_by(calendar_type='team', team_id=team.id, is_default=True)
        .order_by(Calendar.id.asc())
        .first()
    )
    if cal:
        return cal
    cal = (
        Calendar.query.filter_by(calendar_type='team', team_id=team.id)
        .order_by(Calendar.id.asc())
        .first()
    )
    if cal:
        if cal.name != team.name:
            cal.name = team.name
        return _mark_default(cal)
    cal = Calendar(
        name=team.name or TEAM_CALENDAR_NAME,
        calendar_type='team',
        team_id=team.id,
        owner_id=created_by or team.leader_id,
        color=team.color or DEFAULT_TEAM_COLOR,
        is_default=True,
    )
    db.session.add(cal)
    db.session.flush()
    return cal


def list_team_calendars_for_user(user):
    if not is_calendar_team_enabled():
        return []
    from app.utils.team_module_settings import filter_teams_with_section

    team_ids = list(user_calendar_team_ids(user))
    if not team_ids:
        return []
    teams = Team.query.filter(Team.id.in_(team_ids)).order_by(Team.name.asc()).all()
    teams = filter_teams_with_section(teams, 'calendar')
    team_ids = [t.id for t in teams]
    if not team_ids:
        return []
    calendars = []
    for team in teams:
        get_or_create_team_calendar(team, created_by=getattr(user, 'id', None))
    rows = (
        Calendar.query.filter(Calendar.calendar_type == 'team', Calendar.team_id.in_(team_ids))
        .order_by(Calendar.team_id.asc(), Calendar.is_default.desc(), Calendar.name.asc(), Calendar.id.asc())
        .all()
    )
    calendars.extend(rows)
    return calendars


def ensure_imported_calendar_for_source(source):
    """Ensure a Calendar row exists for a sync source (multi mode)."""
    cal = Calendar.query.filter_by(sync_source_id=source.id).first()
    if cal:
        if cal.name != source.name:
            cal.name = source.name
        return cal
    cal = Calendar(
        name=source.name,
        calendar_type='imported',
        owner_id=source.created_by,
        sync_source_id=source.id,
        color=DEFAULT_IMPORT_COLOR,
        is_default=False,
    )
    db.session.add(cal)
    db.session.flush()
    return cal


def can_view_calendar(user, calendar):
    if not calendar:
        return False
    ctype = calendar.calendar_type
    if ctype in ('public', 'events'):
        return True
    if ctype == 'imported':
        return getattr(user, 'is_admin', False) or calendar.owner_id == getattr(user, 'id', None)
    if ctype == 'personal':
        if calendar.owner_id == getattr(user, 'id', None):
            return True
        if not is_calendar_personal_enabled():
            return False
        return not bool(calendar.hidden_from_others)
    if ctype == 'team':
        if not is_calendar_team_enabled():
            return False
        return _is_team_member(user, calendar.team_id)
    return False


def can_create_in_calendar(user, calendar):
    if not calendar or not user:
        return False
    if calendar.calendar_type == 'events':
        return False
    if calendar.calendar_type == 'imported':
        return False
    if calendar.calendar_type == 'public':
        return True
    if calendar.calendar_type == 'personal':
        if not is_calendar_personal_enabled():
            return False
        return calendar.owner_id == user.id
    if calendar.calendar_type == 'team':
        if not is_calendar_team_enabled():
            return False
        return _is_team_member(user, calendar.team_id)
    return False


def can_manage_calendar(user, calendar):
    """Rename / color / hide / delete extra calendars."""
    if not user or not calendar:
        return False
    if calendar.calendar_type == 'events':
        return False
    if calendar.calendar_type == 'imported':
        return getattr(user, 'is_admin', False) or calendar.owner_id == user.id
    if calendar.calendar_type == 'personal':
        return calendar.owner_id == user.id
    if calendar.calendar_type == 'team':
        return _is_team_member(user, calendar.team_id)
    if calendar.calendar_type == 'public':
        return True
    return False


def can_delete_calendar_row(user, calendar):
    if not can_manage_calendar(user, calendar):
        return False
    if calendar.calendar_type == 'events':
        return False
    if calendar.is_default and calendar.calendar_type in ('personal', 'public', 'team'):
        return False
    if calendar.calendar_type == 'imported':
        return True
    return calendar.calendar_type in ('personal', 'public', 'team')


def _is_module_managed_calendar_event(event):
    """Termine aus Events-/Booking-Modul — nicht frei über die Kalender-UI änderbar.

    Admins dürfen weiterhin über can_edit_event / can_delete_event.
    Änderungen laufen sonst über Events-/Booking-Modul (Sync schreibt zurück).
    """
    if event is None:
        return False
    cal = getattr(event, 'calendar', None)
    if cal is not None and getattr(cal, 'calendar_type', None) == 'events':
        return True
    if getattr(event, 'booking_request_id', None):
        return True
    event_id = getattr(event, 'id', None)
    if not event_id:
        return False
    try:
        from app.models.event import EventAppointment
        return (
            EventAppointment.query
            .filter_by(calendar_event_id=event_id)
            .first()
            is not None
        )
    except Exception:
        return False


def can_edit_event(user, event):
    if getattr(user, 'is_admin', False):
        return True
    if _is_module_managed_calendar_event(event):
        return False
    if not is_calendar_multi_enabled():
        return True
    cal = event.calendar
    if cal is None:
        return event.created_by == user.id
    if cal.calendar_type == 'public':
        return True
    if cal.calendar_type == 'personal':
        return event.created_by == user.id
    if cal.calendar_type == 'team':
        return _is_team_member(user, cal.team_id)
    return False


def can_delete_event(user, event):
    if getattr(user, 'is_admin', False):
        return True
    if _is_module_managed_calendar_event(event):
        return False
    if not is_calendar_multi_enabled():
        return False
    cal = event.calendar
    if cal is None:
        return event.created_by == user.id
    if cal.calendar_type == 'public':
        return True
    if cal.calendar_type == 'personal':
        return event.created_by == user.id
    if cal.calendar_type == 'team':
        return _is_team_member(user, cal.team_id)
    return False


def parse_calendar_ids_param(raw, default_ids=None):
    if raw is None or str(raw).strip() == '':
        return list(default_ids or [])
    ids = []
    for part in str(raw).split(','):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return ids


def event_ids_for_invites(user_id):
    rows = (
        EventParticipant.query
        .filter(
            EventParticipant.user_id == user_id,
            EventParticipant.status.in_(('pending', 'accepted')),
        )
        .with_entities(EventParticipant.event_id)
        .all()
    )
    return {r[0] for r in rows}


def _invite_overlay_event_ids(user, selected_calendar_ids):
    """Invite IDs that may appear when personal is selected.

    Only events on *other personal* calendars — never public/events/imported
    (those must be explicitly selected to avoid the participant leak).
    """
    if not is_calendar_personal_enabled():
        return set()
    personal = get_or_create_personal_calendar(user)
    selected = set(selected_calendar_ids or [])
    own_personal_ids = {
        c.id for c in Calendar.query.filter_by(calendar_type='personal', owner_id=user.id).all()
    }
    if not (own_personal_ids & selected) and personal.id not in selected:
        return set()

    invite_ids = event_ids_for_invites(user.id)
    if not invite_ids:
        return set()

    rows = (
        CalendarEvent.query
        .filter(CalendarEvent.id.in_(list(invite_ids)))
        .join(Calendar, CalendarEvent.calendar_id == Calendar.id)
        .filter(
            Calendar.calendar_type == 'personal',
            Calendar.owner_id != user.id,
            Calendar.hidden_from_others.is_(False),
        )
        .with_entities(CalendarEvent.id)
        .all()
    )
    return {r[0] for r in rows}


def filter_events_for_calendars(events, user, selected_calendar_ids):
    """Filter a list of CalendarEvent by selected calendars + invite overlay."""
    if not is_calendar_multi_enabled():
        return list(events)

    selected = set(selected_calendar_ids or [])
    invite_ids = _invite_overlay_event_ids(user, selected)

    result = []
    seen = set()
    for event in events:
        if event.id in seen:
            continue
        cid = event.calendar_id
        if cid in selected:
            result.append(event)
            seen.add(event.id)
        elif event.id in invite_ids:
            result.append(event)
            seen.add(event.id)
    return result


def events_query_for_calendars(user, selected_calendar_ids, base_filters=None):
    """Build a CalendarEvent query filtered for multi-calendar selection."""
    q = CalendarEvent.query
    if base_filters:
        for f in base_filters:
            q = q.filter(f)

    if not is_calendar_multi_enabled():
        return q

    selected = list(selected_calendar_ids or [])
    if not selected:
        default = default_calendar_for_user(user)
        selected = [default.id] if default else []

    invite_ids = _invite_overlay_event_ids(user, selected)

    conditions = [CalendarEvent.calendar_id.in_(selected)] if selected else []
    if invite_ids:
        conditions.append(CalendarEvent.id.in_(list(invite_ids)))
    if not conditions:
        return q.filter(False)
    return q.filter(or_(*conditions))


def default_calendar_for_user(user):
    if is_calendar_personal_enabled() and user:
        return get_or_create_personal_calendar(user)
    return get_public_calendar()


def list_writable_calendars(user):
    cals = []
    if is_calendar_personal_enabled() and user:
        cals.extend(list_personal_calendars(user))
    if is_calendar_team_enabled() and user:
        cals.extend(list_team_calendars_for_user(user))
    cals.extend(list_public_calendars())
    return [c for c in cals if can_create_in_calendar(user, c)]


def list_sidebar_calendars(user):
    """Ordered calendars for sidebar groups."""
    personal = None
    personals = []
    if is_calendar_personal_enabled() and user:
        personals = list_personal_calendars(user)
        personal = get_or_create_personal_calendar(user)

    publics = list_public_calendars()
    public = get_public_calendar()
    events_cal = get_or_create_events_calendar() if is_calendar_multi_enabled() else None
    teams = list_team_calendars_for_user(user) if is_calendar_team_enabled() else []

    reserved_ids = {c.id for c in personals}
    reserved_ids.update(c.id for c in publics)
    reserved_ids.update(c.id for c in teams)
    if events_cal:
        reserved_ids.add(events_cal.id)

    others_q = Calendar.query.filter(Calendar.id.notin_(list(reserved_ids) or [0]))
    others = others_q.order_by(Calendar.calendar_type.asc(), Calendar.name.asc()).all()
    personal_others = []
    imported = []
    for cal in others:
        if cal.calendar_type == 'personal':
            if not can_view_calendar(user, cal):
                continue
            personal_others.append(cal)
        elif cal.calendar_type == 'imported':
            imported.append(cal)
        elif cal.calendar_type == 'team':
            continue
    personal_others.sort(key=lambda c: (c.name or '').lower())
    imported.sort(key=lambda c: (c.name or '').lower())
    return {
        'personal': personal,
        'personals': personals,
        'public': public,
        'publics': publics,
        'events': events_cal,
        'teams': teams,
        'others': personal_others + imported,
    }


def calendar_display_name(cal, user=None):
    """Human-readable calendar source name for UI."""
    if not cal:
        return ''
    if cal.calendar_type == 'personal':
        if user and cal.owner_id == getattr(user, 'id', None):
            if cal.is_default and (not cal.name or cal.name == getattr(user, 'full_name', None)):
                return PERSONAL_CALENDAR_NAME
            return cal.name or PERSONAL_CALENDAR_NAME
        owner_name = cal.owner.full_name if cal.owner and cal.owner.full_name else (cal.name or PERSONAL_CALENDAR_NAME)
        if cal.is_default:
            return owner_name
        return f'{owner_name} – {cal.name}' if cal.name else owner_name
    if cal.calendar_type == 'public':
        return cal.name or PUBLIC_CALENDAR_NAME
    if cal.calendar_type == 'events':
        return EVENTS_CALENDAR_NAME
    if cal.calendar_type == 'team':
        team_name = cal.team.name if cal.team else (cal.name or TEAM_CALENDAR_NAME)
        if cal.is_default:
            return team_name
        return f'{team_name} – {cal.name}' if cal.name else team_name
    return cal.name or ''


def calendar_to_dict(cal, user=None):
    display_name = calendar_display_name(cal, user)
    return {
        'id': cal.id,
        'name': display_name,
        'raw_name': cal.name,
        'calendar_type': cal.calendar_type,
        'owner_id': cal.owner_id,
        'team_id': cal.team_id,
        'color': cal.color or '#0d6efd',
        'sync_source_id': cal.sync_source_id,
        'is_default': bool(cal.is_default),
        'hidden_from_others': bool(cal.hidden_from_others),
        'can_create': can_create_in_calendar(user, cal) if user else False,
        'can_manage': can_manage_calendar(user, cal) if user else False,
        'can_hide': (
            user is not None
            and cal.calendar_type == 'personal'
            and cal.owner_id == user.id
        ),
        'can_delete_calendar': can_delete_calendar_row(user, cal) if user else False,
    }


def display_color_for_event(event, user=None):
    """Color for overview: own/public/events use event_color; others use calendar color."""
    event_color = event.event_color or '#0d6efd'
    cal = event.calendar
    if not cal:
        return event_color
    if cal.calendar_type in ('public', 'events', 'team'):
        return event_color
    if cal.calendar_type == 'personal':
        if user and cal.owner_id == getattr(user, 'id', None):
            return event_color
        return cal.color or event_color
    if cal.calendar_type == 'imported':
        return cal.color or event_color
    return event_color


def fallback_calendar_for(calendar):
    if not calendar:
        return get_public_calendar()
    if calendar.calendar_type == 'personal' and calendar.owner_id:
        default = (
            Calendar.query.filter_by(
                calendar_type='personal',
                owner_id=calendar.owner_id,
                is_default=True,
            ).first()
        )
        if default and default.id != calendar.id:
            return default
    if calendar.calendar_type == 'team' and calendar.team_id:
        default = (
            Calendar.query.filter_by(
                calendar_type='team',
                team_id=calendar.team_id,
                is_default=True,
            ).first()
        )
        if default and default.id != calendar.id:
            return default
    if calendar.calendar_type == 'public':
        default = get_public_calendar()
        if default.id != calendar.id:
            return default
    return get_public_calendar()


def create_extra_calendar(user, name, calendar_type, color=None, team_id=None):
    name = (name or '').strip()
    if not name:
        return None, 'name_required'
    calendar_type = (calendar_type or '').strip().lower()
    if calendar_type not in ('personal', 'public', 'team'):
        return None, 'invalid_type'
    if calendar_type == 'personal':
        if not is_calendar_personal_enabled():
            return None, 'personal_disabled'
        cal = Calendar(
            name=name,
            calendar_type='personal',
            owner_id=user.id,
            color=color or _color_for_user(user.id),
            is_default=False,
        )
        db.session.add(cal)
        db.session.flush()
        return cal, None
    if calendar_type == 'public':
        cal = Calendar(
            name=name,
            calendar_type='public',
            owner_id=user.id,
            color=color or DEFAULT_PUBLIC_COLOR,
            is_default=False,
        )
        db.session.add(cal)
        db.session.flush()
        return cal, None
    if calendar_type == 'team':
        if not is_calendar_team_enabled():
            return None, 'team_disabled'
        try:
            team_id = int(team_id)
        except (TypeError, ValueError):
            return None, 'team_required'
        if not _is_team_member(user, team_id):
            return None, 'team_forbidden'
        team = Team.query.get(team_id)
        if not team:
            return None, 'team_required'
        get_or_create_team_calendar(team, created_by=user.id)
        cal = Calendar(
            name=name,
            calendar_type='team',
            team_id=team.id,
            owner_id=user.id,
            color=color or team.color or DEFAULT_TEAM_COLOR,
            is_default=False,
        )
        db.session.add(cal)
        db.session.flush()
        return cal, None
    return None, 'invalid_type'


def update_calendar_meta(user, calendar, *, name=None, color=None, hidden_from_others=None):
    if not can_manage_calendar(user, calendar):
        return False
    if name is not None:
        name = name.strip()
        if name:
            calendar.name = name
    if color is not None:
        color = color.strip()
        if len(color) == 7 and color.startswith('#'):
            calendar.color = color
    if hidden_from_others is not None and calendar.calendar_type == 'personal' and calendar.owner_id == user.id:
        calendar.hidden_from_others = bool(hidden_from_others)
    return True


def delete_extra_calendar(user, calendar):
    if not can_delete_calendar_row(user, calendar):
        return False
    target = fallback_calendar_for(calendar)
    if target and target.id != calendar.id:
        CalendarEvent.query.filter_by(calendar_id=calendar.id).update(
            {CalendarEvent.calendar_id: target.id},
            synchronize_session=False,
        )
    db.session.delete(calendar)
    return True


def backfill_space_calendars():
    """Create default public / personal / team / events calendars as needed."""
    get_public_calendar()
    if is_calendar_personal_enabled() or is_calendar_team_enabled():
        get_or_create_events_calendar()
    if is_calendar_personal_enabled():
        for u in User.query.filter_by(is_active=True).all():
            get_or_create_personal_calendar(u)
    if is_calendar_team_enabled():
        for team in Team.query.all():
            get_or_create_team_calendar(team)
    # Mark legacy first-of-type rows as default
    public = Calendar.query.filter_by(calendar_type='public').order_by(Calendar.id.asc()).first()
    if public:
        public.is_default = True
        Calendar.query.filter(
            Calendar.calendar_type == 'public',
            Calendar.id != public.id,
            Calendar.is_default.is_(True),
        ).update({Calendar.is_default: False}, synchronize_session=False)


def ensure_multi_calendar_schema_ready():
    """Create public + events + personal calendars if multi is on (idempotent helpers)."""
    get_public_calendar()
    if is_calendar_multi_enabled():
        get_or_create_events_calendar()
