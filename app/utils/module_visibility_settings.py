"""Global Private / Team / Public toggles for all modules."""

from __future__ import annotations

from app.models.settings import SystemSettings

SETTING_ALLOW_PRIVATE = 'modules_allow_private'
SETTING_ALLOW_TEAM = 'modules_allow_team'
SETTING_ALLOW_PUBLIC = 'modules_allow_public'

VISIBILITY_MODULE_KEYS = (
    'credentials',
    'manuals',
    'contacts',
    'wiki',
    'shortlinks',
    'excalidraw',
    'surveys',
    'protocols',
)


def _setting_bool(key: str, default: bool = True) -> bool:
    row = SystemSettings.query.filter_by(key=key).first()
    if row is None:
        return default
    return str(row.value).lower() in ('true', '1', 'yes', 'on')


def is_global_private_enabled() -> bool:
    return _setting_bool(SETTING_ALLOW_PRIVATE, True)


def is_global_team_enabled() -> bool:
    return _setting_bool(SETTING_ALLOW_TEAM, True)


def is_global_public_enabled() -> bool:
    return _setting_bool(SETTING_ALLOW_PUBLIC, True)


def sync_legacy_visibility_keys(allow_private: bool, allow_team: bool, allow_public: bool) -> None:
    """Keep legacy per-module keys in sync when global toggles change."""
    from app.utils.bot_protection import upsert_setting
    from app.utils.kanban_access import (
        SETTING_ALLOW_PRIVATE as KANBAN_PRIVATE,
        SETTING_ALLOW_TEAM as KANBAN_TEAM,
        SETTING_ALLOW_PUBLIC as KANBAN_PUBLIC,
    )
    from app.utils.module_visibility import setting_key

    for module in VISIBILITY_MODULE_KEYS:
        priv = False if module == 'protocols' else allow_private
        upsert_setting(setting_key(module, 'private'), str(priv).lower(), f'{module}: Privat')
        upsert_setting(setting_key(module, 'team'), str(allow_team).lower(), f'{module}: Team')
        upsert_setting(setting_key(module, 'public'), str(allow_public).lower(), f'{module}: Public')

    upsert_setting(KANBAN_PRIVATE, str(allow_private).lower(), 'Kanban: Private Boards')
    upsert_setting(KANBAN_TEAM, str(allow_team).lower(), 'Kanban: Team Boards')
    upsert_setting(KANBAN_PUBLIC, str(allow_public).lower(), 'Kanban: Public Boards')

    upsert_setting('calendar_personal_enabled', str(allow_private).lower(), 'Kalender: Persönliche Kalender')
    upsert_setting('calendar_team_enabled', str(allow_team).lower(), 'Kalender: Team-Kalender')
    upsert_setting('calendar_multi_enabled', str(allow_private or allow_team).lower(), 'Kalender: Multi-Kalender')

    upsert_setting('files_private_folders_enabled', str(allow_private).lower(), 'Dateien: Private Ordner')
    upsert_setting('files_team_folders_enabled', str(allow_team).lower(), 'Dateien: Team-Ordner')
