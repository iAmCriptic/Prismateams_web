"""Bidirectional CalDAV sync bridge between Nextcloud and Portal Calendar."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from app import db
from app.models.calendar import Calendar, CalendarEvent
from app.models.user import User
from app.utils.integrations import get_nextcloud_credentials, nextcloud_configured
from app.utils.nextcloud_caldav import NextcloudCalDAVClient
from app.utils.nextcloud_calendar_settings import is_nextcloud_calendar_active

logger = logging.getLogger(__name__)

_CAL_DISCOVERY_CACHE_TS: float = 0.0
_EVENT_SYNC_CACHE: dict[int, float] = {}
_SYNC_TTL_SECONDS = 15.0


def get_portal_caldav_client() -> NextcloudCalDAVClient:
    creds = get_nextcloud_credentials(include_password=True)
    return NextcloudCalDAVClient(
        server_url=creds.get('server_url') or '',
        username=creds.get('username') or '',
        app_password=creds.get('app_password') or '',
    )


def invalidate_caldav_sync_cache() -> None:
    global _CAL_DISCOVERY_CACHE_TS
    _CAL_DISCOVERY_CACHE_TS = 0.0
    _EVENT_SYNC_CACHE.clear()


def _cleanup_event_references(event_ids: list[int]) -> None:
    if not event_ids:
        return
    try:
        from app.models.booking import BookingRequest
        BookingRequest.query.filter(BookingRequest.calendar_event_id.in_(event_ids)).update(
            {BookingRequest.calendar_event_id: None}, synchronize_session=False
        )
    except Exception:
        pass
    try:
        from app.models.event import EventAppointment
        EventAppointment.query.filter(EventAppointment.calendar_event_id.in_(event_ids)).update(
            {EventAppointment.calendar_event_id: None}, synchronize_session=False
        )
    except Exception:
        pass
    CalendarEvent.query.filter(CalendarEvent.parent_event_id.in_(event_ids)).update(
        {CalendarEvent.parent_event_id: None}, synchronize_session=False
    )


def sync_nextcloud_calendars(*, force: bool = False) -> list[Calendar]:
    """Discover all Nextcloud calendars and upsert Calendar shadow rows."""
    global _CAL_DISCOVERY_CACHE_TS
    if not is_nextcloud_calendar_active() or not nextcloud_configured():
        return []

    now_ts = time.monotonic()
    if not force and (now_ts - _CAL_DISCOVERY_CACHE_TS) < _SYNC_TTL_SECONDS:
        return Calendar.query.filter_by(storage_backend='nextcloud').order_by(Calendar.name.asc()).all()

    client = get_portal_caldav_client()
    remote_cals = client.discover_calendars()
    _CAL_DISCOVERY_CACHE_TS = now_ts

    existing = {
        (c.remote_url or '').rstrip('/'): c
        for c in Calendar.query.filter_by(storage_backend='nextcloud').all()
        if c.remote_url
    }
    seen_urls: set[str] = set()
    result: list[Calendar] = []

    for rc in remote_cals:
        norm_url = rc.url.rstrip('/')
        seen_urls.add(norm_url)
        cal = existing.get(norm_url)
        if cal is None:
            cal = Calendar(
                name=rc.name[:200],
                calendar_type='nextcloud',
                owner_id=None,
                color=rc.color or '#0d6efd',
                is_default=False,
                hidden_from_others=False,
                storage_backend='nextcloud',
                remote_url=rc.url,
                remote_ctag=None,  # force initial event sync
                remote_read_only=bool(rc.read_only),
            )
            db.session.add(cal)
        else:
            cal.name = rc.name[:200]
            cal.color = rc.color or cal.color
            cal.remote_read_only = bool(rc.read_only)
        result.append(cal)

    # Remove calendars deleted on Nextcloud
    for norm_url, cal in existing.items():
        if norm_url not in seen_urls:
            cal_events = CalendarEvent.query.filter_by(calendar_id=cal.id).all()
            _cleanup_event_references([e.id for e in cal_events])
            for ev in cal_events:
                db.session.delete(ev)
            db.session.delete(cal)

    db.session.commit()
    return Calendar.query.filter_by(storage_backend='nextcloud').order_by(Calendar.name.asc()).all()


def ensure_nextcloud_events_calendar() -> Optional[Calendar]:
    """Ensure a Nextcloud 'Veranstaltungen' calendar exists via MKCALENDAR if needed."""
    cals = sync_nextcloud_calendars(force=False)
    for cal in cals:
        if cal.name.strip().lower() == 'veranstaltungen' and not cal.remote_read_only:
            return cal
    client = get_portal_caldav_client()
    rc = client.create_calendar('Veranstaltungen', color='#fd7e14')
    invalidate_caldav_sync_cache()
    cal = Calendar(
        name=rc.name[:200],
        calendar_type='nextcloud',
        owner_id=None,
        color=rc.color,
        is_default=False,
        hidden_from_others=False,
        storage_backend='nextcloud',
        remote_url=rc.url,
        remote_ctag=rc.ctag or None,
        remote_read_only=False,
    )
    db.session.add(cal)
    db.session.commit()
    return cal


def _default_creator_id() -> int:
    admin = User.query.filter_by(is_admin=True, is_active=True).order_by(User.id.asc()).first()
    if admin:
        return admin.id
    any_u = User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
    return any_u.id if any_u else 1


def sync_nextcloud_calendar_events(
    cal: Calendar,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    *,
    force: bool = False,
) -> None:
    """Sync VEVENTs for a single Nextcloud-backed Calendar."""
    if not cal or getattr(cal, 'storage_backend', 'local') != 'nextcloud' or not cal.remote_url:
        return

    now_ts = time.monotonic()
    if not force and (now_ts - _EVENT_SYNC_CACHE.get(cal.id, 0.0)) < _SYNC_TTL_SECONDS:
        return

    now = datetime.utcnow()
    w_start = window_start or (now - timedelta(days=365))
    w_end = window_end or (now + timedelta(days=365))

    client = get_portal_caldav_client()
    remote_events = client.fetch_events(cal.remote_url, w_start, w_end)
    _EVENT_SYNC_CACHE[cal.id] = now_ts

    existing_by_href = {
        (ev.remote_href or ''): ev
        for ev in CalendarEvent.query.filter_by(calendar_id=cal.id).all()
        if ev.remote_href
    }
    existing_by_uid = {
        (ev.ical_uid or ''): ev
        for ev in CalendarEvent.query.filter_by(calendar_id=cal.id).all()
        if ev.ical_uid
    }
    seen_hrefs: set[str] = set()
    creator_id = _default_creator_id()

    for re_ev in remote_events:
        seen_hrefs.add(re_ev.href)
        ev = existing_by_href.get(re_ev.href) or existing_by_uid.get(re_ev.uid)
        if ev is None:
            ev = CalendarEvent(
                title=re_ev.title,
                description=re_ev.description,
                start_time=re_ev.start_time,
                end_time=re_ev.end_time,
                location=re_ev.location,
                event_color=cal.color or '#0d6efd',
                created_by=creator_id,
                calendar_id=cal.id,
                recurrence_type=re_ev.recurrence_type,
                recurrence_interval=re_ev.recurrence_interval,
                recurrence_end_date=re_ev.recurrence_end_date,
                recurrence_days=re_ev.recurrence_days,
                ical_uid=re_ev.uid,
                remote_href=re_ev.href,
                remote_etag=re_ev.etag,
            )
            db.session.add(ev)
        elif not re_ev.etag or ev.remote_etag != re_ev.etag:
            ev.title = re_ev.title
            ev.description = re_ev.description
            ev.start_time = re_ev.start_time
            ev.end_time = re_ev.end_time
            ev.location = re_ev.location
            ev.recurrence_type = re_ev.recurrence_type
            ev.recurrence_interval = re_ev.recurrence_interval
            ev.recurrence_end_date = re_ev.recurrence_end_date
            ev.ical_uid = re_ev.uid
            ev.remote_href = re_ev.href
            ev.remote_etag = re_ev.etag

    # Remove events deleted on Nextcloud within sync window
    to_delete = [
        ev for href, ev in existing_by_href.items()
        if href not in seen_hrefs and w_start <= ev.start_time <= w_end
    ]
    if to_delete:
        _cleanup_event_references([ev.id for ev in to_delete])
        for ev in to_delete:
            db.session.delete(ev)

    db.session.commit()


def sync_all_nextcloud_calendars(*, force: bool = False) -> dict[str, int]:
    if not is_nextcloud_calendar_active() or not nextcloud_configured():
        return {'ok': 0, 'fail': 0}
    ok = 0
    fail = 0
    try:
        cals = sync_nextcloud_calendars(force=force)
    except Exception as exc:
        logger.warning('Nextcloud calendar discovery failed: %s', exc)
        return {'ok': 0, 'fail': 1}
    for cal in cals:
        try:
            sync_nextcloud_calendar_events(cal, force=force)
            ok += 1
        except Exception as exc:
            logger.warning('Nextcloud calendar sync failed for %s: %s', cal.name, exc)
            fail += 1
    return {'ok': ok, 'fail': fail}


def push_event_to_nextcloud(event: CalendarEvent) -> None:
    if not event or not event.calendar_id:
        return
    cal = Calendar.query.get(event.calendar_id)
    if not cal or getattr(cal, 'storage_backend', 'local') != 'nextcloud' or not cal.remote_url:
        return
    client = get_portal_caldav_client()
    uid, href, etag = client.upsert_event(cal.remote_url, event)
    event.ical_uid = uid
    event.remote_href = href
    event.remote_etag = etag
    _EVENT_SYNC_CACHE.pop(cal.id, None)


def delete_event_from_nextcloud(event: CalendarEvent) -> None:
    if not event or not event.remote_href:
        return
    cal = Calendar.query.get(event.calendar_id) if event.calendar_id else None
    if not cal or getattr(cal, 'storage_backend', 'local') != 'nextcloud':
        return
    try:
        client = get_portal_caldav_client()
        client.delete_event(event.remote_href, etag=event.remote_etag)
        _EVENT_SYNC_CACHE.pop(cal.id, None)
    except Exception as exc:
        logger.warning('Failed to delete Nextcloud event %s: %s', event.remote_href, exc)


def create_nextcloud_calendar(name: str, color: str = '#0d6efd') -> Calendar:
    client = get_portal_caldav_client()
    rc = client.create_calendar(name, color=color or '#0d6efd')
    invalidate_caldav_sync_cache()
    cal = Calendar(
        name=rc.name[:200],
        calendar_type='nextcloud',
        owner_id=None,
        color=rc.color or '#0d6efd',
        is_default=False,
        hidden_from_others=False,
        storage_backend='nextcloud',
        remote_url=rc.url,
        remote_ctag=rc.ctag or None,
        remote_read_only=False,
    )
    db.session.add(cal)
    db.session.flush()
    return cal


def update_nextcloud_calendar(cal: Calendar, *, name: str | None = None, color: str | None = None) -> None:
    if not cal or getattr(cal, 'storage_backend', 'local') != 'nextcloud' or not cal.remote_url:
        return
    client = get_portal_caldav_client()
    client.update_calendar_properties(cal.remote_url, name=name, color=color)
    if name is not None and name.strip():
        cal.name = name.strip()[:200]
    if color is not None and color.strip():
        cal.color = color.strip()
    invalidate_caldav_sync_cache()


def delete_nextcloud_calendar(cal: Calendar) -> None:
    if not cal or getattr(cal, 'storage_backend', 'local') != 'nextcloud':
        return
    if cal.remote_url:
        client = get_portal_caldav_client()
        client.delete_calendar(cal.remote_url)
    CalendarEvent.query.filter_by(calendar_id=cal.id).delete(synchronize_session=False)
    db.session.delete(cal)
    invalidate_caldav_sync_cache()
