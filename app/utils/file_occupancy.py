"""Cross-channel file occupancy: Euro-Office / Markdown vs WebDAV desktop.

Browser collaboration (multiple Euro-Office sessions) stays allowed.
Desktop WebDAV and browser editors are mutually exclusive per file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from app.models.file import File, Folder
from app.models.team import Team
from app.models.user import User
from app.utils import file_edit_lock as file_edit_lock_util
from app.utils.onlyoffice_presence import cleanup_stale_sessions, presence_for_file_ids
from app.utils.webdav import ops

PRIVATE = 'Private'
PUBLIC = 'Public'
TEAMS = 'Teams'


@dataclass(frozen=True)
class Occupancy:
    source: str  # 'eurooffice' | 'markdown' | 'webdav'
    display_name: str
    detail: str | None = None

    @property
    def message(self) -> str:
        if self.source == 'eurooffice':
            return f'Datei wird in Euro-Office von {self.display_name} bearbeitet.'
        if self.source == 'markdown':
            return f'Datei wird im Browser von {self.display_name} bearbeitet.'
        return f'Datei wird über WebDAV/Explorer von {self.display_name} bearbeitet.'

    def as_dict(self) -> dict[str, Any]:
        return {
            'source': self.source,
            'display_name': self.display_name,
            'detail': self.detail,
            'message': self.message,
        }


def _normalize_dav_path(path: str | None) -> str:
    raw = unquote(path or '/')
    if not raw.startswith('/'):
        raw = '/' + raw
    return raw.rstrip('/') or '/'


def _path_parts(path: str) -> list[str]:
    return [p for p in _normalize_dav_path(path).strip('/').split('/') if p]


def webdav_path_for_file(file_obj: File) -> str | None:
    """Build the WebDAV resource path for a DB file (leading slash, no trailing slash)."""
    if not file_obj:
        return None
    parts: list[str] = [ops.path_segment_for_name(file_obj.name)]
    folder = file_obj.folder
    while folder is not None:
        if folder.is_personal_root:
            return '/' + '/'.join([PRIVATE] + list(reversed(parts)))
        if folder.is_team_root:
            team = Team.query.get(folder.team_id) if folder.team_id else None
            team_seg = ops.path_segment_for_name(team.name if team else f'team-{folder.team_id}')
            return '/' + '/'.join([TEAMS, team_seg] + list(reversed(parts)))
        parts.append(ops.path_segment_for_name(folder.name))
        folder = folder.parent
    return '/' + '/'.join([PUBLIC] + list(reversed(parts)))


def resolve_file_from_dav_path(path: str) -> File | None:
    """Resolve a WebDAV path to a File row (no ACL check — for lock/occupancy only)."""
    parts = _path_parts(path)
    if len(parts) < 2:
        return None
    top = parts[0]
    rest = parts[1:]

    if top == PRIVATE:
        return _resolve_under_personal(rest)
    if top == PUBLIC:
        return _resolve_under_public(rest)
    if top == TEAMS:
        if len(rest) < 2:
            return None
        team_seg, *file_parts = rest
        team = _find_team_by_segment(team_seg)
        if not team:
            return None
        root = Folder.query.filter_by(is_team_root=True, team_id=team.id, deleted_at=None).first()
        if not root:
            return None
        return _resolve_under_folder(root, file_parts, space_filter=None, team_id=team.id)
    return None


def _find_team_by_segment(segment: str) -> Team | None:
    for team in Team.query.all():
        if ops.names_match(team.name, segment):
            return team
    return None


def _resolve_under_public(rest: list[str]) -> File | None:
    if not rest:
        return None
    parent: Folder | None = None
    for i, segment in enumerate(rest):
        is_last = i == len(rest) - 1
        parent_id = parent.id if parent else None
        if is_last:
            return ops.find_child_file(
                parent_id,
                segment,
                space_filter='public' if parent is None else None,
            )
        folder = ops.find_child_folder(
            parent_id,
            segment,
            space_filter='public' if parent is None else None,
        )
        if not folder:
            return None
        parent = folder
    return None


def _resolve_under_folder(root: Folder, rest: list[str], *, space_filter, team_id) -> File | None:
    if not rest:
        return None
    parent: Folder | None = root
    for i, segment in enumerate(rest):
        is_last = i == len(rest) - 1
        parent_id = parent.id if parent else None
        if is_last:
            return ops.find_child_file(parent_id, segment, space_filter=space_filter, team_id=team_id)
        folder = ops.find_child_folder(parent_id, segment, space_filter=space_filter, team_id=team_id)
        if not folder:
            return None
        parent = folder
    return None


def _resolve_under_personal(rest: list[str]) -> File | None:
    """Match Private/<…> against personal folder trees (any user)."""
    if not rest:
        return None
    roots = Folder.query.filter_by(is_personal_root=True, deleted_at=None).all()
    for root in roots:
        found = _resolve_under_folder(root, rest, space_filter=None, team_id=None)
        if found:
            return found
    return None


def browser_occupancy_for_dav_path(path: str, *, exclude_user_id: int | None = None) -> Occupancy | None:
    """Occupancy from Euro-Office / Markdown that should block WebDAV LOCK/PUT."""
    file_obj = resolve_file_from_dav_path(path)
    if not file_obj:
        return None
    cleanup_stale_sessions()
    presence = presence_for_file_ids([file_obj.id]).get(file_obj.id) or []
    if presence:
        name = presence[0].get('display_name') or 'Euro-Office'
        return Occupancy(source='eurooffice', display_name=name)
    lock = file_edit_lock_util.get_active_lock(file_obj.id)
    if lock:
        if exclude_user_id is not None and lock.locked_by == exclude_user_id:
            return None
        user = lock.locker or User.query.get(lock.locked_by)
        name = (user.full_name if user else None) or 'Browser'
        return Occupancy(source='markdown', display_name=name)
    return None


def raise_if_browser_blocks_webdav(file_obj: File | None, *, user_id: int | None = None) -> None:
    """Raise DAV 423 if Euro-Office or another user's Markdown lock holds the file."""
    if not file_obj:
        return
    cleanup_stale_sessions()
    presence = presence_for_file_ids([file_obj.id]).get(file_obj.id) or []
    if presence:
        from wsgidav.dav_error import DAVError, HTTP_LOCKED

        name = presence[0].get('display_name') or 'Euro-Office'
        raise DAVError(HTTP_LOCKED, Occupancy('eurooffice', name).message)
    lock = file_edit_lock_util.get_active_lock(file_obj.id)
    if lock and (user_id is None or lock.locked_by != user_id):
        from wsgidav.dav_error import DAVError, HTTP_LOCKED

        user = lock.locker or User.query.get(lock.locked_by)
        name = (user.full_name if user else None) or 'Browser'
        raise DAVError(HTTP_LOCKED, Occupancy('markdown', name).message)


def webdav_occupancy_for_file(file_id: int) -> Occupancy | None:
    """Return occupancy from WsgiDAV locks for this file (blocks browser edit)."""
    from app.utils.webdav.lock_store import get_lock_storage

    file_obj = File.query.get(file_id)
    if not file_obj:
        return None
    path = webdav_path_for_file(file_obj)
    if not path:
        return None
    storage = get_lock_storage()
    if storage is None:
        return None
    try:
        locks = storage.get_lock_list(
            _normalize_dav_path(path),
            include_root=True,
            include_children=False,
            token_only=False,
        ) or []
    except Exception:
        return None
    if not locks:
        return None
    lock = locks[0]
    principal = lock.get('principal') or lock.get('owner') or 'WebDAV'
    if isinstance(principal, bytes):
        principal = principal.decode('utf-8', errors='replace')
    name = str(principal).strip() or 'WebDAV'
    return Occupancy(source='webdav', display_name=name, detail=path)
