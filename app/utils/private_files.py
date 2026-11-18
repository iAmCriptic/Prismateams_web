"""Private folders / spaces / ACL helpers for the files module."""

from datetime import datetime

from flask_login import current_user

from sqlalchemy.orm import joinedload

from app import db
from app.models.file import File, Folder, ResourceACL, FolderFavorite
from app.models.settings import SystemSettings
from app.models.team import Team, TeamMember
from app.models.user import User

VALID_VIEWS = ('ablage', 'freigaben', 'public', 'trash', 'team')
PERSONAL_ROOT_NAME = 'Eigene Dateien'


def sanitize_files_item_name(name):
    """
    Normalize display names for files/folders.
    Keeps characters like '/' so names such as "26/27 Förderverein" are stored and shown as entered.
    Only trims surrounding whitespace; empty/whitespace-only input becomes ''.
    """
    if name is None:
        return ''
    return str(name).strip()


def is_private_folders_enabled():
    from app.utils.module_visibility_settings import is_global_private_enabled
    return is_global_private_enabled()


def is_team_folders_enabled():
    from app.utils.module_visibility_settings import is_global_team_enabled
    return is_global_team_enabled()


def is_public_folders_enabled():
    from app.utils.module_visibility_settings import is_global_public_enabled
    return is_global_public_enabled()


def is_files_spaces_enabled():
    return is_private_folders_enabled() or is_team_folders_enabled()


def user_file_team_ids(user):
    if not user or not getattr(user, 'id', None):
        return set()
    return {m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()}


def user_file_teams(user):
    """Teams shown as file-sidebar folders (members only)."""
    from app.utils.team_module_settings import filter_teams_with_section

    if not is_team_folders_enabled() or not user or getattr(user, 'is_guest', False):
        return []
    team_ids = list(user_file_team_ids(user))
    if not team_ids:
        return []
    teams = Team.query.filter(Team.id.in_(team_ids)).order_by(Team.name).all()
    return filter_teams_with_section(teams, 'files')


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


def normalize_view(view, private_enabled=None, team_enabled=None, public_enabled=None, user=None):
    """Normalize ?view= for the files browser."""
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if team_enabled is None:
        team_enabled = is_team_folders_enabled()
    if public_enabled is None:
        public_enabled = is_public_folders_enabled()
    view = (view or '').strip().lower()

    from app.utils.nextcloud_settings import (
        can_access_nextcloud_public,
        get_files_storage_mode,
        is_nextcloud_active,
        is_nextcloud_private_enabled,
        is_portal_storage_active,
        get_nextcloud_team_mappings,
    )
    from app.utils.user_content_access import (
        user_bypasses_content_restrictions,
        user_may_access_private,
        user_may_access_public,
        user_may_access_team,
    )

    portal_active = is_portal_storage_active()
    nc_active = is_nextcloud_active()

    allow_public = public_enabled and portal_active
    allow_private = private_enabled and portal_active
    allow_team = team_enabled and portal_active
    if user and not user_bypasses_content_restrictions(user):
        allow_public = allow_public and user_may_access_public(user)
        allow_private = allow_private and user_may_access_private(user)
        allow_team = allow_team and user_may_access_team(user)

    allow_nc_private = nc_active and is_nextcloud_private_enabled() and private_enabled
    allow_nc_team = nc_active and team_enabled and bool(get_nextcloud_team_mappings())
    allow_nc_public = nc_active and can_access_nextcloud_public(user)
    if user and not user_bypasses_content_restrictions(user):
        allow_nc_private = allow_nc_private and user_may_access_private(user)
        allow_nc_team = allow_nc_team and user_may_access_team(user)

    # In pure nextcloud mode, map generic view names to nc_*
    if not portal_active and nc_active:
        if view == 'ablage':
            view = 'nc_ablage'
        elif view == 'team':
            view = 'nc_team'
        elif view == 'public':
            view = 'nc_public'

    allowed = {'trash'}
    if allow_public:
        allowed.add('public')
    if allow_private:
        allowed.update({'ablage', 'freigaben'})
    if allow_team:
        allowed.update({'team', 'freigaben'})
    if allow_nc_private:
        allowed.add('nc_ablage')
    if allow_nc_team:
        allowed.add('nc_team')
    if allow_nc_public:
        allowed.add('nc_public')

    if view in allowed:
        return view
    if allow_private:
        return 'ablage'
    if allow_team:
        return 'team'
    if allow_public:
        return 'public'
    if allow_nc_private:
        return 'nc_ablage'
    if allow_nc_team:
        return 'nc_team'
    if allow_nc_public:
        return 'nc_public'
    return 'trash'


