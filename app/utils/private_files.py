"""Private folders / spaces / ACL helpers for the files module."""

from datetime import datetime

from flask_login import current_user

from app import db
from app.models.file import File, Folder, ResourceACL, FolderFavorite
from app.models.settings import SystemSettings
from app.models.team import Team, TeamMember
from app.models.user import User

VALID_VIEWS = ('ablage', 'freigaben', 'public', 'trash', 'team')
PERSONAL_ROOT_NAME = 'Eigene Dateien'


def is_private_folders_enabled():
    setting = SystemSettings.query.filter_by(key='files_private_folders_enabled').first()
    return bool(setting and str(setting.value).lower() == 'true')


def is_team_folders_enabled():
    setting = SystemSettings.query.filter_by(key='files_team_folders_enabled').first()
    return bool(setting and str(setting.value).lower() == 'true')


def is_files_spaces_enabled():
    return is_private_folders_enabled() or is_team_folders_enabled()


def user_file_team_ids(user):
    if not user or not getattr(user, 'id', None):
        return set()
    return {m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()}


def user_file_teams(user):
    """Teams shown as file-sidebar folders (members; admins see all)."""
    if not is_team_folders_enabled() or not user or getattr(user, 'is_guest', False):
        return []
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return Team.query.order_by(Team.name).all()
    team_ids = list(user_file_team_ids(user))
    if not team_ids:
        return []
    return Team.query.filter(Team.id.in_(team_ids)).order_by(Team.name).all()


def user_may_use_file_team(user, team_id):
    if not team_id:
        return False
    try:
        team_id = int(team_id)
    except (TypeError, ValueError):
        return False
    return any(t.id == team_id for t in user_file_teams(user))


def parse_team_id(raw):
    if raw in (None, '', 'null'):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def normalize_view(view, private_enabled=None, team_enabled=None):
    """Normalize ?view= for the files browser."""
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if team_enabled is None:
        team_enabled = is_team_folders_enabled()
    view = (view or '').strip().lower()

    allowed = {'public', 'trash'}
    if private_enabled:
        allowed.update({'ablage', 'freigaben'})
    if team_enabled:
        allowed.update({'team', 'freigaben'})

    if view in allowed:
        return view
    if view == 'ablage':
        return 'public'
    if view == 'freigaben':
        return 'public'
    if view == 'team':
        return 'ablage' if private_enabled else 'public'
    if private_enabled:
        return 'ablage'
    return 'public'


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


def ensure_team_root(team_id, created_by):
    """Create or return the team's shared root folder."""
    if not team_id:
        return None
    team = Team.query.get(team_id)
    if not team:
        return None

    root = Folder.query.filter_by(team_id=team_id, is_team_root=True).first()
    if root:
        dirty = False
        if root.deleted_at is not None:
            root.deleted_at = None
            root.deleted_by = None
            dirty = True
        if root.name != team.name:
            root.name = team.name
            dirty = True
        if root.space != 'team':
            root.space = 'team'
            dirty = True
        if dirty:
            db.session.commit()
        return root

    root = Folder(
        name=team.name,
        parent_id=None,
        created_by=created_by,
        space='team',
        team_id=team_id,
        is_team_root=True,
    )
    db.session.add(root)
    db.session.commit()
    return root


def sync_team_root_name(team):
    if not team:
        return
    root = Folder.query.filter_by(team_id=team.id, is_team_root=True).first()
    if root and root.name != team.name:
        root.name = team.name


def soft_delete_team_tree(team_id, user_id):
    """Soft-delete the team's file tree and detach FKs so the team row can be removed."""
    root = Folder.query.filter_by(team_id=team_id, is_team_root=True).first()
    if root and root.deleted_at is None:
        soft_delete_folder(root, user_id)
    for folder in Folder.query.filter_by(team_id=team_id).all():
        folder.team_id = None
        if folder.is_team_root:
            folder.is_team_root = False
    for file_obj in File.query.filter_by(team_id=team_id).all():
        file_obj.team_id = None
    ResourceACL.query.filter_by(grantee_team_id=team_id).delete(synchronize_session=False)


def folder_is_under_team_root(folder, team_root_id):
    node = folder
    while node:
        if node.id == team_root_id:
            return True
        node = node.parent
    return False


def _folder_is_team_space(folder):
    return bool(folder) and (
        getattr(folder, 'is_team_root', False)
        or (getattr(folder, 'space', None) or '') == 'team'
    )


def _file_is_team_space(file_obj):
    return bool(file_obj) and (getattr(file_obj, 'space', None) or '') == 'team'


def _user_has_team_membership(user, team_id):
    if not user or not team_id:
        return False
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return True
    return team_id in user_file_team_ids(user)


