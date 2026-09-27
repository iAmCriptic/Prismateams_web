"""Shared WsgiDAV lock storage (Redis or Shelve) + occupancy-aware wrapper."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_lock_storage = None


def get_lock_storage():
    """Return the process-wide WebDAV lock storage (may be None before mount)."""
    return _lock_storage


def set_lock_storage(storage) -> None:
    global _lock_storage
    _lock_storage = storage


def build_lock_storage(flask_app):
    """Create Redis or Shelve lock storage based on app config."""
    from wsgidav.lock_man.lock_storage import LockStorageShelve
    from wsgidav.lock_man.lock_storage_redis import LockStorageRedis

    if flask_app.config.get('REDIS_ENABLED'):
        raw = flask_app.config.get('REDIS_URL') or 'redis://localhost:6379/0'
        parsed = urlparse(raw)
        host = parsed.hostname or '127.0.0.1'
        port = parsed.port or 6379
        db_path = (parsed.path or '/0').lstrip('/') or '0'
        try:
            db = int(db_path.split('/')[0])
        except ValueError:
            db = 0
        logger.info('WebDAV lock storage: Redis %s:%s/%s', host, port, db)
        return LockStorageRedis(
            host=host,
            port=port,
            db=db,
            password=parsed.password,
        )

    upload = flask_app.config.get('UPLOAD_FOLDER') or 'uploads'
    storage_path = os.path.abspath(os.path.join(upload, '.webdav_locks'))
    parent = os.path.dirname(storage_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    logger.info('WebDAV lock storage: Shelve %s', storage_path)
    return LockStorageShelve(storage_path)


class OccupancyAwareLockStorage:
    """Delegate lock storage that refuses LOCK when Euro-Office/Markdown holds the file."""

    def __init__(self, inner):
        self._inner = inner

    def open(self):
        return self._inner.open()

    def close(self):
        return self._inner.close()

    def clear(self):
        return self._inner.clear()

    def cleanup(self):
        return self._inner.cleanup()

    def get(self, token):
        return self._inner.get(token)

    def delete(self, token):
        return self._inner.delete(token)

    def refresh(self, token, *, timeout):
        return self._inner.refresh(token, timeout=timeout)

    def get_lock_list(self, path, *, include_root, include_children, token_only):
        return self._inner.get_lock_list(
            path,
            include_root=include_root,
            include_children=include_children,
            token_only=token_only,
        )

    def create(self, path, lock):
        from wsgidav.dav_error import DAVError, HTTP_LOCKED

        from app.utils.file_occupancy import browser_occupancy_for_dav_path

        try:
            blocker = browser_occupancy_for_dav_path(path)
        except Exception:
            logger.exception('WebDAV occupancy check failed for %s', path)
            blocker = None
        if blocker:
            raise DAVError(HTTP_LOCKED, blocker.message)
        return self._inner.create(path, lock)