def ensure_personal_root(user_id):
    """Create or return the user's personal root folder."""
    root = Folder.query.filter_by(
        created_by=user_id,
        is_personal_root=True,
        storage_backend='local',
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
        storage_backend='local',
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

    root = Folder.query.filter_by(team_id=team_id, is_team_root=True, storage_backend='local').first()
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


def _folder_team_id(folder):
    node = folder
    while node:
        tid = getattr(node, 'team_id', None)
        if tid:
            return tid
        node = getattr(node, 'parent', None)
    return None


def _file_team_id(file_obj):
    if not file_obj:
        return None
    tid = getattr(file_obj, 'team_id', None)
    if tid:
        return tid
    if getattr(file_obj, 'folder_id', None):
        folder = getattr(file_obj, 'folder', None) or Folder.query.get(file_obj.folder_id)
        if folder:
            return _folder_team_id(folder)
    return None


def _folder_is_team_space(folder):
    if not folder:
        return False
    if getattr(folder, 'is_team_root', False):
        return True
    if (getattr(folder, 'space', None) or '') == 'team':
        return True
    return _folder_team_id(folder) is not None


def _file_is_team_space(file_obj):
    if not file_obj:
        return False
    if (getattr(file_obj, 'space', None) or '') == 'team':
        return True
    return _file_team_id(file_obj) is not None


def _folder_is_personal_space(folder):
    if not folder:
        return False
    if getattr(folder, 'is_personal_root', False):
        return True
    if (getattr(folder, 'space', None) or '') == 'personal':
        return True
    node = getattr(folder, 'parent', None)
    while node:
        if getattr(node, 'is_personal_root', False) or (getattr(node, 'space', None) or '') == 'personal':
            return True
        node = getattr(node, 'parent', None)
    return False


def _file_is_personal_space(file_obj):
    if not file_obj:
        return False
    if (getattr(file_obj, 'space', None) or '') == 'personal':
        return True
    if getattr(file_obj, 'folder_id', None):
        folder = getattr(file_obj, 'folder', None) or Folder.query.get(file_obj.folder_id)
        if folder:
            return _folder_is_personal_space(folder)
    return False


def _user_has_team_membership(user, team_id):
    if not user or not team_id:
        return False
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


def window_folders_then_files(folder_query, file_query, offset=0, limit=48):
    """SQL window: folders first, then files. Does not load the full folder."""
    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or 48))
    folder_count = int(folder_query.order_by(None).count() or 0)
    file_count = int(file_query.order_by(None).count() or 0)
    total = folder_count + file_count
    has_more = (offset + limit) < total
    folders = []
    files = []
    fetch_files = file_query.options(joinedload(File.uploader))
    if offset < folder_count:
        take_folders = min(limit, folder_count - offset)
        folders = folder_query.offset(offset).limit(take_folders).all()
        remain = limit - len(folders)
        if remain > 0:
            files = fetch_files.offset(0).limit(remain).all()
    else:
        files = fetch_files.offset(offset - folder_count).limit(limit).all()
    return folders, files, has_more, total


