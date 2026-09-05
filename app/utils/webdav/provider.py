"""Virtual WebDAV provider mapping Private / Public / Teams to DB folders."""

from __future__ import annotations

import hashlib
import io
import os
import tempfile

from wsgidav import util
from wsgidav.dav_error import HTTP_FORBIDDEN, HTTP_NOT_FOUND, DAVError
from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider

from app.models.file import File, Folder
from app.models.user import User
from app.utils.private_files import (
    can_edit_file,
    can_edit_folder,
    can_view_file,
    can_view_folder,
    ensure_personal_root,
    ensure_team_root,
    is_private_folders_enabled,
    is_team_folders_enabled,
    list_view_contents,
    user_file_teams,
)
from app.utils.webdav import ops

_logger = util.get_module_logger(__name__)

PRIVATE = 'Private'
PUBLIC = 'Public'
TEAMS = 'Teams'


def _as_str(value) -> str:
    """Normalize path-like values to str (WsgiDAV 4.x dropped util.to_unicode)."""
    if value is None:
        return ''
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return str(value)


def _user_from_environ(environ) -> User | None:
    user_id = environ.get('prisma.user_id')
    if not user_id:
        return None
    return User.query.get(user_id)


def _split_path(path: str) -> list[str]:
    path = _as_str(path or '/')
    parts = [p for p in path.strip('/').split('/') if p]
    return parts


class PrismaFilesProvider(DAVProvider):
    def __init__(self):
        super().__init__()

    def get_resource_inst(self, path, environ):
        path = _as_str(path or '/')
        user = _user_from_environ(environ)
        if user is None:
            return None
        parts = _split_path(path)
        if not parts:
            return RootCollection(path, environ)

        top = parts[0]
        if top == PRIVATE:
            if not is_private_folders_enabled():
                return None
            return _resolve_under_view(path, environ, user, 'ablage', parts[1:], personal=True)
        if top == PUBLIC:
            return _resolve_under_view(path, environ, user, 'public', parts[1:], personal=False)
        if top == TEAMS:
            if not is_team_folders_enabled():
                return None
            if len(parts) == 1:
                return TeamsCollection(path, environ)
            team = _find_team_by_segment(user, parts[1])
            if not team:
                return None
            return _resolve_under_view(
                path,
                environ,
                user,
                'team',
                parts[2:],
                personal=False,
                team_id=team.id,
                team_name_segment=parts[1],
            )
        return None


def _find_team_by_segment(user, segment: str):
    for team in user_file_teams(user):
        if ops.names_match(team.name, segment):
            return team
    return None


def _resolve_under_view(path, environ, user, view, rest_parts, personal=False, team_id=None, team_name_segment=None):
    if view == 'ablage':
        root = ensure_personal_root(user.id)
        parent_folder = root
        if not rest_parts:
            return SpaceRootCollection(
                path,
                environ,
                view=view,
                root_folder=root,
                team_id=None,
                display_name=PRIVATE,
            )
    elif view == 'team':
        root = ensure_team_root(team_id, user.id)
        if not root:
            return None
        parent_folder = root
        if not rest_parts:
            return SpaceRootCollection(
                path,
                environ,
                view=view,
                root_folder=root,
                team_id=team_id,
                display_name=ops.name_from_path_segment(team_name_segment or root.name),
            )
    else:  # public
        root = None
        parent_folder = None
        if not rest_parts:
            return SpaceRootCollection(
                path,
                environ,
                view=view,
                root_folder=None,
                team_id=None,
                display_name=PUBLIC,
            )

    current_folder = parent_folder
    for i, segment in enumerate(rest_parts):
        is_last = i == len(rest_parts) - 1
        parent_id = current_folder.id if current_folder is not None else None
        space_filter = 'public' if view == 'public' and parent_id is None else None
        folder = ops.find_child_folder(
            parent_id,
            segment,
            space_filter=space_filter,
            team_id=team_id if view == 'team' else None,
        )
        if folder and can_view_folder(folder, user):
            if is_last:
                return DbFolderCollection(
                    path,
                    environ,
                    folder=folder,
                    view=view,
                    team_id=team_id,
                )
            current_folder = folder
            continue

        if is_last:
            file_obj = ops.find_child_file(
                parent_id,
                segment,
                space_filter=space_filter,
                team_id=team_id if view == 'team' else None,
            )
            if file_obj and can_view_file(file_obj, user):
                return DbFileResource(
                    path,
                    environ,
                    file_obj=file_obj,
                    view=view,
                    team_id=team_id,
                )
            return None
        return None

    return None


