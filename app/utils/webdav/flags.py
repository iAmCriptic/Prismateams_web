"""Feature flag helpers for WebDAV."""

from __future__ import annotations


def is_webdav_enabled():
    from app.models.settings import SystemSettings

    setting = SystemSettings.query.filter_by(key='files_webdav_enabled').first()
    return bool(setting and str(setting.value).lower() == 'true')
