"""Utilities for dual-link public file/folder shares."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Literal

from flask import Request, url_for

from app import db
from app.models.file import File, Folder
from app.models.public_share import PublicShare, ShareAccessLog

ResourceType = Literal['file', 'folder']
ShareMode = Literal['view', 'edit']

VALID_MODES = frozenset({'view', 'edit'})
VALID_RESOURCE_TYPES = frozenset({'file', 'folder'})


def normalize_share_mode(value: str | None) -> ShareMode:
    mode = (value or 'edit').strip().lower()
    return 'view' if mode == 'view' else 'edit'


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


def resolve_resource(share: PublicShare) -> File | Folder | None:
    if share.resource_type == 'file':
        return File.query.get(share.resource_id)
    if share.resource_type == 'folder':
        return Folder.query.get(share.resource_id)
    return None


def get_shares_for_resource(resource_type: ResourceType, resource_id: int) -> list[PublicShare]:
    return (
        PublicShare.query.filter_by(resource_type=resource_type, resource_id=resource_id)
        .order_by(PublicShare.mode)
        .all()
    )


def get_share_for_mode(resource_type: ResourceType, resource_id: int, mode: ShareMode) -> PublicShare | None:
    return PublicShare.query.filter_by(
        resource_type=resource_type,
        resource_id=resource_id,
        mode=normalize_share_mode(mode),
    ).first()


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
    """Keep legacy share_enabled on File/Folder in sync with public_shares."""
    shares = get_shares_for_resource(resource_type, resource.id)
    active = [s for s in shares if s.enabled]
    if not active:
        resource.share_enabled = False
        resource.share_token = None
        resource.share_password_hash = None
        resource.share_expires_at = None
        resource.share_mode = 'edit'
        return

    resource.share_enabled = True
    primary = next((s for s in active if s.mode == 'edit'), active[0])
    resource.share_token = primary.token
    resource.share_password_hash = primary.password_hash
    resource.share_expires_at = primary.expires_at
    resource.share_mode = primary.mode


def share_is_expired(share: PublicShare) -> bool:
    return bool(share.expires_at and datetime.utcnow() > share.expires_at)


def share_url(share: PublicShare, *, external: bool = True) -> str:
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
        ip_address = request.remote_addr
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
                'ip_address': log.ip_address,
                'guest_name': log.guest_name,
                'accessed_at': log.accessed_at.isoformat() if log.accessed_at else None,
            }
        )
    return result


def serialize_share_link(share: PublicShare) -> dict[str, Any]:
    return {
        'mode': share.mode,
        'enabled': share.enabled,
        'share_url': share_url(share),
        'has_password': share.password_hash is not None,
        'expires_at': share.expires_at.isoformat() if share.expires_at else None,
        'token_prefix': share.token[:8] if share.token else '',
    }


def resolve_token_to_share_and_resource(token: str) -> tuple[PublicShare | None, File | Folder | None]:
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


def upsert_share_link(
    resource_type: ResourceType,
    resource: File | Folder,
    mode: ShareMode,
    *,
    created_by: int,
    password: str = '',
    expires_at_raw: str = '',
) -> PublicShare:
    from werkzeug.security import generate_password_hash

    mode = normalize_share_mode(mode)
    password = (password or '').strip()
    expires_at = None
    if expires_at_raw and str(expires_at_raw).strip():
        expires_at = datetime.fromisoformat(str(expires_at_raw).strip())

    share = get_share_for_mode(resource_type, resource.id, mode)
    if share:
        share.enabled = True
        if password:
            share.password_hash = generate_password_hash(password)
        share.expires_at = expires_at
    else:
        share = PublicShare(
            resource_type=resource_type,
            resource_id=resource.id,
            mode=mode,
            token=generate_unique_share_token(),
            enabled=True,
            password_hash=generate_password_hash(password) if password else None,
            expires_at=expires_at,
            created_by=created_by,
        )
        db.session.add(share)
    sync_legacy_share_flags(resource_type, resource)
    return share


def disable_share_link(resource_type: ResourceType, resource: File | Folder, mode: ShareMode) -> None:
    share = get_share_for_mode(resource_type, resource.id, mode)
    if share:
        share.enabled = False
    sync_legacy_share_flags(resource_type, resource)


def get_assignable_public_shares() -> list[dict[str, Any]]:
    """Active public shares for guest assignment UI."""
    shares = PublicShare.query.filter_by(enabled=True).order_by(
        PublicShare.resource_type, PublicShare.resource_id, PublicShare.mode
    ).all()
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
        result.append(
            {
                'token': share.token,
                'share_type': share.resource_type,
                'mode': share.mode,
                'label': f'{name} ({mode_label})',
                'token_prefix': share.token[:8],
            }
        )
    return result


def serialize_share_settings(resource_type: ResourceType, resource_id: int, name: str) -> dict[str, Any]:
    shares = get_shares_for_resource(resource_type, resource_id)
    links = []
    for mode in ('view', 'edit'):
        share = next((s for s in shares if s.mode == mode), None)
        if share and share.enabled:
            links.append(serialize_share_link(share))
        else:
            links.append({'mode': mode, 'enabled': False, 'share_url': None, 'has_password': False, 'expires_at': None})

    return {
        'type': resource_type,
        'id': resource_id,
        'name': name,
        'links': links,
        'access_logs': get_access_logs_for_resource(resource_type, resource_id),
    }
