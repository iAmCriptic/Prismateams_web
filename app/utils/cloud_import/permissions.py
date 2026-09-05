"""Authorization for cloud-import target spaces."""

from __future__ import annotations

from typing import Any, Optional

from app.models.file import Folder
from app.utils.multi_mailboxes import can_manage_team, get_led_teams
from app.utils.private_files import (
    ensure_personal_root,
    ensure_team_root,
    is_private_folders_enabled,
    is_team_folders_enabled,
)


class CloudImportPermissionError(PermissionError):
    """Raised when the user may not import into the requested space."""


def allowed_import_spaces_for_user(user) -> list[dict[str, Any]]:
    """Return space options the user may import into (for UI)."""
    options: list[dict[str, Any]] = []
    if not user:
        return options

    if is_private_folders_enabled():
        options.append({
            'space': 'personal',
            'label_key': 'settings.cloud_import.space.personal',
            'team_id': None,
        })
    else:
        # Personal root still exists conceptually; allow personal when private folders off
        # only if we fall back — plan says every user can import to personal.
        options.append({
            'space': 'personal',
            'label_key': 'settings.cloud_import.space.personal',
            'team_id': None,
        })

    if getattr(user, 'is_admin', False):
        options.insert(0, {
            'space': 'public',
            'label_key': 'settings.cloud_import.space.public',
            'team_id': None,
        })

    if is_team_folders_enabled() or getattr(user, 'is_admin', False):
        teams = get_led_teams(user) if not getattr(user, 'is_admin', False) else None
        if getattr(user, 'is_admin', False):
            from app.models.team import Team
            teams = Team.query.order_by(Team.name).all()
        for team in teams or []:
            if can_manage_team(user, team.id):
                options.append({
                    'space': 'team',
                    'label_key': 'settings.cloud_import.space.team',
                    'team_id': team.id,
                    'team_name': team.name,
                })

    return options


def assert_can_import_to_space(user, space: str, team_id: Optional[int] = None) -> None:
    space = (space or '').strip().lower()
    if space == 'personal':
        if not user or not getattr(user, 'id', None):
            raise CloudImportPermissionError('not_authenticated')
        return

    if space == 'public':
        if not getattr(user, 'is_admin', False):
            raise CloudImportPermissionError('admin_required')
        return

    if space == 'team':
        if not team_id:
            raise CloudImportPermissionError('team_required')
        if not can_manage_team(user, int(team_id)):
            raise CloudImportPermissionError('team_forbidden')
        return

    raise CloudImportPermissionError('invalid_space')


def resolve_import_target_folder(
    user,
    space: str,
    team_id: Optional[int] = None,
    target_folder_id: Optional[int] = None,
) -> Folder:
    """Resolve and validate the destination folder for an import job."""
    assert_can_import_to_space(user, space, team_id)
    space = (space or '').strip().lower()

    if target_folder_id:
        folder = Folder.query.get(int(target_folder_id))
        if not folder or folder.deleted_at is not None:
            raise CloudImportPermissionError('folder_not_found')
        folder_space = (folder.space or 'public').lower()
        if space == 'personal':
            if folder_space != 'personal' or folder.created_by != user.id:
                raise CloudImportPermissionError('folder_forbidden')
        elif space == 'public':
            if folder_space != 'public':
                raise CloudImportPermissionError('folder_forbidden')
        elif space == 'team':
            if folder_space != 'team' or folder.team_id != int(team_id):
                raise CloudImportPermissionError('folder_forbidden')
        return folder

    if space == 'personal':
        return ensure_personal_root(user.id)
    if space == 'team':
        root = ensure_team_root(int(team_id), user.id)
        if not root:
            raise CloudImportPermissionError('team_root_missing')
        return root
    # public root: folder_id None means files/folders at public root
    # Use a sentinel: return a lightweight namespace object — callers use folder.id or None
    return _PublicRoot()


class _PublicRoot:
    """Virtual public root (no Folder row)."""

    id = None
    space = 'public'
    team_id = None
    name = ''
    deleted_at = None
