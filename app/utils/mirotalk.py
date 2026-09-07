"""MiroTalk SFU join helper — API key stays on the server."""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import requests
from flask import current_app

logger = logging.getLogger(__name__)

_MIROTALK_VERSION_RE = re.compile(
    r'(?:WebRTC\s+)?SFU\s+v\.?\s*(\d+\.\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
_MIROTALK_GENERIC_VERSION_RE = re.compile(
    r'version["\']?\s*[:=]\s*["\'](\d+\.\d+(?:\.\d+)?)',
    re.IGNORECASE,
)


def mirotalk_configured() -> bool:
    url = (current_app.config.get('MIROTALK_URL') or '').strip()
    if not url:
        return False
    enabled = current_app.config.get('MIROTALK_ENABLED')
    if enabled is None:
        return True
    return bool(enabled)


def get_mirotalk_version() -> Optional[str]:
    """Return MiroTalk SFU version string, or None if unreachable."""
    if not mirotalk_configured():
        return None
    seen = set()
    for base in (_api_base_url(), _base_url()):
        if not base or base in seen:
            continue
        seen.add(base)
        version = _fetch_mirotalk_version_from_base(base)
        if version:
            return version
    return None


def _extract_mirotalk_version(text: str) -> Optional[str]:
    if not text:
        return None
    match = _MIROTALK_VERSION_RE.search(text)
    if match:
        return match.group(1)
    match = _MIROTALK_GENERIC_VERSION_RE.search(text)
    if match:
        return match.group(1)
    return None


def _version_from_brand_payload(data) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    brand = data.get('message') if isinstance(data.get('message'), dict) else data
    if not isinstance(brand, dict):
        return None
    about = brand.get('about') if isinstance(brand.get('about'), dict) else {}
    title = str(about.get('title') or '')
    return _extract_mirotalk_version(title)


def _fetch_mirotalk_version_from_base(base_url: str) -> Optional[str]:
    """Try /brand JSON, then Brand.js, then the landing page."""
    root = base_url.rstrip('/')
    brand_url = f'{root}/brand'
    try:
        response = requests.get(brand_url, timeout=3)
        if response.ok and response.content:
            version = _version_from_brand_payload(response.json())
            if version:
                return version
    except Exception:
        logger.debug('MiroTalk /brand version lookup failed for %s', brand_url, exc_info=True)

    brand_js_url = f'{root}/js/Brand.js'
    try:
        response = requests.get(brand_js_url, timeout=3)
        if response.ok and response.text:
            version = _extract_mirotalk_version(response.text)
            if version:
                return version
    except Exception:
        logger.debug('MiroTalk Brand.js version lookup failed for %s', brand_js_url, exc_info=True)

    try:
        response = requests.get(root + '/', timeout=3)
        if response.ok and response.text:
            version = _extract_mirotalk_version(response.text)
            if version:
                return version
    except Exception:
        logger.debug('MiroTalk homepage version lookup failed for %s', root, exc_info=True)

    return None


def _base_url() -> str:
    return (current_app.config.get('MIROTALK_URL') or '').strip().rstrip('/')


def _api_base_url() -> str:
    api = (current_app.config.get('MIROTALK_API_URL') or '').strip().rstrip('/')
    return api or _base_url()


def _publicize_join_url(join_url: str) -> str:
    """Rewrite API/join URLs onto the configured public MiroTalk origin.

    MiroTalk may return https://127.0.0.1 or https://LAN-IP:3010 even when the
    portal embeds via http://meet.host (nginx). Always pin scheme+host to
    MIROTALK_URL so the iframe matches CSP and the public vHost.
    """
    public = _base_url()
    if not public or not join_url:
        return join_url
    parsed = urlparse(join_url)
    public_parsed = urlparse(public)
    if not public_parsed.scheme or not public_parsed.netloc:
        return join_url
    if parsed.scheme == public_parsed.scheme and parsed.netloc == public_parsed.netloc:
        return join_url
    return urlunparse((
        public_parsed.scheme,
        public_parsed.netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))


def build_direct_join_url(
    room: str,
    name: str,
    *,
    avatar: Optional[str] = None,
    token: Optional[str] = None,
) -> str:
    params = {
        'room': room,
        'name': name or 'Guest',
        'audio': '0',
        'video': '0',
        'screen': '0',
        'notify': '0',
        'duration': 'unlimited',
    }
    if avatar:
        params['avatar'] = avatar
    else:
        params['avatar'] = '0'
    if token:
        params['token'] = token
    return f"{_base_url()}/join?{urlencode(params)}"


def _join_url_has_token(join_url: str) -> bool:
    if not join_url:
        return False
    query = urlparse(join_url).query
    if not query:
        return False
    for part in query.split('&'):
        key, _, value = part.partition('=')
        if key == 'token' and value:
            return True
    return False


def _normalize_join_url(join_url: str) -> Optional[str]:
    public = _publicize_join_url(join_url)
    parsed = urlparse(public)
    if parsed.scheme in ('http', 'https') and parsed.netloc:
        return public
    return None


def request_join_url(
    room: str,
    name: str,
    *,
    avatar: Optional[str] = None,
    presenter: bool = False,
) -> str:
    """Ask the SFU for a join URL; fall back to a constructed direct-join link.

    When HOST credentials are configured (typical HOST_PROTECTED install), a JWT
    token is mandatory. Without it MiroTalk only shows “Waiting for host…” in the
    iframe — never a real room.
    """
    if not mirotalk_configured():
        raise RuntimeError('MiroTalk is not configured')

    api_key = (current_app.config.get('MIROTALK_API_KEY') or '').strip()
    host_user = (current_app.config.get('MIROTALK_HOST_USER') or '').strip()
    host_password = (current_app.config.get('MIROTALK_HOST_PASSWORD') or '').strip()
    auth_required = bool(api_key and host_user and host_password)

    payload = {
        'room': room,
        'name': name or 'Guest',
        'avatar': avatar or False,
        'audio': False,
        'video': False,
        'screen': False,
        'chat': False,
        'hide': False,
        'notify': False,
        'duration': 'unlimited',
    }
    if auth_required:
        payload['token'] = {
            'username': host_user,
            'password': host_password,
            'presenter': bool(presenter),
            'expire': '8h',
        }

    if api_key:
        try:
            response = requests.post(
                urljoin(_api_base_url() + '/', 'api/v1/join'),
                headers={
                    'authorization': api_key,
                    'Content-Type': 'application/json',
                },
                json=payload,
                timeout=8,
            )
            data = response.json() if response.content else {}
            join_url = data.get('join') if isinstance(data, dict) else None
            if response.ok and join_url:
                public = _normalize_join_url(join_url)
                if public and (not auth_required or _join_url_has_token(public)):
                    return public
                if public and auth_required and not _join_url_has_token(public):
                    logger.warning(
                        'MiroTalk join API returned URL without token (HOST_PROTECTED)'
                    )
            logger.warning(
                'MiroTalk join API %s: %s',
                response.status_code,
                data.get('error') if isinstance(data, dict) else response.text[:200],
            )
        except Exception:
            logger.warning('MiroTalk join API failed', exc_info=True)

    if auth_required:
        token = _request_token(
            host_user, host_password, presenter=presenter, api_key=api_key
        )
        if not token:
            raise RuntimeError(
                'MiroTalk auth failed: check MIROTALK_API_KEY / '
                'MIROTALK_HOST_USER / MIROTALK_HOST_PASSWORD'
            )
        return build_direct_join_url(room, name, avatar=avatar, token=token)

    return build_direct_join_url(room, name, avatar=avatar, token=None)


def _request_token(username: str, password: str, *, presenter: bool, api_key: str) -> Optional[str]:
    try:
        response = requests.post(
            urljoin(_api_base_url() + '/', 'api/v1/token'),
            headers={
                'authorization': api_key,
                'Content-Type': 'application/json',
            },
            json={
                'username': username,
                'password': password,
                'presenter': presenter,
                'expire': '8h',
            },
            timeout=8,
        )
        data = response.json() if response.content else {}
        if response.ok and isinstance(data, dict):
            return data.get('token')
    except Exception:
        logger.warning('MiroTalk token API failed', exc_info=True)
    return None
