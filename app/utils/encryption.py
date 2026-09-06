"""Shared Fernet-key loading from Flask config / environment."""

from __future__ import annotations

import os
from typing import Optional


def read_encryption_key(*names: str) -> Optional[bytes]:
    """Return the first non-empty key from Flask config, then os.environ, as bytes.

    Quote-strips .env values. Does not generate keys or fall back to files —
    callers keep those policies locally (credentials fail-closed, TOTP/music
    have their own fallbacks).
    """
    seen: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    if not seen:
        return None

    try:
        from flask import current_app, has_app_context

        if has_app_context():
            cfg = current_app.config
            for name in seen:
                val = cfg.get(name)
                key = _as_key_bytes(val)
                if key:
                    return key
    except Exception:
        pass

    for name in seen:
        key = _as_key_bytes(os.environ.get(name))
        if key:
            return key
    return None


def _as_key_bytes(val) -> Optional[bytes]:
    if val is None:
        return None
    if isinstance(val, bytes):
        stripped = val.strip()
        return stripped or None
    text = str(val).strip().strip('"').strip("'")
    if not text:
        return None
    return text.encode("utf-8")
