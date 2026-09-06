"""Kanban overview, closed boards, and board page."""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app import db
from app.models.comment import Comment
from app.models.public_share import PublicShare
from app.models.kanban import (
    KanbanActivity,
    KanbanAttachment,
    KanbanBoard,
    KanbanBoardMember,
    KanbanBoardTemplate,
    KanbanBoardView,
    KanbanCard,
    KanbanCardAssignee,
    KanbanCardFieldEnabled,
    KanbanCardLabel,
    KanbanCardVote,
    KanbanCardFieldValue,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanCustomField,
    KanbanCustomFieldCategory,
    KanbanLabel,
    KanbanList,
)
from app.models.team import Team, TeamMember
from app.models.user import User
from app.utils.access_control import check_module_access
from app.utils.common import portal_now_naive
from app.utils.i18n import translate
from app.utils.kanban_access import (
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    VISIBILITY_TEAM,
    accessible_boards_query,
    can_edit_board,
    can_manage_board,
    can_view_board,
    get_allowed_visibilities,
    get_board_member_roles,
    get_board_membership,
    is_effective_board_member,
    KanbanImportPermissionError,
    visibility_allowed,
)
from app.utils.onlyoffice import is_onlyoffice_enabled, is_onlyoffice_file_type
from app.utils.public_share import (
    generate_unique_share_token,
    get_share_by_token,
    get_shares_for_resource,
    serialize_share_link,
    share_is_expired,
)

from app.blueprints.kanban._bp import BOARD_BACKGROUNDS, CUSTOM_FIELD_TYPES, kanban_bp
from app.blueprints.kanban.helpers import *  # noqa: F401,F403

# ── Pages ──────────────────────────────────────────────────────────────

@kanban_bp.route('/')
@login_required
@check_module_access('module_kanban')
def index():
    section = (request.args.get('section') or 'all').strip().lower()
    if section not in ('all', 'recent', 'private', 'team', 'public'):
        section = 'all'
    filter_team_id = None
    if section == 'team':
        try:
            filter_team_id = int(request.args.get('team_id') or 0) or None
        except (TypeError, ValueError):
            filter_team_id = None
    boards = (
        accessible_boards_query(current_user, include_closed=False)
        .order_by(KanbanBoard.updated_at.desc())
        .all()
    )
    recent_views = (
        KanbanBoardView.query.filter_by(user_id=current_user.id)
        .order_by(KanbanBoardView.viewed_at.desc())
        .limit(8)
        .all()
    )
    recent_boards = []
    for v in recent_views:
        if v.board and not v.board.closed_at and can_view_board(current_user, v.board):
            recent_boards.append(v.board)

    private_boards = [b for b in boards if b.visibility == VISIBILITY_PRIVATE] if VISIBILITY_PRIVATE in get_allowed_visibilities() else []
    team_boards = [b for b in boards if b.visibility == VISIBILITY_TEAM] if VISIBILITY_TEAM in get_allowed_visibilities() else []
    public_boards = [b for b in boards if b.visibility == VISIBILITY_PUBLIC] if VISIBILITY_PUBLIC in get_allowed_visibilities() else []

    teams = _user_kanban_teams(current_user)
    team_board_groups = []
    for team in teams:
        group_boards = [b for b in team_boards if b.team_id == team.id]
        if group_boards:
            team_board_groups.append({'team': team, 'boards': group_boards})
    ungrouped_team_boards = [b for b in team_boards if not b.team_id]
    if ungrouped_team_boards:
        team_board_groups.append({'team': None, 'boards': ungrouped_team_boards})

    selected_team_boards = team_boards
    if filter_team_id:
        if not any(t.id == filter_team_id for t in teams):
            filter_team_id = None
            section = 'all'
        else:
            selected_team_boards = [b for b in team_boards if b.team_id == filter_team_id]

    templates = KanbanBoardTemplate.query.filter(
        db.or_(
            KanbanBoardTemplate.is_global.is_(True),
            KanbanBoardTemplate.created_by == current_user.id,
        )
    ).order_by(KanbanBoardTemplate.name).all()

    all_visible = {b.id: b for b in boards}
    for b in recent_boards:
        all_visible[b.id] = b
    manageable_ids = {
        bid for bid, b in all_visible.items()
        if can_manage_board(current_user, b)
    }

    active_nav = f'team-{filter_team_id}' if section == 'team' and filter_team_id else section

    return render_template(
        'kanban/index.html',
        recent_boards=recent_boards,
        private_boards=private_boards,
        team_boards=selected_team_boards,
        team_board_groups=team_board_groups,
        public_boards=public_boards,
        allowed_visibilities=get_allowed_visibilities(),
        teams=teams,
        templates=templates,
        backgrounds=BOARD_BACKGROUNDS,
        show_closed_link=True,
        manageable_ids=manageable_ids,
        section_filter=section,
        filter_team_id=filter_team_id,
        active_nav=active_nav,
    )


@kanban_bp.route('/closed')
@login_required
@check_module_access('module_kanban')
def closed_boards():
    boards = (
        accessible_boards_query(current_user, include_closed=True)
        .filter(KanbanBoard.closed_at.isnot(None))
        .order_by(KanbanBoard.closed_at.desc())
        .all()
    )
    # filter to manageable
    boards = [b for b in boards if can_manage_board(current_user, b) or can_view_board(current_user, b)]
    return render_template(
        'kanban/closed.html',
        boards=boards,
        allowed_visibilities=get_allowed_visibilities(),
        teams=_user_kanban_teams(current_user),
        active_nav='closed',
        create_modal=False,
    )


@kanban_bp.route('/board/<int:board_id>')
@login_required
@check_module_access('module_kanban')
def board(board_id):
    board_obj = KanbanBoard.query.get_or_404(board_id)
    if board_obj.closed_at:
        if not can_manage_board(current_user, board_obj):
            flash(translate('kanban.flash.board_closed'), 'warning')
            return redirect(url_for('kanban.index'))
    elif not can_view_board(current_user, board_obj):
        flash(translate('kanban.flash.no_access'), 'danger')
        return redirect(url_for('kanban.index'))

    _track_view(board_obj)
    db.session.commit()

    cover_url = _board_cover_url(board_obj)
    return render_template(
        'kanban/board.html',
        board=board_obj,
        board_json=_serialize_board(board_obj, full=True),
        background_css=_board_background_css(board_obj),
        background_image_url=cover_url,
        backgrounds=BOARD_BACKGROUNDS,
        can_edit=can_edit_board(current_user, board_obj),
        can_manage=can_manage_board(current_user, board_obj),
        onlyoffice_enabled=is_onlyoffice_enabled(),
        share_token='',
        is_share=False,
    )
