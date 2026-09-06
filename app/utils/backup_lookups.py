"""Batch id→email / id→name maps for backup export/import (avoids per-row get())."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

_user_emails: ContextVar[Optional[dict]] = ContextVar("backup_user_emails", default=None)
_team_names: ContextVar[Optional[dict]] = ContextVar("backup_team_names", default=None)
_entity_names: ContextVar[Optional[dict]] = ContextVar("backup_entity_names", default=None)
_entity_objs: ContextVar[Optional[dict]] = ContextVar("backup_entity_objs", default=None)


def id_name_map(model, attr: str = "name") -> dict:
    col = getattr(model, attr)
    return dict(model.query.with_entities(model.id, col).all())


def objects_by_id(model) -> dict:
    return {row.id: row for row in model.query.all()}


def objects_by_name(model, attr: str = "name") -> dict:
    """All rows of ``model`` keyed by ``attr`` (skips empty names)."""
    out = {}
    for row in model.query.all():
        key = getattr(row, attr, None)
        if key:
            out[key] = row
    return out


def prime_backup_lookups() -> None:
    """Load User/Team and common entity lookup tables once per backup run."""
    from app.models import Comment, Manual, WikiPage
    from app.models.calendar import CalendarEvent
    from app.models.chat import Chat
    from app.models.excalidraw import ExcalidrawDrawing
    from app.models.file import File, Folder
    from app.models.inventory import Inventory, Product, ProductFolder, ProductSet
    from app.models.team import Team
    from app.models.user import User

    _user_emails.set(dict(User.query.with_entities(User.id, User.email).all()))
    _team_names.set(dict(Team.query.with_entities(Team.id, Team.name).all()))

    _entity_names.set({
        "chat": id_name_map(Chat),
        "folder": id_name_map(Folder),
        "file": id_name_map(File),
        "product": id_name_map(Product),
        "product_folder": id_name_map(ProductFolder),
        "product_set": id_name_map(ProductSet),
        "inventory": id_name_map(Inventory),
        "calendar_event": id_name_map(CalendarEvent, "title"),
        "manual": id_name_map(Manual, "title"),
        "wiki_page_slug": id_name_map(WikiPage, "slug"),
        "excalidraw": id_name_map(ExcalidrawDrawing),
    })

    _entity_objs.set({
        "folder": objects_by_id(Folder),
        "file": objects_by_id(File),
        "wiki_page": objects_by_id(WikiPage),
        "comment": objects_by_id(Comment),
        "excalidraw": objects_by_id(ExcalidrawDrawing),
    })


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


def lookup_entity_name(kind: str, obj_id) -> Optional[str]:
    """id→name/title/slug for primed entity kind (chat, folder, file, product, …)."""
    if not obj_id:
        return None
    maps = _entity_names.get()
    if maps is None:
        prime_backup_lookups()
        maps = _entity_names.get() or {}
    return (maps.get(kind) or {}).get(obj_id)


def lookup_entity(kind: str, obj_id) -> Any:
    """id→ORM-Objekt für Export-Pfade, die mehr als den Namen brauchen."""
    if not obj_id:
        return None
    maps = _entity_objs.get()
    if maps is None:
        prime_backup_lookups()
        maps = _entity_objs.get() or {}
    return (maps.get(kind) or {}).get(obj_id)
