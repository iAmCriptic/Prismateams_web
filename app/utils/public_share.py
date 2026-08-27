"""Utilities for multi-link public file/folder shares (view | edit | dropbox)."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Literal

from flask import Request, url_for
from werkzeug.security import generate_password_hash

from app import db
from app.models.file import File, Folder
from app.models.public_share import PublicShare, ShareAccessLog

ResourceType = Literal['file', 'folder', 'kanban_board', 'excalidraw_drawing']
ShareMode = Literal['view', 'edit', 'dropbox']

VALID_MODES = frozenset({'view', 'edit', 'dropbox'})
VALID_RESOURCE_TYPES = frozenset({'file', 'folder', 'kanban_board', 'excalidraw_drawing'})
VIEW_EDIT_MODES = frozenset({'view', 'edit'})


def normalize_share_mode(value: str | None) -> ShareMode:
    mode = (value or 'edit').strip().lower()
    if mode == 'view':
        return 'view'
    if mode == 'dropbox':
        return 'dropbox'
    return 'edit'


def generate_unique_share_token() -> str:
    token = secrets.token_urlsafe(32)
    while PublicShare.query.filter_by(token=token).first():
        token = secrets.token_urlsafe(32)
    return token


def get_share_by_token(token: str, *, require_enabled: bool = True) -> PublicShare | None:
    query = PublicShare.query.filter_by(token=token)
    if require_enabled:
        query = query.filter_by(enabled=True)
    return query.first()


def resolve_resource(share: PublicShare):
    if share.resource_type == 'file':
        return File.query.get(share.resource_id)
    if share.resource_type == 'folder':
        return Folder.query.get(share.resource_id)
    if share.resource_type == 'kanban_board':
        from app.models.kanban import KanbanBoard
        return KanbanBoard.query.get(share.resource_id)
    if share.resource_type == 'excalidraw_drawing':
        from app.models.excalidraw import ExcalidrawDrawing
        return ExcalidrawDrawing.query.get(share.resource_id)
    return None


def get_shares_for_resource(resource_type: ResourceType, resource_id: int) -> list[PublicShare]:
    return (
        PublicShare.query.filter_by(resource_type=resource_type, resource_id=resource_id)
        .order_by(PublicShare.id.asc())
        .all()
    )


def get_share_for_mode(
    resource_type: ResourceType,
    resource_id: int,
    mode: str,
) -> PublicShare | None:
    """Return the first enabled share for the given mode."""
    return (
        PublicShare.query.filter_by(
            resource_type=resource_type,
            resource_id=resource_id,
            mode=normalize_share_mode(mode),
            enabled=True,
        )
        .order_by(PublicShare.id.asc())
        .first()
    )


def _get_first_share_for_mode(
    resource_type: ResourceType,
    resource_id: int,
    mode: ShareMode,
) -> PublicShare | None:
    """Return the first share for mode regardless of enabled (legacy upsert)."""
    return (
        PublicShare.query.filter_by(
            resource_type=resource_type,
            resource_id=resource_id,
            mode=mode,
        )
        .order_by(PublicShare.id.asc())
        .first()
    )


def is_resource_shared(resource_type: ResourceType, resource_id: int) -> bool:
    return (
        PublicShare.query.filter_by(
            resource_type=resource_type,
            resource_id=resource_id,
            enabled=True,
        ).first()
        is not None
    )


def sync_legacy_share_flags(resource_type: ResourceType, resource: File | Folder) -> None:
    """Keep legacy File/Folder share_* (and folder dropbox_*) in sync with public_shares."""
    if resource_type in ('kanban_board', 'excalidraw_drawing'):
        return
    shares = get_shares_for_resource(resource_type, resource.id)
    active_view_edit = [s for s in shares if s.enabled and s.mode in VIEW_EDIT_MODES]

    if not active_view_edit:
        resource.share_enabled = False
        resource.share_token = None
        resource.share_password_hash = None
        resource.share_expires_at = None
        resource.share_mode = 'edit'
    else:
        resource.share_enabled = True
        primary = next((s for s in active_view_edit if s.mode == 'edit'), active_view_edit[0])
        resource.share_token = primary.token
        resource.share_password_hash = primary.password_hash
        resource.share_expires_at = primary.expires_at
        resource.share_mode = primary.mode

    if resource_type == 'folder' and isinstance(resource, Folder):
        active_dropbox = [s for s in shares if s.enabled and s.mode == 'dropbox']
        if active_dropbox:
            primary_db = active_dropbox[0]
            resource.is_dropbox = True
            resource.dropbox_token = primary_db.token
            resource.dropbox_password_hash = primary_db.password_hash
        else:
            resource.is_dropbox = False
            resource.dropbox_token = None
            resource.dropbox_password_hash = None


def share_is_expired(share: PublicShare) -> bool:
    return bool(share.expires_at and datetime.utcnow() > share.expires_at)


def share_url(share: PublicShare, *, external: bool = True) -> str:
    if share.resource_type == 'kanban_board':
        return url_for('kanban.public_share', token=share.token, _external=external)
    if share.resource_type == 'excalidraw_drawing':
        return url_for('excalidraw.public_share', token=share.token, _external=external)
    if share.mode == 'dropbox':
        return url_for('files.dropbox_upload', token=share.token, _external=external)
    return url_for('files.public_share', token=share.token, _external=external)


def log_share_access(
    share: PublicShare,
    action: str,
    request: Request | None = None,
    *,
    guest_name: str | None = None,
) -> None:
    ip_address = None
    user_agent = None
    if request is not None:
        ip_address = (
            request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
            or request.headers.get('X-Real-IP', '').strip()
            or request.remote_addr
        )
        user_agent = (request.user_agent.string or '')[:500] if request.user_agent else None

    entry = ShareAccessLog(
        public_share_id=share.id,
        action=action,
        ip_address=ip_address,
        user_agent=user_agent,
        guest_name=guest_name,
    )
    db.session.add(entry)


def get_access_logs_for_resource(
    resource_type: ResourceType,
    resource_id: int,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    shares = get_shares_for_resource(resource_type, resource_id)
    if not shares:
        return []

    share_ids = [s.id for s in shares]
    logs = (
        ShareAccessLog.query.filter(ShareAccessLog.public_share_id.in_(share_ids))
        .order_by(ShareAccessLog.accessed_at.desc())
        .limit(limit)
        .all()
    )
    share_by_id = {s.id: s for s in shares}
    result = []
    for log in logs:
        share = share_by_id.get(log.public_share_id)
        result.append(
            {
                'id': log.id,
                'action': log.action,
                'mode': share.mode if share else None,
                'label': share.label if share else None,
                'ip_address': log.ip_address,
                'guest_name': log.guest_name,
                'accessed_at': log.accessed_at.isoformat() if log.accessed_at else None,
            }
        )
    return result


def serialize_share_link(share: PublicShare) -> dict[str, Any]:
    return {
        'id': share.id,
        'mode': share.mode,
        'label': share.label,
        'enabled': share.enabled,
        'share_url': share_url(share),
        'has_password': share.password_hash is not None,
        'expires_at': share.expires_at.isoformat() if share.expires_at else None,
        'token_prefix': share.token[:8] if share.token else '',
        'is_expired': share_is_expired(share),
    }


def resolve_token_to_share_and_resource(
    token: str,
) -> tuple[PublicShare | None, File | Folder | None]:
    """Resolve token via public_shares (fallback: legacy columns on File/Folder)."""
    share = PublicShare.query.filter_by(token=token, enabled=True).first()
    if share and not share_is_expired(share):
        item = resolve_resource(share)
        if item:
            return share, item

    file_obj = File.query.filter_by(share_token=token, share_enabled=True).first()
    if file_obj:
        return None, file_obj
    folder = Folder.query.filter_by(share_token=token, share_enabled=True).first()
    if folder:
        return None, folder
    return None, None


def resolve_dropbox_folder(token: str) -> tuple[PublicShare | None, Folder | None]:
    """Resolve dropbox token via public_shares first, then legacy Folder.dropbox_token."""
    share = PublicShare.query.filter_by(token=token, mode='dropbox', enabled=True).first()
    if share and not share_is_expired(share):
        item = resolve_resource(share)
        if isinstance(item, Folder):
            return share, item

    folder = Folder.query.filter_by(dropbox_token=token, is_dropbox=True).first()
    if folder:
        return None, folder
    return None, None


def parse_expires_at(raw_value: str | None) -> datetime | None:
    if raw_value is None or not str(raw_value).strip():
        return None
    raw = str(raw_value).strip()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(f'Invalid expires_at: {raw_value}')


def _normalize_label(label: str | None) -> str | None:
    if label is None:
        return None
    cleaned = str(label).strip()
    return cleaned or None


def _password_hash_from_input(password: str) -> str | None:
    password = (password or '').strip()
    if not password:
        return None
    return generate_password_hash(password)


def create_share_link(
    resource_type: ResourceType,
    resource: File | Folder,
    mode: str,
    *,
    created_by: int,
    password: str = '',
    expires_at_raw: str = '',
    label: str | None = None,
    enabled: bool = True,
) -> PublicShare:
    """Always create a new share link (multi-link). Dropbox only for folders."""
    mode = normalize_share_mode(mode)
    if mode == 'dropbox' and resource_type != 'folder':
        raise ValueError('Dropbox shares are only allowed for folders')

    share = PublicShare(
        resource_type=resource_type,
        resource_id=resource.id,
        mode=mode,
        token=generate_unique_share_token(),
        enabled=bool(enabled),
        password_hash=_password_hash_from_input(password),
        expires_at=parse_expires_at(expires_at_raw),
        label=_normalize_label(label),
        created_by=created_by,
    )
    db.session.add(share)
    sync_legacy_share_flags(resource_type, resource)
    return share


def upsert_share_link(
    resource_type: ResourceType,
    resource: File | Folder,
    mode: str,
    *,
    created_by: int,
    password: str = '',
    expires_at_raw: str = '',
    label: str | None = None,
) -> PublicShare:
    """Legacy helper: update first share of mode, or create one."""
    mode = normalize_share_mode(mode)
    if mode == 'dropbox' and resource_type != 'folder':
        raise ValueError('Dropbox shares are only allowed for folders')

    password = (password or '').strip()
    expires_at = parse_expires_at(expires_at_raw)

    share = _get_first_share_for_mode(resource_type, resource.id, mode)
    if share:
        share.enabled = True
        if password:
            share.password_hash = generate_password_hash(password)
        share.expires_at = expires_at
        if label is not None:
            share.label = _normalize_label(label)
    else:
        share = PublicShare(
            resource_type=resource_type,
            resource_id=resource.id,
            mode=mode,
            token=generate_unique_share_token(),
            enabled=True,
            password_hash=generate_password_hash(password) if password else None,
            expires_at=expires_at,
            label=_normalize_label(label),
            created_by=created_by,
        )
        db.session.add(share)
    sync_legacy_share_flags(resource_type, resource)
    return share


def update_share_link(
    share: PublicShare,
    *,
    password: str | None = None,
    clear_password: bool = False,
    expires_at_raw: str | None = None,
    label: str | None = None,
    enabled: bool | None = None,
    regenerate_token: bool = False,
) -> PublicShare:
    if clear_password:
        share.password_hash = None
    elif password is not None and str(password).strip():
        share.password_hash = generate_password_hash(str(password).strip())

    if expires_at_raw is not None:
        share.expires_at = parse_expires_at(expires_at_raw)

    if label is not None:
        share.label = _normalize_label(label)

    if enabled is not None:
        share.enabled = bool(enabled)

    if regenerate_token:
        share.token = generate_unique_share_token()

    resource = resolve_resource(share)
    if resource is not None:
        sync_legacy_share_flags(share.resource_type, resource)
    return share


def disable_share_by_id(share_id: int) -> PublicShare | None:
    share = PublicShare.query.get(share_id)
    if not share:
        return None
    share.enabled = False
    resource = resolve_resource(share)
    if resource is not None:
        sync_legacy_share_flags(share.resource_type, resource)
    return share


def enable_share_by_id(share_id: int) -> PublicShare | None:
    share = PublicShare.query.get(share_id)
    if not share:
        return None
    share.enabled = True
    resource = resolve_resource(share)
    if resource is not None:
        sync_legacy_share_flags(share.resource_type, resource)
    return share


def delete_share_by_id(share_id: int) -> bool:
    share = PublicShare.query.get(share_id)
    if not share:
        return False
    resource_type = share.resource_type
    resource = resolve_resource(share)
    db.session.delete(share)
    if resource is not None:
        # Flush so deleted share is excluded from sync query.
        db.session.flush()
        sync_legacy_share_flags(resource_type, resource)
    return True


def disable_share_link(resource_type: ResourceType, resource: File | Folder, mode: str) -> None:
    share = get_share_for_mode(resource_type, resource.id, mode)
    if share:
        share.enabled = False
    sync_legacy_share_flags(resource_type, resource)


def get_assignable_public_shares() -> list[dict[str, Any]]:
    """Active view/edit public shares for guest assignment UI."""
    shares = (
        PublicShare.query.filter(
            PublicShare.enabled.is_(True),
            PublicShare.mode.in_(('view', 'edit')),
        )
        .order_by(PublicShare.resource_type, PublicShare.resource_id, PublicShare.mode, PublicShare.id)
        .all()
    )
    result = []
    for share in shares:
        if share_is_expired(share):
            continue
        item = resolve_resource(share)
        if not item:
            continue
        if share.resource_type == 'file':
            name = getattr(item, 'original_name', getattr(item, 'name', '?'))
        else:
            name = getattr(item, 'name', '?')
        mode_label = 'Betrachten' if share.mode == 'view' else 'Bearbeiten'
        display = share.label.strip() if share.label and share.label.strip() else f'{name} ({mode_label})'
        result.append(
            {
                'token': share.token,
                'share_type': share.resource_type,
                'mode': share.mode,
                'label': display,
                'token_prefix': share.token[:8],
            }
        )
    return result


def serialize_share_settings(
    resource_type: ResourceType,
    resource_id: int,
    name: str,
    *,
    dropbox_enabled: bool = True,
) -> dict[str, Any]:
    shares = get_shares_for_resource(resource_type, resource_id)
    links = [serialize_share_link(share) for share in shares]
    can_add_dropbox = bool(dropbox_enabled and resource_type == 'folder')
    return {
        'type': resource_type,
        'id': resource_id,
        'name': name,
        'links': links,
        'access_logs': get_access_logs_for_resource(resource_type, resource_id),
        'can_add_dropbox': can_add_dropbox,
    }
