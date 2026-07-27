"""Helpers for optional multi-calendar mode."""

from sqlalchemy import or_

from app import db
from app.models.calendar import Calendar, CalendarEvent, EventParticipant
from app.models.settings import SystemSettings
from app.models.user import User

PUBLIC_CALENDAR_NAME = 'Public'
EVENTS_CALENDAR_NAME = 'Veranstaltungen'
PERSONAL_CALENDAR_NAME = 'Mein Kalender'
DEFAULT_PUBLIC_COLOR = '#198754'
DEFAULT_EVENTS_COLOR = '#e85d04'
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


def get_or_create_events_calendar():
    """Singleton calendar for Events/Booking module entries."""
    cal = Calendar.query.filter_by(calendar_type='events').first()
    if cal:
        return cal
    cal = Calendar(
        name=EVENTS_CALENDAR_NAME,
        calendar_type='events',
        owner_id=None,
        color=DEFAULT_EVENTS_COLOR,
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
    # Events calendar is module-writable only (not via calendar UI)
    if calendar.calendar_type == 'events':
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
    # Veranstaltungen/Booking: nur Modul (oder Admin), nicht jeder Kalender-Nutzer
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
    # imported / events: read-only via calendar UI
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
    personal = get_or_create_personal_calendar(user)
    selected = set(selected_calendar_ids or [])
    if personal.id not in selected:
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
        personal = get_or_create_personal_calendar(user)
        selected = [personal.id]

    invite_ids = _invite_overlay_event_ids(user, selected)

    conditions = [CalendarEvent.calendar_id.in_(selected)]
    if invite_ids:
        conditions.append(CalendarEvent.id.in_(list(invite_ids)))
    return q.filter(or_(*conditions))


def list_sidebar_calendars(user):
    """Ordered calendars for sidebar: mine, public, events, then others + imported."""
    personal = get_or_create_personal_calendar(user)
    public = get_public_calendar()
    events_cal = get_or_create_events_calendar()
    reserved_ids = [personal.id, public.id, events_cal.id]
    others = (
        Calendar.query
        .filter(
            Calendar.id.notin_(reserved_ids),
            or_(
                Calendar.calendar_type == 'imported',
                Calendar.calendar_type == 'personal',
            ),
        )
        .order_by(Calendar.calendar_type.asc(), Calendar.name.asc())
        .all()
    )
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
        'events': events_cal,
        'others': personal_others + imported,
    }


def calendar_display_name(cal, user=None):
    """Human-readable calendar source name for UI."""
    if not cal:
        return ''
    if cal.calendar_type == 'personal':
        if user and cal.owner_id == getattr(user, 'id', None):
            return PERSONAL_CALENDAR_NAME
        if cal.owner and cal.owner.full_name:
            return cal.owner.full_name
        return cal.name or PERSONAL_CALENDAR_NAME
    if cal.calendar_type == 'public':
        return PUBLIC_CALENDAR_NAME
    if cal.calendar_type == 'events':
        return EVENTS_CALENDAR_NAME
    return cal.name or ''


def calendar_to_dict(cal, user=None):
    display_name = calendar_display_name(cal, user)
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


def display_color_for_event(event, user=None):
    """Color for overview: own/public/events use event_color; others use calendar color."""
    event_color = event.event_color or '#0d6efd'
    cal = event.calendar
    if not cal:
        return event_color
    if cal.calendar_type in ('public', 'events'):
        return event_color
    if cal.calendar_type == 'personal':
        if user and cal.owner_id == getattr(user, 'id', None):
            return event_color
        return cal.color or event_color
    if cal.calendar_type == 'imported':
        return cal.color or event_color
    return event_color


def ensure_multi_calendar_schema_ready():
    """Create public + events + personal calendars if multi is on (idempotent helpers)."""
    get_public_calendar()
    get_or_create_events_calendar()