class _BaseCollection(DAVCollection):
    def support_recursive_delete(self):
        return True

    def support_recursive_move(self, dest_path):
        return True

    def get_creation_date(self):
        return None

    def get_last_modified(self):
        return None

    def get_user(self):
        return _user_from_environ(self.environ)

    def _raise_forbidden(self, msg='Forbidden'):
        raise DAVError(HTTP_FORBIDDEN, msg)


class RootCollection(_BaseCollection):
    def get_member_names(self):
        names = [PUBLIC]
        if is_private_folders_enabled():
            names.insert(0, PRIVATE)
        if is_team_folders_enabled():
            names.append(TEAMS)
        return names

    def get_member(self, name):
        path = util.join_uri(self.path, name)
        return self.provider.get_resource_inst(path, self.environ)

    def create_empty_resource(self, name):
        self._raise_forbidden('Cannot create files at WebDAV root')

    def create_collection(self, name):
        self._raise_forbidden('Cannot create folders at WebDAV root')

    def delete(self):
        self._raise_forbidden('Cannot delete WebDAV root')


class TeamsCollection(_BaseCollection):
    def get_display_name(self):
        return TEAMS

    def get_member_names(self):
        user = self.get_user()
        if not user:
            return []
        return [ops.path_segment_for_name(t.name) for t in user_file_teams(user)]

    def get_member(self, name):
        path = util.join_uri(self.path, name)
        return self.provider.get_resource_inst(path, self.environ)

    def create_empty_resource(self, name):
        self._raise_forbidden('Cannot create files under Teams')

    def create_collection(self, name):
        self._raise_forbidden('Cannot create folders under Teams')

    def delete(self):
        self._raise_forbidden('Cannot delete Teams')


class SpaceRootCollection(_BaseCollection):
    """Virtual root for Private / Public / a team."""

    def __init__(self, path, environ, *, view, root_folder, team_id, display_name):
        super().__init__(path, environ)
        self.view = view
        self.root_folder = root_folder
        self.team_id = team_id
        self._display_name = display_name

    def get_display_name(self):
        return self._display_name

    def _list(self):
        user = self.get_user()
        result = list_view_contents(self.view, None, user, team_id=self.team_id)
        if result[0] == 'forbidden':
            return [], []
        _cur, folders, files, _extra = result
        return folders, files

    def get_member_names(self):
        folders, files = self._list()
        names = [ops.path_segment_for_name(f.name) for f in folders]
        names += [ops.path_segment_for_name(f.name) for f in files]
        return names

    def get_member(self, name):
        path = util.join_uri(self.path, name)
        return self.provider.get_resource_inst(path, self.environ)

    def create_empty_resource(self, name):
        user = self.get_user()
        parent = self.root_folder
        if parent is not None and not can_edit_folder(parent, user):
            self._raise_forbidden()
        if self.view == 'public' and parent is None:
            # Public root: anyone with module access can create when spaces rules allow
            pass
        return PendingFileResource(
            util.join_uri(self.path, name),
            self.environ,
            name=name,
            parent_folder=parent,
            view=self.view,
            team_id=self.team_id,
        )

    def create_collection(self, name):
        user = self.get_user()
        try:
            ops.create_folder_record(name, self.root_folder, user, self.view, self.team_id)
        except PermissionError as exc:
            self._raise_forbidden(str(exc))
        except (ValueError, FileExistsError) as exc:
            raise DAVError(HTTP_FORBIDDEN, str(exc)) from exc

    def delete(self):
        self._raise_forbidden('Cannot delete space root')

    def handle_move(self, dest_path):
        self._raise_forbidden('Cannot move space root')
        return True

    def handle_copy(self, dest_path, *, depth_infinity):
        self._raise_forbidden('Cannot copy space root')
        return True


