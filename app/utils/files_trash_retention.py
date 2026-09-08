"""Papierkorb-Retention und automatische Endlöschung (DSGVO-Speicherfrist)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from flask import current_app

from app import db

logger = logging.getLogger(__name__)

SETTING_TRASH_DAYS = 'files_trash_retention_days'
DEFAULT_TRASH_DAYS = 30


def get_trash_retention_days() -> int:
    """Days soft-deleted files/folders stay in trash before hard purge.

    0 disables automatic purge. Prefer SystemSettings, else FILES_TRASH_DAYS env,
    else DEFAULT_TRASH_DAYS.
    """
    try:
        from app.models.settings import SystemSettings
        row = SystemSettings.query.filter_by(key=SETTING_TRASH_DAYS).first()
        if row is not None and str(row.value).strip() != '':
            return max(0, int(str(row.value).strip()))
    except Exception:
        pass
    try:
        return max(0, int(current_app.config.get('FILES_TRASH_DAYS', DEFAULT_TRASH_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_TRASH_DAYS


def set_trash_retention_days(days: int) -> None:
    from app.models.settings import SystemSettings
    days = max(0, int(days))
    row = SystemSettings.query.filter_by(key=SETTING_TRASH_DAYS).first()
    if row:
        row.value = str(days)
    else:
        db.session.add(SystemSettings(
            key=SETTING_TRASH_DAYS,
            value=str(days),
            description='Papierkorb-Aufbewahrung in Tagen (0 = kein Auto-Purge)',
        ))


def _delete_shares_and_acls(resource_type: str, resource_id: int) -> None:
    from app.models.public_share import PublicShare
    from app.models.file import ResourceACL

    PublicShare.query.filter_by(resource_type=resource_type, resource_id=resource_id).delete(
        synchronize_session=False
    )
    ResourceACL.query.filter_by(resource_type=resource_type, resource_id=resource_id).delete(
        synchronize_session=False
    )


def _cleanup_folder_tree_refs(folder) -> None:
    _delete_shares_and_acls('folder', folder.id)
    for child_file in list(folder.files):
        _delete_shares_and_acls('file', child_file.id)
    for sub in list(folder.subfolders):
        _cleanup_folder_tree_refs(sub)


def purge_expired_trash() -> dict:
    """Hard-delete soft-deleted files/folders older than retention. Returns counts."""
    from app.models.file import File, Folder
    from app.utils.private_files import hard_delete_file_disk_and_db, hard_delete_folder_recursive

    days = get_trash_retention_days()
    if days <= 0:
        return {'purged_files': 0, 'purged_folders': 0, 'disabled': True}

    cutoff = datetime.utcnow() - timedelta(days=days)
    purged_folders = 0
    purged_files = 0

    folders = (
        Folder.query.filter(Folder.deleted_at.isnot(None), Folder.deleted_at < cutoff)
        .order_by(Folder.id.asc())
        .all()
    )
    top_folders = []
    for folder in folders:
        if folder.is_personal_root or getattr(folder, 'is_team_root', False):
            continue
        parent = folder.parent
        if parent is not None and parent.deleted_at is not None:
            continue
        top_folders.append(folder)

    for folder in top_folders:
        try:
            _cleanup_folder_tree_refs(folder)
            hard_delete_folder_recursive(folder, os)
            db.session.commit()
            purged_folders += 1
        except Exception:
            db.session.rollback()
            logger.exception('Failed to purge trash folder id=%s', getattr(folder, 'id', None))

    files = (
        File.query.filter(File.deleted_at.isnot(None), File.deleted_at < cutoff)
        .order_by(File.id.asc())
        .all()
    )
    for file_obj in files:
        try:
            _delete_shares_and_acls('file', file_obj.id)
            hard_delete_file_disk_and_db(file_obj, os)
            db.session.commit()
            purged_files += 1
        except Exception:
            db.session.rollback()
            logger.exception('Failed to purge trash file id=%s', getattr(file_obj, 'id', None))

    if purged_files or purged_folders:
        logger.info(
            'Trash purge: removed %s file(s) and %s folder(s) older than %s day(s).',
            purged_files,
            purged_folders,
            days,
        )

    return {
        'purged_files': purged_files,
        'purged_folders': purged_folders,
        'disabled': False,
        'retention_days': days,
        'cutoff': cutoff.isoformat(),
    }
