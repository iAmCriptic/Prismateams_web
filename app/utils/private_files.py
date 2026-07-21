"""Private folders / spaces / ACL helpers for the files module."""

from datetime import datetime

from flask_login import current_user

from app import db
from app.models.file import File, Folder, ResourceACL, FolderFavorite
from app.models.settings import SystemSettings
from app.models.user import User

VALID_VIEWS = ('ablage', 'freigaben', 'public', 'trash')
PERSONAL_ROOT_NAME = 'Eigene Dateien'


def is_private_folders_enabled():
    setting = SystemSettings.query.filter_by(key='files_private_folders_enabled').first()
    return bool(setting and str(setting.value).lower() == 'true')


def normalize_view(view, private_enabled=None):
    """Normalize ?view= for the files browser.

    Private on: ablage | freigaben | public | trash (default ablage).
    Private off: public | trash only (default public); ablage/freigaben → public.
    """
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    view = (view or '').strip().lower()

    if private_enabled:
        if view not in VALID_VIEWS:
            return 'ablage'
        return view

    # Sidebar stays; private destinations are not available
    if view in ('ablage', 'freigaben'):
        return 'public'
    if view not in ('public', 'trash'):
        return 'public'
    return view


def ensure_personal_root(user_id):
    """Create or return the user's personal root folder."""
    root = Folder.query.filter_by(
        created_by=user_id,
        is_personal_root=True,
    ).first()
    if root:
        if root.deleted_at is not None:
            root.deleted_at = None
            root.deleted_by = None
            db.session.commit()
        return root

    root = Folder(
        name=PERSONAL_ROOT_NAME,
        parent_id=None,
        created_by=user_id,
        space='personal',
        is_personal_root=True,
    )
    db.session.add(root)
    db.session.commit()
    return root


def _alive_folder_query():
    return Folder.query.filter(Folder.deleted_at.is_(None))


def _alive_file_query():
    return File.query.filter(File.deleted_at.is_(None), File.is_current.is_(True))


def _folder_owned_by(folder, user_id):
    return folder and folder.created_by == user_id


def _file_owned_by(file_obj, user_id):
    return file_obj and file_obj.uploaded_by == user_id


def _acl_rows_for(resource_type, resource_id):
    return ResourceACL.query.filter_by(
        resource_type=resource_type,
        resource_id=resource_id,
    ).all()


def has_acl_access(resource_type, resource_id, user_id, need_edit=False):
    rows = _acl_rows_for(resource_type, resource_id)
    for row in rows:
        if row.grantee_user_id is None or row.grantee_user_id == user_id:
            if need_edit and row.permission != 'edit':
                continue
            return True
    return False


def folder_is_under_personal_root(folder, personal_root_id):
    node = folder
    while node:
        if node.id == personal_root_id:
            return True
        node = node.parent
    return False


def can_view_folder(folder, user, private_enabled=None):
    if not folder:
        return False
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if not private_enabled:
        return folder.deleted_at is None
    if folder.deleted_at is not None:
        return False
    if folder.is_personal_root and folder.created_by != user.id:
        return False
    if _folder_owned_by(folder, user.id):
        return True
    if has_acl_access('folder', folder.id, user.id):
        return True
    # Ancestor shared with all / user grants access to descendants
    node = folder.parent
    while node:
        if has_acl_access('folder', node.id, user.id):
            return True
        if node.space == 'public' and node.deleted_at is None and not node.is_personal_root:
            # public tree readable when private mode on
            if folder.space == 'public':
                return True
        node = node.parent
    if folder.space == 'public' and not folder.is_personal_root:
        return True
    return False


def can_view_file(file_obj, user, private_enabled=None):
    if not file_obj:
        return False
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if not private_enabled:
        return file_obj.deleted_at is None
    if file_obj.deleted_at is not None:
        return False
    if _file_owned_by(file_obj, user.id):
        return True
    if has_acl_access('file', file_obj.id, user.id):
        return True
    if file_obj.folder_id:
        folder = Folder.query.get(file_obj.folder_id)
        if folder and can_view_folder(folder, user, private_enabled=True):
            return True
    if file_obj.space == 'public':
        return True
    return False


def can_edit_folder(folder, user, private_enabled=None):
    if not folder:
        return False
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if not private_enabled:
        return True
    if folder.deleted_at is not None:
        return False
    if _folder_owned_by(folder, user.id):
        return True
    return has_acl_access('folder', folder.id, user.id, need_edit=True)


def can_edit_file(file_obj, user, private_enabled=None):
    if not file_obj:
        return False
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if not private_enabled:
        return True
    if file_obj.deleted_at is not None:
        return False
    if _file_owned_by(file_obj, user.id):
        return True
    return has_acl_access('file', file_obj.id, user.id, need_edit=True)


