"""
Bounded thread pools for LibreOffice/FFmpeg work (QA G06).

HTTP handlers enqueue jobs and return immediately; conversion runs off the
gthread request slot in a capped pool so workers are not flooded with
unbounded daemon threads.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_converter_pool: ThreadPoolExecutor | None = None
_converter_pool_size = 0
_media_pool: ThreadPoolExecutor | None = None
_media_pool_size = 0


def _ensure_pool(kind: str, size: int) -> ThreadPoolExecutor:
    global _converter_pool, _converter_pool_size, _media_pool, _media_pool_size
    size = max(1, int(size or 1))
    with _lock:
        if kind == 'converter':
            if _converter_pool is None or _converter_pool_size != size:
                if _converter_pool is not None:
                    _converter_pool.shutdown(wait=False, cancel_futures=False)
                _converter_pool = ThreadPoolExecutor(
                    max_workers=size,
                    thread_name_prefix='file-convert',
                )
                _converter_pool_size = size
                logger.info('File-converter pool size=%s', size)
            return _converter_pool
        if _media_pool is None or _media_pool_size != size:
            if _media_pool is not None:
                _media_pool.shutdown(wait=False, cancel_futures=False)
            _media_pool = ThreadPoolExecutor(
                max_workers=size,
                thread_name_prefix='media-convert',
            )
            _media_pool_size = size
            logger.info('Media-converter pool size=%s', size)
        return _media_pool


def submit_file_conversion(fn, /, *args, max_workers: int = 2, **kwargs):
    """Run file conversion off the request thread (bounded)."""
    pool = _ensure_pool('converter', max_workers)
    return pool.submit(fn, *args, **kwargs)


def submit_media_conversion(fn, /, *args, max_workers: int = 2, **kwargs):
    """Run media FFmpeg conversion off the request thread (bounded)."""
    pool = _ensure_pool('media', max_workers)
    return pool.submit(fn, *args, **kwargs)