def apply_space_to_folder_tree(folder, space, team_id):
    """Update space/team_id on a folder and all descendants (used by move)."""
    if not folder:
        return
    folder.space = space or 'public'
    folder.team_id = team_id
    for child_file in list(folder.files):
        child_file.space = space or 'public'
        child_file.team_id = team_id
    for child in list(folder.subfolders):
        apply_space_to_folder_tree(child, space, team_id)


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
    team_ids = None
    for row in rows:
        if need_edit and row.permission != 'edit':
            continue
        if row.grantee_user_id is None and not getattr(row, 'grantee_team_id', None):
            return True
        if row.grantee_user_id == user_id:
            return True
        team_id = getattr(row, 'grantee_team_id', None)
        if team_id:
            if team_ids is None:
                team_ids = {
                    m.team_id for m in TeamMember.query.filter_by(user_id=user_id).all()
                }
            if team_id in team_ids:
                return True
    return False


def _share_all_acl_ids(resource_type):
    return {
        row.resource_id
        for row in ResourceACL.query.filter(
            ResourceACL.resource_type == resource_type,
            ResourceACL.grantee_user_id.is_(None),
            ResourceACL.grantee_team_id.is_(None),
        ).all()
    }


def folder_is_under_personal_root(folder, personal_root_id):
    node = folder
    while node:
        if node.id == personal_root_id:
            return True
        node = node.parent
    return False


def can_view_folder(folder, user, private_enabled=None, team_enabled=None):
    if not folder:
        return False
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if team_enabled is None:
        team_enabled = is_team_folders_enabled()
    if folder.deleted_at is not None:
        return False

    if _folder_is_team_space(folder):
        if not team_enabled:
            return False
        if _user_has_team_membership(user, folder.team_id):
            return True
        if has_acl_access('folder', folder.id, user.id):
            return True
        node = folder.parent
        while node:
            if has_acl_access('folder', node.id, user.id):
                return True
            if _user_has_team_membership(user, getattr(node, 'team_id', None)):
                return True
            node = node.parent
        return False

    if not private_enabled:
        return True
    if getattr(folder, 'is_personal_root', False) and folder.created_by != user.id:
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
            if folder.space == 'public':
                return True
        node = node.parent
    if folder.space == 'public' and not folder.is_personal_root:
        return True
    return False


def can_view_file(file_obj, user, private_enabled=None, team_enabled=None):
    if not file_obj:
        return False
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if team_enabled is None:
        team_enabled = is_team_folders_enabled()
    if file_obj.deleted_at is not None:
        return False

    if _file_is_team_space(file_obj):
        if not team_enabled:
            return False
        if _user_has_team_membership(user, getattr(file_obj, 'team_id', None)):
            return True
        if has_acl_access('file', file_obj.id, user.id):
            return True
        if file_obj.folder_id:
            folder = Folder.query.get(file_obj.folder_id)
            if folder and can_view_folder(
                folder, user, private_enabled=private_enabled, team_enabled=True
            ):
                return True
        return False

    if not private_enabled:
        return True
    if _file_owned_by(file_obj, user.id):
        return True
    if has_acl_access('file', file_obj.id, user.id):
        return True
    if file_obj.folder_id:
        folder = Folder.query.get(file_obj.folder_id)
        if folder and can_view_folder(folder, user, private_enabled=True, team_enabled=team_enabled):
            return True
    if file_obj.space == 'public':
        return True
    return False


def can_edit_folder(folder, user, private_enabled=None, team_enabled=None):
    if not folder:
        return False
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if team_enabled is None:
        team_enabled = is_team_folders_enabled()
    if folder.deleted_at is not None:
        return False

    if _folder_is_team_space(folder):
        if not team_enabled:
            return False
        if _user_has_team_membership(user, folder.team_id):
            return True
        return has_acl_access('folder', folder.id, user.id, need_edit=True)

    if not private_enabled:
        return True
    if _folder_owned_by(folder, user.id):
        return True
    return has_acl_access('folder', folder.id, user.id, need_edit=True)


def can_edit_file(file_obj, user, private_enabled=None, team_enabled=None):
    if not file_obj:
        return False
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if team_enabled is None:
        team_enabled = is_team_folders_enabled()
    if file_obj.deleted_at is not None:
        return False

    if _file_is_team_space(file_obj):
        if not team_enabled:
            return False
        if _user_has_team_membership(user, getattr(file_obj, 'team_id', None)):
            return True
        return has_acl_access('file', file_obj.id, user.id, need_edit=True)

    if not private_enabled:
        return True
    if _file_owned_by(file_obj, user.id):
        return True
    return has_acl_access('file', file_obj.id, user.id, need_edit=True)


