"""Access helpers and settings for the Kanban module."""

from __future__ import annotations

from flask import current_app

from app.models.kanban import KanbanBoard, KanbanBoardMember, KanbanCard, KanbanList
from app.models.settings import SystemSettings
from app.models.team import Team, TeamMember
from app.models.user import User
from app.utils.access_control import has_module_access
from app.utils.common import is_module_enabled

VISIBILITY_PRIVATE = 'private'
VISIBILITY_TEAM = 'team'
VISIBILITY_PUBLIC = 'public'
VALID_VISIBILITIES = frozenset({VISIBILITY_PRIVATE, VISIBILITY_TEAM, VISIBILITY_PUBLIC})

SETTING_ALLOW_PRIVATE = 'kanban_allow_private'
SETTING_ALLOW_TEAM = 'kanban_allow_team'
SETTING_ALLOW_PUBLIC = 'kanban_allow_public'


def _setting_bool(key: str, default: bool = True) -> bool:
    row = SystemSettings.query.filter_by(key=key).first()
    if row is None:
        return default
    return str(row.value).lower() in ('true', '1', 'yes', 'on')


def is_kanban_module_enabled() -> bool:
    return is_module_enabled('module_kanban')


def get_allowed_visibilities() -> list[str]:
    """Board types that may be created / openly discovered."""
    from app.utils.module_visibility_settings import (
        is_global_private_enabled,
        is_global_public_enabled,
        is_global_team_enabled,
    )

    allowed = []
    if is_global_private_enabled() and _setting_bool(SETTING_ALLOW_PRIVATE, True):
        allowed.append(VISIBILITY_PRIVATE)
    if is_global_team_enabled() and _setting_bool(SETTING_ALLOW_TEAM, True):
        allowed.append(VISIBILITY_TEAM)
    if is_global_public_enabled() and _setting_bool(SETTING_ALLOW_PUBLIC, True):
        allowed.append(VISIBILITY_PUBLIC)
    return allowed or [VISIBILITY_PRIVATE]


def visibility_allowed(visibility: str) -> bool:
    return visibility in get_allowed_visibilities()


class KanbanImportPermissionError(PermissionError):
    """Raised when the user may not import a board into the requested visibility."""


def assert_can_import_board_visibility(user, visibility: str, team_id: int | None = None) -> None:
    """Import rights: private=self, team=team leader, public=admin (and visibility must be enabled)."""
    if not user or not getattr(user, 'id', None):
        raise KanbanImportPermissionError('not_authenticated')

    visibility = (visibility or '').strip().lower()
    if visibility not in VALID_VISIBILITIES:
        raise KanbanImportPermissionError('invalid_visibility')
    if not visibility_allowed(visibility):
        raise KanbanImportPermissionError('visibility_not_allowed')

    if visibility == VISIBILITY_PRIVATE:
        return

    if visibility == VISIBILITY_PUBLIC:
        if not getattr(user, 'is_admin', False):
            raise KanbanImportPermissionError('admin_required')
        return

    # team
    if not team_id:
        raise KanbanImportPermissionError('team_required')
    from app.utils.multi_mailboxes import can_manage_team

    if not can_manage_team(user, int(team_id)):
        raise KanbanImportPermissionError('team_forbidden')


def allowed_import_board_targets(user) -> list[dict]:
    """Space options the user may import a board into (for UI)."""
    options: list[dict] = []
    if not user or not getattr(user, 'id', None):
        return options

    allowed = set(get_allowed_visibilities())

    if VISIBILITY_PRIVATE in allowed:
        options.append({
            'visibility': VISIBILITY_PRIVATE,
            'team_id': None,
            'label_key': 'kanban.index.vis_private',
        })

    if VISIBILITY_PUBLIC in allowed and getattr(user, 'is_admin', False):
        options.insert(0, {
            'visibility': VISIBILITY_PUBLIC,
            'team_id': None,
            'label_key': 'kanban.index.vis_public',
        })

    if VISIBILITY_TEAM in allowed:
        from app.utils.multi_mailboxes import can_manage_team, get_led_teams

        if getattr(user, 'is_admin', False):
            teams = Team.query.order_by(Team.name).all()
        else:
            teams = get_led_teams(user)
        for team in teams or []:
            if can_manage_team(user, team.id):
                options.append({
                    'visibility': VISIBILITY_TEAM,
                    'team_id': team.id,
                    'team_name': team.name,
                    'label_key': 'kanban.index.vis_team',
                })

    return options


def user_team_ids(user) -> set[int]:
    if not user or not getattr(user, 'id', None):
        return set()
    return {m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()}


def get_board_membership(board: KanbanBoard, user) -> KanbanBoardMember | None:
    if not board or not user:
        return None
    return KanbanBoardMember.query.filter_by(board_id=board.id, user_id=user.id).first()


def _team_member_user_ids(team: Team | None) -> set[int]:
    if not team:
        return set()
    ids = {m.user_id for m in TeamMember.query.filter_by(team_id=team.id).all()}
    if team.leader_id:
        ids.add(team.leader_id)
    return ids


def _kanban_eligible_user_ids() -> set[int]:
    """Active users who may use the Kanban module."""
    return {
        user.id
        for user in User.query.filter_by(is_active=True).all()
        if has_module_access(user, 'module_kanban')
    }