def _apply_browse_window(folders, files, offset, limit, window_meta):
    """In-memory window for mixed/ACL-filtered lists. SQL paths use window_folders_then_files."""
    folders = list(folders or [])
    files = list(files or [])
    total = len(folders) + len(files)
    if limit is None:
        if window_meta is not None:
            window_meta['has_more'] = False
            window_meta['total'] = total
        return folders, files
    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or 48))
    combined = [('folder', f) for f in folders] + [('file', f) for f in files]
    window = combined[offset:offset + limit]
    out_folders = [item for kind, item in window if kind == 'folder']
    out_files = [item for kind, item in window if kind == 'file']
    if window_meta is not None:
        window_meta['has_more'] = (offset + limit) < total
        window_meta['total'] = total
    return out_folders, out_files


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

    if getattr(folder, 'storage_backend', 'local') == 'nextcloud' and (getattr(folder, 'space', '') == 'public'):
        from app.utils.nextcloud_settings import can_access_nextcloud_public
        if not can_access_nextcloud_public(user, write=False):
            return False

    from app.utils.user_content_access import (
        user_bypasses_content_restrictions,
        user_may_access_private,
        user_may_access_public,
        user_may_access_team,
    )

    if _folder_is_team_space(folder):
        if not team_enabled:
            return False
        if user and not user_bypasses_content_restrictions(user) and not user_may_access_team(user):
            return False
        team_id = _folder_team_id(folder)
        if team_id and _user_has_team_membership(user, team_id):
            return True
        if has_acl_access('folder', folder.id, user.id):
            return True
        node = folder.parent
        while node:
            if has_acl_access('folder', node.id, user.id):
                return True
            node_team = getattr(node, 'team_id', None)
            if node_team and _user_has_team_membership(user, node_team):
                return True
            node = node.parent
        return False

    is_personal = _folder_is_personal_space(folder)
    if user and not user_bypasses_content_restrictions(user):
        if is_personal and not user_may_access_private(user):
            return False
        if not is_personal and not user_may_access_public(user):
            return False

    if not is_personal:
        if not is_public_folders_enabled():
            return has_acl_access('folder', folder.id, user.id if user else None)
        return True

    if not private_enabled:
        return True
    if getattr(folder, 'is_personal_root', False) and folder.created_by != user.id:
        return False
    if _folder_owned_by(folder, user.id):
        return True
    if has_acl_access('folder', folder.id, user.id):
        return True
    node = folder.parent
    while node:
        if has_acl_access('folder', node.id, user.id):
            return True
        node = node.parent
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

    if getattr(file_obj, 'storage_backend', 'local') == 'nextcloud' and (getattr(file_obj, 'space', '') == 'public'):
        from app.utils.nextcloud_settings import can_access_nextcloud_public
        if not can_access_nextcloud_public(user, write=False):
            return False

    from app.utils.user_content_access import (
        user_bypasses_content_restrictions,
        user_may_access_private,
        user_may_access_public,
        user_may_access_team,
    )

    if _file_is_team_space(file_obj):
        if not team_enabled:
            return False
        if user and not user_bypasses_content_restrictions(user) and not user_may_access_team(user):
            return False
        team_id = _file_team_id(file_obj)
        if team_id and _user_has_team_membership(user, team_id):
            return True
        if has_acl_access('file', file_obj.id, user.id):
            return True
        if file_obj.folder_id:
            folder = getattr(file_obj, 'folder', None) or Folder.query.get(file_obj.folder_id)
            if folder and can_view_folder(
                folder, user, private_enabled=private_enabled, team_enabled=True
            ):
                return True
        return False

    is_personal = _file_is_personal_space(file_obj)
    if user and not user_bypasses_content_restrictions(user):
        if is_personal and not user_may_access_private(user):
            return False
        if not is_personal and not user_may_access_public(user):
            return False

    if not is_personal:
        if not is_public_folders_enabled():
            return has_acl_access('file', file_obj.id, user.id if user else None)
        return True

    if not private_enabled:
        return True
    if _file_owned_by(file_obj, user.id):
        return True
    if has_acl_access('file', file_obj.id, user.id):
        return True
    if file_obj.folder_id:
        folder = getattr(file_obj, 'folder', None) or Folder.query.get(file_obj.folder_id)
        if folder and can_view_folder(folder, user, private_enabled=True, team_enabled=team_enabled):
            return True
    return False


def can_edit_folder(folder, user, private_enabled=None, team_enabled=None):
    if not folder:
        return False
    if folder.deleted_at is not None:
        return False

    if getattr(folder, 'storage_backend', 'local') == 'nextcloud' and (getattr(folder, 'space', '') == 'public'):
        from app.utils.nextcloud_settings import can_access_nextcloud_public
        if not can_access_nextcloud_public(user, write=True):
            return False
    if getattr(folder, 'is_personal_root', False) and folder.created_by != getattr(user, 'id', None):
        return False
    if getattr(user, 'is_admin', False):
        return True
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if team_enabled is None:
        team_enabled = is_team_folders_enabled()

    from app.utils.user_content_access import (
        user_bypasses_content_restrictions,
        user_may_access_private,
        user_may_access_public,
        user_may_access_team,
    )

    if _folder_is_team_space(folder):
        if not team_enabled:
            return False
        if not user_bypasses_content_restrictions(user) and not user_may_access_team(user):
            return False
        team_id = _folder_team_id(folder)
        if team_id and _user_has_team_membership(user, team_id):
            return True
        node = folder.parent
        while node:
            if has_acl_access('folder', node.id, user.id, need_edit=True):
                return True
            node_team = getattr(node, 'team_id', None)
            if node_team and _user_has_team_membership(user, node_team):
                return True
            node = node.parent
        return has_acl_access('folder', folder.id, user.id, need_edit=True)

    is_personal = _folder_is_personal_space(folder)
    if not user_bypasses_content_restrictions(user):
        if is_personal and not user_may_access_private(user):
            return False
        if not is_personal and not user_may_access_public(user):
            return False

    if not is_personal:
        if not is_public_folders_enabled():
            return has_acl_access('folder', folder.id, user.id, need_edit=True)
        return True

    if not private_enabled:
        return True
    if _folder_owned_by(folder, user.id):
        return True
    return has_acl_access('folder', folder.id, user.id, need_edit=True)


