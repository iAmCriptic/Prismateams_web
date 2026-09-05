"""Shared write/read helpers for the WebDAV provider."""

from __future__ import annotations

import mimetypes
import os
import shutil
from datetime import datetime

from app import db
from app.models.file import File, FileVersion, Folder
from app.utils.file_storage_limits import check_upload_allowed
from app.utils.private_files import (
    apply_space_to_folder_tree,
    can_edit_file,
    can_edit_folder,
    can_view_file,
    can_view_folder,
    hard_delete_file_disk_and_db,
    hard_delete_folder_recursive,
    is_files_spaces_enabled,
    resolve_space_for_parent,
    resolve_team_id_for_parent,
    soft_delete_file,
    soft_delete_folder,
)

MAX_FILE_VERSIONS = 3
SLASH_REPLACEMENT = '\u2044'  # fraction slash — safe as a single path segment


def path_segment_for_name(name: str) -> str:
    return (name or '').replace('/', SLASH_REPLACEMENT).replace('\\', SLASH_REPLACEMENT)


def name_from_path_segment(segment: str) -> str:
    return (segment or '').replace(SLASH_REPLACEMENT, '/')


def names_match(stored_name: str, path_segment: str) -> bool:
    if stored_name == path_segment:
        return True
    return path_segment_for_name(stored_name) == path_segment


def absolute_file_path(file_path: str | None) -> str | None:
    if not file_path:
        return None
    if os.path.isabs(file_path):
        return file_path
    return os.path.join(os.getcwd(), file_path)


def guess_mime(filename: str, fallback: str | None = None) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or fallback or 'application/octet-stream'


def find_child_folder(parent_id, name_segment: str, space_filter=None, team_id=None):
    q = Folder.query.filter(Folder.deleted_at.is_(None), Folder.is_personal_root.is_(False), Folder.is_team_root.is_(False))
    if parent_id is None:
        q = q.filter(Folder.parent_id.is_(None))
    else:
        q = q.filter(Folder.parent_id == parent_id)
    if space_filter:
        q = q.filter(Folder.space == space_filter)
    if team_id is not None:
        q = q.filter(Folder.team_id == team_id)
    for folder in q.all():
        if names_match(folder.name, name_segment):
            return folder
    return None


def find_child_file(parent_id, name_segment: str, space_filter=None, team_id=None):
    q = File.query.filter(File.deleted_at.is_(None), File.is_current.is_(True))
    if parent_id is None:
        q = q.filter(File.folder_id.is_(None))
    else:
        q = q.filter(File.folder_id == parent_id)
    if space_filter:
        q = q.filter(File.space == space_filter)
    if team_id is not None:
        q = q.filter(File.team_id == team_id)
    for file_obj in q.all():
        if names_match(file_obj.name, name_segment):
            return file_obj
    return None


def create_folder_record(name: str, parent_folder, user, view: str, team_id=None):
    if parent_folder is not None and not can_edit_folder(parent_folder, user):
        raise PermissionError('No edit permission for parent folder')

    folder_name = name_from_path_segment(name).strip()
    if not folder_name:
        raise ValueError('Empty folder name')

    space = resolve_space_for_parent(parent_folder, view)
    resolved_team_id = resolve_team_id_for_parent(parent_folder, view, team_id)
    parent_id = parent_folder.id if parent_folder else None

    existing = find_child_folder(parent_id, path_segment_for_name(folder_name), space_filter=None if parent_id else space, team_id=resolved_team_id if view == 'team' else None)
    if existing:
        raise FileExistsError(f'Folder already exists: {folder_name}')

    folder = Folder(
        name=folder_name,
        parent_id=parent_id,
        created_by=user.id,
        space=space,
        team_id=resolved_team_id,
        is_personal_root=False,
        is_team_root=False,
    )
    db.session.add(folder)
    db.session.commit()
    return folder


