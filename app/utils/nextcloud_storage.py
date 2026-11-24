"""Nextcloud WebDAV storage bridge, shadow-index sync, and cross-system locking."""

from __future__ import annotations

import logging
import mimetypes
import time
from datetime import datetime
from typing import Optional

from app import db
from app.models.file import File, Folder
from app.utils.cloud_import.nextcloud import NextcloudLockError, NextcloudProvider
from app.utils.integrations import get_nextcloud_credentials
from app.utils.nextcloud_settings import is_nextcloud_webdav_locks_enabled

logger = logging.getLogger(__name__)

# Short in-process TTL cache (remote_dir -> timestamp) to avoid redundant PROPFINDs
_SYNC_CACHE: dict[str, float] = {}
_SYNC_TTL_SECONDS = 5.0


def is_nextcloud_folder(folder: Folder | None) -> bool:
    return bool(folder is not None and getattr(folder, 'storage_backend', 'local') == 'nextcloud')


def is_nextcloud_file(file_obj: File | None) -> bool:
    return bool(file_obj is not None and getattr(file_obj, 'storage_backend', 'local') == 'nextcloud')


def get_portal_nextcloud_provider() -> NextcloudProvider:
    creds = get_nextcloud_credentials(include_password=True)
    return NextcloudProvider(
        server_url=creds.get('server_url') or '',
        username=creds.get('username') or '',
        app_password=creds.get('app_password') or '',
    )


def _norm_remote(path: str | None) -> str:
    return (path or '').strip('/')


def join_remote_path(base: str | None, name: str) -> str:
    b = _norm_remote(base)
    n = (name or '').strip('/')
    if not b:
        return n
    if not n:
        return b
    return f'{b}/{n}'


def invalidate_sync_cache(remote_dir: str | None = None) -> None:
    if remote_dir is None:
        _SYNC_CACHE.clear()
    else:
        _SYNC_CACHE.pop(_norm_remote(remote_dir), None)


def ensure_nextcloud_root_folder(
    *,
    space: str,
    user_id: int,
    remote_path: str,
    team_id: int | None = None,
    name: str | None = None,
    create_remote_if_missing: bool = False,
) -> Folder:
    """Find or create the DB shadow root Folder for a Nextcloud space."""
    norm = _norm_remote(remote_path)
    q = Folder.query.filter(
        Folder.storage_backend == 'nextcloud',
        Folder.space == space,
        Folder.parent_id.is_(None),
        Folder.deleted_at.is_(None),
    )
    if space == 'team' and team_id is not None:
        q = q.filter(Folder.team_id == int(team_id), Folder.is_team_root.is_(True))
    elif space == 'personal':
        q = q.filter(Folder.created_by == int(user_id), Folder.is_personal_root.is_(True))
    else:
        q = q.filter(Folder.is_personal_root.is_(False), Folder.is_team_root.is_(False), Folder.remote_path == norm)

    root = q.first()
    if root:
        if root.remote_path != norm:
            root.remote_path = norm
            db.session.flush()
        return root

    if create_remote_if_missing and norm:
        try:
            provider = get_portal_nextcloud_provider()
            provider.create_folder(norm)
        except Exception as exc:
            logger.warning('Could not ensure Nextcloud folder %s: %s', norm, exc)

    display_name = name or (norm.rsplit('/', 1)[-1] if norm else 'Nextcloud')
    root = Folder(
        name=display_name,
        parent_id=None,
        created_by=int(user_id),
        space=space,
        is_personal_root=(space == 'personal'),
        is_team_root=(space == 'team'),
        team_id=int(team_id) if (space == 'team' and team_id is not None) else None,
        storage_backend='nextcloud',
        remote_path=norm,
    )
    db.session.add(root)
    db.session.flush()
    return root