class DbFolderCollection(_BaseCollection):
    def __init__(self, path, environ, *, folder: Folder, view: str, team_id=None):
        super().__init__(path, environ)
        self.folder = folder
        self.view = view
        self.team_id = team_id

    def get_display_name(self):
        return self.folder.name

    def get_creation_date(self):
        if self.folder.created_at:
            return self.folder.created_at.timestamp()
        return None

    def get_last_modified(self):
        ts = self.folder.updated_at or self.folder.created_at
        return ts.timestamp() if ts else None

    def get_member_names(self):
        user = self.get_user()
        result = list_view_contents(self.view, self.folder.id, user, team_id=self.team_id)
        if result[0] == 'forbidden':
            return []
        _cur, folders, files, _extra = result
        names = [ops.path_segment_for_name(f.name) for f in folders]
        names += [ops.path_segment_for_name(f.name) for f in files]
        return names

    def get_member(self, name):
        path = util.join_uri(self.path, name)
        return self.provider.get_resource_inst(path, self.environ)

    def create_empty_resource(self, name):
        user = self.get_user()
        if not can_edit_folder(self.folder, user):
            self._raise_forbidden()
        return PendingFileResource(
            util.join_uri(self.path, name),
            self.environ,
            name=name,
            parent_folder=self.folder,
            view=self.view,
            team_id=self.team_id,
        )

    def create_collection(self, name):
        user = self.get_user()
        try:
            ops.create_folder_record(name, self.folder, user, self.view, self.team_id)
        except PermissionError as exc:
            self._raise_forbidden(str(exc))
        except (ValueError, FileExistsError) as exc:
            raise DAVError(HTTP_FORBIDDEN, str(exc)) from exc

    def delete(self):
        user = self.get_user()
        try:
            ops.delete_folder_record(self.folder, user)
        except PermissionError as exc:
            self._raise_forbidden(str(exc))

    def handle_move(self, dest_path):
        return _handle_collection_move(self, dest_path)

    def handle_copy(self, dest_path, *, depth_infinity):
        # Shallow: refuse deep copy for v1
        raise DAVError(HTTP_FORBIDDEN, 'Copy not supported')
        return True

    def move_recursive(self, dest_path):
        return _handle_collection_move(self, dest_path)


def _handle_collection_move(coll: DbFolderCollection, dest_path: str) -> bool:
    user = coll.get_user()
    dest_path = _as_str(dest_path)
    dest_parent_path = util.get_uri_parent(dest_path)
    dest_name = util.get_uri_name(dest_path)
    dest_parent = coll.provider.get_resource_inst(dest_parent_path, coll.environ)
    if dest_parent is None or not dest_parent.is_collection:
        raise DAVError(HTTP_FORBIDDEN, 'Invalid destination')

    # Rename within same parent
    if dest_parent_path.rstrip('/') == coll.path.rsplit('/', 1)[0] or (
        isinstance(dest_parent, (SpaceRootCollection, DbFolderCollection))
        and dest_parent.path.rstrip('/') == util.get_uri_parent(coll.path).rstrip('/')
    ):
        if dest_name != ops.path_segment_for_name(coll.folder.name):
            try:
                ops.rename_folder_record(coll.folder, dest_name, user)
            except (PermissionError, ValueError, FileExistsError) as exc:
                raise DAVError(HTTP_FORBIDDEN, str(exc)) from exc
            return True

    target_folder, view, team_id = _parent_db_folder(dest_parent)
    try:
        if dest_name != ops.path_segment_for_name(coll.folder.name):
            ops.rename_folder_record(coll.folder, dest_name, user)
            coll.folder = Folder.query.get(coll.folder.id)
        ops.move_folder_record(coll.folder, target_folder, user, view, team_id)
    except (PermissionError, ValueError, FileExistsError) as exc:
        raise DAVError(HTTP_FORBIDDEN, str(exc)) from exc
    return True


def _parent_db_folder(parent_res):
    if isinstance(parent_res, SpaceRootCollection):
        return parent_res.root_folder, parent_res.view, parent_res.team_id
    if isinstance(parent_res, DbFolderCollection):
        return parent_res.folder, parent_res.view, parent_res.team_id
    raise DAVError(HTTP_FORBIDDEN, 'Invalid destination parent')


class _FileWriteMixin:
    def begin_write(self, *, content_type=None):
        self._write_content_type = content_type
        self._temp = tempfile.NamedTemporaryFile(delete=False, prefix='webdav_', suffix='.bin')
        self._temp_path = self._temp.name
        return self._temp

    def _cleanup_temp(self):
        path = getattr(self, '_temp_path', None)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        self._temp_path = None


class PendingFileResource(_FileWriteMixin, DAVNonCollection):
    """Placeholder created by MKCOL-equivalent create_empty_resource before PUT body."""

    def __init__(self, path, environ, *, name, parent_folder, view, team_id=None):
        super().__init__(path, environ)
        self.name = name
        self.parent_folder = parent_folder
        self.view = view
        self.team_id = team_id
        self._file_obj = None
        self._temp_path = None

    def get_content_length(self):
        return 0

    def get_content_type(self):
        return ops.guess_mime(ops.name_from_path_segment(self.name))

    def get_content(self):
        return io.BytesIO(b'')

    def get_etag(self):
        return hashlib.md5(self.path.encode('utf-8')).hexdigest()

    def support_etag(self):
        return True

    def end_write(self, *, with_errors):
        user = _user_from_environ(self.environ)
        if with_errors or not user:
            self._cleanup_temp()
            return
        try:
            self._file_obj = ops.create_or_version_file(
                name=self.name,
                parent_folder=self.parent_folder,
                user=user,
                view=self.view,
                team_id=self.team_id,
                temp_path=self._temp_path,
                content_type=getattr(self, '_write_content_type', None),
            )
        except (PermissionError, ValueError, FileExistsError, FileNotFoundError) as exc:
            self._cleanup_temp()
            raise DAVError(HTTP_FORBIDDEN, str(exc)) from exc
        finally:
            self._cleanup_temp()

    def delete(self):
        if self._file_obj:
            user = _user_from_environ(self.environ)
            ops.delete_file_record(self._file_obj, user)


