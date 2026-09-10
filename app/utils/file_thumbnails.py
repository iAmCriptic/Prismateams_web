"""On-demand image thumbnails for file-grid previews (WebP, disk cache)."""

from __future__ import annotations

import logging
import os

from flask import current_app

logger = logging.getLogger(__name__)

THUMB_MAX_EDGE = 400
THUMB_QUALITY = 80
THUMB_MAX_PIXELS = 50_000_000


def _thumbs_dir() -> str:
    upload_root = current_app.config.get('UPLOAD_FOLDER') or 'uploads'
    path = os.path.join(upload_root, 'files', 'thumbs')
    os.makedirs(path, exist_ok=True)
    return path


def _source_mtime(source_path: str) -> int:
    try:
        return int(os.path.getmtime(source_path))
    except OSError:
        return 0


def thumbnail_cache_path(file_id: int, version_number: int, source_path: str) -> str:
    mtime = _source_mtime(source_path)
    version = int(version_number or 0)
    return os.path.join(_thumbs_dir(), f'{int(file_id)}_v{version}_{mtime}.webp')


def purge_thumbnails_for_file(file_id: int, keep_path: str | None = None) -> None:
    prefix = f'{int(file_id)}_'
    try:
        names = os.listdir(_thumbs_dir())
    except OSError:
        return
    keep = os.path.abspath(keep_path) if keep_path else None
    for name in names:
        if not name.startswith(prefix) or not name.endswith('.webp'):
            continue
        path = os.path.join(_thumbs_dir(), name)
        if keep and os.path.abspath(path) == keep:
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def _prepare_preview_image(img):
    from PIL import ImageOps

    img = ImageOps.exif_transpose(img)
    if getattr(img, 'is_animated', False):
        img.seek(0)
    frame = img.copy()
    if frame.mode in ('RGBA', 'LA'):
        return frame.convert('RGBA')
    if frame.mode == 'P':
        return frame.convert('RGBA') if 'transparency' in img.info else frame.convert('RGB')
    if frame.mode != 'RGB':
        return frame.convert('RGB')
    return frame


def ensure_image_thumbnail(file_id: int, version_number: int, source_path: str) -> str | None:
    """Return a cached WebP thumbnail path, or None to serve the original."""
    if not source_path or not os.path.isfile(source_path):
        return None
    dest = thumbnail_cache_path(file_id, version_number, source_path)
    if os.path.isfile(dest):
        return dest

    from PIL import Image

    try:
        with Image.open(source_path) as src:
            width, height = src.size
            if width * height > THUMB_MAX_PIXELS:
                return None
            work = _prepare_preview_image(src)
            work.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE), Image.Resampling.LANCZOS)
            tmp = dest + '.tmp'
            work.save(tmp, format='WEBP', quality=THUMB_QUALITY, method=4)
        os.replace(tmp, dest)
    except Exception:
        logger.warning('Thumbnail failed for file %s', file_id, exc_info=True)
        try:
            os.remove(dest + '.tmp')
        except OSError:
            pass
        return None

    purge_thumbnails_for_file(file_id, keep_path=dest)
    return dest
