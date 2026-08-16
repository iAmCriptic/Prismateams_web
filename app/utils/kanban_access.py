"""Access helpers and settings for the Kanban module."""

from __future__ import annotations

from flask import current_app

from app.models.kanban import KanbanBoard, KanbanBoardMember, KanbanCard, KanbanList
from app.models.settings import SystemSettings
from app.models.team import TeamMember
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
    allowed = []
    if _setting_bool(SETTING_ALLOW_PRIVATE, True):
        allowed.append(VISIBILITY_PRIVATE)
    if _setting_bool(SETTING_ALLOW_TEAM, True):
        allowed.append(VISIBILITY_TEAM)
    if _setting_bool(SETTING_ALLOW_PUBLIC, True):
        allowed.append(VISIBILITY_PUBLIC)
    return allowed or [VISIBILITY_PRIVATE]


def visibility_allowed(visibility: str) -> bool:
    return visibility in get_allowed_visibilities()


def user_team_ids(user) -> set[int]:
    if not user or not getattr(user, 'id', None):
        return set()
    return {m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()}


def get_board_membership(board: KanbanBoard, user) -> KanbanBoardMember | None:
    if not board or not user:
        return None
    return KanbanBoardMember.query.filter_by(board_id=board.id, user_id=user.id).first()


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
