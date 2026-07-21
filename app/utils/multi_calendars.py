"""Helpers for optional multi-calendar mode."""

from sqlalchemy import or_

from app import db
from app.models.calendar import Calendar, CalendarEvent, EventParticipant
from app.models.settings import SystemSettings
from app.models.user import User

PUBLIC_CALENDAR_NAME = 'Public'
PERSONAL_CALENDAR_NAME = 'Mein Kalender'
DEFAULT_PUBLIC_COLOR = '#198754'
DEFAULT_IMPORT_COLOR = '#6c757d'

PERSONAL_COLORS = (
    '#0d6efd', '#6610f2', '#d63384', '#fd7e14',
    '#20c997', '#0dcaf0', '#ffc107', '#dc3545',
)


def _setting_bool(key, default=False):
    setting = SystemSettings.query.filter_by(key=key).first()
    if not setting or setting.value is None or str(setting.value).strip() == '':
        return default
    return str(setting.value).lower() == 'true'


def is_calendar_multi_enabled():
    return _setting_bool('calendar_multi_enabled', False)


def is_calendar_export_enabled():
    return _setting_bool('calendar_export_enabled', True)


def is_calendar_import_enabled():
    return _setting_bool('calendar_import_enabled', True)


def _color_for_user(user_id):
    return PERSONAL_COLORS[int(user_id or 0) % len(PERSONAL_COLORS)]


def get_public_calendar():
    cal = Calendar.query.filter_by(calendar_type='public').first()
    if cal:
        return cal
    cal = Calendar(
        name=PUBLIC_CALENDAR_NAME,
        calendar_type='public',
        owner_id=None,
        color=DEFAULT_PUBLIC_COLOR,
    )
    db.session.add(cal)
    db.session.flush()
    return cal


def get_or_create_personal_calendar(user):
    user_id = user.id if hasattr(user, 'id') else int(user)
    cal = Calendar.query.filter_by(calendar_type='personal', owner_id=user_id).first()
    if cal:
        return cal
    owner = user if hasattr(user, 'full_name') else User.query.get(user_id)
    name = PERSONAL_CALENDAR_NAME
    if owner and getattr(owner, 'full_name', None):
        name = owner.full_name
    cal = Calendar(
        name=name,
        calendar_type='personal',
        owner_id=user_id,
        color=_color_for_user(user_id),
    )
    db.session.add(cal)
    db.session.flush()
    return cal


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
    )
    db.session.add(cal)
    db.session.flush()
    return cal


def can_create_in_calendar(user, calendar):
    if not calendar:
        return False
    if getattr(user, 'is_admin', False):
        return calendar.calendar_type in ('personal', 'public') and (
            calendar.calendar_type == 'public' or calendar.owner_id == user.id
        )
    if calendar.calendar_type == 'public':
        return True
    if calendar.calendar_type == 'personal':
        return calendar.owner_id == user.id
    return False


def can_edit_event(user, event):
    if getattr(user, 'is_admin', False):
        return True
    if not is_calendar_multi_enabled():
        return True
    cal = event.calendar
    if cal is None:
        return event.created_by == user.id
    if cal.calendar_type == 'public':
        return True
    if cal.calendar_type == 'personal':
        return event.created_by == user.id
    # imported: read-only events
    return False


def can_delete_event(user, event):
    if getattr(user, 'is_admin', False):
        return True
    if not is_calendar_multi_enabled():
        return getattr(user, 'is_admin', False)
    cal = event.calendar
    if cal is None:
        return event.created_by == user.id
    if cal.calendar_type == 'public':
        return True
    if cal.calendar_type == 'personal':
        return event.created_by == user.id
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


def filter_events_for_calendars(events, user, selected_calendar_ids):
    """Filter a list of CalendarEvent by selected calendars + invite overlay."""
    if not is_calendar_multi_enabled():
        return list(events)

    selected = set(selected_calendar_ids or [])
    personal = get_or_create_personal_calendar(user)
    invite_ids = event_ids_for_invites(user.id) if personal.id in selected else set()

    result = []
    seen = set()
    for event in events:
        if event.id in seen:
            continue
        cid = event.calendar_id
        if cid in selected:
            result.append(event)
            seen.add(event.id)
        elif personal.id in selected and event.id in invite_ids and cid != personal.id:
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
        personal = get_or_create_personal_calendar(user)
        selected = [personal.id]

    personal = get_or_create_personal_calendar(user)
    invite_ids = event_ids_for_invites(user.id) if personal.id in selected else set()

    conditions = [CalendarEvent.calendar_id.in_(selected)]
    if invite_ids:
        conditions.append(CalendarEvent.id.in_(list(invite_ids)))
    return q.filter(or_(*conditions))


def list_sidebar_calendars(user):
    """Ordered calendars for sidebar: mine, public, then others + imported."""
    personal = get_or_create_personal_calendar(user)
    public = get_public_calendar()
    others = (
        Calendar.query
        .filter(
            Calendar.id.notin_([personal.id, public.id]),
            or_(
                Calendar.calendar_type == 'imported',
                Calendar.calendar_type == 'personal',
            ),
        )
        .order_by(Calendar.calendar_type.asc(), Calendar.name.asc())
        .all()
    )
    # Refresh personal names from users
    personal_others = []
    imported = []
    for cal in others:
        if cal.calendar_type == 'personal':
            if cal.owner and cal.owner.full_name:
                cal.name = cal.owner.full_name
            personal_others.append(cal)
        else:
            imported.append(cal)
    personal_others.sort(key=lambda c: (c.name or '').lower())
    imported.sort(key=lambda c: (c.name or '').lower())
    return {
        'personal': personal,
        'public': public,
        'others': personal_others + imported,
    }


def calendar_to_dict(cal, user=None):
    display_name = cal.name
    if cal.calendar_type == 'personal' and user and cal.owner_id == user.id:
        display_name = PERSONAL_CALENDAR_NAME
    elif cal.calendar_type == 'personal' and cal.owner and cal.owner.full_name:
        display_name = cal.owner.full_name
    elif cal.calendar_type == 'public':
        display_name = PUBLIC_CALENDAR_NAME
    return {
        'id': cal.id,
        'name': display_name,
        'calendar_type': cal.calendar_type,
        'owner_id': cal.owner_id,
        'color': cal.color or '#0d6efd',
        'sync_source_id': cal.sync_source_id,
        'can_create': can_create_in_calendar(user, cal) if user else False,
        'can_delete_calendar': (
            user is not None
            and cal.calendar_type == 'imported'
            and (getattr(user, 'is_admin', False) or cal.owner_id == user.id)
        ),
    }


def ensure_multi_calendar_schema_ready():
    """Create public + personal calendars if multi is on (idempotent helpers)."""
    get_public_calendar()
