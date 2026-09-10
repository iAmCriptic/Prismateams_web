"""Concatenate always-on CSS into one response (P04)."""

from __future__ import annotations

import hashlib
import os
import threading

CORE_CSS_FILES = (
    'css/base.css',
    'css/top-navbar.css',
    'css/portal-msg.css',
    'css/module-ui.css',
    'css/mod-buttons.css',
    'css/mod-search.css',
    'css/mod-toggles.css',
    'css/mod-toolbar.css',
    'css/mod-forms.css',
    'css/mod-list-chrome.css',
    'css/context-menu.css',
    'css/cookie-consent.css',
    'css/notification-center.css',
)

_lock = threading.Lock()
_cache_key = None
_cache_body = None
_cache_etag = None


def _mtime_key(static_folder):
    parts = []
    for rel in CORE_CSS_FILES:
        path = os.path.join(static_folder, rel.replace('/', os.sep))
        try:
            parts.append(f'{rel}:{os.path.getmtime(path):.0f}:{os.path.getsize(path)}')
        except OSError:
            parts.append(f'{rel}:missing')
    return '|'.join(parts)


def build_core_css(static_folder):
    """Return (css_bytes, etag). Rebuilds when source files change."""
    global _cache_key, _cache_body, _cache_etag
    key = _mtime_key(static_folder)
    with _lock:
        if _cache_key == key and _cache_body is not None:
            return _cache_body, _cache_etag
        chunks = []
        for rel in CORE_CSS_FILES:
            path = os.path.join(static_folder, rel.replace('/', os.sep))
            chunks.append(f'/* --- {rel} --- */\n')
            with open(path, 'r', encoding='utf-8') as fh:
                chunks.append(fh.read())
            if not chunks[-1].endswith('\n'):
                chunks.append('\n')
        body = ''.join(chunks).encode('utf-8')
        etag = hashlib.sha256(body).hexdigest()[:16]
        _cache_key = key
        _cache_body = body
        _cache_etag = etag
        return body, etag
