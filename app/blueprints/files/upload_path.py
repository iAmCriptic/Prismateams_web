"""Nested folder-path resolution and per-folder file-name caches for uploads."""

from werkzeug.utils import secure_filename

from app import db
from app.models.file import File, Folder
from app.utils.private_files import resolve_space_for_parent, resolve_team_id_for_parent


def child_folders_by_name(parent_id, cache):
    """Prefetch live children of one parent into ``cache[parent_id]``."""
    if parent_id not in cache:
        cache[parent_id] = {
            f.name: f
            for f in Folder.query.filter_by(parent_id=parent_id)
            .filter(Folder.deleted_at.is_(None))
            .all()
        }
    return cache[parent_id]


def current_files_by_name(folder_id, cache):
    """Prefetch current files in one folder into ``cache[folder_id]`` (name→File)."""
    if folder_id not in cache:
        query = File.query.filter_by(is_current=True)
        if folder_id is None:
            query = query.filter(File.folder_id.is_(None))
        else:
            query = query.filter_by(folder_id=folder_id)
        cache[folder_id] = {f.name: f for f in query.all()}
    return cache[folder_id]


def ensure_nested_upload_folder_path(
    root_folder_id, path_parts, files_view, team_id, created_by, children_cache=None
):
    """Walk or create nested folders for a relative upload path.

    Children of each parent are loaded once and reused across files in the same upload.
    """
    cache = children_cache if children_cache is not None else {}
    current_parent_id = root_folder_id
    parent_obj_cache = {}
    for folder_name in path_parts:
        folder_name_clean = secure_filename(folder_name)
        if not folder_name_clean:
            continue
        siblings = child_folders_by_name(current_parent_id, cache)
        existing = siblings.get(folder_name_clean)
        if existing:
            current_parent_id = existing.id
            continue
        parent_for_space = None
        if current_parent_id:
            parent_for_space = parent_obj_cache.get(current_parent_id)
            if parent_for_space is None:
                parent_for_space = Folder.query.get(current_parent_id)
                if parent_for_space:
                    parent_obj_cache[current_parent_id] = parent_for_space
        new_folder = Folder(
            name=folder_name_clean,
            parent_id=current_parent_id,
            created_by=created_by,
            space=resolve_space_for_parent(parent_for_space, files_view or "public"),
            team_id=resolve_team_id_for_parent(parent_for_space, files_view, team_id),
        )
        db.session.add(new_folder)
        db.session.flush()
        siblings[folder_name_clean] = new_folder
        cache[new_folder.id] = {}
        parent_obj_cache[new_folder.id] = new_folder
        current_parent_id = new_folder.id
    return current_parent_id


def unique_filename_among(filename, occupied_names):
    """Return a non-conflicting name given an in-memory set/dict of occupied names."""
    from app.blueprints.files.helpers import _split_filename_parts

    base, extension = _split_filename_parts(filename)
    candidate = filename
    suffix = 1
    while candidate in occupied_names:
        candidate = f"{base} ({suffix}){extension}"
        suffix += 1
    return candidate


def apply_conflict_or_create(
    *,
    file_storage,
    file_name,
    folder_id,
    conflict_strategy,
    user_id,
    files_cache,
):
    """Version / separate / skip / create for one upload into ``folder_id``.

    Returns ``(status, file_size_delta)`` where status is ``'uploaded'`` or ``'skipped'``.
    """
    from app.blueprints.files.helpers import (
        _create_new_file_version,
        _process_file_upload,
    )

    occupied = current_files_by_name(folder_id, files_cache)
    existing = occupied.get(file_name)
    if existing:
        if conflict_strategy == "version":
            _create_new_file_version(existing, file_storage, user_id)
            return "uploaded", True
        if conflict_strategy == "separate":
            unique_name = unique_filename_among(file_name, occupied)
            new_file = _process_file_upload(file_storage, unique_name, folder_id, user_id)
            occupied[unique_name] = new_file
            return "uploaded", True
        return "skipped", False

    new_file = _process_file_upload(file_storage, file_name, folder_id, user_id)
    occupied[file_name] = new_file
    return "uploaded", True
