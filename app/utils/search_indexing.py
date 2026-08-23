"""Optionale Suchmaschinen-Indexierung (Google) über SystemSettings."""

from __future__ import annotations

from flask import request, url_for

from app import db
from app.models.settings import SystemSettings

SETTING_KEY = 'search_indexing_enabled'
SETTING_DESCRIPTION = 'Öffentliche Seiten für Suchmaschinen (Google) indexieren'

# Nur diese öffentlichen Seiten dürfen bei aktivierter Indexierung erscheinen.
INDEXABLE_ENDPOINTS = frozenset({
    'auth.index',
    'auth.login',
    'auth.register',
    'auth.privacy',
    'auth.imprint',
    'auth.terms',
})

SITEMAP_ENDPOINTS = (
    'auth.login',
    'auth.register',
    'auth.privacy',
    'auth.imprint',
    'auth.terms',
)

ROBOTS_ALLOW_PATHS = (
    '/',
    '/login',
    '/register',
    '/datenschutz',
    '/impressum',
    '/nutzungsbedingungen',
    '/terms',
    '/static/',
)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def is_search_indexing_enabled() -> bool:
    try:
        row = SystemSettings.query.filter_by(key=SETTING_KEY).first()
    except Exception:
        return False
    if row is None:
        return False
    return _as_bool(row.value, False)


def ensure_default_settings() -> None:
    if SystemSettings.query.filter_by(key=SETTING_KEY).first():
        return
    db.session.add(SystemSettings(
        key=SETTING_KEY,
        value='false',
        description=SETTING_DESCRIPTION,
    ))


def is_indexable_request() -> bool:
    if not is_search_indexing_enabled():
        return False
    endpoint = getattr(request, 'endpoint', None) if request else None
    return endpoint in INDEXABLE_ENDPOINTS


def robots_meta_content() -> str:
    if is_indexable_request():
        return 'index, follow'
    return 'noindex, nofollow'


def build_robots_txt() -> str:
    if not is_search_indexing_enabled():
        return 'User-agent: *\nDisallow: /\n'

    lines = ['User-agent: *']
    for path in ROBOTS_ALLOW_PATHS:
        lines.append(f'Allow: {path}')
    lines.append('Disallow: /')
    try:
        sitemap_url = url_for('sitemap_xml', _external=True)
        lines.append('')
        lines.append(f'Sitemap: {sitemap_url}')
    except Exception:
        pass
    lines.append('')
    return '\n'.join(lines)


def build_sitemap_xml() -> str:
    urls: list[str] = []
    if is_search_indexing_enabled():
        for endpoint in SITEMAP_ENDPOINTS:
            try:
                urls.append(url_for(endpoint, _external=True))
            except Exception:
                continue

    seen = set()
    unique_urls = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url in unique_urls:
        parts.append('  <url>')
        parts.append(f'    <loc>{url}</loc>')
        parts.append('    <changefreq>weekly</changefreq>')
        parts.append('  </url>')
    parts.append('</urlset>')
    parts.append('')
    return '\n'.join(parts)