def can_edit_file(file_obj, user, private_enabled=None, team_enabled=None):
    if not file_obj:
        return False
    if file_obj.deleted_at is not None:
        return False

    if getattr(file_obj, 'storage_backend', 'local') == 'nextcloud' and (getattr(file_obj, 'space', '') == 'public'):
        from app.utils.nextcloud_settings import can_access_nextcloud_public
        if not can_access_nextcloud_public(user, write=False):
            return False
    if getattr(file_obj, 'storage_backend', 'local') == 'nextcloud' and (getattr(file_obj, 'space', '') == 'public'):
        from app.utils.nextcloud_settings import can_access_nextcloud_public
        if not can_access_nextcloud_public(user, write=True):
            return False
    if getattr(user, 'is_admin', False):
        return True
    if private_enabled is None:
        private_enabled = is_private_folders_enabled()
    if team_enabled is None:
        team_enabled = is_team_folders_enabled()

    from app.utils.user_content_access import (
        user_bypasses_content_restrictions,
        user_may_access_private,
        user_may_access_public,
        user_may_access_team,
    )

    if _file_is_team_space(file_obj):
        if not team_enabled:
            return False
        if not user_bypasses_content_restrictions(user) and not user_may_access_team(user):
            return False
        team_id = _file_team_id(file_obj)
        if team_id and _user_has_team_membership(user, team_id):
            return True
        if file_obj.folder_id:
            folder = getattr(file_obj, 'folder', None) or Folder.query.get(file_obj.folder_id)
            if folder and can_edit_folder(folder, user, private_enabled=private_enabled, team_enabled=True):
                return True
        return has_acl_access('file', file_obj.id, user.id, need_edit=True)

    is_personal = _file_is_personal_space(file_obj)
    if not user_bypasses_content_restrictions(user):
        if is_personal and not user_may_access_private(user):
            return False
        if not is_personal and not user_may_access_public(user):
            return False

    if not is_personal:
        if not is_public_folders_enabled():
            return has_acl_access('file', file_obj.id, user.id, need_edit=True)
        return True

    if not private_enabled:
        return True
    if _file_owned_by(file_obj, user.id):
        return True
    return has_acl_access('file', file_obj.id, user.id, need_edit=True)


def can_manage_acl(resource, resource_type, user):
    """Who may change internal ACL: owner, admin, or team member of a team space."""
    if not resource or not user:
        return False
    if getattr(user, 'is_admin', False):
        return True
    if resource_type == 'file':
        if _file_owned_by(resource, user.id):
            return True
        if _file_is_team_space(resource):
            team_id = _file_team_id(resource)
            if team_id and _user_has_team_membership(user, team_id):
                return True
        return False
    if _folder_owned_by(resource, user.id):
        return True
    if _folder_is_team_space(resource):
        team_id = _folder_team_id(resource)
        if team_id and _user_has_team_membership(user, team_id):
            return True
    return False


def resolve_default_parent_for_view(view, user_id, team_id=None):
    """Parent folder id for new items when creating at view root."""
    if view == 'ablage':
        return ensure_personal_root(user_id).id
    if view == 'team' and team_id:
        root = ensure_team_root(team_id, user_id)
        return root.id if root else None
    if view in ('nc_ablage', 'nc_team', 'nc_public'):
        from app.models.user import User
        from app.utils.nextcloud_settings import (
            get_nextcloud_private_user_path,
            get_nextcloud_public_path,
            get_team_nextcloud_mapping,
        )
        from app.utils.nextcloud_storage import ensure_nextcloud_root_folder

        if view == 'nc_ablage':
            u = User.query.get(user_id)
            root = ensure_nextcloud_root_folder(
                space='personal',
                user_id=user_id,
                remote_path=get_nextcloud_private_user_path(u) if u else f'/Ablage/user-{user_id}',
                name='Meine Ablage',
                create_remote_if_missing=True,
            )
            return root.id
        if view == 'nc_team' and team_id:
            mapping = get_team_nextcloud_mapping(team_id)
            if not mapping:
                return None
            team_obj = Team.query.get(team_id)
            root = ensure_nextcloud_root_folder(
                space='team',
                user_id=user_id,
                remote_path=mapping['path'],
                team_id=team_id,
                name=team_obj.name if team_obj else f'Team {team_id}',
            )
            return root.id
        if view == 'nc_public':
            root = ensure_nextcloud_root_folder(
                space='public',
                user_id=user_id,
                remote_path=get_nextcloud_public_path(),
                name='Public',
            )
            return root.id
    return None  # public / freigaben root → public root (parent None)


