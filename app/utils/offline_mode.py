"""Offline-/Wartungsmodus über SystemSettings."""

from __future__ import annotations

from app import db
from app.models.settings import SystemSettings
from app.utils.system_settings_cache import (
    invalidate_system_settings_cache,
    setting_bool,
)

SETTING_KEY = 'offline_mode_enabled'
SETTING_DESCRIPTION = (
    'Offline-Modus (Wartungsarbeiten): Zeigt statt Login eine Wartungsseite; '
    'Admin-Login über /recover'
)


def is_offline_mode_enabled() -> bool:
    """Gibt zurück, ob der globale Offline-/Wartungsmodus aktiv ist."""
    try:
        return setting_bool(SETTING_KEY, False)
    except Exception:
        return False


def set_offline_mode_enabled(enabled: bool) -> None:
    """Setzt den Offline-Modus in SystemSettings (ohne Commit)."""
    value = 'true' if enabled else 'false'
    row = SystemSettings.query.filter_by(key=SETTING_KEY).first()
    if row:
        row.value = value
        if not row.description:
            row.description = SETTING_DESCRIPTION
    else:
        db.session.add(SystemSettings(
            key=SETTING_KEY,
            value=value,
            description=SETTING_DESCRIPTION,
        ))


def disable_offline_mode() -> None:
    """Deaktiviert den Offline-Modus, speichert und invalidiert den Cache."""
    set_offline_mode_enabled(False)
    db.session.commit()
    invalidate_system_settings_cache()
