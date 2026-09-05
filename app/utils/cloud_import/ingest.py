"""Ingest downloaded bytes into the Files module storage."""

from __future__ import annotations

import mimetypes
import os
from datetime import datetime
from typing import BinaryIO, Optional, Union

from app import db
from app.models.file import File, Folder
from app.utils.private_files import sanitize_files_item_name


def find_or_create_folder_path(
    parent_folder_id: Optional[int],
    relative_parts: list[str],
    user_id: int,
    space: str,
    team_id: Optional[int] = None,
) -> Optional[int]:
    """Ensure nested folders exist under parent; return deepest folder id."""
    current_id = parent_folder_id
    space = space or 'public'
    for raw_name in relative_parts:
        name = sanitize_files_item_name(raw_name)
        if not name:
            continue
        q = Folder.query.filter_by(
            parent_id=current_id,
            name=name,
            space=space,
        ).filter(Folder.deleted_at.is_(None))
        if space == 'team' and team_id:
            q = q.filter_by(team_id=team_id)
        elif space == 'personal':
            q = q.filter_by(created_by=user_id)
        existing = q.first()
        if existing:
            current_id = existing.id
            continue

        folder = Folder(
            name=name,
            parent_id=current_id,
            created_by=user_id,
            space=space,
            team_id=team_id if space == 'team' else None,
            is_personal_root=False,
            is_team_root=False,
        )
        db.session.add(folder)
        db.session.flush()
        current_id = folder.id
    return current_id


def file_exists_in_folder(folder_id: Optional[int], name: str) -> bool:
    name = sanitize_files_item_name(name) or name
    return File.query.filter_by(
        name=name,
        folder_id=folder_id,
        is_current=True,
    ).filter(File.deleted_at.is_(None)).first() is not None


def ingest_file_bytes(
    data: Union[bytes, BinaryIO],
    original_name: str,
    folder_id: Optional[int],
    user_id: int,
    space: str = 'public',
    team_id: Optional[int] = None,
    mime_type: Optional[str] = None,
) -> File:
    """Write bytes to disk and create a File row (same layout as upload)."""
    original_name = sanitize_files_item_name(original_name) or 'unnamed'
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f'{timestamp}_{original_name}'
    filepath = os.path.join('uploads', 'files', filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    if hasattr(data, 'read'):
        with open(filepath, 'wb') as out:
            while True:
                chunk = data.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    else:
        with open(filepath, 'wb') as out:
            out.write(data)

    absolute_filepath = os.path.abspath(filepath)

    if folder_id:
        parent = Folder.query.get(folder_id)
        if parent:
            if parent.space:
                space = parent.space
            team_id = getattr(parent, 'team_id', None)

    if not mime_type:
        mime_type = mimetypes.guess_type(original_name)[0] or 'application/octet-stream'

    new_file = File(
        name=original_name,
        original_name=original_name,
        folder_id=folder_id,
        uploaded_by=user_id,
        file_path=absolute_filepath,
        file_size=os.path.getsize(absolute_filepath),
        mime_type=mime_type,
        version_number=1,
        is_current=True,
        space=space or 'public',
        team_id=team_id,
    )
    db.session.add(new_file)
    return new_file