def resolve_space_for_parent(parent_folder, view):
    if parent_folder is not None:
        return parent_folder.space or 'public'
    if view in ('ablage', 'nc_ablage'):
        return 'personal'
    if view in ('team', 'nc_team'):
        return 'team'
    return 'public'


def resolve_team_id_for_parent(parent_folder, view, team_id=None):
    if parent_folder is not None:
        return getattr(parent_folder, 'team_id', None)
    if view in ('team', 'nc_team'):
        return team_id
    return None


def _collect_descendant_folder_ids(folder_id):
    """All folder ids under folder_id (including folder_id itself)."""
    if not folder_id:
        return set()
    result = {int(folder_id)}
    queue = [int(folder_id)]
    while queue:
        parent_id = queue.pop()
        children = (
            _alive_folder_query()
            .filter(Folder.parent_id == parent_id)
            .with_entities(Folder.id)
            .all()
        )
        for (child_id,) in children:
            if child_id not in result:
                result.add(child_id)
                queue.append(child_id)
    return result


def _build_folder_children_map(folders):
    by_parent = {}
    for folder in folders:
        by_parent.setdefault(folder.parent_id, []).append(folder)
    for siblings in by_parent.values():
        siblings.sort(key=lambda f: (f.name or '').lower())
    return by_parent


def _serialize_move_folder_nodes(by_parent, parent_id, exclude_ids):
    nodes = []
    for folder in by_parent.get(parent_id, []):
        if folder.id in exclude_ids:
            continue
        nodes.append({
            'id': folder.id,
            'name': folder.name,
            'color': folder.color,
            'children': _serialize_move_folder_nodes(by_parent, folder.id, exclude_ids),
        })
    return nodes


def _build_move_folder_tree(by_parent, root_parent_id, exclude_ids):
    """
    Nested folder tree for the move picker.
    Orphan folders (parent missing/not visible) are attached at the space root
    so every reachable destination remains selectable.
    """
    tree = _serialize_move_folder_nodes(by_parent, root_parent_id, exclude_ids)
    included = set()

    def _walk(nodes):
        for node in nodes:
            included.add(node['id'])
            _walk(node.get('children') or [])

    _walk(tree)

    orphans = []
    for parent_id, folders in by_parent.items():
        if parent_id == root_parent_id:
            continue
        parent_visible = parent_id in included
        for folder in folders:
            if folder.id in exclude_ids or folder.id in included:
                continue
            if parent_visible:
                continue
            orphans.append({
                'id': folder.id,
                'name': folder.name,
                'color': folder.color,
                'children': _serialize_move_folder_nodes(by_parent, folder.id, exclude_ids),
            })
            included.add(folder.id)
            _walk(orphans[-1]['children'])

    if orphans:
        orphans.sort(key=lambda n: (n.get('name') or '').lower())
        tree.extend(orphans)
    return tree


def _folders_in_subtree(root_id):
    """Non-root folders whose ancestry includes root_id."""
    if root_id is None:
        return []
    descendant_ids = _collect_descendant_folder_ids(root_id) - {root_id}
    if not descendant_ids:
        return []
    return (
        _alive_folder_query()
        .filter(
            Folder.id.in_(descendant_ids),
            Folder.is_personal_root.is_(False),
            Folder.is_team_root.is_(False),
        )
        .all()
    )