def sync_folder_children(
    parent_folder: Folder,
    *,
    user_id: int,
    force: bool = False,
) -> None:
    """Synchronize direct children of a Nextcloud-backed Folder from WebDAV PROPFIND."""
    if not parent_folder or not is_nextcloud_folder(parent_folder):
        return
    remote_dir = _norm_remote(parent_folder.remote_path)
    cache_key = f'{parent_folder.id}:{remote_dir}'
    now_ts = time.monotonic()
    if not force and (now_ts - _SYNC_CACHE.get(cache_key, 0.0)) < _SYNC_TTL_SECONDS:
        return

    provider = get_portal_nextcloud_provider()
    entries = provider.list_children(remote_dir)
    _SYNC_CACHE[cache_key] = now_ts

    existing_folders = {
        _norm_remote(f.remote_path): f
        for f in Folder.query.filter(
            Folder.parent_id == parent_folder.id,
            Folder.storage_backend == 'nextcloud',
        ).all()
        if f.remote_path is not None
    }
    existing_files = {
        _norm_remote(f.remote_path): f
        for f in File.query.filter(
            File.folder_id == parent_folder.id,
            File.storage_backend == 'nextcloud',
            File.is_current.is_(True),
        ).all()
        if f.remote_path is not None
    }

    seen_dirs: set[str] = set()
    seen_files: set[str] = set()

    for entry in entries:
        rpath = _norm_remote(entry.path or entry.id)
        if not rpath:
            continue
        if entry.is_dir:
            seen_dirs.add(rpath)
            row = existing_folders.get(rpath)
            if row is None:
                now = datetime.utcnow()
                row = Folder(
                    name=entry.name,
                    parent_id=parent_folder.id,
                    created_by=int(user_id),
                    space=parent_folder.space,
                    team_id=parent_folder.team_id,
                    storage_backend='nextcloud',
                    remote_path=rpath,
                    remote_etag=entry.etag or None,
                    remote_owner=entry.owner or None,
                    created_at=entry.created_at or now,
                    updated_at=entry.modified_at or entry.created_at or now,
                )
                db.session.add(row)
            else:
                # Keep portal trash state untouched until permanently deleted or restored
                if row.name != entry.name:
                    row.name = entry.name
                if entry.etag and row.remote_etag != entry.etag:
                    row.remote_etag = entry.etag
                if entry.owner and row.remote_owner != entry.owner:
                    row.remote_owner = entry.owner
                if entry.created_at and row.created_at != entry.created_at:
                    row.created_at = entry.created_at
                if entry.modified_at and row.updated_at != entry.modified_at:
                    row.updated_at = entry.modified_at
        else:
            seen_files.add(rpath)
            row = existing_files.get(rpath)
            mime = entry.content_type or mimetypes.guess_type(entry.name)[0] or 'application/octet-stream'
            if row is None:
                now = datetime.utcnow()
                row = File(
                    name=entry.name,
                    original_name=entry.name,
                    folder_id=parent_folder.id,
                    uploaded_by=int(user_id),
                    file_path=f'nextcloud://{rpath}',
                    file_size=int(entry.size or 0),
                    mime_type=mime,
                    version_number=1,
                    is_current=True,
                    space=parent_folder.space,
                    team_id=parent_folder.team_id,
                    storage_backend='nextcloud',
                    remote_path=rpath,
                    remote_etag=entry.etag or None,
                    remote_owner=entry.owner or None,
                    created_at=entry.created_at or now,
                    updated_at=entry.modified_at or entry.created_at or now,
                )
                db.session.add(row)
            else:
                if row.name != entry.name:
                    row.name = entry.name
                    row.original_name = entry.name
                if int(entry.size or 0) != int(row.file_size or 0):
                    row.file_size = int(entry.size or 0)
                if mime and row.mime_type != mime:
                    row.mime_type = mime
                if entry.etag and row.remote_etag != entry.etag:
                    row.remote_etag = entry.etag
                    if not entry.modified_at:
                        row.updated_at = datetime.utcnow()
                if entry.owner and row.remote_owner != entry.owner:
                    row.remote_owner = entry.owner
                if entry.created_at and row.created_at != entry.created_at:
                    row.created_at = entry.created_at
                if entry.modified_at and row.updated_at != entry.modified_at:
                    row.updated_at = entry.modified_at

    # Remove shadow rows that no longer exist on Nextcloud (and are not in portal trash)
    def _delete_shadow_folder(folder_row: Folder) -> None:
        for child_dir in list(folder_row.subfolders):
            _delete_shadow_folder(child_dir)
        db.session.delete(folder_row)

    for rpath, row in existing_folders.items():
        if rpath not in seen_dirs and row.deleted_at is None:
            _delete_shadow_folder(row)
    for rpath, row in existing_files.items():
        if rpath not in seen_files and row.deleted_at is None:
            db.session.delete(row)

    db.session.commit()


