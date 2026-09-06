"""Small helpers shared by Flask factory modules."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse


def resolve_socketio_cors_origins(app):
    """
    Socket.IO CORS-Origins.

    - leer: None → Engine.IO erlaubt nur same-origin (Host / X-Forwarded-*)
    - '*': bewusst offen
    - Komma-Liste: explizite Origins; PUBLIC_BASE_URL wird ergänzt falls gesetzt
    """
    raw = (app.config.get('SOCKETIO_CORS_ORIGINS') or '').strip()
    if raw == '*':
        return '*'

    origins = []
    if raw:
        origins.extend(part.strip().rstrip('/') for part in raw.split(',') if part.strip())

    public_base = (app.config.get('PUBLIC_BASE_URL') or '').strip().rstrip('/')
    if public_base and public_base not in origins:
        origins.append(public_base)

    if origins:
        seen = []
        for origin in origins:
            if origin and origin not in seen:
                seen.append(origin)
        return seen

    return None


def is_insecure_secret_key(value):
    secret = (value or "").strip()
    return (not secret) or secret == 'dev-secret-key-change-in-production'


def is_same_origin(target_url, expected_host):
    if not target_url:
        return False
    try:
        parsed = urlparse(target_url)
        return (parsed.netloc or '').lower() == (expected_host or '').lower()
    except Exception:
        return False


def env_flag(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def configure_app_logging(app, config_name='default'):
    """Central logging for Gunicorn/systemd (stderr → journalctl)."""
    default_level = logging.INFO if config_name == 'production' else logging.DEBUG
    level_name = os.getenv('LOG_LEVEL', '').strip().upper()
    if level_name:
        level = getattr(logging, level_name, default_level)
    else:
        level = default_level

    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        force=True,
    )
    app.logger.setLevel(level)
    werkzeug_level = logging.WARNING if config_name == 'production' else logging.INFO
    logging.getLogger('werkzeug').setLevel(werkzeug_level)


def asset_version(app):
    build = str(app.config.get('ABOUT_BUILD_NUMBER') or '').strip()
    release = str(app.config.get('ABOUT_RELEASE_VERSION') or '').strip()
    return build or release or 'dev'
