"""Batch id→email / id→name maps for backup export/import (avoids per-row get())."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_user_emails: ContextVar[Optional[dict]] = ContextVar("backup_user_emails", default=None)
_team_names: ContextVar[Optional[dict]] = ContextVar("backup_team_names", default=None)


def prime_backup_lookups() -> None:
    """Load User and Team lookup tables once per backup run."""
    from app.models.team import Team
    from app.models.user import User

    _user_emails.set(dict(User.query.with_entities(User.id, User.email).all()))
    _team_names.set(dict(Team.query.with_entities(Team.id, Team.name).all()))


def lookup_user_email(user_id) -> Optional[str]:
    if not user_id:
        return None
    mapping = _user_emails.get()
    if mapping is None:
        prime_backup_lookups()
        mapping = _user_emails.get() or {}
    return mapping.get(user_id)


def lookup_team_name(team_id) -> Optional[str]:
    if not team_id:
        return None
    mapping = _team_names.get()
    if mapping is None:
        prime_backup_lookups()
        mapping = _team_names.get() or {}
    return mapping.get(team_id)


def objects_by_name(model, attr: str = "name") -> dict:
    """All rows of ``model`` keyed by ``attr`` (skips empty names)."""
    out = {}
    for row in model.query.all():
        key = getattr(row, attr, None)
        if key:
            out[key] = row
    return out


def id_name_map(model, attr: str = "name") -> dict:
    col = getattr(model, attr)
    return dict(model.query.with_entities(model.id, col).all())