def read_file_bytes(file_obj: File) -> bytes:
    provider = get_portal_nextcloud_provider()
    return provider.download_bytes(_norm_remote(file_obj.remote_path))


def write_file_bytes(
    file_obj: File,
    data: bytes,
    *,
    content_type: str | None = None,
) -> str:
    provider = get_portal_nextcloud_provider()
    token = _active_token_for(file_obj)
    etag = provider.upload_bytes(
        _norm_remote(file_obj.remote_path),
        data,
        content_type=content_type or file_obj.mime_type,
        lock_token=token,
    )
    file_obj.file_size = len(data)
    file_obj.updated_at = datetime.utcnow()
    if etag:
        file_obj.remote_etag = etag
    db.session.commit()
    return etag


def create_nextcloud_folder(
    parent_folder: Folder,
    name: str,
    *,
    user_id: int,
) -> Folder:
    provider = get_portal_nextcloud_provider()
    rpath = join_remote_path(parent_folder.remote_path, name)
    provider.create_folder(rpath)
    invalidate_sync_cache(parent_folder.remote_path)
    folder = Folder(
        name=name,
        parent_id=parent_folder.id,
        created_by=int(user_id),
        space=parent_folder.space,
        team_id=parent_folder.team_id,
        storage_backend='nextcloud',
        remote_path=rpath,
    )
    db.session.add(folder)
    db.session.commit()
    return folder


def upload_nextcloud_file(
    parent_folder: Folder,
    filename: str,
    data: bytes,
    *,
    user_id: int,
    mime_type: str | None = None,
    existing_file: File | None = None,
) -> File:
    provider = get_portal_nextcloud_provider()
    rpath = join_remote_path(parent_folder.remote_path, filename)
    mime = mime_type or mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    token = _active_token_for(existing_file) if existing_file else None
    etag = provider.upload_bytes(rpath, data, content_type=mime, lock_token=token)
    invalidate_sync_cache(parent_folder.remote_path)

    if existing_file is not None:
        existing_file.file_size = len(data)
        existing_file.mime_type = mime
        existing_file.remote_etag = etag or existing_file.remote_etag
        existing_file.updated_at = datetime.utcnow()
        existing_file.version_number = (existing_file.version_number or 1) + 1
        db.session.commit()
        return existing_file

    file_obj = File(
        name=filename,
        original_name=filename,
        folder_id=parent_folder.id,
        uploaded_by=int(user_id),
        file_path=f'nextcloud://{rpath}',
        file_size=len(data),
        mime_type=mime,
        version_number=1,
        is_current=True,
        space=parent_folder.space,
        team_id=parent_folder.team_id,
        storage_backend='nextcloud',
        remote_path=rpath,
        remote_etag=etag or None,
    )
    db.session.add(file_obj)
    db.session.commit()
    return file_obj


def rename_nextcloud_file(file_obj: File, new_name: str) -> None:
    provider = get_portal_nextcloud_provider()
    old_path = _norm_remote(file_obj.remote_path)
    parent_dir = old_path.rsplit('/', 1)[0] if '/' in old_path else ''
    new_path = join_remote_path(parent_dir, new_name)
    if new_path != old_path:
        provider.move_entry(old_path, new_path, lock_token=_active_token_for(file_obj))
        invalidate_sync_cache(parent_dir)
    file_obj.name = new_name
    file_obj.original_name = new_name
    file_obj.remote_path = new_path
    file_obj.file_path = f'nextcloud://{new_path}'
    file_obj.updated_at = datetime.utcnow()


