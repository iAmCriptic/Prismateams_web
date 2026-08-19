"""Excalidraw module helpers: collab flags, storage paths, scene I/O."""
from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime

from flask import current_app

EMPTY_SCENE = {
    'type': 'excalidraw',
    'version': 2,
    'source': 'prismateams',
    'elements': [],
    'appState': {
        'gridSize': None,
        'viewBackgroundColor': '#ffffff',
    },
    'files': {},
}

MAX_SCENE_BYTES = 50 * 1024 * 1024
MAX_VERSIONS = 5
UPLOAD_SUBDIR = os.path.join('uploads', 'excalidraw')
THUMB_SUBDIR = os.path.join(UPLOAD_SUBDIR, 'thumbs')
EXCALIDRAW_PACKAGE_VERSION = '0.18.1'


def get_excalidraw_package_version():
    return EXCALIDRAW_PACKAGE_VERSION


def is_excalidraw_collab_enabled():
    try:
        return bool(current_app.config.get('EXCALIDRAW_ENABLED', False))
    except RuntimeError:
        return False


def get_excalidraw_room_url():
    url = (current_app.config.get('EXCALIDRAW_ROOM_URL') or '/excalidraw-room').strip()
    if not url:
        return '/excalidraw-room'
    return url.rstrip('/') or '/excalidraw-room'


def ensure_upload_dirs():
    os.makedirs(UPLOAD_SUBDIR, exist_ok=True)
    os.makedirs(THUMB_SUBDIR, exist_ok=True)


def _safe_stem(name: str) -> str:
    stem = re.sub(r'[^\w\s-]', '', (name or 'drawing').strip(), flags=re.UNICODE)
    stem = re.sub(r'[-\s]+', '-', stem).strip('-') or 'drawing'
    return stem[:80]


def new_scene_path(drawing_id: int, name: str) -> str:
    ensure_upload_dirs()
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f'{timestamp}_{drawing_id}_{_safe_stem(name)}.excalidraw'
    return os.path.abspath(os.path.join(UPLOAD_SUBDIR, filename))


def thumbnail_path_for(drawing_id: int) -> str:
    ensure_upload_dirs()
    return os.path.abspath(os.path.join(THUMB_SUBDIR, f'{drawing_id}.png'))


def write_scene_file(path: str, scene: dict):
    payload = json.dumps(scene, ensure_ascii=False, separators=(',', ':'))
    encoded = payload.encode('utf-8')
    if len(encoded) > MAX_SCENE_BYTES:
        raise ValueError('scene_too_large')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(payload)


def read_scene_file(path: str) -> dict:
    if not path or not os.path.exists(path):
        return dict(EMPTY_SCENE)
    with open(path, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return dict(EMPTY_SCENE)
    return data


def normalize_scene(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError('invalid_scene')
    elements = raw.get('elements')
    if elements is None:
        elements = []
    if not isinstance(elements, list):
        raise ValueError('invalid_scene')
    files = raw.get('files')
    if files is None:
        files = {}
    if not isinstance(files, dict):
        raise ValueError('invalid_scene')
    app_state = raw.get('appState')
    if app_state is not None and not isinstance(app_state, dict):
        raise ValueError('invalid_scene')
    scene = {
        'type': 'excalidraw',
        'version': int(raw.get('version') or 2),
        'source': raw.get('source') or 'prismateams',
        'elements': elements,
        'appState': app_state if isinstance(app_state, dict) else dict(EMPTY_SCENE['appState']),
        'files': files,
    }
    return scene


def save_thumbnail_data(drawing_id: int, data_url: str | None) -> str | None:
    if not data_url or not isinstance(data_url, str):
        return None
    match = re.match(r'^data:image/png;base64,(.+)$', data_url.strip(), re.DOTALL)
    if not match:
        return None
    try:
        raw = base64.b64decode(match.group(1), validate=True)
    except Exception:
        return None
    if not raw or len(raw) > 2 * 1024 * 1024:
        return None
    path = thumbnail_path_for(drawing_id)
    with open(path, 'wb') as handle:
        handle.write(raw)
    return path


def remove_file_quietly(path: str | None):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def download_name(drawing_name: str) -> str:
    stem = _safe_stem(drawing_name)
    if not stem.lower().endswith('.excalidraw'):
        stem = f'{stem}.excalidraw'
    return stem