def resolve_default_parent_for_view(view, user_id):
    """Parent folder id for new items when creating at view root."""
    if view == 'ablage':
        return ensure_personal_root(user_id).id
    return None  # public / freigaben root → public root (parent None)


def resolve_space_for_parent(parent_folder, view):
    if parent_folder is not None:
        return parent_folder.space or 'public'
    if view == 'ablage':
        return 'personal'
    return 'public'


def list_view_contents(view, folder_id, user):
    """
    Return (current_folder, subfolders, files, breadcrumb_extra).
    breadcrumb_extra is the virtual root label for the view.
    """
    personal_root = ensure_personal_root(user.id) if view in ('ablage',) else None

    if view == 'trash':
        folders = (
            Folder.query.filter(
                Folder.deleted_at.isnot(None),
                Folder.created_by == user.id,
                Folder.is_personal_root.is_(False),
            )
            .order_by(Folder.deleted_at.desc())
            .all()
        )
        files = (
            File.query.filter(
                File.deleted_at.isnot(None),
                File.uploaded_by == user.id,
                File.is_current.is_(True),
            )
            .order_by(File.deleted_at.desc())
            .all()
        )
        return None, folders, files, 'trash'

    if view == 'freigaben' and not folder_id:
        folder_ids = {
            row.resource_id
            for row in ResourceACL.query.filter(
                ResourceACL.resource_type == 'folder',
                ResourceACL.grantee_user_id == user.id,
            ).all()
        }
        file_ids = {
            row.resource_id
            for row in ResourceACL.query.filter(
                ResourceACL.resource_type == 'file',
                ResourceACL.grantee_user_id == user.id,
            ).all()
        }
        # Also: items I shared with specific people (outgoing) — show at root as owned shared
        outgoing_folder_ids = {
            row.resource_id
            for row in ResourceACL.query.filter(
                ResourceACL.resource_type == 'folder',
                ResourceACL.created_by == user.id,
                ResourceACL.grantee_user_id.isnot(None),
            ).all()
        }
        outgoing_file_ids = {
            row.resource_id
            for row in ResourceACL.query.filter(
                ResourceACL.resource_type == 'file',
                ResourceACL.created_by == user.id,
                ResourceACL.grantee_user_id.isnot(None),
            ).all()
        }

        folders = []
        for fid in folder_ids | outgoing_folder_ids:
            folder = Folder.query.get(fid)
            if folder and folder.deleted_at is None and not folder.is_personal_root:
                if folder.created_by != user.id or fid in outgoing_folder_ids:
                    folders.append(folder)
        # Deduplicate
        seen = set()
        uniq_folders = []
        for f in folders:
            if f.id not in seen:
                seen.add(f.id)
                uniq_folders.append(f)

        files = []
        for fid in file_ids | outgoing_file_ids:
            file_obj = File.query.get(fid)
            if file_obj and file_obj.deleted_at is None and file_obj.is_current:
                if file_obj.uploaded_by != user.id or fid in outgoing_file_ids:
                    files.append(file_obj)
        seen_f = set()
        uniq_files = []
        for f in files:
            if f.id not in seen_f:
                seen_f.add(f.id)
                uniq_files.append(f)

        uniq_folders.sort(key=lambda x: x.name.lower())
        uniq_files.sort(key=lambda x: x.name.lower())
        return None, uniq_folders, uniq_files, 'freigaben'

    current_folder = None
    effective_parent_id = folder_id

    if view == 'ablage':
        if not folder_id:
            effective_parent_id = personal_root.id
            current_folder = None  # virtual root
        else:
            current_folder = Folder.query.get_or_404(folder_id)
            if not can_view_folder(current_folder, user, private_enabled=True):
                return 'forbidden', [], [], 'ablage'
            if not folder_is_under_personal_root(current_folder, personal_root.id):
                return 'forbidden', [], [], 'ablage'

    elif view == 'public':
        if folder_id:
            current_folder = Folder.query.get_or_404(folder_id)
            if not can_view_folder(current_folder, user, private_enabled=True):
                return 'forbidden', [], [], 'public'
            # Shared-with-all personal folders may appear here
        else:
            effective_parent_id = None

    elif view == 'freigaben' and folder_id:
        current_folder = Folder.query.get_or_404(folder_id)
        if not can_view_folder(current_folder, user, private_enabled=True):
            return 'forbidden', [], [], 'freigaben'
        effective_parent_id = folder_id

    # List children
    if view == 'public' and not folder_id:
        subfolders = (
            _alive_folder_query()
            .filter(
                Folder.parent_id.is_(None),
                Folder.space == 'public',
                Folder.is_personal_root.is_(False),
            )
            .order_by(Folder.name)
            .all()
        )
        # Plus folders shared with everyone (not already listed)
        share_all_folder_ids = {
            row.resource_id
            for row in ResourceACL.query.filter(
                ResourceACL.resource_type == 'folder',
                ResourceACL.grantee_user_id.is_(None),
            ).all()
        }
        existing_ids = {f.id for f in subfolders}
        for fid in share_all_folder_ids:
            if fid in existing_ids:
                continue
            folder = Folder.query.get(fid)
            if folder and folder.deleted_at is None and not folder.is_personal_root:
                if folder.parent_id is None or folder.space == 'personal':
                    subfolders.append(folder)
                    existing_ids.add(folder.id)
        subfolders.sort(key=lambda x: x.name.lower())

        files = (
            _alive_file_query()
            .filter(File.folder_id.is_(None), File.space == 'public')
            .order_by(File.name)
            .all()
        )
        share_all_file_ids = {
            row.resource_id
            for row in ResourceACL.query.filter(
                ResourceACL.resource_type == 'file',
                ResourceACL.grantee_user_id.is_(None),
            ).all()
        }
        existing_f = {f.id for f in files}
        for fid in share_all_file_ids:
            if fid in existing_f:
                continue
            file_obj = File.query.get(fid)
            if file_obj and file_obj.deleted_at is None and file_obj.is_current:
                files.append(file_obj)
                existing_f.add(file_obj.id)
        files.sort(key=lambda x: x.name.lower())
        return current_folder, subfolders, files, 'public'

    # Standard child listing for a parent
    parent_id = effective_parent_id
    subfolders = (
        _alive_folder_query()
        .filter(Folder.parent_id == parent_id, Folder.is_personal_root.is_(False))
        .order_by(Folder.name)
        .all()
    )
    files = (
        _alive_file_query()
        .filter(File.folder_id == parent_id)
        .order_by(File.name)
        .all()
    )

    if view == 'ablage':
        # Only show own personal content under ablage
        subfolders = [f for f in subfolders if f.created_by == user.id or can_view_folder(f, user)]
        files = [f for f in files if f.uploaded_by == user.id or can_view_file(f, user)]

    return current_folder, subfolders, files, view