def rename_nextcloud_folder(folder: Folder, new_name: str) -> None:
    provider = get_portal_nextcloud_provider()
    old_path = _norm_remote(folder.remote_path)
    parent_dir = old_path.rsplit('/', 1)[0] if '/' in old_path else ''
    new_path = join_remote_path(parent_dir, new_name)
    if new_path != old_path:
        provider.move_entry(old_path, new_path)
        invalidate_sync_cache(parent_dir)
        _update_descendant_remote_paths(folder, old_path, new_path)
    folder.name = new_name
    folder.remote_path = new_path
    folder.updated_at = datetime.utcnow()


def move_nextcloud_file(file_obj: File, dest_folder: Folder) -> None:
    provider = get_portal_nextcloud_provider()
    old_path = _norm_remote(file_obj.remote_path)
    new_path = join_remote_path(dest_folder.remote_path, file_obj.name)
    if new_path != old_path:
        provider.move_entry(old_path, new_path, lock_token=_active_token_for(file_obj))
        invalidate_sync_cache(old_path.rsplit('/', 1)[0] if '/' in old_path else '')
        invalidate_sync_cache(dest_folder.remote_path)
    file_obj.folder_id = dest_folder.id
    file_obj.space = dest_folder.space
    file_obj.team_id = dest_folder.team_id
    file_obj.remote_path = new_path
    file_obj.file_path = f'nextcloud://{new_path}'
    file_obj.updated_at = datetime.utcnow()


def move_nextcloud_folder(folder: Folder, dest_folder: Folder) -> None:
    provider = get_portal_nextcloud_provider()
    old_path = _norm_remote(folder.remote_path)
    new_path = join_remote_path(dest_folder.remote_path, folder.name)
    if new_path != old_path:
        provider.move_entry(old_path, new_path)
        invalidate_sync_cache(old_path.rsplit('/', 1)[0] if '/' in old_path else '')
        invalidate_sync_cache(dest_folder.remote_path)
        _update_descendant_remote_paths(folder, old_path, new_path)
    folder.parent_id = dest_folder.id
    folder.space = dest_folder.space
    folder.team_id = dest_folder.team_id
    folder.remote_path = new_path
    folder.updated_at = datetime.utcnow()


def _update_descendant_remote_paths(folder: Folder, old_prefix: str, new_prefix: str) -> None:
    old_slash = old_prefix.rstrip('/') + '/'
    for sub in Folder.query.filter(
        Folder.storage_backend == 'nextcloud',
        Folder.remote_path.like(f'{old_slash}%'),
    ).all():
        sub.remote_path = new_prefix.rstrip('/') + '/' + sub.remote_path[len(old_slash):]
    for f in File.query.filter(
        File.storage_backend == 'nextcloud',
        File.remote_path.like(f'{old_slash}%'),
    ).all():
        new_rp = new_prefix.rstrip('/') + '/' + f.remote_path[len(old_slash):]
        f.remote_path = new_rp
        f.file_path = f'nextcloud://{new_rp}'


def delete_nextcloud_file_permanently(file_obj: File) -> None:
    if not file_obj or not file_obj.remote_path:
        return
    provider = get_portal_nextcloud_provider()
    try:
        provider.delete_entry(_norm_remote(file_obj.remote_path), lock_token=_active_token_for(file_obj))
    except NextcloudLockError:
        raise
    except Exception as exc:
        logger.warning('Failed to delete Nextcloud file %s: %s', file_obj.remote_path, exc)
    invalidate_sync_cache(_norm_remote(file_obj.remote_path).rsplit('/', 1)[0] if '/' in _norm_remote(file_obj.remote_path) else '')


def delete_nextcloud_folder_permanently(folder: Folder) -> None:
    if not folder or not folder.remote_path:
        return
    provider = get_portal_nextcloud_provider()
    try:
        provider.delete_entry(_norm_remote(folder.remote_path))
    except Exception as exc:
        logger.warning('Failed to delete Nextcloud folder %s: %s', folder.remote_path, exc)
    invalidate_sync_cache(_norm_remote(folder.remote_path).rsplit('/', 1)[0] if '/' in _norm_remote(folder.remote_path) else '')