def can_manage_acl(resource, resource_type, user):
    """Who may change internal ACL: owner, admin, or team member of a team space."""
    if not resource or not user:
        return False
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return True
    if resource_type == 'file':
        if _file_owned_by(resource, user.id):
            return True
        if _file_is_team_space(resource) and _user_has_team_membership(user, getattr(resource, 'team_id', None)):
            return True
        return False
    if _folder_owned_by(resource, user.id):
        return True
    if _folder_is_team_space(resource) and _user_has_team_membership(user, resource.team_id):
        return True
    return False


def resolve_default_parent_for_view(view, user_id, team_id=None):
    """Parent folder id for new items when creating at view root."""
    if view == 'ablage':
        return ensure_personal_root(user_id).id
    if view == 'team' and team_id:
        root = ensure_team_root(team_id, user_id)
        return root.id if root else None
    return None  # public / freigaben root → public root (parent None)


def resolve_space_for_parent(parent_folder, view):
    if parent_folder is not None:
        return parent_folder.space or 'public'
    if view == 'ablage':
        return 'personal'
    if view == 'team':
        return 'team'
    return 'public'


def resolve_team_id_for_parent(parent_folder, view, team_id=None):
    if parent_folder is not None:
        return getattr(parent_folder, 'team_id', None)
    if view == 'team':
        return team_id
    return None


def list_view_contents(view, folder_id, user, team_id=None):
    """
    Return (current_folder, subfolders, files, breadcrumb_extra).
    breadcrumb_extra is the virtual root label for the view.
    """
    personal_root = ensure_personal_root(user.id) if view in ('ablage',) else None
    team_root = None
    if view == 'team':
        if not user_may_use_file_team(user, team_id):
            return 'forbidden', [], [], 'team'
        team_root = ensure_team_root(team_id, user.id)
        if not team_root:
            return 'forbidden', [], [], 'team'

    if view == 'trash':
        folders = (
            Folder.query.filter(
                Folder.deleted_at.isnot(None),
                Folder.created_by == user.id,
                Folder.is_personal_root.is_(False),
                Folder.is_team_root.is_(False),
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
        member_team_ids = list(user_file_team_ids(user))
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
        if member_team_ids:
            folder_ids |= {
                row.resource_id
                for row in ResourceACL.query.filter(
                    ResourceACL.resource_type == 'folder',
                    ResourceACL.grantee_team_id.in_(member_team_ids),
                ).all()
            }
            file_ids |= {
                row.resource_id
                for row in ResourceACL.query.filter(
                    ResourceACL.resource_type == 'file',
                    ResourceACL.grantee_team_id.in_(member_team_ids),
                ).all()
            }
        # Also: items I shared with specific people or teams (outgoing)
        outgoing_folder_ids = {
            row.resource_id
            for row in ResourceACL.query.filter(
                ResourceACL.resource_type == 'folder',
                ResourceACL.created_by == user.id,
                db.or_(
                    ResourceACL.grantee_user_id.isnot(None),
                    ResourceACL.grantee_team_id.isnot(None),
                ),
            ).all()
        }
        outgoing_file_ids = {
            row.resource_id
            for row in ResourceACL.query.filter(
                ResourceACL.resource_type == 'file',
                ResourceACL.created_by == user.id,
                db.or_(
                    ResourceACL.grantee_user_id.isnot(None),
                    ResourceACL.grantee_team_id.isnot(None),
                ),
            ).all()
        }

        folders = []
        for fid in folder_ids | outgoing_folder_ids:
            folder = Folder.query.get(fid)
            if folder and folder.deleted_at is None and not folder.is_personal_root:
                if getattr(folder, 'is_team_root', False) and folder.team_id in member_team_ids:
                    continue
                if folder.created_by != user.id or fid in outgoing_folder_ids:
                    folders.append(folder)
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

    elif view == 'team':
        if not folder_id:
            effective_parent_id = team_root.id
            current_folder = None
        else:
            current_folder = Folder.query.get_or_404(folder_id)
            if not can_view_folder(current_folder, user, team_enabled=True):
                return 'forbidden', [], [], 'team'
            if not folder_is_under_team_root(current_folder, team_root.id):
                return 'forbidden', [], [], 'team'

    elif view == 'public':
        if folder_id:
            current_folder = Folder.query.get_or_404(folder_id)
            if not can_view_folder(current_folder, user, private_enabled=True):
                return 'forbidden', [], [], 'public'
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
                Folder.is_team_root.is_(False),
            )
            .order_by(Folder.name)
            .all()
        )
        share_all_folder_ids = _share_all_acl_ids('folder')
        existing_ids = {f.id for f in subfolders}
        for fid in share_all_folder_ids:
            if fid in existing_ids:
                continue
            folder = Folder.query.get(fid)
            if folder and folder.deleted_at is None and not folder.is_personal_root:
                if getattr(folder, 'is_team_root', False) or folder.parent_id is None or folder.space == 'personal':
                    subfolders.append(folder)
                    existing_ids.add(folder.id)
        subfolders.sort(key=lambda x: x.name.lower())

        files = (
            _alive_file_query()
            .filter(File.folder_id.is_(None), File.space == 'public')
            .order_by(File.name)
            .all()
        )
        share_all_file_ids = _share_all_acl_ids('file')
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
        .filter(
            Folder.parent_id == parent_id,
            Folder.is_personal_root.is_(False),
            Folder.is_team_root.is_(False),
        )
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
        subfolders = [f for f in subfolders if f.created_by == user.id or can_view_folder(f, user)]
        files = [f for f in files if f.uploaded_by == user.id or can_view_file(f, user)]
    elif view == 'team':
        subfolders = [f for f in subfolders if can_view_folder(f, user, team_enabled=True)]
        files = [f for f in files if can_view_file(f, user, team_enabled=True)]

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