def soft_delete_file(file_obj, user_id):
    now = datetime.utcnow()
    file_obj.deleted_at = now
    file_obj.deleted_by = user_id


def soft_delete_folder(folder, user_id):
    now = datetime.utcnow()

    def _walk(f):
        f.deleted_at = now
        f.deleted_by = user_id
        for child_file in list(f.files):
            if child_file.deleted_at is None:
                soft_delete_file(child_file, user_id)
        for child in list(f.subfolders):
            if child.deleted_at is None:
                _walk(child)

    _walk(folder)


def restore_file(file_obj):
    file_obj.deleted_at = None
    file_obj.deleted_by = None
    if file_obj.folder_id:
        parent = Folder.query.get(file_obj.folder_id)
        if parent and parent.deleted_at is not None:
            restore_folder(parent)


def restore_folder(folder):
    def _walk_up(f):
        if f.deleted_at is not None:
            f.deleted_at = None
            f.deleted_by = None
        if f.parent_id:
            parent = Folder.query.get(f.parent_id)
            if parent:
                _walk_up(parent)

    def _walk_down(f):
        f.deleted_at = None
        f.deleted_by = None
        for child_file in list(f.files):
            child_file.deleted_at = None
            child_file.deleted_by = None
        for child in list(f.subfolders):
            _walk_down(child)

    _walk_up(folder)
    _walk_down(folder)


def hard_delete_file_disk_and_db(file_obj, os_module):
    import os as _os
    paths = [file_obj.file_path] + [v.file_path for v in file_obj.versions]
    for path in paths:
        if not path:
            continue
        file_path = path if _os.path.isabs(path) else _os.path.join(_os.getcwd(), path)
        if _os.path.exists(file_path):
            try:
                _os.remove(file_path)
            except OSError:
                pass
    db.session.delete(file_obj)


def hard_delete_folder_recursive(folder, os_module):
    for file_obj in list(folder.files):
        hard_delete_file_disk_and_db(file_obj, os_module)
    for sub in list(folder.subfolders):
        hard_delete_folder_recursive(sub, os_module)
    db.session.delete(folder)