# ---------------------------------------------------------------------------
# Cross-system WebDAV Locking
# ---------------------------------------------------------------------------

def _active_token_for(file_obj: File | None) -> Optional[str]:
    if not file_obj or not file_obj.remote_lock_token:
        return None
    if file_obj.remote_lock_expires_at and file_obj.remote_lock_expires_at <= datetime.utcnow():
        return None
    return file_obj.remote_lock_token


def acquire_nextcloud_lock(file_obj: File, owner_label: str = 'PrismaTeams') -> tuple[bool, Optional[str]]:
    """Acquire or refresh a Nextcloud WebDAV LOCK for this file."""
    if not is_nextcloud_file(file_obj) or not is_nextcloud_webdav_locks_enabled():
        return True, None
    provider = get_portal_nextcloud_provider()
    rpath = _norm_remote(file_obj.remote_path)
    existing = _active_token_for(file_obj)
    if existing:
        try:
            expires_at = provider.refresh_lock(rpath, existing, timeout_seconds=300)
            file_obj.remote_lock_expires_at = expires_at
            db.session.commit()
            return True, None
        except NextcloudLockError as exc:
            owner = exc.owner or 'einem externen Nextcloud-Nutzer'
            return False, f'Die Datei ist aktuell in Nextcloud durch {owner} gesperrt.'
        except Exception:
            # Token might have expired on server; fall through to acquire fresh lock
            file_obj.remote_lock_token = None
            file_obj.remote_lock_expires_at = None

    try:
        token, expires_at = provider.lock_resource(rpath, owner=f'PrismaTeams ({owner_label})', timeout_seconds=300)
        file_obj.remote_lock_token = token
        file_obj.remote_lock_expires_at = expires_at
        db.session.commit()
        return True, None
    except NextcloudLockError as exc:
        owner = exc.owner or 'einem externen Nextcloud-Nutzer'
        return False, f'Die Datei wird aktuell in Nextcloud von {owner} bearbeitet.'
    except Exception as exc:
        logger.warning('Could not acquire Nextcloud WebDAV lock for %s: %s', rpath, exc)
        return True, None


def refresh_nextcloud_lock(file_obj: File) -> bool:
    if not is_nextcloud_file(file_obj) or not is_nextcloud_webdav_locks_enabled():
        return True
    token = _active_token_for(file_obj)
    if not token:
        return False
    provider = get_portal_nextcloud_provider()
    try:
        expires_at = provider.refresh_lock(_norm_remote(file_obj.remote_path), token, timeout_seconds=300)
        file_obj.remote_lock_expires_at = expires_at
        db.session.commit()
        return True
    except Exception as exc:
        logger.warning('Failed to refresh Nextcloud WebDAV lock for %s: %s', file_obj.remote_path, exc)
        return False


def release_nextcloud_lock_if_unused(file_obj: File) -> None:
    """Release Nextcloud WebDAV LOCK when no portal edit sessions remain."""
    if not is_nextcloud_file(file_obj) or not file_obj.remote_lock_token:
        return
    try:
        from app.utils import file_edit_lock as file_edit_lock_util
        from app.utils.onlyoffice_presence import cleanup_stale_sessions, presence_for_file_ids

        cleanup_stale_sessions()
        oo_active = bool(presence_for_file_ids([file_obj.id]).get(file_obj.id))
        md_active = file_edit_lock_util.get_active_lock(file_obj.id) is not None
        if oo_active or md_active:
            return
    except Exception:
        pass

    token = file_obj.remote_lock_token
    file_obj.remote_lock_token = None
    file_obj.remote_lock_expires_at = None
    db.session.commit()

    if not token:
        return
    try:
        provider = get_portal_nextcloud_provider()
        provider.unlock_resource(_norm_remote(file_obj.remote_path), token)
    except Exception as exc:
        logger.warning('Failed to unlock Nextcloud resource %s: %s', file_obj.remote_path, exc)
