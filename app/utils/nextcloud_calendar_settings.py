"""Configuration helpers for Nextcloud CalDAV integration in the Calendar module."""

from __future__ import annotations

from app import db
from app.models.settings import SystemSettings
from app.utils.system_settings_cache import get_setting as setting_text, setting_bool

SETTING_NC_CAL_ENABLED = 'calendar_nextcloud_enabled'
SETTING_NC_CAL_MODE = 'calendar_storage_mode'  # 'local' | 'nextcloud' | 'hybrid'
SETTING_NC_CAL_EVENTS_TARGET = 'calendar_events_sync_target'  # 'internal' | 'nextcloud'
SETTING_NC_CAL_EVENTS_NC_URL = 'calendar_events_nextcloud_url'
SETTING_NC_CAL_EVENTS_INTERNAL_ID = 'calendar_events_internal_id'

VALID_CALENDAR_MODES = frozenset({'local', 'nextcloud', 'hybrid'})
VALID_EVENTS_TARGETS = frozenset({'internal', 'nextcloud'})


def is_nextcloud_calendar_enabled() -> bool:
    return setting_bool(SETTING_NC_CAL_ENABLED, False)


def get_calendar_storage_mode() -> str:
    if not is_nextcloud_calendar_enabled():
        return 'local'
    mode = (setting_text(SETTING_NC_CAL_MODE, 'local') or 'local').strip().lower()
    return mode if mode in VALID_CALENDAR_MODES else 'local'


def is_nextcloud_calendar_active() -> bool:
    return get_calendar_storage_mode() in ('nextcloud', 'hybrid')


def is_portal_calendar_active() -> bool:
    return get_calendar_storage_mode() in ('local', 'hybrid')


def is_hybrid_calendar_mode() -> bool:
    return get_calendar_storage_mode() == 'hybrid'


def get_events_sync_target() -> str:
    target = (setting_text(SETTING_NC_CAL_EVENTS_TARGET, 'internal') or 'internal').strip().lower()
    if target not in VALID_EVENTS_TARGETS:
        target = 'internal'
    if target == 'nextcloud' and not is_nextcloud_calendar_active():
        return 'internal'
    if target == 'internal' and not is_portal_calendar_active() and is_nextcloud_calendar_active():
        return 'nextcloud'
    return target


def get_events_nextcloud_url() -> str:
    return (setting_text(SETTING_NC_CAL_EVENTS_NC_URL, '') or '').strip()


def get_events_internal_calendar_id() -> int | None:
    raw = (setting_text(SETTING_NC_CAL_EVENTS_INTERNAL_ID, '') or '').strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def upsert_calendar_setting(key: str, value: str, description: str = '') -> None:
    row = SystemSettings.query.filter_by(key=key).first()
    if row:
        row.value = value
        if description:
            row.description = description
    else:
        db.session.add(SystemSettings(key=key, value=value, description=description or key))
