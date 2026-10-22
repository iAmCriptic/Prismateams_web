"""In-process email sync job status (fallback when Redis/SSE is unavailable)."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_MAX_AGE_SECONDS = 30 * 60
_MAX_JOBS = 200


def _prune_locked(now: float) -> None:
    stale = [jid for jid, job in _JOBS.items() if (now - float(job.get('updated_at') or 0)) > _MAX_AGE_SECONDS]
    for jid in stale:
        _JOBS.pop(jid, None)
    if len(_JOBS) > _MAX_JOBS:
        ordered = sorted(_JOBS.items(), key=lambda item: float(item[1].get('updated_at') or 0))
        for jid, _ in ordered[: max(0, len(_JOBS) - _MAX_JOBS)]:
            _JOBS.pop(jid, None)


def set_email_sync_job(job_id: str, payload: dict[str, Any]) -> None:
    if not job_id:
        return
    now = time.time()
    with _LOCK:
        current = dict(_JOBS.get(job_id) or {})
        current.update(payload or {})
        current['jobId'] = job_id
        current['updated_at'] = now
        _JOBS[job_id] = current
        _prune_locked(now)


def get_email_sync_job(job_id: str) -> Optional[dict[str, Any]]:
    if not job_id:
        return None
    now = time.time()
    with _LOCK:
        _prune_locked(now)
        job = _JOBS.get(job_id)
        return dict(job) if job else None
