"""Admin-Verknüpfungen: Google Cloud + Microsoft Azure (SystemSettings)."""

from __future__ import annotations

from typing import Optional

from app import db
from app.models.settings import SystemSettings

GOOGLE_KEYS = {
    'client_id': 'google_client_id',
    'client_secret': 'google_client_secret',
    'api_key': 'google_api_key',
}

# Legacy MusicSettings-Keys, die auf Google-Cloud-Werte mappen
YOUTUBE_LEGACY_MAP = {
    'youtube_client_id': 'google_client_id',
    'youtube_client_secret': 'google_client_secret',
    'youtube_api_key': 'google_api_key',
}

MICROSOFT_KEYS = {
    'client_id': 'microsoft_client_id',
    'client_secret': 'microsoft_client_secret',
    'tenant': 'microsoft_tenant',
}


def get_system_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    row = SystemSettings.query.filter_by(key=key).first()
    if row and row.value is not None and str(row.value).strip() != '':
        return str(row.value)
    return default


def set_system_setting(key: str, value: str, description: str = '') -> None:
    row = SystemSettings.query.filter_by(key=key).first()
    if row:
        row.value = value
        if description:
            row.description = description
    else:
        db.session.add(SystemSettings(key=key, value=value, description=description or key))


def get_google_credentials() -> dict:
    return {
        'client_id': get_system_setting(GOOGLE_KEYS['client_id'], '') or '',
        'client_secret': get_system_setting(GOOGLE_KEYS['client_secret'], '') or '',
        'api_key': get_system_setting(GOOGLE_KEYS['api_key'], '') or '',
    }


def get_microsoft_credentials() -> dict:
    return {
        'client_id': get_system_setting(MICROSOFT_KEYS['client_id'], '') or '',
        'client_secret': get_system_setting(MICROSOFT_KEYS['client_secret'], '') or '',
        'tenant': get_system_setting(MICROSOFT_KEYS['tenant'], 'common') or 'common',
    }


def google_oauth_configured() -> bool:
    creds = get_google_credentials()
    return bool(creds['client_id'] and creds['client_secret'])


def google_oauth_redirect_uri() -> str:
    """Einheitliche Redirect-URI für alle Google-OAuth-Flows (Login, Postfach, YouTube)."""
    from flask import url_for
    return url_for('auth.google_callback', _external=True)


def microsoft_oauth_configured() -> bool:
    creds = get_microsoft_credentials()
    return bool(creds['client_id'] and creds['client_secret'])


def save_integrations_from_form(form) -> None:
    """Speichert Verknüpfungen und spiegelt Google-Werte in YouTube-MusicSettings."""
    mapping = [
        ('google_client_id', 'Google OAuth Client ID'),
        ('google_client_secret', 'Google OAuth Client Secret'),
        ('google_api_key', 'Google API Key (YouTube / APIs)'),
        ('microsoft_client_id', 'Microsoft Azure Application (client) ID'),
        ('microsoft_client_secret', 'Microsoft Azure Client Secret'),
        ('microsoft_tenant', 'Microsoft Azure Tenant (common/organizations/id)'),
    ]
    for key, desc in mapping:
        set_system_setting(key, (form.get(key) or '').strip(), desc)

    # Legacy-Spiegelung für Musik-Modul
    try:
        from app.models.music import MusicSettings
        mirrors = [
            ('google_api_key', 'youtube_api_key', 'YouTube API-Key (gespiegelt von Verknüpfungen)'),
            ('google_client_id', 'youtube_client_id', 'YouTube OAuth Client ID (gespiegelt)'),
            ('google_client_secret', 'youtube_client_secret', 'YouTube OAuth Client Secret (gespiegelt)'),
        ]
        for src, dest, desc in mirrors:
            val = (form.get(src) or '').strip()
            row = MusicSettings.query.filter_by(key=dest).first()
            if row:
                row.value = val
            else:
                db.session.add(MusicSettings(key=dest, value=val, description=desc))
    except Exception:
        pass


def migrate_youtube_keys_to_system() -> None:
    """Einmalig: vorhandene MusicSettings YouTube-Keys nach SystemSettings kopieren."""
    try:
        from app.models.music import MusicSettings
    except Exception:
        return
    for legacy, system_key in YOUTUBE_LEGACY_MAP.items():
        if get_system_setting(system_key):
            continue
        row = MusicSettings.query.filter_by(key=legacy).first()
        if row and row.value:
            set_system_setting(system_key, row.value, f'Migriert von {legacy}')