def _save_upload_bytes(src_path: str, original_name: str) -> tuple[str, int]:
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    safe_name = os.path.basename(original_name) or 'file'
    filename = f'{timestamp}_{safe_name}'
    dest = os.path.join('uploads', 'files', filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(src_path, dest)
    absolute = os.path.abspath(dest)
    return absolute, os.path.getsize(absolute)


def create_or_version_file(
    *,
    name: str,
    parent_folder,
    user,
    view: str,
    team_id=None,
    temp_path: str,
    content_type: str | None = None,
):
    display_name = name_from_path_segment(name).strip()
    if not display_name:
        raise ValueError('Empty file name')

    if parent_folder is not None and not can_edit_folder(parent_folder, user):
        raise PermissionError('No edit permission for parent folder')

    if not os.path.isfile(temp_path):
        raise FileNotFoundError('Upload temp file missing')

    size = os.path.getsize(temp_path)
    ok, _code, msg = check_upload_allowed(user.id, size)
    if not ok:
        raise PermissionError(msg or 'Upload not allowed')

    parent_id = parent_folder.id if parent_folder else None
    space = resolve_space_for_parent(parent_folder, view)
    resolved_team_id = resolve_team_id_for_parent(parent_folder, view, team_id)

    existing = find_child_file(
        parent_id,
        path_segment_for_name(display_name),
        space_filter=None if parent_id else space,
        team_id=resolved_team_id if view == 'team' else None,
    )

    if existing:
        if not can_edit_file(existing, user):
            raise PermissionError('No edit permission for file')
        _create_version_from_temp(existing, temp_path, user.id)
        db.session.commit()
        return existing

    absolute, file_size = _save_upload_bytes(temp_path, display_name)
    new_file = File(
        name=display_name,
        original_name=display_name,
        folder_id=parent_id,
        uploaded_by=user.id,
        file_path=absolute,
        file_size=file_size,
        mime_type=guess_mime(display_name, content_type),
        version_number=1,
        is_current=True,
        space=space or 'public',
        team_id=resolved_team_id,
    )
    db.session.add(new_file)
    db.session.commit()
    return new_file


def _create_version_from_temp(existing_file: File, temp_path: str, user_id: int):
    version_number = existing_file.version_number + 1
    old_version = FileVersion(
        file_id=existing_file.id,
        version_number=existing_file.version_number,
        file_path=os.path.abspath(existing_file.file_path),
        file_size=existing_file.file_size,
        uploaded_by=existing_file.uploaded_by,
    )
    db.session.add(old_version)

    versions = (
        FileVersion.query.filter_by(file_id=existing_file.id)
        .order_by(FileVersion.version_number.desc())
        .all()
    )
    if len(versions) >= MAX_FILE_VERSIONS:
        oldest = versions[-1]
        if oldest.file_path and os.path.exists(oldest.file_path):
            try:
                os.remove(oldest.file_path)
            except OSError:
                pass
        db.session.delete(oldest)

    absolute, file_size = _save_upload_bytes(temp_path, existing_file.name)
    existing_file.file_path = absolute
    existing_file.file_size = file_size
    existing_file.version_number = version_number
    existing_file.uploaded_by = user_id
    existing_file.updated_at = datetime.utcnow()
    return version_number


def delete_file_record(file_obj: File, user):
    if not can_edit_file(file_obj, user):
        raise PermissionError('No edit permission for file')
    if is_files_spaces_enabled():
        soft_delete_file(file_obj, user.id)
    else:
        hard_delete_file_disk_and_db(file_obj, os)
    db.session.commit()


def delete_folder_record(folder: Folder, user):
    if getattr(folder, 'is_personal_root', False) or getattr(folder, 'is_team_root', False):
        raise PermissionError('Cannot delete root folder')
    if not can_edit_folder(folder, user):
        raise PermissionError('No edit permission for folder')
    if is_files_spaces_enabled():
        soft_delete_folder(folder, user.id)
    else:
        hard_delete_folder_recursive(folder, os)
    db.session.commit()


def rename_file_record(file_obj: File, new_name: str, user):
    if not can_edit_file(file_obj, user):
        raise PermissionError('No edit permission for file')
    display = name_from_path_segment(new_name).strip()
    if not display:
        raise ValueError('Empty name')
    conflict = File.query.filter_by(
        name=display,
        folder_id=file_obj.folder_id,
        is_current=True,
    ).filter(File.deleted_at.is_(None), File.id != file_obj.id).first()
    if conflict:
        raise FileExistsError('Name conflict')
    file_obj.name = display
    file_obj.original_name = display
    db.session.commit()


def rename_folder_record(folder: Folder, new_name: str, user):
    if getattr(folder, 'is_personal_root', False) or getattr(folder, 'is_team_root', False):
        raise PermissionError('Cannot rename root folder')
    if not can_edit_folder(folder, user):
        raise PermissionError('No edit permission for folder')
    display = name_from_path_segment(new_name).strip()
    if not display:
        raise ValueError('Empty name')
    folder.name = display
    db.session.commit()


def move_file_record(file_obj: File, target_folder, user, view: str, team_id=None):
    if not can_edit_file(file_obj, user):
        raise PermissionError('No edit permission for file')
    if target_folder is not None and not can_edit_folder(target_folder, user):
        raise PermissionError('No edit permission for target')
    if target_folder is not None and not can_view_folder(target_folder, user):
        raise PermissionError('No view permission for target')

    target_id = target_folder.id if target_folder else None
    conflict = File.query.filter_by(
        name=file_obj.name,
        folder_id=target_id,
        is_current=True,
    ).filter(File.deleted_at.is_(None), File.id != file_obj.id).first()
    if conflict:
        raise FileExistsError('Name conflict')

    space = resolve_space_for_parent(target_folder, view)
    resolved_team_id = resolve_team_id_for_parent(target_folder, view, team_id)
    file_obj.folder_id = target_id
    file_obj.space = space or 'public'
    file_obj.team_id = resolved_team_id
    db.session.commit()


def move_folder_record(folder: Folder, target_folder, user, view: str, team_id=None):
    if getattr(folder, 'is_personal_root', False) or getattr(folder, 'is_team_root', False):
        raise PermissionError('Cannot move root folder')
    if not can_edit_folder(folder, user):
        raise PermissionError('No edit permission for folder')
    if target_folder is not None and not can_edit_folder(target_folder, user):
        raise PermissionError('No edit permission for target')

    # Prevent cycles
    cursor = target_folder
    while cursor is not None:
        if cursor.id == folder.id:
            raise ValueError('Cannot move folder into itself')
        cursor = Folder.query.get(cursor.parent_id) if cursor.parent_id else None

    space = resolve_space_for_parent(target_folder, view)
    resolved_team_id = resolve_team_id_for_parent(target_folder, view, team_id)
    folder.parent_id = target_folder.id if target_folder else None
    apply_space_to_folder_tree(folder, space, resolved_team_id)
    db.session.commit()


def assert_can_view_folder(folder, user):
    if folder is not None and not can_view_folder(folder, user):
        raise PermissionError('No view permission')


def assert_can_view_file(file_obj, user):
    if not can_view_file(file_obj, user):
        raise PermissionError('No view permission')
