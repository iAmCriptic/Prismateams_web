"""Helpers for HyCanvas integration: presets, SSO/avatar sync, REST client & snapshots."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import jwt
import requests
from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

AVATAR_TOKEN_SALT = 'canvas-avatar-token'
AVATAR_TOKEN_MAX_AGE = 86400

CANVAS_PRESET_CATEGORIES = [
    {
        'key': 'workspace',
        'label_key': 'canvas.create.cat.workspace',
        'items': [
            {'key': 'whiteboard', 'type': 'whiteboard', 'width': 1920, 'height': 1080, 'icon': 'bi-grid-1x2', 'label_key': 'canvas.preset.whiteboard'},
            {'key': 'sheet', 'type': 'sheet', 'width': 1280, 'height': 800, 'icon': 'bi-table', 'label_key': 'canvas.preset.sheet'},
        ],
    },
    {
        'key': 'presentation',
        'label_key': 'canvas.create.cat.presentation',
        'items': [
            {'key': 'presentation', 'type': 'presentation', 'width': 1920, 'height': 1080, 'icon': 'bi-easel', 'label_key': 'canvas.preset.presentation'},
            {'key': 'video', 'type': 'video', 'width': 1920, 'height': 1080, 'icon': 'bi-film', 'label_key': 'canvas.preset.video'},
        ],
    },
    {
        'key': 'documents',
        'label_key': 'canvas.create.cat.documents',
        'items': [
            {'key': 'a4_doc', 'type': 'doc', 'width': 1240, 'height': 1754, 'icon': 'bi-book', 'label_key': 'canvas.preset.a4_doc'},
            {'key': 'document', 'type': 'doc', 'width': 816, 'height': 1056, 'icon': 'bi-file-earmark-text', 'label_key': 'canvas.preset.document'},
            {'key': 'poster', 'type': 'graphic', 'width': 1080, 'height': 1350, 'icon': 'bi-file-earmark-richtext', 'label_key': 'canvas.preset.poster'},
            {'key': 'flyer', 'type': 'graphic', 'width': 816, 'height': 1056, 'icon': 'bi-file-earmark', 'label_key': 'canvas.preset.flyer'},
            {'key': 'business_card', 'type': 'graphic', 'width': 1050, 'height': 600, 'icon': 'bi-person-vcard', 'label_key': 'canvas.preset.business_card'},
        ],
    },
    {
        'key': 'web',
        'label_key': 'canvas.create.cat.web',
        'items': [
            {'key': 'banner', 'type': 'graphic', 'width': 1500, 'height': 500, 'icon': 'bi-aspect-ratio', 'label_key': 'canvas.preset.banner'},
            {'key': 'desktop_bg', 'type': 'graphic', 'width': 1920, 'height': 1080, 'icon': 'bi-display', 'label_key': 'canvas.preset.desktop_bg'},
            {'key': 'logo', 'type': 'graphic', 'width': 500, 'height': 500, 'icon': 'bi-image', 'label_key': 'canvas.preset.logo'},
        ],
    },
    {
        'key': 'social',
        'label_key': 'canvas.create.cat.social',
        'items': [
            {'key': 'ig_post', 'type': 'graphic', 'width': 1080, 'height': 1080, 'icon': 'bi-instagram', 'label_key': 'canvas.preset.ig_post'},
            {'key': 'ig_portrait', 'type': 'graphic', 'width': 1080, 'height': 1350, 'icon': 'bi-instagram', 'label_key': 'canvas.preset.ig_portrait'},
            {'key': 'ig_story', 'type': 'graphic', 'width': 1080, 'height': 1920, 'icon': 'bi-phone', 'label_key': 'canvas.preset.ig_story'},
            {'key': 'fb_post', 'type': 'graphic', 'width': 1200, 'height': 630, 'icon': 'bi-facebook', 'label_key': 'canvas.preset.fb_post'},
            {'key': 'li_post', 'type': 'graphic', 'width': 1200, 'height': 627, 'icon': 'bi-linkedin', 'label_key': 'canvas.preset.li_post'},
            {'key': 'yt_thumb', 'type': 'graphic', 'width': 1280, 'height': 720, 'icon': 'bi-youtube', 'label_key': 'canvas.preset.yt_thumb'},
        ],
    },
    {
        'key': 'custom',
        'label_key': 'canvas.create.cat.custom',
        'items': [
            {'key': 'custom', 'type': 'graphic', 'width': 1920, 'height': 1080, 'icon': 'bi-plus-square-dotted', 'label_key': 'canvas.preset.custom'},
        ],
    },
]

CANVAS_PRESET_MAP = {
    item['key']: item
    for cat in CANVAS_PRESET_CATEGORIES
    for item in cat['items']
}


def is_canvas_enabled() -> bool:
    return bool(current_app.config.get('HYCANVAS_ENABLED', True))


def get_hycanvas_browser_url() -> str:
    return (current_app.config.get('HYCANVAS_URL') or '/hycanvas').strip().rstrip('/')


def get_hycanvas_api_url() -> str:
    return (current_app.config.get('HYCANVAS_API_URL') or 'http://hycanvas:8005').strip().rstrip('/')


def sign_canvas_avatar_token(user_id: int) -> str:
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps({'uid': int(user_id)}, salt=AVATAR_TOKEN_SALT)


def load_canvas_avatar_user_id(token: str) -> int | None:
    if not token:
        return None
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = s.loads(token, salt=AVATAR_TOKEN_SALT, max_age=AVATAR_TOKEN_MAX_AGE)
        return int(data['uid'])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


def get_user_avatar_external_url(user) -> str | None:
    if not user or not getattr(user, 'profile_picture', None):
        return None
    return url_for('canvas.avatar', token=sign_canvas_avatar_token(user.id), _external=True)


def build_hycanvas_sso_jwt(user) -> str | None:
    """Build a short-lived JWT signed with HYCANVAS_JWT_SECRET for seamless SSO."""
    secret = (current_app.config.get('HYCANVAS_JWT_SECRET') or '').strip()
    if not secret:
        return None
    now = int(time.time())
    payload = {
        'sub': str(user.id),
        'email': getattr(user, 'email', None) or f'user-{user.id}@portal.local',
        'name': getattr(user, 'full_name', None) or getattr(user, 'username', None) or f'User {user.id}',
        'avatar_url': get_user_avatar_external_url(user),
        'iat': now,
        'exp': now + 3600 * 8,
    }
    return jwt.encode(payload, secret, algorithm='HS256')


def _hycanvas_headers(user=None) -> dict[str, str]:
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    api_key = (current_app.config.get('HYCANVAS_API_KEY') or '').strip()
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    elif user is not None:
        token = build_hycanvas_sso_jwt(user)
        if token:
            headers['Authorization'] = f'Bearer {token}'
    return headers


def ensure_hycanvas_user(user) -> None:
    """Best-effort sync of user name, email and profile picture to HyCanvas."""
    api_url = get_hycanvas_api_url()
    if not api_url or not user:
        return
    payload = {
        'email': getattr(user, 'email', None) or f'user-{user.id}@portal.local',
        'name': getattr(user, 'full_name', None) or getattr(user, 'username', None) or f'User {user.id}',
        'avatar_url': get_user_avatar_external_url(user),
    }
    try:
        requests.post(
            f'{api_url}/api/v1/users/sync',
            json=payload,
            headers=_hycanvas_headers(user),
            timeout=4,
        )
    except Exception as exc:
        logger.debug('HyCanvas user sync skipped/failed: %s', exc)


def hycanvas_create_design(
    *,
    title: str,
    design_type: str,
    width: int,
    height: int,
    user=None,
) -> str | None:
    """Create a design in HyCanvas and return its remote design_id (or None if offline)."""
    api_url = get_hycanvas_api_url()
    if not api_url:
        return None
    ensure_hycanvas_user(user)
    payload: dict[str, Any] = {
        'title': title,
        'type': design_type,
        'width': int(width),
        'height': int(height),
    }
    try:
        resp = requests.post(
            f'{api_url}/api/v1/designs',
            json=payload,
            headers=_hycanvas_headers(user),
            timeout=6,
        )
        if resp.ok:
            data = resp.json() if resp.content else {}
            design_id = data.get('id') or (data.get('data') or {}).get('id')
            if design_id:
                return str(design_id)
    except Exception as exc:
        logger.warning('HyCanvas create design failed: %s', exc)
    return None


def hycanvas_export_hyc(design_id: str, user=None) -> bytes | None:
    if not design_id:
        return None
    api_url = get_hycanvas_api_url()
    try:
        resp = requests.get(
            f'{api_url}/api/v1/designs/{design_id}/export',
            params={'format': 'hyc'},
            headers=_hycanvas_headers(user),
            timeout=10,
        )
        if resp.ok and resp.content:
            return resp.content
    except Exception as exc:
        logger.warning('HyCanvas .hyc export failed for %s: %s', design_id, exc)
    return None


def hycanvas_export_thumbnail(design_id: str, user=None) -> bytes | None:
    if not design_id:
        return None
    api_url = get_hycanvas_api_url()
    try:
        resp = requests.get(
            f'{api_url}/api/v1/designs/{design_id}/export',
            params={'format': 'png', 'width': 640},
            headers=_hycanvas_headers(user),
            timeout=10,
        )
        if resp.ok and resp.content:
            return resp.content
    except Exception as exc:
        logger.warning('HyCanvas thumbnail export failed for %s: %s', design_id, exc)
    return None


def hycanvas_delete_design(design_id: str, user=None) -> None:
    if not design_id:
        return
    api_url = get_hycanvas_api_url()
    try:
        requests.delete(
            f'{api_url}/api/v1/designs/{design_id}',
            headers=_hycanvas_headers(user),
            timeout=5,
        )
    except Exception as exc:
        logger.warning('HyCanvas delete design failed for %s: %s', design_id, exc)


def get_hycanvas_embed_url(doc, user=None) -> str:
    base = get_hycanvas_browser_url()
    if doc.hycanvas_design_id:
        return f'{base}/design/{doc.hycanvas_design_id}'
    return f'{base}/'


def _canvas_upload_dir() -> str:
    root = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    path = os.path.join(root, 'canvas')
    os.makedirs(path, exist_ok=True)
    return path


def save_canvas_hyc_file(doc_id: int, name: str, raw_bytes: bytes) -> str:
    slug = secure_filename(re.sub(r'\s+', '_', name or 'canvas')) or 'canvas'
    filename = f'canvas_{doc_id}_{int(time.time())}_{slug[:40]}.hyc'
    full_path = os.path.join(_canvas_upload_dir(), filename)
    with open(full_path, 'wb') as fh:
        fh.write(raw_bytes)
    return full_path


def save_canvas_thumbnail(doc_id: int, raw_bytes: bytes) -> str:
    filename = f'canvas_{doc_id}_thumb.png'
    full_path = os.path.join(_canvas_upload_dir(), filename)
    with open(full_path, 'wb') as fh:
        fh.write(raw_bytes)
    return full_path


def remove_file_quietly(path: str | None) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