def upsert_acl(resource_type, resource_id, grantee_user_id, permission, created_by, grantee_team_id=None):
    permission = permission if permission in ('view', 'edit') else 'view'
    q = ResourceACL.query.filter_by(
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if grantee_team_id:
        q = q.filter(
            ResourceACL.grantee_team_id == grantee_team_id,
            ResourceACL.grantee_user_id.is_(None),
        )
        grantee_user_id = None
    elif grantee_user_id is None:
        q = q.filter(
            ResourceACL.grantee_user_id.is_(None),
            ResourceACL.grantee_team_id.is_(None),
        )
    else:
        q = q.filter(
            ResourceACL.grantee_user_id == grantee_user_id,
            ResourceACL.grantee_team_id.is_(None),
        )
    row = q.first()
    if row:
        row.permission = permission
        return row
    row = ResourceACL(
        resource_type=resource_type,
        resource_id=resource_id,
        grantee_user_id=grantee_user_id,
        grantee_team_id=grantee_team_id,
        permission=permission,
        created_by=created_by,
    )
    db.session.add(row)
    return row


def remove_acl(resource_type, resource_id, grantee_user_id, grantee_team_id=None):
    q = ResourceACL.query.filter_by(
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if grantee_team_id:
        q = q.filter(ResourceACL.grantee_team_id == grantee_team_id)
    elif grantee_user_id is None:
        q = q.filter(
            ResourceACL.grantee_user_id.is_(None),
            ResourceACL.grantee_team_id.is_(None),
        )
    else:
        q = q.filter(
            ResourceACL.grantee_user_id == grantee_user_id,
            ResourceACL.grantee_team_id.is_(None),
        )
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
    grantee_team_name = None
    team_id = getattr(row, 'grantee_team_id', None)
    if row.grantee_user_id:
        user = User.query.get(row.grantee_user_id)
        grantee_name = user.full_name if user else f'#{row.grantee_user_id}'
    elif team_id:
        team = Team.query.get(team_id)
        grantee_team_name = team.name if team else f'#{team_id}'
        grantee_name = grantee_team_name
    share_all = row.grantee_user_id is None and not team_id
    return {
        'id': row.id,
        'resource_type': row.resource_type,
        'resource_id': row.resource_id,
        'grantee_user_id': row.grantee_user_id,
        'grantee_team_id': team_id,
        'grantee_name': grantee_name,
        'grantee_team_name': grantee_team_name,
        'share_all': share_all,
        'permission': row.permission,
        'created_by': row.created_by,
        'created_at': row.created_at.isoformat() if row.created_at else None,
    }


def view_url_kwargs(view, folder_id=None, team_id=None):
    kwargs = {}
    if view:
        kwargs['view'] = view
    if view == 'team' and team_id:
        kwargs['team_id'] = team_id
    if folder_id:
        return 'files.browse_folder', {**kwargs, 'folder_id': folder_id}
    return 'files.index', kwargs


FOLDER_FAVORITES_MAX = 10


def _favorite_view_kwargs(folder, user=None):
    space = (getattr(folder, 'space', None) or 'public').lower()
    if space == 'team':
        kwargs = {'view': 'team'}
        if getattr(folder, 'team_id', None):
            kwargs['team_id'] = folder.team_id
        return kwargs
    if space == 'public':
        return {'view': 'public'}
    if space == 'personal':
        if user is not None and _folder_owned_by(folder, user.id):
            return {'view': 'ablage'}
        return {'view': 'freigaben'}
    return {'view': 'public'}


def serialize_folder_favorite(folder, url_for_func, user=None):
    kwargs = _favorite_view_kwargs(folder, user=user)
    return {
        'id': folder.id,
        'name': folder.name,
        'color': folder.color,
        'space': getattr(folder, 'space', None) or 'public',
        'url': url_for_func('files.browse_folder', folder_id=folder.id, **kwargs),
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
        if not folder or folder.deleted_at is not None or folder.is_personal_root or getattr(folder, 'is_team_root', False):
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
    if not folder or folder.is_personal_root or getattr(folder, 'is_team_root', False):
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