def list_move_destinations(user, exclude_folder_id=None):
    """
    Destination spaces + folder trees for the move picker.
    exclude_folder_id: when moving a folder, hide it and its descendants.
    """
    exclude_ids = _collect_descendant_folder_ids(exclude_folder_id) if exclude_folder_id else set()
    spaces = []

    from app.utils.nextcloud_settings import (
        can_access_nextcloud_public,
        get_nextcloud_private_user_path,
        get_nextcloud_public_path,
        get_team_nextcloud_mapping,
        is_nextcloud_active,
        is_nextcloud_private_enabled,
        is_portal_storage_active,
    )
    from app.utils.user_content_access import (
        user_may_access_private,
        user_may_access_public,
        user_may_access_team,
        user_bypasses_content_restrictions,
    )
    portal_active = is_portal_storage_active()
    nc_active = is_nextcloud_active()

    if portal_active and is_private_folders_enabled():
        if user_bypasses_content_restrictions(user) or user_may_access_private(user):
            personal_root = ensure_personal_root(user.id)
            folders = [
                f for f in _folders_in_subtree(personal_root.id)
                if can_view_folder(f, user, private_enabled=True)
                or getattr(user, 'is_admin', False)
            ]
            by_parent = _build_folder_children_map(folders)
            spaces.append({
                'key': 'ablage',
                'view': 'ablage',
                'team_id': None,
                'root_folder_id': personal_root.id,
                'label': 'ablage',
                'folders': _build_move_folder_tree(by_parent, personal_root.id, exclude_ids),
            })

    if portal_active and is_team_folders_enabled():
        if user_bypasses_content_restrictions(user) or user_may_access_team(user):
            for team in user_file_teams(user):
                team_root = ensure_team_root(team.id, user.id)
                if not team_root:
                    continue
                folders = [
                    f for f in _folders_in_subtree(team_root.id)
                    if can_view_folder(f, user, team_enabled=True)
                    or getattr(user, 'is_admin', False)
                ]
                by_parent = _build_folder_children_map(folders)
                spaces.append({
                    'key': f'team-{team.id}',
                    'view': 'team',
                    'team_id': team.id,
                    'root_folder_id': team_root.id,
                    'label': team.name,
                    'color': getattr(team, 'color', None),
                    'folders': _build_move_folder_tree(by_parent, team_root.id, exclude_ids),
                })

    if portal_active and is_public_folders_enabled() and (user_bypasses_content_restrictions(user) or user_may_access_public(user)):
        public_folders = (
            _alive_folder_query()
            .filter(
                Folder.space == 'public',
                Folder.storage_backend == 'local',
                Folder.is_personal_root.is_(False),
                Folder.is_team_root.is_(False),
            )
            .all()
        )
        public_folders = [
            f for f in public_folders
            if can_view_folder(f, user) or getattr(user, 'is_admin', False)
        ]
        by_parent = _build_folder_children_map(public_folders)
        spaces.append({
            'key': 'public',
            'view': 'public',
            'team_id': None,
            'root_folder_id': None,
            'label': 'public',
            'folders': _build_move_folder_tree(by_parent, None, exclude_ids),
        })

    if nc_active:
        from app.utils.nextcloud_storage import ensure_nextcloud_root_folder
        if is_nextcloud_private_enabled() and is_private_folders_enabled() and (user_bypasses_content_restrictions(user) or user_may_access_private(user)):
            nc_personal = ensure_nextcloud_root_folder(
                space='personal',
                user_id=user.id,
                remote_path=get_nextcloud_private_user_path(user),
                name='Meine Ablage',
            )
            folders = [
                f for f in _folders_in_subtree(nc_personal.id)
                if can_view_folder(f, user, private_enabled=True) or getattr(user, 'is_admin', False)
            ]
            by_parent = _build_folder_children_map(folders)
            spaces.append({
                'key': 'nc_ablage',
                'view': 'nc_ablage',
                'team_id': None,
                'root_folder_id': nc_personal.id,
                'label': 'ablage',
                'folders': _build_move_folder_tree(by_parent, nc_personal.id, exclude_ids),
            })

        if is_team_folders_enabled() and (user_bypasses_content_restrictions(user) or user_may_access_team(user)):
            for team in user_file_teams(user):
                mapping = get_team_nextcloud_mapping(team.id)
                if not mapping:
                    continue
                nc_team_root = ensure_nextcloud_root_folder(
                    space='team',
                    user_id=user.id,
                    remote_path=mapping['path'],
                    team_id=team.id,
                    name=team.name,
                )
                folders = [
                    f for f in _folders_in_subtree(nc_team_root.id)
                    if can_view_folder(f, user, team_enabled=True) or getattr(user, 'is_admin', False)
                ]
                by_parent = _build_folder_children_map(folders)
                spaces.append({
                    'key': f'nc_team-{team.id}',
                    'view': 'nc_team',
                    'team_id': team.id,
                    'root_folder_id': nc_team_root.id,
                    'label': f'{team.name} (Nextcloud)',
                    'color': getattr(team, 'color', None),
                    'folders': _build_move_folder_tree(by_parent, nc_team_root.id, exclude_ids),
                })

        if can_access_nextcloud_public(user, write=True):
            nc_pub_root = ensure_nextcloud_root_folder(
                space='public',
                user_id=user.id,
                remote_path=get_nextcloud_public_path(),
                name='Public',
            )
            folders = [
                f for f in _folders_in_subtree(nc_pub_root.id)
                if can_view_folder(f, user) or getattr(user, 'is_admin', False)
            ]
            by_parent = _build_folder_children_map(folders)
            spaces.append({
                'key': 'nc_public',
                'view': 'nc_public',
                'team_id': None,
                'root_folder_id': nc_pub_root.id,
                'label': 'public',
                'folders': _build_move_folder_tree(by_parent, nc_pub_root.id, exclude_ids),
            })

    return spaces