def upsert_acl(resource_type, resource_id, grantee_user_id, permission, created_by):
    permission = permission if permission in ('view', 'edit') else 'view'
    q = ResourceACL.query.filter_by(
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if grantee_user_id is None:
        q = q.filter(ResourceACL.grantee_user_id.is_(None))
    else:
        q = q.filter(ResourceACL.grantee_user_id == grantee_user_id)
    row = q.first()
    if row:
        row.permission = permission
        return row
    row = ResourceACL(
        resource_type=resource_type,
        resource_id=resource_id,
        grantee_user_id=grantee_user_id,
        permission=permission,
        created_by=created_by,
    )
    db.session.add(row)
    return row


def remove_acl(resource_type, resource_id, grantee_user_id):
    q = ResourceACL.query.filter_by(
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if grantee_user_id is None:
        q = q.filter(ResourceACL.grantee_user_id.is_(None))
    else:
        q = q.filter(ResourceACL.grantee_user_id == grantee_user_id)
    for row in q.all():
        db.session.delete(row)


def list_acl_for_resource(resource_type, resource_id):
    return (
        ResourceACL.query.filter_by(resource_type=resource_type, resource_id=resource_id)
        .order_by(ResourceACL.created_at.desc())
        .all()
    )


def serialize_acl_row(row):
    grantee_name = None
    if row.grantee_user_id:
        user = User.query.get(row.grantee_user_id)
        grantee_name = user.full_name if user else f'#{row.grantee_user_id}'
    return {
        'id': row.id,
        'resource_type': row.resource_type,
        'resource_id': row.resource_id,
        'grantee_user_id': row.grantee_user_id,
        'grantee_name': grantee_name,
        'share_all': row.grantee_user_id is None,
        'permission': row.permission,
        'created_by': row.created_by,
        'created_at': row.created_at.isoformat() if row.created_at else None,
    }


def view_url_kwargs(view, folder_id=None):
    kwargs = {}
    if view:
        kwargs['view'] = view
    if folder_id:
        return 'files.browse_folder', {**kwargs, 'folder_id': folder_id}
    return 'files.index', kwargs


FOLDER_FAVORITES_MAX = 10


def _favorite_view_for_folder(folder, user=None):
    space = (getattr(folder, 'space', None) or 'public').lower()
    if space == 'public':
        return 'public'
    if space == 'personal':
        if user is not None and _folder_owned_by(folder, user.id):
            return 'ablage'
        return 'freigaben'
    return 'public'


def serialize_folder_favorite(folder, url_for_func, user=None):
    view = _favorite_view_for_folder(folder, user=user)
    return {
        'id': folder.id,
        'name': folder.name,
        'color': folder.color,
        'space': getattr(folder, 'space', None) or 'public',
        'url': url_for_func('files.browse_folder', folder_id=folder.id, view=view),
    }


def list_folder_favorites(user, url_for_func=None):
    """Return up to FOLDER_FAVORITES_MAX visible, non-deleted folders favorited by user."""
    if not user or getattr(user, 'is_guest', False):
        return []
    rows = (
        FolderFavorite.query.filter_by(user_id=user.id)
        .order_by(FolderFavorite.created_at.asc())
        .all()
    )
    result = []
    for row in rows:
        folder = Folder.query.get(row.folder_id)
        if not folder or folder.deleted_at is not None or folder.is_personal_root:
            continue
        if not can_view_folder(folder, user):
            continue
        if url_for_func:
            result.append(serialize_folder_favorite(folder, url_for_func, user=user))
        else:
            result.append(folder)
        if len(result) >= FOLDER_FAVORITES_MAX:
            break
    return result


def is_folder_favorited(user_id, folder_id):
    return (
        FolderFavorite.query.filter_by(user_id=user_id, folder_id=folder_id).first()
        is not None
    )


def toggle_folder_favorite(user, folder_id):
    """
    Toggle favorite. Returns (ok, favorited, error_message, favorites_count).
    """
    if not user or getattr(user, 'is_guest', False):
        return False, False, 'Keine Berechtigung.', 0

    folder = Folder.query.get(folder_id)
    if not folder or folder.is_personal_root:
        return False, False, 'Ungültiger Ordner.', 0
    if folder.deleted_at is not None:
        return False, False, 'Gelöschte Ordner können nicht favorisiert werden.', 0
    if not can_view_folder(folder, user):
        return False, False, 'Kein Zugriff auf diesen Ordner.', 0

    existing = FolderFavorite.query.filter_by(user_id=user.id, folder_id=folder.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        count = FolderFavorite.query.filter_by(user_id=user.id).count()
        return True, False, None, count

    count = FolderFavorite.query.filter_by(user_id=user.id).count()
    if count >= FOLDER_FAVORITES_MAX:
        return False, False, f'Maximal {FOLDER_FAVORITES_MAX} Favoriten.', count

    db.session.add(FolderFavorite(user_id=user.id, folder_id=folder.id))
    db.session.commit()
    return True, True, None, count + 1
