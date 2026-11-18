"""Configuration helpers for Nextcloud integration in the files module."""

from __future__ import annotations

import json
from typing import Any

from app import db
from app.models.settings import SystemSettings
from app.utils.system_settings_cache import get_setting as setting_text, setting_bool

SETTING_NC_ENABLED = 'files_nextcloud_enabled'
SETTING_NC_MODE = 'files_storage_mode'  # 'local' | 'nextcloud' | 'hybrid'
SETTING_NC_EUROOFFICE = 'files_nextcloud_eurooffice_enabled'
SETTING_NC_MD_EDIT = 'files_nextcloud_markdown_enabled'
SETTING_NC_WEBDAV_LOCKS = 'files_nextcloud_webdav_locks_enabled'

SETTING_NC_PRIVATE_ENABLED = 'files_nextcloud_private_enabled'
SETTING_NC_PRIVATE_BASE = 'files_nextcloud_private_base_path'

SETTING_NC_PUBLIC_ENABLED = 'files_nextcloud_public_enabled'
SETTING_NC_PUBLIC_PATH = 'files_nextcloud_public_path'
SETTING_NC_PUBLIC_ACCESS = 'files_nextcloud_public_access'  # 'all' | 'read_only' | 'admins_only' | 'disabled'

SETTING_NC_TEAM_MAPPINGS = 'files_nextcloud_team_mappings'

VALID_STORAGE_MODES = frozenset({'local', 'nextcloud', 'hybrid'})
VALID_PUBLIC_ACCESS_MODES = frozenset({'all', 'read_only', 'admins_only', 'disabled'})


def normalize_remote_path(path: str | None) -> str:
    raw = (path or '').strip().replace('\\', '/')
    parts = [p for p in raw.split('/') if p and p not in ('.', '..')]
    return '/' + '/'.join(parts) if parts else ''


def is_nextcloud_files_enabled() -> bool:
    return setting_bool(SETTING_NC_ENABLED, False)


def get_files_storage_mode() -> str:
    if not is_nextcloud_files_enabled():
        return 'local'
    mode = (setting_text(SETTING_NC_MODE, 'local') or 'local').strip().lower()
    return mode if mode in VALID_STORAGE_MODES else 'local'


def is_nextcloud_active() -> bool:
    return get_files_storage_mode() in ('nextcloud', 'hybrid')


def is_portal_storage_active() -> bool:
    return get_files_storage_mode() in ('local', 'hybrid')


def is_hybrid_storage_mode() -> bool:
    return get_files_storage_mode() == 'hybrid'


def is_nextcloud_eurooffice_enabled() -> bool:
    return is_nextcloud_active() and setting_bool(SETTING_NC_EUROOFFICE, True)


def is_nextcloud_markdown_enabled() -> bool:
    return is_nextcloud_active() and setting_bool(SETTING_NC_MD_EDIT, True)


def is_nextcloud_webdav_locks_enabled() -> bool:
    return is_nextcloud_active() and setting_bool(SETTING_NC_WEBDAV_LOCKS, True)


def is_nextcloud_private_enabled() -> bool:
    return is_nextcloud_active() and setting_bool(SETTING_NC_PRIVATE_ENABLED, True)


def get_nextcloud_private_base_path() -> str:
    return normalize_remote_path(setting_text(SETTING_NC_PRIVATE_BASE, '/Ablage')) or '/Ablage'


def get_nextcloud_private_user_path(user) -> str:
    base = get_nextcloud_private_base_path().strip('/')
    raw_ident = (
        getattr(user, 'username', None)
        or getattr(user, 'email', None)
        or f'user-{getattr(user, "id", 0)}'
    ).strip()
    if '@' in raw_ident:
        raw_ident = raw_ident.split('@', 1)[0]
    safe_user = ''.join(ch if ch.isalnum() or ch in ('-', '_', '.') else '_' for ch in raw_ident) or f'user-{user.id}'
    return f'/{base}/{safe_user}' if base else f'/{safe_user}'


def is_nextcloud_public_enabled() -> bool:
    if not is_nextcloud_active():
        return False
    if not setting_bool(SETTING_NC_PUBLIC_ENABLED, True):
        return False
    return get_nextcloud_public_access() != 'disabled'


def get_nextcloud_public_path() -> str:
    return normalize_remote_path(setting_text(SETTING_NC_PUBLIC_PATH, '/Public')) or '/Public'


def get_nextcloud_public_access() -> str:
    val = (setting_text(SETTING_NC_PUBLIC_ACCESS, 'all') or 'all').strip().lower()
    return val if val in VALID_PUBLIC_ACCESS_MODES else 'all'


def can_access_nextcloud_public(user, *, write: bool = False) -> bool:
    if not is_nextcloud_public_enabled():
        return False
    if not user or getattr(user, 'is_guest', False):
        return False
    if getattr(user, 'is_admin', False):
        return True
    mode = get_nextcloud_public_access()
    if mode == 'disabled':
        return False
    if mode == 'admins_only':
        return False
    if mode == 'read_only' and write:
        return False
    return True


def get_nextcloud_team_mappings() -> dict[int, dict[str, Any]]:
    raw = setting_text(SETTING_NC_TEAM_MAPPINGS, '{}') or '{}'
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for k, v in parsed.items():
        try:
            tid = int(k)
        except (TypeError, ValueError):
            continue
        if not isinstance(v, dict):
            continue
        path = normalize_remote_path(v.get('path'))
        enabled = bool(v.get('enabled', bool(path)))
        if path:
            result[tid] = {'path': path, 'enabled': enabled}
    return result


def get_team_nextcloud_mapping(team_id: int | None) -> dict[str, Any] | None:
    if not team_id or not is_nextcloud_active():
        return None
    mapping = get_nextcloud_team_mappings().get(int(team_id))
    if not mapping or not mapping.get('enabled') or not mapping.get('path'):
        return None
    return mapping


def upsert_nextcloud_setting(key: str, value: str, description: str = '') -> None:
    row = SystemSettings.query.filter_by(key=key).first()
    if row:
        row.value = value
        if description:
            row.description = description
    else:
        db.session.add(SystemSettings(key=key, value=value, description=description or key))