def list_view_contents(view, folder_id, user, team_id=None, *, offset=0, limit=None, window_meta=None):
    """
    Return (current_folder, subfolders, files, breadcrumb_extra).
    breadcrumb_extra is the virtual root label for the view.
    If limit is set, only a window of folders-then-files is returned and
    window_meta is filled with has_more / total.
    """
    if view in ('nc_ablage', 'nc_team', 'nc_public'):
        from app.utils.nextcloud_settings import (
            can_access_nextcloud_public,
            get_nextcloud_private_user_path,
            get_nextcloud_public_path,
            get_team_nextcloud_mapping,
            is_nextcloud_private_enabled,
        )
        from app.utils.nextcloud_storage import (
            ensure_nextcloud_root_folder,
            is_nextcloud_folder,
            sync_folder_children,
        )

        nc_root = None
        if view == 'nc_ablage':
            if not is_nextcloud_private_enabled():
                return 'forbidden', [], [], view
            nc_root = ensure_nextcloud_root_folder(
                space='personal',
                user_id=user.id,
                remote_path=get_nextcloud_private_user_path(user),
                name='Meine Ablage',
                create_remote_if_missing=True,
            )
        elif view == 'nc_team':
            mapping = get_team_nextcloud_mapping(team_id)
            if not mapping or not user_may_use_file_team(user, team_id):
                return 'forbidden', [], [], view
            team_obj = Team.query.get(team_id)
            nc_root = ensure_nextcloud_root_folder(
                space='team',
                user_id=user.id,
                remote_path=mapping['path'],
                team_id=team_id,
                name=team_obj.name if team_obj else f'Team {team_id}',
            )
        elif view == 'nc_public':
            if not can_access_nextcloud_public(user, write=False):
                return 'forbidden', [], [], view
            nc_root = ensure_nextcloud_root_folder(
                space='public',
                user_id=user.id,
                remote_path=get_nextcloud_public_path(),
                name='Public',
            )

        if folder_id:
            current_folder = Folder.query.get_or_404(folder_id)
            if not is_nextcloud_folder(current_folder) or not can_view_folder(current_folder, user, private_enabled=True, team_enabled=True):
                return 'forbidden', [], [], view
            target_folder = current_folder
        else:
            current_folder = None
            target_folder = nc_root

        try:
            sync_folder_children(target_folder, user_id=user.id)
        except Exception:
            pass

        folder_q = (
            _alive_folder_query()
            .filter(
                Folder.parent_id == target_folder.id,
                Folder.storage_backend == 'nextcloud',
                Folder.is_personal_root.is_(False),
                Folder.is_team_root.is_(False),
            )
            .order_by(Folder.name)
        )
        file_q = (
            _alive_file_query()
            .filter(
                File.folder_id == target_folder.id,
                File.storage_backend == 'nextcloud',
            )
            .order_by(File.name)
        )
        if limit is not None:
            subfolders, files, has_more, total = window_folders_then_files(
                folder_q, file_q, offset, limit,
            )
            if window_meta is not None:
                window_meta['has_more'] = has_more
                window_meta['total'] = total
            return current_folder, subfolders, files, view
        return current_folder, folder_q.all(), file_q.all(), view

    personal_root = ensure_personal_root(user.id) if view in ('ablage',) else None
    team_root = None
    if view == 'team':
        if not user_may_use_file_team(user, team_id):
            return 'forbidden', [], [], 'team'
        team_root = ensure_team_root(team_id, user.id)
        if not team_root:
            return 'forbidden', [], [], 'team'

    if view == 'trash':
        folder_q = (
            Folder.query.filter(
                Folder.deleted_at.isnot(None),
                Folder.created_by == user.id,
                Folder.is_personal_root.is_(False),
                Folder.is_team_root.is_(False),
            )
            .order_by(Folder.deleted_at.desc())
        )
        file_q = (
            File.query.filter(
                File.deleted_at.isnot(None),
                File.uploaded_by == user.id,
                File.is_current.is_(True),
            )
            .order_by(File.deleted_at.desc())
        )
        if limit is not None:
            folders, files, has_more, total = window_folders_then_files(
                folder_q, file_q, offset, limit,
            )
            if window_meta is not None:
                window_meta['has_more'] = has_more
                window_meta['total'] = total
            return None, folders, files, 'trash'
        return None, folder_q.all(), file_q.all(), 'trash'

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

        all_folder_ids = folder_ids | outgoing_folder_ids
        folders = []
        if all_folder_ids:
            for folder in Folder.query.filter(
                Folder.id.in_(all_folder_ids),
                Folder.deleted_at.is_(None),
            ).all():
                if folder.is_personal_root:
                    continue
                if getattr(folder, 'is_team_root', False) and folder.team_id in member_team_ids:
                    continue
                if folder.created_by != user.id or folder.id in outgoing_folder_ids:
                    folders.append(folder)
        seen = set()
        uniq_folders = []
        for f in folders:
            if f.id not in seen:
                seen.add(f.id)
                uniq_folders.append(f)

        all_file_ids = file_ids | outgoing_file_ids
        files = []
        if all_file_ids:
            for file_obj in File.query.filter(
                File.id.in_(all_file_ids),
                File.deleted_at.is_(None),
                File.is_current.is_(True),
            ).all():
                if file_obj.uploaded_by != user.id or file_obj.id in outgoing_file_ids:
                    files.append(file_obj)
        seen_f = set()
        uniq_files = []
        for f in files:
            if f.id not in seen_f:
                seen_f.add(f.id)
                uniq_files.append(f)

        uniq_folders.sort(key=lambda x: x.name.lower())
        uniq_files.sort(key=lambda x: x.name.lower())
        uniq_folders, uniq_files = _apply_browse_window(
            uniq_folders, uniq_files, offset, limit, window_meta,
        )
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
                Folder.storage_backend == 'local',
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
            .filter(File.folder_id.is_(None), File.space == 'public', File.storage_backend == 'local')
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
        subfolders, files = _apply_browse_window(
            subfolders, files, offset, limit, window_meta,
        )
        return current_folder, subfolders, files, 'public'

    # Standard child listing for a parent
    parent_id = effective_parent_id
    folder_q = (
        _alive_folder_query()
        .filter(
            Folder.parent_id == parent_id,
            Folder.is_personal_root.is_(False),
            Folder.is_team_root.is_(False),
        )
        .order_by(Folder.name)
    )
    file_q = (
        _alive_file_query()
        .filter(File.folder_id == parent_id)
        .order_by(File.name)
    )

    if limit is not None:
        subfolders, files, has_more, total = window_folders_then_files(
            folder_q, file_q, offset, limit,
        )
        if view == 'ablage':
            subfolders = [f for f in subfolders if f.created_by == user.id or can_view_folder(f, user)]
            files = [f for f in files if f.uploaded_by == user.id or can_view_file(f, user)]
        elif view == 'team':
            subfolders = [f for f in subfolders if can_view_folder(f, user, team_enabled=True)]
            files = [f for f in files if can_view_file(f, user, team_enabled=True)]
        if window_meta is not None:
            window_meta['has_more'] = has_more
            window_meta['total'] = total
        return current_folder, subfolders, files, view

    subfolders = folder_q.all()
    files = file_q.all()

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
    if getattr(file_obj, 'storage_backend', 'local') == 'nextcloud':
        from app.utils.nextcloud_storage import delete_nextcloud_file_permanently
        delete_nextcloud_file_permanently(file_obj)
    else:
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
    try:
        from app.utils.file_thumbnails import purge_thumbnails_for_file
        purge_thumbnails_for_file(file_obj.id)
    except Exception:
        pass
    try:
        from app.utils.files_trash_retention import _delete_shares_and_acls
        _delete_shares_and_acls('file', file_obj.id)
    except Exception:
        pass
    db.session.delete(file_obj)


def hard_delete_folder_recursive(folder, os_module):
    if getattr(folder, 'storage_backend', 'local') == 'nextcloud':
        from app.utils.nextcloud_storage import delete_nextcloud_folder_permanently
        delete_nextcloud_folder_permanently(folder)
    for file_obj in list(folder.files):
        if getattr(folder, 'storage_backend', 'local') == 'nextcloud':
            # Already deleted recursively on Nextcloud via parent folder DELETE
            file_obj.remote_path = None
        hard_delete_file_disk_and_db(file_obj, os_module)
    for sub in list(folder.subfolders):
        if getattr(folder, 'storage_backend', 'local') == 'nextcloud':
            sub.remote_path = None
        hard_delete_folder_recursive(sub, os_module)
    try:
        from app.utils.files_trash_retention import _delete_shares_and_acls
        _delete_shares_and_acls('folder', folder.id)
    except Exception:
        pass
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

    if getattr(folder, 'storage_backend', 'local') == 'nextcloud' and (getattr(folder, 'space', '') == 'public'):
        from app.utils.nextcloud_settings import can_access_nextcloud_public
        if not can_access_nextcloud_public(user, write=False):
            return False, False, 'Kein Zugriff auf diesen Ordner.', 0
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