def get_board_member_roles(board: KanbanBoard) -> dict[int, str]:
    """User id -> role for everyone shown as a board member in the UI."""
    explicit = {m.user_id: m.role for m in (board.members or []) if m.user_id}

    if board.visibility == VISIBILITY_PRIVATE:
        candidate_ids = set(explicit)
        if board.created_by:
            candidate_ids.add(board.created_by)
    elif board.visibility == VISIBILITY_TEAM and board.team_id:
        team = board.team or Team.query.get(board.team_id)
        candidate_ids = _team_member_user_ids(team)
        candidate_ids.update(explicit)
        if board.created_by:
            candidate_ids.add(board.created_by)
        candidate_ids &= _kanban_eligible_user_ids()
    elif board.visibility == VISIBILITY_PUBLIC:
        candidate_ids = _kanban_eligible_user_ids()
        candidate_ids.update(explicit)
    else:
        candidate_ids = set(explicit)

    active_ids = {
        user.id
        for user in User.query.filter(User.id.in_(candidate_ids), User.is_active.is_(True)).all()
    } if candidate_ids else set()

    roles: dict[int, str] = {}
    for user_id in active_ids:
        if user_id == board.created_by:
            roles[user_id] = explicit.get(user_id, 'owner')
        elif user_id in explicit:
            roles[user_id] = explicit[user_id]
        else:
            roles[user_id] = 'member'
    return roles


def is_effective_board_member(board: KanbanBoard, user_id: int | None) -> bool:
    if not user_id:
        return False
    return user_id in get_board_member_roles(board)


def can_view_board(user, board: KanbanBoard, *, allow_closed: bool = False) -> bool:
    if not user or not board:
        return False
    if board.closed_at and not allow_closed:
        return False
    if not is_kanban_module_enabled() or not has_module_access(user, 'module_kanban'):
        return False
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return True

    if board.created_by and board.created_by == getattr(user, 'id', None):
        return True

    membership = get_board_membership(board, user)
    if membership:
        return True

    allowed = set(get_allowed_visibilities())

    # Open discovery only when the admin enabled that visibility type
    if board.visibility == VISIBILITY_PUBLIC and VISIBILITY_PUBLIC in allowed:
        return True

    if (
        board.visibility == VISIBILITY_TEAM
        and VISIBILITY_TEAM in allowed
        and board.team_id
        and board.team_id in user_team_ids(user)
    ):
        return True

    return False


def can_edit_board(user, board: KanbanBoard) -> bool:
    if not can_view_board(user, board):
        return False
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return True
    if board.created_by and board.created_by == getattr(user, 'id', None):
        return True
    membership = get_board_membership(board, user)
    if membership and membership.role in ('owner', 'admin', 'member'):
        return True
    # Public boards: view-only for non-members unless they are members/creator
    if board.visibility == VISIBILITY_PUBLIC and get_board_membership(board, user):
        return True
    if board.visibility == VISIBILITY_TEAM and board.team_id and board.team_id in user_team_ids(user):
        # Team members can edit team boards only when team boards are enabled
        return VISIBILITY_TEAM in set(get_allowed_visibilities())
    return False


def can_manage_board(user, board: KanbanBoard) -> bool:
    """Settings, members, shares, close/reopen board."""
    if not can_view_board(user, board, allow_closed=True):
        return False
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return True
    if board.created_by and board.created_by == getattr(user, 'id', None):
        return True
    membership = get_board_membership(board, user)
    return bool(membership and membership.role in ('owner', 'admin'))


def accessible_boards_query(user, *, include_closed: bool = False):
    """Return SQLAlchemy query of boards the user can see."""
    from app import db
    from sqlalchemy import or_, and_

    q = KanbanBoard.query
    if not include_closed:
        q = q.filter(KanbanBoard.closed_at.is_(None))

    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return q

    team_ids = list(user_team_ids(user))
    member_board_ids = [
        m.board_id
        for m in KanbanBoardMember.query.filter_by(user_id=user.id).all()
    ]
    allowed = set(get_allowed_visibilities())
    if VISIBILITY_TEAM in allowed and team_ids:
        from app.utils.team_module_settings import is_team_section_enabled
        team_ids = [tid for tid in team_ids if is_team_section_enabled(tid, 'kanban')]

    clauses = []
    if member_board_ids:
        clauses.append(KanbanBoard.id.in_(member_board_ids))
    clauses.append(KanbanBoard.created_by == user.id)

    if VISIBILITY_PUBLIC in allowed:
        clauses.append(KanbanBoard.visibility == VISIBILITY_PUBLIC)
    if VISIBILITY_TEAM in allowed and team_ids:
        clauses.append(
            and_(
                KanbanBoard.visibility == VISIBILITY_TEAM,
                KanbanBoard.team_id.in_(team_ids),
            )
        )

    if not clauses:
        return q.filter(db.false())
    return q.filter(or_(*clauses))


def get_board_for_card(card: KanbanCard) -> KanbanBoard | None:
    if not card or not card.list:
        return None
    return card.list.board


def get_card_or_404(card_id: int) -> KanbanCard | None:
    return KanbanCard.query.get(card_id)


def get_list_or_404(list_id: int) -> KanbanList | None:
    return KanbanList.query.get(list_id)


def log_debug(msg: str, *args):
    try:
        current_app.logger.debug(msg, *args)
    except Exception:
        pass