class DbFileResource(_FileWriteMixin, DAVNonCollection):
    def __init__(self, path, environ, *, file_obj: File, view: str, team_id=None):
        super().__init__(path, environ)
        self.file_obj = file_obj
        self.view = view
        self.team_id = team_id
        self._temp_path = None

    def get_display_name(self):
        return self.file_obj.name

    def get_content_length(self):
        return int(self.file_obj.file_size or 0)

    def get_content_type(self):
        return self.file_obj.mime_type or ops.guess_mime(self.file_obj.name)

    def get_creation_date(self):
        if self.file_obj.created_at:
            return self.file_obj.created_at.timestamp()
        return None

    def get_last_modified(self):
        ts = self.file_obj.updated_at or self.file_obj.created_at
        return ts.timestamp() if ts else None

    def get_etag(self):
        raw = f'{self.file_obj.id}:{self.file_obj.version_number}:{self.file_obj.file_size}'
        return hashlib.md5(raw.encode('utf-8')).hexdigest()

    def support_etag(self):
        return True

    def support_ranges(self):
        return True

    def get_content(self):
        path = ops.absolute_file_path(self.file_obj.file_path)
        if not path or not os.path.isfile(path):
            raise DAVError(HTTP_NOT_FOUND, 'File missing on disk')
        return open(path, 'rb')

    def begin_write(self, *, content_type=None):
        user = _user_from_environ(self.environ)
        if not user or not can_edit_file(self.file_obj, user):
            raise DAVError(HTTP_FORBIDDEN, 'No edit permission')
        return super().begin_write(content_type=content_type)

    def end_write(self, *, with_errors):
        user = _user_from_environ(self.environ)
        if with_errors or not user:
            self._cleanup_temp()
            return
        parent = Folder.query.get(self.file_obj.folder_id) if self.file_obj.folder_id else None
        try:
            ops.create_or_version_file(
                name=self.file_obj.name,
                parent_folder=parent,
                user=user,
                view=self.view,
                team_id=self.team_id,
                temp_path=self._temp_path,
                content_type=getattr(self, '_write_content_type', None) or self.file_obj.mime_type,
            )
            self.file_obj = File.query.get(self.file_obj.id)
        except (PermissionError, ValueError, FileExistsError, FileNotFoundError) as exc:
            self._cleanup_temp()
            raise DAVError(HTTP_FORBIDDEN, str(exc)) from exc
        finally:
            self._cleanup_temp()

    def delete(self):
        user = _user_from_environ(self.environ)
        try:
            ops.delete_file_record(self.file_obj, user)
        except PermissionError as exc:
            raise DAVError(HTTP_FORBIDDEN, str(exc)) from exc

    def handle_move(self, dest_path):
        return _handle_file_move(self, dest_path)

    def handle_copy(self, dest_path, *, depth_infinity):
        raise DAVError(HTTP_FORBIDDEN, 'Copy not supported')
        return True

    def move_recursive(self, dest_path):
        return _handle_file_move(self, dest_path)


def _handle_file_move(res: DbFileResource, dest_path: str) -> bool:
    user = _user_from_environ(res.environ)
    dest_path = _as_str(dest_path)
    dest_parent_path = util.get_uri_parent(dest_path)
    dest_name = util.get_uri_name(dest_path)
    dest_parent = res.provider.get_resource_inst(dest_parent_path, res.environ)
    if dest_parent is None or not dest_parent.is_collection:
        raise DAVError(HTTP_FORBIDDEN, 'Invalid destination')

    same_parent = util.get_uri_parent(res.path).rstrip('/') == dest_parent_path.rstrip('/')
    try:
        if same_parent:
            if dest_name != ops.path_segment_for_name(res.file_obj.name):
                ops.rename_file_record(res.file_obj, dest_name, user)
            return True
        target_folder, view, team_id = _parent_db_folder(dest_parent)
        if dest_name != ops.path_segment_for_name(res.file_obj.name):
            ops.rename_file_record(res.file_obj, dest_name, user)
            res.file_obj = File.query.get(res.file_obj.id)
        ops.move_file_record(res.file_obj, target_folder, user, view, team_id)
    except (PermissionError, ValueError, FileExistsError) as exc:
        raise DAVError(HTTP_FORBIDDEN, str(exc)) from exc
    return True
