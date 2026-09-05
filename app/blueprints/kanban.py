"""Kanban board blueprint – overview, board view, cards, shares, live sync."""

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

kanban_bp = Blueprint('kanban', __name__)

BOARD_BACKGROUNDS = [
    {'key': 'teal', 'css': 'linear-gradient(135deg, #0f766e, #14b8a6)'},
    {'key': 'slate', 'css': 'linear-gradient(135deg, #334155, #64748b)'},
    {'key': 'ocean', 'css': 'linear-gradient(135deg, #0ea5e9, #0369a1)'},
    {'key': 'forest', 'css': 'linear-gradient(135deg, #166534, #22c55e)'},
    {'key': 'sunset', 'css': 'linear-gradient(135deg, #c2410c, #f59e0b)'},
    {'key': 'berry', 'css': 'linear-gradient(135deg, #9f1239, #e11d48)'},
]

CUSTOM_FIELD_TYPES = ('text', 'select', 'date', 'time', 'checkbox')


def _share_token_from_request() -> str | None:
    token = (request.headers.get('X-Share-Token') or request.args.get('share_token') or '').strip()
    if not token:
        token = (session.get('kanban_share_token') or '').strip()
    return token or None


def _get_valid_share_for_board(board_id: int) -> PublicShare | None:
    token = _share_token_from_request()
    if not token:
        return None
    share = get_share_by_token(token)
    if not share or share.resource_type != 'kanban_board':
        return None
    try:
        if int(share.resource_id) != int(board_id):
            return None
    except (TypeError, ValueError):
        return None
    if share_is_expired(share):
        return None
    if share.password_hash and not _share_guest_ok(token):
        return None
    return share


def _actor_user_id(board: KanbanBoard | None = None) -> int | None:
    if current_user.is_authenticated:
        return current_user.id
    if board and board.created_by:
        return board.created_by
    return None


def _enqueue_kanban_notify(
    board: KanbanBoard,
    card_id: int,
    event_kind: str,
    *,
    detail: str | None = None,
    push_suffix: str | None = None,
) -> None:
    from app.utils.notifications import enqueue_kanban_notification

    actor_id = _actor_user_id(board)
    if not actor_id:
        return
    enqueue_kanban_notification(
        board_id=board.id,
        actor_id=actor_id,
        event_kind=event_kind,
        card_id=card_id,
        detail=detail,
        push_suffix=push_suffix,
    )


def _can_view_board_ctx(board: KanbanBoard) -> bool:
    if current_user.is_authenticated:
        if can_view_board(current_user, board):
            return True
        if board.closed_at and can_manage_board(current_user, board):
            return True
    return _get_valid_share_for_board(board.id) is not None


def _can_edit_board_ctx(board: KanbanBoard) -> bool:
    if current_user.is_authenticated and can_edit_board(current_user, board):
        return True
    share = _get_valid_share_for_board(board.id)
    return bool(share and share.mode == 'edit')


def _can_manage_board_ctx(board: KanbanBoard) -> bool:
    return bool(current_user.is_authenticated and can_manage_board(current_user, board))


@kanban_bp.app_template_global('kanban_board_cover_url')
def kanban_board_cover_url(board: KanbanBoard) -> str | None:
    return _board_cover_url(board)


def login_or_share_required(f):
    """Allow authenticated users or a valid share token (checked later per-board)."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if current_user.is_authenticated:
            return f(*args, **kwargs)
        if _share_token_from_request():
            return f(*args, **kwargs)
        return jsonify({'error': 'Unauthorized'}), 401
    return wrapped


def _emit_board(board_id: int, event_type: str, data: dict):
    try:
        from app.blueprints.sse import emit_kanban_update
        emit_kanban_update(board_id, event_type, data)
    except Exception:
        pass


def _log_activity(board_id: int, action: str, detail: str = None, card_id: int = None, user_id: int = None):
    try:
        act = KanbanActivity(
            board_id=board_id,
            card_id=card_id,
            user_id=user_id or (current_user.id if current_user.is_authenticated else None),
            action=action,
            detail=detail,
        )
        db.session.add(act)
        db.session.flush()
    except Exception:
        pass


def _upload_root():
    root = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'kanban')
    os.makedirs(root, exist_ok=True)
    return root


def _boards_upload_root():
    root = os.path.join(_upload_root(), 'boards')
    os.makedirs(root, exist_ok=True)
    return root


def _board_cover_file_path(board: KanbanBoard) -> str | None:
    """Return absolute filesystem path if cover_path points to a local file."""
    path = (board.cover_path or '').strip()
    if not path:
        return None
    if path.startswith(('http://', 'https://')):
        return None
    if os.path.isfile(path):
        return path
    # Relative to upload root / project
    candidates = [
        path,
        os.path.join(_upload_root(), path),
        os.path.join(_boards_upload_root(), os.path.basename(path)),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _board_cover_url(board: KanbanBoard) -> str | None:
    """Public URL for board background/cover image."""
    path = (board.cover_path or '').strip()
    if not path:
        return None
    if path.startswith(('http://', 'https://')):
        return path
    if path.startswith('/') and not path.startswith('//'):
        # Already an app-relative URL (legacy)
        return path
    if _board_cover_file_path(board):
        return url_for('kanban.board_background', board_id=board.id)
    return None


def _board_background_css(board: KanbanBoard) -> str:
    bg = next(
        (b for b in BOARD_BACKGROUNDS if b['key'] == (board.background or 'teal')),
        BOARD_BACKGROUNDS[0],
    )
    return bg['css']


def _delete_board_cover_file(board: KanbanBoard) -> None:
    path = _board_cover_file_path(board)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
    board.cover_path = None


def _serialize_board_members(board: KanbanBoard) -> list[dict]:
    roles = get_board_member_roles(board)
    if not roles:
        return []
    users = {
        user.id: user
        for user in User.query.filter(User.id.in_(roles)).all()
    }
    role_order = {'owner': 0, 'admin': 1, 'member': 2}
    entries = []
    for user_id, role in roles.items():
        user = users.get(user_id)
        if not user:
            continue
        entries.append((
            role_order.get(role, 3),
            (user.full_name or user.email or '').lower(),
            user,
            role,
        ))
    entries.sort()
    return [
        {**(_user_brief(user) or {}), 'role': role}
        for _, _, user, role in entries
    ]


def _user_brief(user: User | None) -> dict | None:
    if not user:
        return None
    initials = ''
    if user.first_name:
        initials += user.first_name[:1]
    if user.last_name:
        initials += user.last_name[:1]
    if not initials and user.email:
        initials = user.email[:2]
    avatar_url = None
    if getattr(user, 'profile_picture', None):
        try:
            avatar_url = url_for('settings.profile_picture', filename=user.profile_picture)
        except Exception:
            avatar_url = None
    return {
        'id': user.id,
        'name': user.full_name or user.email,
        'initials': initials.upper(),
        'profile_picture': avatar_url,
        'avatar_url': avatar_url,
    }


def _attachment_url(att: KanbanAttachment) -> str:
    if att.url:
        return att.url
    if not att.storage_path:
        return '#'
    return url_for('kanban.download_attachment', attachment_id=att.id)


def _serialize_attachment(att: KanbanAttachment, share_token: str | None = None) -> dict:
    is_link = bool(att.url)
    mime = att.mime_type or ''
    name = att.original_filename or att.filename or (att.url or 'Link')
    ext = (os.path.splitext(name)[1] or '').lower().lstrip('.')
    is_image = mime.startswith('image/') or ext in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg')
    if is_link:
        file_url = att.url
        # External image links can still act as card covers / previews
        preview_url = att.url if is_image else None
    elif share_token:
        file_url = url_for('kanban.share_download_attachment', token=share_token, attachment_id=att.id)
        preview_url = url_for('kanban.share_preview_attachment', token=share_token, attachment_id=att.id)
    else:
        file_url = url_for('kanban.download_attachment', attachment_id=att.id)
        preview_url = url_for('kanban.preview_attachment', attachment_id=att.id)
    return {
        'id': att.id,
        'filename': name,
        'mime_type': mime,
        'file_size': att.file_size,
        'url': file_url,
        'external_url': att.url,
        'preview_url': preview_url,
        'is_link': is_link,
        'is_image': is_image and (not is_link or bool(preview_url)),
        'is_pdf': (not is_link) and (mime == 'application/pdf' or ext == 'pdf'),
        'is_office': (not is_link) and (is_onlyoffice_file_type(ext) if ext else False),
        'onlyoffice_enabled': is_onlyoffice_enabled() and not share_token,
        'onlyoffice_url': (
            url_for('kanban.edit_onlyoffice', attachment_id=att.id)
            if (not is_link) and not share_token and is_onlyoffice_enabled() and ext and is_onlyoffice_file_type(ext)
            else None
        ),
        'created_at': att.created_at.isoformat() if att.created_at else None,
    }


def _checklist_progress(card: KanbanCard) -> dict:
    total = done = 0
    for cl in card.checklists:
        for item in cl.items:
            total += 1
            if item.done:
                done += 1
    return {'done': done, 'total': total}


def _serialize_checklist_item(it: KanbanChecklistItem) -> dict:
    return {
        'id': it.id,
        'text': it.text,
        'done': it.done,
        'position': it.position,
        'due_date': it.due_date.isoformat() if it.due_date else None,
        'assignee_id': it.assignee_id,
        'assignee': _user_brief(it.assignee) if it.assignee_id else None,
    }


def _serialize_card_summary(card: KanbanCard, share_token: str | None = None) -> dict:
    actor_id = _actor_user_id(card.list.board if card.list else None)
    cover = None
    if card.cover_attachment_id:
        att = next((a for a in card.attachments if a.id == card.cover_attachment_id), None)
        if not att:
            att = KanbanAttachment.query.get(card.cover_attachment_id)
        if att:
            cover = _serialize_attachment(att, share_token=share_token)
    comment_count = Comment.query.filter_by(
        content_type='kanban_card', content_id=card.id, is_deleted=False
    ).count()
    return {
        'id': card.id,
        'list_id': card.list_id,
        'title': card.title,
        'description': card.description,
        'poll_text': card.poll_text,
        'due_date': card.due_date.isoformat() if card.due_date else None,
        'position': card.position,
        'archived': bool(card.archived_at),
        'completed': bool(card.completed_at),
        'cover': cover,
        'cover_attachment_id': card.cover_attachment_id,
        'labels': [
            {'id': cl.label.id, 'name': cl.label.name, 'color': cl.label.color}
            for cl in card.card_labels if cl.label
        ],
        'assignees': [_user_brief(a.user) for a in card.assignees if a.user],
        'checklist': _checklist_progress(card),
        'attachment_count': len(card.attachments),
        'comment_count': comment_count,
        'vote_count': len(card.votes),
        'voted_by_me': bool(actor_id and any(v.user_id == actor_id for v in card.votes)),
    }


def _parse_custom_field_options(raw, field_type: str) -> str | None:
    if field_type != 'select':
        return None
    opts: list[str] = []
    if isinstance(raw, list):
        opts = [str(x).strip() for x in raw if str(x).strip()]
    else:
        text = (raw or '').strip()
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    opts = [str(x).strip() for x in parsed if str(x).strip()]
                else:
                    opts = [ln.strip() for ln in text.splitlines() if ln.strip()]
            except Exception:
                opts = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return json.dumps(opts)


def _serialize_custom_field(field: KanbanCustomField) -> dict:
    options = []
    if field.options:
        try:
            parsed = json.loads(field.options)
            if isinstance(parsed, list):
                options = [str(x) for x in parsed]
        except Exception:
            options = [ln.strip() for ln in field.options.splitlines() if ln.strip()]
    return {
        'id': field.id,
        'board_id': field.board_id,
        'card_id': field.card_id,
        'category_id': field.category_id,
        'field_type': field.field_type,
        'label': field.label,
        'position': field.position,
        'options': options,
        'placeholder': field.placeholder,
    }


def _serialize_card_detail(card: KanbanCard, share_token: str | None = None) -> dict:
    token = share_token if share_token is not None else _share_token_from_request()
    data = _serialize_card_summary(card, share_token=token)
    data.update({
        'checklists': [
            {
                'id': cl.id,
                'title': cl.title,
                'position': cl.position,
                'items': [_serialize_checklist_item(it) for it in cl.items],
            }
            for cl in card.checklists
        ],
        'attachments': [_serialize_attachment(a, share_token=token) for a in card.attachments],
        'custom_field_values': {str(fv.field_id): fv.value for fv in card.field_values},
        'custom_fields': [
            _serialize_custom_field(f)
            for f in (
                [enabled.field for enabled in card.enabled_fields if enabled.field]
                + list(card.local_fields)
            )
        ],
        'enabled_field_ids': [e.field_id for e in card.enabled_fields],
        'cover_attachment_id': card.cover_attachment_id,
        'board_id': card.list.board_id if card.list else None,
        'list_title': card.list.title if card.list else None,
    })
    return data


def _serialize_list(
    lst: KanbanList,
    include_archived_cards: bool = False,
    share_token: str | None = None,
) -> dict:
    cards = [c for c in lst.cards if include_archived_cards or not c.archived_at]
    return {
        'id': lst.id,
        'title': lst.title,
        'position': lst.position,
        'archived': bool(lst.archived_at),
        'card_count': len(cards),
        'cards': [_serialize_card_summary(c, share_token=share_token) for c in cards],
    }


def _serialize_board(
    board: KanbanBoard,
    *,
    full: bool = False,
    share_token: str | None = None,
) -> dict:
    data = {
        'id': board.id,
        'title': board.title,
        'description': board.description,
        'cover_path': _board_cover_url(board),
        'has_cover_image': bool(_board_cover_url(board)),
        'background': board.background or 'teal',
        'background_css': _board_background_css(board),
        'visibility': board.visibility,
        'team_id': board.team_id,
        'team_name': board.team.name if board.team else None,
        'closed': bool(board.closed_at),
        'created_at': board.created_at.isoformat() if board.created_at else None,
        'member_count': len(get_board_member_roles(board)),
        'url': url_for('kanban.board', board_id=board.id),
    }
    if full:
        data['lists'] = [
            _serialize_list(l, share_token=share_token)
            for l in board.lists if not l.archived_at
        ]
        data['labels'] = [
            {'id': lb.id, 'name': lb.name, 'color': lb.color, 'position': lb.position}
            for lb in sorted(board.labels, key=lambda x: x.position)
        ]
        data['members'] = _serialize_board_members(board)
        if share_token:
            data['can_edit'] = True  # caller passes token only for authorized share view; refine below
            share = get_share_by_token(share_token)
            data['can_edit'] = bool(
                share
                and share.resource_type == 'kanban_board'
                and str(share.resource_id) == str(board.id)
                and share.mode == 'edit'
                and not share_is_expired(share)
            )
            data['can_manage'] = False
        else:
            data['can_edit'] = _can_edit_board_ctx(board)
            data['can_manage'] = _can_manage_board_ctx(board)
        data['custom_fields'] = [_serialize_custom_field(f) for f in board.custom_fields]
        data['custom_field_categories'] = [
            {'id': c.id, 'name': c.name, 'position': c.position}
            for c in board.custom_field_categories
        ]
        data['share_token'] = share_token
    return data


def _require_board_view(board_id: int):
    board = KanbanBoard.query.get_or_404(board_id)
    if _get_valid_share_for_board(board.id):
        return board, None
    if not current_user.is_authenticated:
        return None, (jsonify({'error': 'Unauthorized'}), 401)
    if not can_view_board(current_user, board) and not board.closed_at:
        if not (board.closed_at and can_manage_board(current_user, board)):
            return None, (jsonify({'error': 'Forbidden'}), 403)
    elif board.closed_at and not can_manage_board(current_user, board):
        return None, (jsonify({'error': 'Board closed'}), 403)
    return board, None


def _require_board_edit(board_id: int):
    board = KanbanBoard.query.get_or_404(board_id)
    if _can_edit_board_ctx(board):
        return board, None
    if not current_user.is_authenticated:
        return None, (jsonify({'error': 'Unauthorized'}), 401)
    return None, (jsonify({'error': 'Forbidden'}), 403)


def _require_board_manage(board_id: int):
    board = KanbanBoard.query.get_or_404(board_id)
    if not current_user.is_authenticated:
        return None, (jsonify({'error': 'Unauthorized'}), 401)
    if not can_manage_board(current_user, board):
        return None, (jsonify({'error': 'Forbidden'}), 403)
    return board, None


def _track_view(board: KanbanBoard):
    if not current_user.is_authenticated:
        return
    view = KanbanBoardView.query.filter_by(board_id=board.id, user_id=current_user.id).first()
    now = portal_now_naive()
    if view:
        view.viewed_at = now
    else:
        db.session.add(KanbanBoardView(board_id=board.id, user_id=current_user.id, viewed_at=now))
    board.last_viewed_at = now


def _share_guest_ok(token: str) -> bool:
    return bool(session.get(f'share_auth_{token}'))


def _user_kanban_teams(user):
    """Teams the user may assign boards to / see as sidebar folders."""
    if VISIBILITY_TEAM not in get_allowed_visibilities():
        return []
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return Team.query.order_by(Team.name).all()
    team_ids = [m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()]
    if not team_ids:
        return []
    return Team.query.filter(Team.id.in_(team_ids)).order_by(Team.name).all()


def _user_may_use_team(user, team_id: int) -> bool:
    return any(t.id == team_id for t in _user_kanban_teams(user))


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


# ── Board CRUD API ─────────────────────────────────────────────────────

@kanban_bp.route('/api/boards', methods=['POST'])
@login_required
@check_module_access('module_kanban')
def api_create_board():
    data = request.get_json(silent=True) or request.form
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Title required'}), 400

    visibility = (data.get('visibility') or VISIBILITY_PRIVATE).strip().lower()
    team_id = data.get('team_id')
    if visibility.startswith('team:'):
        try:
            team_id = int(visibility.split(':', 1)[1])
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid team'}), 400
        visibility = VISIBILITY_TEAM
    if visibility not in (VISIBILITY_PRIVATE, VISIBILITY_TEAM, VISIBILITY_PUBLIC):
        visibility = VISIBILITY_PRIVATE
    if not visibility_allowed(visibility):
        return jsonify({'error': 'Visibility not allowed'}), 400

    if team_id in ('', None):
        team_id = None
    else:
        try:
            team_id = int(team_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid team'}), 400

    if visibility == VISIBILITY_TEAM:
        if not team_id:
            return jsonify({'error': 'Team required'}), 400
        if not Team.query.get(team_id):
            return jsonify({'error': 'Team not found'}), 404
        if not _user_may_use_team(current_user, team_id):
            return jsonify({'error': 'Forbidden'}), 403
    else:
        team_id = None

    background = (data.get('background') or 'teal').strip()
    if background not in {b['key'] for b in BOARD_BACKGROUNDS}:
        background = 'teal'

    template_id = data.get('template_id')
    board = KanbanBoard(
        title=title,
        description=(data.get('description') or '').strip() or None,
        visibility=visibility,
        team_id=team_id,
        created_by=current_user.id,
        background=background,
    )
    db.session.add(board)
    db.session.flush()

    db.session.add(KanbanBoardMember(board_id=board.id, user_id=current_user.id, role='owner'))

    # default labels
    for i, (name, color) in enumerate([
        ('Wichtig', '#ef4444'),
        ('In Arbeit', '#3b82f6'),
        ('Fertig', '#22c55e'),
    ]):
        db.session.add(KanbanLabel(board_id=board.id, name=name, color=color, position=i))

    if template_id:
        tmpl = KanbanBoardTemplate.query.get(int(template_id))
        if tmpl:
            try:
                payload = json.loads(tmpl.payload_json or '{}')
                for i, lst in enumerate(payload.get('lists') or []):
                    db.session.add(KanbanList(
                        board_id=board.id,
                        title=lst.get('title') or f'Liste {i + 1}',
                        position=i,
                    ))
                for i, lb in enumerate(payload.get('labels') or []):
                    db.session.add(KanbanLabel(
                        board_id=board.id,
                        name=lb.get('name') or 'Label',
                        color=lb.get('color') or '#0d6efd',
                        position=10 + i,
                    ))
            except Exception:
                pass
    else:
        for i, title_l in enumerate(['To Do', 'In Arbeit', 'Erledigt']):
            db.session.add(KanbanList(board_id=board.id, title=title_l, position=i))

    _log_activity(board.id, 'board_created', title)
    db.session.commit()
    return jsonify({'success': True, 'board': _serialize_board(board)}), 201


@kanban_bp.route('/api/boards/<int:board_id>/export', methods=['GET'])
@login_or_share_required
def api_export_board(board_id):
    """Export board as Trello-compatible JSON or CSV (anyone who can view)."""
    board, err = _require_board_view(board_id)
    if err:
        return err

    fmt = (request.args.get('format') or 'json').strip().lower()
    from app.utils.kanban_export import export_board_csv_bytes, export_board_json_bytes

    if fmt == 'csv':
        raw, filename = export_board_csv_bytes(board)
        mimetype = 'text/csv; charset=utf-8'
    else:
        raw, filename = export_board_json_bytes(board)
        mimetype = 'application/json; charset=utf-8'

    from flask import Response
    return Response(
        raw,
        mimetype=mimetype,
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Cache-Control': 'no-store',
        },
    )


@kanban_bp.route('/api/boards/import', methods=['POST'])
@login_required
@check_module_access('module_kanban')
def api_import_board():
    """Import a Trello JSON/CSV export as a new board."""
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': translate('kanban.import.error_no_file'), 'code': 'no_file'}), 400

    visibility = (request.form.get('visibility') or VISIBILITY_PRIVATE).strip().lower()
    team_id = request.form.get('team_id')
    if visibility.startswith('team:'):
        try:
            team_id = int(visibility.split(':', 1)[1])
        except (TypeError, ValueError):
            return jsonify({'error': translate('kanban.import.error_team'), 'code': 'invalid_team'}), 400
        visibility = VISIBILITY_TEAM
    if team_id in ('', None):
        team_id = None
    else:
        try:
            team_id = int(team_id)
        except (TypeError, ValueError):
            return jsonify({'error': translate('kanban.import.error_team'), 'code': 'invalid_team'}), 400

    title_override = (request.form.get('title') or '').strip() or None
    raw = f.read()
    if not raw:
        return jsonify({'error': translate('kanban.import.error_empty'), 'code': 'empty'}), 400

    from app.utils.kanban_import import KanbanImportError, detect_import_format, import_board_from_bytes, import_boards_from_zip

    try:
        fmt = detect_import_format(f.filename, raw)
        if fmt == 'zip':
            boards, errors = import_boards_from_zip(
                raw=raw,
                user=current_user,
                visibility=visibility,
                team_id=team_id,
            )
            for board in boards:
                _log_activity(board.id, 'board_imported', board.title, user_id=current_user.id)
            db.session.commit()
            return jsonify({
                'success': True,
                'boards': [_serialize_board(b) for b in boards],
                'board': _serialize_board(boards[0]) if boards else None,
                'errors': errors,
            }), 201

        board = import_board_from_bytes(
            raw=raw,
            filename=f.filename,
            user=current_user,
            visibility=visibility,
            team_id=team_id,
            title_override=title_override,
        )
    except KanbanImportPermissionError as exc:
        code = str(exc) or 'forbidden'
        msg = {
            'not_authenticated': translate('kanban.import.error_forbidden'),
            'admin_required': translate('kanban.import.error_admin'),
            'team_required': translate('kanban.import.error_team'),
            'team_forbidden': translate('kanban.import.error_team_leader'),
            'visibility_not_allowed': translate('kanban.import.error_visibility'),
            'invalid_visibility': translate('kanban.import.error_visibility'),
        }.get(code, translate('kanban.import.error_forbidden'))
        return jsonify({'error': msg, 'code': code}), 403
    except KanbanImportError as exc:
        code = str(exc) or 'invalid'
        msg = {
            'invalid_json': translate('kanban.import.error_invalid'),
            'not_trello_json': translate('kanban.import.error_invalid'),
            'invalid_csv': translate('kanban.import.error_invalid'),
            'empty_csv': translate('kanban.import.error_empty'),
            'invalid_zip': translate('kanban.import.error_invalid_zip'),
            'empty_zip': translate('kanban.import.error_empty_zip'),
            'visibility_not_allowed': translate('kanban.import.error_visibility'),
        }.get(code, translate('kanban.import.error_invalid'))
        return jsonify({'error': msg, 'code': code}), 400
    except Exception:
        current_app.logger.exception('Kanban board import failed')
        return jsonify({'error': translate('kanban.import.error_failed'), 'code': 'failed'}), 500

    _log_activity(board.id, 'board_imported', board.title, user_id=current_user.id)
    db.session.commit()
    return jsonify({'success': True, 'board': _serialize_board(board), 'boards': [_serialize_board(board)], 'errors': []}), 201


@kanban_bp.route('/api/boards/<int:board_id>', methods=['GET', 'PATCH', 'DELETE'])
@login_or_share_required
def api_board(board_id):
    board, err = _require_board_view(board_id)
    if err:
        return err

    if request.method == 'GET':
        return jsonify(_serialize_board(board, full=True, share_token=_share_token_from_request()))

    if request.method == 'DELETE':
        if not can_manage_board(current_user, board):
            return jsonify({'error': 'Forbidden'}), 403
        db.session.delete(board)
        db.session.commit()
        return jsonify({'success': True})

    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        board.title = (data['title'] or board.title).strip() or board.title
    if 'description' in data:
        board.description = (data.get('description') or '').strip() or None
    if 'background' in data:
        bg = (data['background'] or '').strip()
        if bg in {b['key'] for b in BOARD_BACKGROUNDS}:
            board.background = bg
    if 'clear_cover' in data and data.get('clear_cover'):
        _delete_board_cover_file(board)
    if 'closed' in data:
        board.closed_at = portal_now_naive() if data['closed'] else None
        _log_activity(board.id, 'board_closed' if board.closed_at else 'board_reopened')
    db.session.commit()
    _emit_board(board.id, 'board_updated', _serialize_board(board, full=True))
    return jsonify({'success': True, 'board': _serialize_board(board, full=True)})


@kanban_bp.route('/boards/<int:board_id>/background')
@login_or_share_required
def board_background(board_id):
    """Serve the board background/cover image."""
    board, err = _require_board_view(board_id)
    if err:
        return err
    path = _board_cover_file_path(board)
    if not path:
        # Redirect external/legacy URLs
        url = (board.cover_path or '').strip()
        if url.startswith(('http://', 'https://')):
            return redirect(url)
        return ('', 404)
    mime = mimetypes.guess_type(path)[0] or 'image/jpeg'
    return send_file(path, mimetype=mime, conditional=True)


@kanban_bp.route('/api/boards/<int:board_id>/background', methods=['POST', 'DELETE'])
@login_required
@check_module_access('module_kanban')
def api_board_background(board_id):
    board = KanbanBoard.query.get_or_404(board_id)
    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403

    if request.method == 'DELETE':
        _delete_board_cover_file(board)
        db.session.commit()
        payload = _serialize_board(board, full=True)
        _emit_board(board.id, 'board_updated', payload)
        return jsonify({'success': True, 'board': payload})

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'No file'}), 400
    original = secure_filename(f.filename) or 'background.jpg'
    mime = f.mimetype or mimetypes.guess_type(original)[0] or ''
    if not mime.startswith('image/'):
        return jsonify({'error': 'Image required'}), 400
    stored = f'{uuid.uuid4().hex}_{original}'
    path = os.path.join(_boards_upload_root(), stored)
    _delete_board_cover_file(board)
    f.save(path)
    board.cover_path = path
    db.session.commit()
    payload = _serialize_board(board, full=True)
    _emit_board(board.id, 'board_updated', payload)
    return jsonify({'success': True, 'board': payload}), 201


# ── Lists ──────────────────────────────────────────────────────────────

@kanban_bp.route('/api/boards/<int:board_id>/lists', methods=['POST'])
@login_or_share_required
def api_create_list(board_id):
    board, err = _require_board_edit(board_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Title required'}), 400
    max_pos = db.session.query(db.func.max(KanbanList.position)).filter_by(board_id=board.id).scalar() or 0
    lst = KanbanList(board_id=board.id, title=title, position=max_pos + 1)
    db.session.add(lst)
    _log_activity(board.id, 'list_created', title)
    db.session.commit()
    payload = _serialize_list(lst, share_token=_share_token_from_request())
    _emit_board(board.id, 'list_created', payload)
    return jsonify({'success': True, 'list': payload}), 201


@kanban_bp.route('/api/lists/<int:list_id>', methods=['PATCH', 'DELETE'])
@login_or_share_required
def api_list(list_id):
    lst = KanbanList.query.get_or_404(list_id)
    board = lst.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403

    if request.method == 'DELETE':
        board_id = board.id
        db.session.delete(lst)
        db.session.commit()
        _emit_board(board_id, 'list_deleted', {'id': list_id})
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        lst.title = (data['title'] or lst.title).strip() or lst.title
    if 'archived' in data:
        lst.archived_at = portal_now_naive() if data['archived'] else None
    if 'position' in data:
        try:
            lst.position = int(data['position'])
        except (TypeError, ValueError):
            pass
    db.session.commit()
    payload = _serialize_list(lst, share_token=_share_token_from_request())
    _emit_board(board.id, 'list_updated', payload)
    return jsonify({'success': True, 'list': payload})


@kanban_bp.route('/api/boards/<int:board_id>/lists/reorder', methods=['POST'])
@login_or_share_required
def api_reorder_lists(board_id):
    board, err = _require_board_edit(board_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    order = data.get('order') or []
    for i, lid in enumerate(order):
        lst = KanbanList.query.filter_by(id=int(lid), board_id=board.id).first()
        if lst:
            lst.position = i
    db.session.commit()
    _emit_board(board.id, 'lists_reordered', {'order': order})
    return jsonify({'success': True})


# ── Cards ──────────────────────────────────────────────────────────────

@kanban_bp.route('/api/lists/<int:list_id>/cards', methods=['POST'])
@login_or_share_required
def api_create_card(list_id):
    lst = KanbanList.query.get_or_404(list_id)
    board = lst.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Title required'}), 400
    max_pos = db.session.query(db.func.max(KanbanCard.position)).filter_by(list_id=lst.id).scalar() or 0
    card = KanbanCard(
        list_id=lst.id,
        title=title,
        description=(data.get('description') or '').strip() or None,
        position=max_pos + 1,
        created_by=_actor_user_id(board),
    )
    db.session.add(card)
    _log_activity(board.id, 'card_created', title, card_id=None)
    db.session.flush()
    _log_activity(board.id, 'card_created', title, card_id=card.id)
    db.session.commit()
    payload = _serialize_card_summary(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_created', payload)
    return jsonify({'success': True, 'card': payload}), 201


@kanban_bp.route('/api/cards/<int:card_id>', methods=['GET', 'PATCH', 'DELETE'])
@login_or_share_required
def api_card(card_id):
    card = KanbanCard.query.get_or_404(card_id)
    board = card.list.board
    if not _can_view_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403

    if request.method == 'GET':
        return jsonify(_serialize_card_detail(card, share_token=_share_token_from_request()))

    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403

    if request.method == 'DELETE':
        bid = board.id
        db.session.delete(card)
        db.session.commit()
        _emit_board(bid, 'card_deleted', {'id': card_id})
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        card.title = (data['title'] or card.title).strip() or card.title
    if 'description' in data:
        card.description = data.get('description')
    if 'poll_text' in data:
        raw_poll = data.get('poll_text')
        if raw_poll is None or str(raw_poll).strip() == '':
            card.poll_text = None
            # Clear votes when poll removed
            KanbanCardVote.query.filter_by(card_id=card.id).delete()
        else:
            card.poll_text = str(raw_poll).strip()
    if 'due_date' in data:
        raw = data.get('due_date')
        if not raw:
            card.due_date = None
        else:
            try:
                card.due_date = datetime.fromisoformat(str(raw).replace('Z', ''))
            except ValueError:
                pass
    if 'archived' in data:
        card.archived_at = portal_now_naive() if data['archived'] else None
        _log_activity(board.id, 'card_archived' if card.archived_at else 'card_restored', card.title, card.id)
    if 'completed' in data:
        card.completed_at = portal_now_naive() if data['completed'] else None
        _log_activity(
            board.id,
            'card_completed' if card.completed_at else 'card_uncompleted',
            card.title,
            card.id,
        )
    if 'cover_attachment_id' in data:
        cid = data.get('cover_attachment_id')
        if cid is None:
            card.cover_attachment_id = None
        else:
            att = KanbanAttachment.query.filter_by(id=int(cid), card_id=card.id).first()
            if att:
                card.cover_attachment_id = att.id
    if 'list_id' in data or 'position' in data:
        new_list_id = int(data.get('list_id') or card.list_id)
        new_list = KanbanList.query.filter_by(id=new_list_id, board_id=board.id).first()
        if new_list:
            old_list_id = card.list_id
            card.list_id = new_list.id
            if 'position' in data:
                try:
                    card.position = int(data['position'])
                except (TypeError, ValueError):
                    pass
            if old_list_id != new_list.id:
                _log_activity(board.id, 'card_moved', f'{card.title} → {new_list.title}', card.id)

    db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)

    _notify_keys = {'title', 'description', 'due_date', 'completed', 'archived', 'list_id', 'position'}
    if any(k in data for k in _notify_keys):
        _enqueue_kanban_notify(
            board,
            card.id,
            'change',
            push_suffix=f'change:{card.id}:{int(portal_now_naive().timestamp())}',
        )

    return jsonify({'success': True, 'card': payload})


@kanban_bp.route('/api/boards/<int:board_id>/cards/move', methods=['POST'])
@login_or_share_required
def api_move_card(board_id):
    board, err = _require_board_edit(board_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    card_id = int(data['card_id'])
    list_id = int(data['list_id'])
    position = int(data.get('position', 0))
    card = KanbanCard.query.get_or_404(card_id)
    if card.list.board_id != board.id:
        return jsonify({'error': 'Wrong board'}), 400
    lst = KanbanList.query.filter_by(id=list_id, board_id=board.id).first_or_404()
    card.list_id = lst.id
    card.position = position
    # compact sibling positions
    siblings = (
        KanbanCard.query.filter_by(list_id=lst.id)
        .filter(KanbanCard.id != card.id)
        .order_by(KanbanCard.position)
        .all()
    )
    siblings.insert(max(0, min(position, len(siblings))), card)
    for i, c in enumerate(siblings):
        c.position = i
    db.session.commit()
    payload = _serialize_card_summary(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_moved', payload)
    _enqueue_kanban_notify(board, card.id, 'change', push_suffix=f'move:{card.id}:{int(portal_now_naive().timestamp())}')
    return jsonify({'success': True, 'card': payload})


# ── Labels / Assignees / Checklists / Votes ────────────────────────────

@kanban_bp.route('/api/boards/<int:board_id>/labels', methods=['POST'])
@login_or_share_required
def api_create_label(board_id):
    board, err = _require_board_edit(board_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    label = KanbanLabel(
        board_id=board.id,
        name=(data.get('name') or 'Label').strip(),
        color=(data.get('color') or '#0d6efd').strip(),
        position=len(board.labels),
    )
    db.session.add(label)
    db.session.commit()
    payload = {'id': label.id, 'name': label.name, 'color': label.color}
    _emit_board(board.id, 'label_created', payload)
    return jsonify({'success': True, 'label': payload}), 201


@kanban_bp.route('/api/cards/<int:card_id>/labels', methods=['POST'])
@login_or_share_required
def api_toggle_card_label(card_id):
    card = KanbanCard.query.get_or_404(card_id)
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    label_id = int(data['label_id'])
    label = KanbanLabel.query.filter_by(id=label_id, board_id=board.id).first_or_404()
    existing = KanbanCardLabel.query.filter_by(card_id=card.id, label_id=label.id).first()
    if existing:
        db.session.delete(existing)
        attached = False
    else:
        db.session.add(KanbanCardLabel(card_id=card.id, label_id=label.id))
        attached = True
    db.session.commit()
    payload = _serialize_card_summary(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    return jsonify({'success': True, 'attached': attached, 'card': payload})


@kanban_bp.route('/api/cards/<int:card_id>/assignees', methods=['POST'])
@login_or_share_required
def api_toggle_assignee(card_id):
    card = KanbanCard.query.get_or_404(card_id)
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    user_id = int(data['user_id'])
    if not is_effective_board_member(board, user_id):
        return jsonify({'error': 'Assignee is not a board member'}), 400
    existing = KanbanCardAssignee.query.filter_by(card_id=card.id, user_id=user_id).first()
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(KanbanCardAssignee(card_id=card.id, user_id=user_id))
    db.session.commit()
    payload = _serialize_card_summary(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    return jsonify({'success': True, 'card': payload})


@kanban_bp.route('/api/cards/<int:card_id>/checklists', methods=['POST'])
@login_or_share_required
def api_create_checklist(card_id):
    card = KanbanCard.query.get_or_404(card_id)
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    cl = KanbanChecklist(
        card_id=card.id,
        title=(data.get('title') or 'Checkliste').strip(),
        position=len(card.checklists),
    )
    db.session.add(cl)
    db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    return jsonify({'success': True, 'card': payload}), 201


@kanban_bp.route('/api/checklists/<int:checklist_id>', methods=['PATCH', 'DELETE'])
@login_or_share_required
def api_checklist(checklist_id):
    cl = KanbanChecklist.query.get_or_404(checklist_id)
    card = cl.card
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    if request.method == 'DELETE':
        db.session.delete(cl)
        db.session.commit()
        payload = _serialize_card_detail(card, share_token=_share_token_from_request())
        _emit_board(board.id, 'card_updated', payload)
        return jsonify({'success': True, 'card': payload})
    data = request.get_json(silent=True) or {}
    if 'title' in data:
        title = (data.get('title') or '').strip()
        cl.title = title or cl.title
    db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    return jsonify({'success': True, 'card': payload})


@kanban_bp.route('/api/checklists/<int:checklist_id>/items', methods=['POST'])
@login_or_share_required
def api_add_checklist_item(checklist_id):
    cl = KanbanChecklist.query.get_or_404(checklist_id)
    board = cl.card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Text required'}), 400
    item = KanbanChecklistItem(checklist_id=cl.id, text=text, position=len(cl.items))
    db.session.add(item)
    db.session.commit()
    payload = _serialize_card_detail(cl.card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    _enqueue_kanban_notify(
        board,
        cl.card.id,
        'checklist',
        detail=text,
        push_suffix=f'checklist-add:{item.id}',
    )
    return jsonify({'success': True, 'card': payload}), 201


@kanban_bp.route('/api/checklist-items/<int:item_id>', methods=['PATCH', 'DELETE'])
@login_or_share_required
def api_checklist_item(item_id):
    item = KanbanChecklistItem.query.get_or_404(item_id)
    card = item.checklist.card
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    if request.method == 'DELETE':
        item_text = item.text
        db.session.delete(item)
        db.session.commit()
        payload = _serialize_card_detail(card, share_token=_share_token_from_request())
        _emit_board(board.id, 'card_updated', payload)
        _enqueue_kanban_notify(
            board,
            card.id,
            'checklist',
            detail=item_text,
            push_suffix=f'checklist-del:{item_id}',
        )
        return jsonify({'success': True, 'card': payload})
    data = request.get_json(silent=True) or {}
    if 'done' in data:
        item.done = bool(data['done'])
    if 'text' in data:
        item.text = (data['text'] or item.text).strip() or item.text
    if 'due_date' in data:
        raw_due = data.get('due_date')
        if raw_due in (None, ''):
            item.due_date = None
        else:
            try:
                item.due_date = datetime.fromisoformat(str(raw_due).replace('Z', '+00:00')).replace(tzinfo=None)
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid due_date'}), 400
    if 'assignee_id' in data:
        raw_assignee = data.get('assignee_id')
        if raw_assignee in (None, ''):
            item.assignee_id = None
        else:
            try:
                assignee_id = int(raw_assignee)
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid assignee_id'}), 400
            if not is_effective_board_member(board, assignee_id):
                return jsonify({'error': 'Assignee is not a board member'}), 400
            item.assignee_id = assignee_id
    db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    if any(k in data for k in ('done', 'text')):
        _enqueue_kanban_notify(
            board,
            card.id,
            'checklist',
            detail=item.text,
            push_suffix=f'checklist-upd:{item.id}:{int(portal_now_naive().timestamp())}',
        )
    return jsonify({'success': True, 'card': payload})


@kanban_bp.route('/api/boards/<int:board_id>/custom-fields', methods=['GET', 'POST'])
@login_or_share_required
def api_board_custom_fields(board_id):
    if request.method == 'GET':
        board, err = _require_board_view(board_id)
        if err:
            return err
        return jsonify({
            'success': True,
            'custom_fields': [_serialize_custom_field(f) for f in board.custom_fields],
        })
    board, err = _require_board_manage(board_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    field_type = (data.get('field_type') or 'text').strip().lower()
    if field_type not in CUSTOM_FIELD_TYPES:
        return jsonify({'error': 'Invalid field type'}), 400
    label = (data.get('label') or '').strip()
    if not label:
        return jsonify({'error': 'Label required'}), 400
    category_id = data.get('category_id')
    if category_id not in (None, ''):
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid category_id'}), 400
        if not KanbanCustomFieldCategory.query.filter_by(
            id=category_id, board_id=board.id
        ).first():
            return jsonify({'error': 'Category not found'}), 400
    else:
        category_id = None
    field = KanbanCustomField(
        board_id=board.id,
        category_id=category_id,
        field_type=field_type,
        label=label[:200],
        position=len(board.custom_fields),
        options=_parse_custom_field_options(data.get('options'), field_type),
        placeholder=(data.get('placeholder') or '').strip()[:255] or None,
    )
    db.session.add(field)
    db.session.commit()
    payload = _serialize_custom_field(field)
    _emit_board(board.id, 'custom_field_created', payload)
    return jsonify({'success': True, 'custom_field': payload, 'custom_fields': [_serialize_custom_field(f) for f in board.custom_fields]}), 201


@kanban_bp.route('/api/boards/<int:board_id>/custom-field-categories', methods=['GET', 'POST'])
@login_or_share_required
def api_custom_field_categories(board_id):
    if request.method == 'GET':
        board, err = _require_board_view(board_id)
        if err:
            return err
        return jsonify({
            'success': True,
            'categories': [
                {'id': c.id, 'name': c.name, 'position': c.position}
                for c in board.custom_field_categories
            ],
        })

    board, err = _require_board_manage(board_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400
    category = KanbanCustomFieldCategory(
        board_id=board.id,
        name=name[:200],
        position=len(board.custom_field_categories),
    )
    db.session.add(category)
    db.session.commit()
    payload = {'id': category.id, 'name': category.name, 'position': category.position}
    return jsonify({'success': True, 'category': payload}), 201


@kanban_bp.route('/api/custom-field-categories/<int:category_id>', methods=['PATCH', 'DELETE'])
@login_or_share_required
def api_custom_field_category(category_id):
    category = KanbanCustomFieldCategory.query.get_or_404(category_id)
    board, err = _require_board_manage(category.board_id)
    if err:
        return err
    if request.method == 'DELETE':
        db.session.delete(category)
        db.session.commit()
        return jsonify({'success': True})
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Name required'}), 400
        category.name = name[:200]
    if 'position' in data:
        try:
            category.position = int(data['position'])
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid position'}), 400
    db.session.commit()
    return jsonify({
        'success': True,
        'category': {'id': category.id, 'name': category.name, 'position': category.position},
    })


@kanban_bp.route('/api/custom-fields/<int:field_id>', methods=['PATCH', 'DELETE'])
@login_or_share_required
def api_custom_field(field_id):
    field = KanbanCustomField.query.get_or_404(field_id)
    if field.card_id:
        board, err = _require_board_edit(field.board_id)
    else:
        board, err = _require_board_manage(field.board_id)
    if err:
        return err
    if request.method == 'DELETE':
        card_id = field.card_id
        db.session.delete(field)
        db.session.commit()
        fields = [_serialize_custom_field(f) for f in board.custom_fields]
        _emit_board(board.id, 'custom_field_deleted', {'id': field_id})
        result = {'success': True, 'custom_fields': fields}
        if card_id:
            card = KanbanCard.query.get(card_id)
            if card:
                payload = _serialize_card_detail(card)
                _emit_board(board.id, 'card_updated', payload)
                result['card'] = payload
        return jsonify(result)
    data = request.get_json(silent=True) or {}
    if 'label' in data:
        label = (data.get('label') or '').strip()
        if label:
            field.label = label[:200]
    if 'field_type' in data:
        field_type = (data.get('field_type') or field.field_type).strip().lower()
        if field_type not in CUSTOM_FIELD_TYPES:
            return jsonify({'error': 'Invalid field type'}), 400
        field.field_type = field_type
    if 'placeholder' in data:
        field.placeholder = (data.get('placeholder') or '').strip()[:255] or None
    if 'category_id' in data:
        raw_category = data.get('category_id')
        if raw_category in (None, ''):
            field.category_id = None
        else:
            try:
                category_id = int(raw_category)
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid category_id'}), 400
            if not KanbanCustomFieldCategory.query.filter_by(
                id=category_id, board_id=board.id
            ).first():
                return jsonify({'error': 'Category not found'}), 400
            field.category_id = category_id
    if 'options' in data or 'field_type' in data:
        field.options = _parse_custom_field_options(data.get('options', field.options), field.field_type)
    if 'position' in data:
        try:
            field.position = int(data['position'])
        except (TypeError, ValueError):
            pass
    db.session.commit()
    payload = _serialize_custom_field(field)
    _emit_board(board.id, 'custom_field_updated', payload)
    return jsonify({
        'success': True,
        'custom_field': payload,
        'custom_fields': [_serialize_custom_field(f) for f in board.custom_fields],
    })


@kanban_bp.route('/api/cards/<int:card_id>/custom-fields', methods=['POST'])
@login_or_share_required
def api_create_card_custom_field(card_id):
    card = KanbanCard.query.get_or_404(card_id)
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    label = (data.get('label') or '').strip()
    if not label:
        return jsonify({'error': 'Label required'}), 400
    field_type = (data.get('field_type') or 'text').strip().lower()
    if field_type not in CUSTOM_FIELD_TYPES:
        return jsonify({'error': 'Invalid field type'}), 400
    field = KanbanCustomField(
        board_id=board.id,
        card_id=card.id,
        label=label[:200],
        field_type=field_type,
        position=len(card.local_fields),
        options=_parse_custom_field_options(data.get('options'), field_type),
        placeholder=(data.get('placeholder') or '').strip()[:255] or None,
    )
    db.session.add(field)
    db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    return jsonify({'success': True, 'custom_field': _serialize_custom_field(field), 'card': payload}), 201


@kanban_bp.route('/api/cards/<int:card_id>/custom-fields/enable', methods=['POST'])
@login_or_share_required
def api_enable_card_custom_field(card_id):
    card = KanbanCard.query.get_or_404(card_id)
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    try:
        field_id = int(data.get('field_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'field_id required'}), 400
    field = KanbanCustomField.query.filter_by(
        id=field_id, board_id=board.id, card_id=None
    ).first_or_404()
    enabled = KanbanCardFieldEnabled.query.filter_by(
        card_id=card.id, field_id=field.id
    ).first()
    if not enabled:
        db.session.add(KanbanCardFieldEnabled(card_id=card.id, field_id=field.id))
        db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    return jsonify({'success': True, 'card': payload})


@kanban_bp.route('/api/cards/<int:card_id>/custom-fields/enable/<int:field_id>', methods=['DELETE'])
@login_or_share_required
def api_disable_card_custom_field(card_id, field_id):
    card = KanbanCard.query.get_or_404(card_id)
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    enabled = KanbanCardFieldEnabled.query.filter_by(
        card_id=card.id, field_id=field_id
    ).first_or_404()
    if not enabled.field or enabled.field.board_id != board.id or enabled.field.card_id is not None:
        return jsonify({'error': 'Wrong board'}), 400
    db.session.delete(enabled)
    db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    return jsonify({'success': True, 'card': payload})


@kanban_bp.route('/api/cards/<int:card_id>/custom-field-values', methods=['PUT'])
@login_or_share_required
def api_set_card_custom_field_value(card_id):
    card = KanbanCard.query.get_or_404(card_id)
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    try:
        field_id = int(data.get('field_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'field_id required'}), 400
    field = KanbanCustomField.query.filter_by(id=field_id, board_id=board.id).first_or_404()
    raw = data.get('value')
    if field.field_type == 'checkbox':
        value = 'true' if raw in (True, 'true', '1', 1, 'on') else 'false'
    else:
        value = '' if raw is None else str(raw).strip()
    existing = KanbanCardFieldValue.query.filter_by(card_id=card.id, field_id=field.id).first()
    if existing:
        existing.value = value
    else:
        db.session.add(KanbanCardFieldValue(card_id=card.id, field_id=field.id, value=value))
    db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    return jsonify({'success': True, 'card': payload})


@kanban_bp.route('/api/cards/<int:card_id>/vote', methods=['POST'])
@login_or_share_required
def api_vote_card(card_id):
    card = KanbanCard.query.get_or_404(card_id)
    board = card.list.board
    if not _can_view_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    if not (card.poll_text or '').strip():
        return jsonify({'error': 'Keine Abstimmung vorhanden'}), 400
    actor_id = _actor_user_id(board)
    existing = KanbanCardVote.query.filter_by(card_id=card.id, user_id=actor_id).first()
    if existing:
        db.session.delete(existing)
        voted = False
    else:
        db.session.add(KanbanCardVote(card_id=card.id, user_id=actor_id))
        voted = True
    db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    return jsonify({'success': True, 'voted': voted, 'card': payload})


# ── Attachments ────────────────────────────────────────────────────────

@kanban_bp.route('/api/cards/<int:card_id>/attachments', methods=['POST'])
@login_or_share_required
def api_upload_attachment(card_id):
    card = KanbanCard.query.get_or_404(card_id)
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403

    # Link attachment (JSON)
    if request.is_json or (request.content_type or '').startswith('application/json'):
        data = request.get_json(silent=True) or {}
        raw_url = (data.get('url') or '').strip()
        if not raw_url:
            return jsonify({'error': 'URL required'}), 400
        if not raw_url.startswith(('http://', 'https://')):
            raw_url = 'https://' + raw_url
        title = (data.get('title') or data.get('name') or '').strip() or raw_url
        if len(title) > 255:
            title = title[:252] + '…'
        att = KanbanAttachment(
            card_id=card.id,
            filename='link',
            original_filename=title,
            mime_type='text/uri-list',
            file_size=None,
            storage_path='',
            url=raw_url,
            uploaded_by=_actor_user_id(board),
        )
        db.session.add(att)
        _log_activity(board.id, 'attachment_added', title, card.id)
        db.session.commit()
        payload = _serialize_card_detail(card, share_token=_share_token_from_request())
        _emit_board(board.id, 'card_updated', payload)
        _enqueue_kanban_notify(
            board,
            card.id,
            'upload',
            detail=title,
            push_suffix=f'upload:{att.id}',
        )
        return jsonify({
            'success': True,
            'card': payload,
            'attachment': _serialize_attachment(att, share_token=_share_token_from_request()),
        }), 201

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'No file'}), 400
    original = secure_filename(f.filename) or 'file'
    stored = f'{uuid.uuid4().hex}_{original}'
    path = os.path.join(_upload_root(), stored)
    f.save(path)
    mime = f.mimetype or mimetypes.guess_type(original)[0]
    att = KanbanAttachment(
        card_id=card.id,
        filename=stored,
        original_filename=original,
        mime_type=mime,
        file_size=os.path.getsize(path),
        storage_path=path,
        uploaded_by=_actor_user_id(board),
    )
    db.session.add(att)
    db.session.flush()
    if not card.cover_attachment_id and (mime or '').startswith('image/'):
        card.cover_attachment_id = att.id
    _log_activity(board.id, 'attachment_added', original, card.id)
    db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    _enqueue_kanban_notify(
        board,
        card.id,
        'upload',
        detail=original,
        push_suffix=f'upload:{att.id}',
    )
    return jsonify({
        'success': True,
        'card': payload,
        'attachment': _serialize_attachment(att, share_token=_share_token_from_request()),
    }), 201


@kanban_bp.route('/attachments/<int:attachment_id>/download')
@login_required
@check_module_access('module_kanban')
def download_attachment(attachment_id):
    att = KanbanAttachment.query.get_or_404(attachment_id)
    board = att.card.list.board
    if not can_view_board(current_user, board):
        flash(translate('kanban.flash.no_access'), 'danger')
        return redirect(url_for('kanban.index'))
    if att.url and not att.storage_path:
        return redirect(att.url)
    if not att.storage_path or not os.path.isfile(att.storage_path):
        flash(translate('kanban.flash.no_access'), 'danger')
        return redirect(url_for('kanban.index'))
    return send_file(att.storage_path, as_attachment=True, download_name=att.original_filename or att.filename)


# ── OnlyOffice for Kanban attachments ───────────────────────────────────

def _kanban_oo_cors(payload, status_code=200):
    response = jsonify(payload)
    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    if onlyoffice_url.startswith('http'):
        from urllib.parse import urlparse
        parsed = urlparse(onlyoffice_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response, status_code


@kanban_bp.route('/attachments/<int:attachment_id>/edit-onlyoffice')
@login_required
@check_module_access('module_kanban')
def edit_onlyoffice(attachment_id):
    """Open a Kanban attachment in OnlyOffice (auto-save via callback)."""
    from types import SimpleNamespace
    from urllib.parse import quote
    import logging

    from app.utils.i18n import get_current_language
    from app.utils.onlyoffice import (
        get_onlyoffice_document_type,
        get_onlyoffice_file_type,
        generate_onlyoffice_access_token,
        generate_onlyoffice_token,
        build_onlyoffice_document_key,
    )

    if not is_onlyoffice_enabled():
        flash('ONLYOFFICE ist nicht aktiviert.', 'warning')
        return redirect(url_for('kanban.index'))

    att = KanbanAttachment.query.get_or_404(attachment_id)
    card = att.card
    board = card.list.board
    if not can_view_board(current_user, board):
        flash(translate('kanban.flash.no_access'), 'danger')
        return redirect(url_for('kanban.index'))
    if att.url or not att.storage_path or not os.path.isfile(att.storage_path):
        flash('Datei nicht gefunden.', 'danger')
        return redirect(url_for('kanban.board', board_id=board.id, card=card.id))

    can_edit = can_edit_board(current_user, board)
    name = att.original_filename or att.filename or 'Dokument'
    file_ext = os.path.splitext(name)[1].lower()
    if not is_onlyoffice_file_type(file_ext):
        flash('Dieser Dateityp wird von ONLYOFFICE nicht unterstützt.', 'warning')
        return redirect(url_for('kanban.board', board_id=board.id, card=card.id))

    document_type = get_onlyoffice_document_type(file_ext)
    file_type = get_onlyoffice_file_type(file_ext)
    document_key = build_onlyoffice_document_key(
        'kanban_att', att.id, att.file_size or 0, att.storage_path
    )
    access_token = generate_onlyoffice_access_token(att.id, current_user.id)

    public_url = (current_app.config.get('ONLYOFFICE_PUBLIC_URL') or '').strip()
    if public_url:
        public_url = public_url.rstrip('/')
        base_url = url_for('kanban.onlyoffice_document', attachment_id=att.id)
        document_url = f"{public_url}{base_url}?token={quote(access_token, safe='')}"
        callback_url = f"{public_url}{url_for('kanban.onlyoffice_callback', attachment_id=att.id)}"
    else:
        base_url = url_for('kanban.onlyoffice_document', attachment_id=att.id, _external=True)
        document_url = f"{base_url}?token={quote(access_token, safe='')}"
        callback_url = url_for('kanban.onlyoffice_callback', attachment_id=att.id, _external=True)

    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    if onlyoffice_url.startswith('http'):
        api_url = f"{onlyoffice_url.rstrip('/')}/web-apps/apps/api/documents/api.js"
    else:
        if not onlyoffice_url.startswith('/'):
            onlyoffice_url = '/' + onlyoffice_url
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{request.scheme}://{request.host}{onlyoffice_url}/web-apps/apps/api/documents/api.js"

    user_image = None
    if getattr(current_user, 'profile_picture', None):
        try:
            user_image = url_for('settings.profile_picture', filename=current_user.profile_picture, _external=True)
        except Exception:
            user_image = None

    editor_config = {
        "document": {
            "fileType": file_type,
            "key": document_key,
            "title": name,
            "url": document_url,
        },
        "documentType": document_type,
        "editorConfig": {
            "callbackUrl": callback_url,
            "mode": "edit" if can_edit else "view",
            "user": {
                "id": str(current_user.id),
                "name": current_user.full_name or current_user.email,
            },
            "customization": {
                "uiTheme": (
                    "theme-contrast-dark"
                    if getattr(current_user, "oled_mode", False)
                    else ("theme-dark" if getattr(current_user, "dark_mode", False) else "theme-classic-light")
                )
            },
        },
    }
    if user_image:
        editor_config["editorConfig"]["user"]["image"] = user_image

    token = generate_onlyoffice_token(editor_config)
    return_url = url_for('kanban.board', board_id=board.id, card=card.id)
    file_proxy = SimpleNamespace(
        id=att.id,
        name=name,
        created_at=att.created_at,
        updated_at=att.created_at,
        folder_id=None,
        uploader=att.uploader,
    )

    logging.info("Kanban OnlyOffice document_url=%s callback=%s", document_url, callback_url)

    return render_template(
        'files/edit_onlyoffice.html',
        file=file_proxy,
        document_key=document_key,
        document_type=document_type,
        file_type=file_type,
        document_url=document_url,
        callback_url=callback_url,
        onlyoffice_api_url=api_url,
        onlyoffice_url=onlyoffice_url,
        token=token or '',
        guest_mode=False,
        return_url=return_url,
        download_url=url_for('kanban.download_attachment', attachment_id=att.id),
        accent_color=getattr(current_user, 'accent_color', None) or '#0d6efd',
        accent_style=getattr(current_user, 'accent_style', None) or 'linear-gradient(45deg, #0d6efd, #0d6efd)',
        current_language=get_current_language(),
        user_image=user_image or '',
        presence_enabled=False,
        is_mobile_client=False,
        theme_dark=bool(getattr(current_user, 'dark_mode', False)),
        theme_oled=bool(getattr(current_user, 'oled_mode', False)),
        onlyoffice_ui_theme=editor_config["editorConfig"]["customization"]["uiTheme"],
        forcesave_url=url_for('kanban.onlyoffice_forcesave', attachment_id=att.id),
    )


@kanban_bp.route('/api/onlyoffice-document/<int:attachment_id>', methods=['GET', 'HEAD', 'OPTIONS'])
def onlyoffice_document(attachment_id):
    """Serve Kanban attachment binary to OnlyOffice Document Server."""
    from app.utils.onlyoffice import validate_onlyoffice_access_token

    if request.method == 'OPTIONS':
        return _kanban_oo_cors({})[0]

    if not is_onlyoffice_enabled():
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404

    access_token = request.args.get('token')
    if not access_token or not validate_onlyoffice_access_token(access_token, attachment_id):
        return jsonify({'error': 'Invalid access token'}), 403

    att = KanbanAttachment.query.get_or_404(attachment_id)
    if not att.storage_path or not os.path.isfile(att.storage_path):
        return jsonify({'error': 'File not found'}), 404

    name = att.original_filename or att.filename or 'document'
    mime = att.mime_type or 'application/octet-stream'
    response = send_file(att.storage_path, mimetype=mime, download_name=name, as_attachment=False)
    return response


@kanban_bp.route('/onlyoffice-callback/<int:attachment_id>', methods=['POST', 'OPTIONS'])
def onlyoffice_callback(attachment_id):
    """Autosave callback from OnlyOffice for Kanban attachments."""
    import logging

    from app.utils.onlyoffice import (
        is_onlyoffice_callback_download_url_allowed,
        verify_onlyoffice_callback_token,
    )

    if request.method == 'OPTIONS':
        return _kanban_oo_cors({})[0]

    if not is_onlyoffice_enabled():
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404

    data = request.get_json(silent=True)
    if not data:
        return _kanban_oo_cors({'error': 'No data'}, 400)[0]

    ok, signed_payload, reason = verify_onlyoffice_callback_token(
        data, request.headers.get('Authorization', '')
    )
    if not ok:
        logging.warning('Kanban OnlyOffice callback rejected: %s', reason)
        return _kanban_oo_cors({'error': 'Unauthorized callback'}, 403)[0]

    payload = signed_payload if isinstance(signed_payload, dict) else data
    status = payload.get('status')
    # 2 = ready for saving (close), 6 = force save while editing
    if status in (2, 6):
        saved_url = payload.get('url')
        if saved_url:
            allowed, why = is_onlyoffice_callback_download_url_allowed(saved_url)
            if not allowed:
                logging.warning('Kanban OnlyOffice download blocked: %s', why)
                return _kanban_oo_cors({'error': 0})[0]
            try:
                import requests as http_requests
                resp = http_requests.get(saved_url, timeout=60)
                resp.raise_for_status()
                content = resp.content
            except Exception as exc:
                logging.error('Kanban OnlyOffice download failed: %s', exc)
                return _kanban_oo_cors({'error': 0})[0]

            att = KanbanAttachment.query.get(attachment_id)
            if att and att.storage_path:
                try:
                    os.makedirs(os.path.dirname(att.storage_path) or '.', exist_ok=True)
                    with open(att.storage_path, 'wb') as fh:
                        fh.write(content)
                    att.file_size = len(content)
                    db.session.commit()
                    logging.info('Kanban OnlyOffice saved attachment %s (%s bytes)', attachment_id, len(content))
                except Exception as exc:
                    logging.error('Kanban OnlyOffice write failed: %s', exc)

    return _kanban_oo_cors({'error': 0})[0]


@kanban_bp.route('/api/onlyoffice-forcesave/<int:attachment_id>', methods=['POST'])
@login_required
@check_module_access('module_kanban')
def onlyoffice_forcesave(attachment_id):
    """Force-save an open Kanban OnlyOffice attachment."""
    import logging

    from app.utils.onlyoffice import send_onlyoffice_command

    if not is_onlyoffice_enabled():
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404

    att = KanbanAttachment.query.get_or_404(attachment_id)
    board = att.card.list.board
    if not can_view_board(current_user, board):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    key = (payload.get('key') or '').strip()
    if not key or len(key) > 128:
        return jsonify({'success': False, 'error': 'invalid_key'}), 400

    ok, error_code, detail = send_onlyoffice_command('forcesave', key)
    logging.info(
        'Kanban OnlyOffice forcesave attachment=%s ok=%s error_code=%s detail=%s',
        attachment_id, ok, error_code, detail,
    )
    return jsonify({'success': ok, 'error_code': error_code, 'detail': detail})


@kanban_bp.route('/attachments/<int:attachment_id>/preview')
@login_required
@check_module_access('module_kanban')
def preview_attachment(attachment_id):
    att = KanbanAttachment.query.get_or_404(attachment_id)
    board = att.card.list.board
    if not can_view_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403
    if att.url and not att.storage_path:
        return redirect(att.url)
    if not att.storage_path or not os.path.isfile(att.storage_path):
        return jsonify({'error': 'Not found'}), 404
    mime = att.mime_type or 'application/octet-stream'
    if mime.startswith('image/') or mime == 'application/pdf':
        return send_file(att.storage_path, mimetype=mime)
    return send_file(att.storage_path, as_attachment=True, download_name=att.original_filename or att.filename)


def _get_share_attachment(token: str, attachment_id: int):
    share = get_share_by_token(token)
    if not share or share.resource_type != 'kanban_board' or share_is_expired(share):
        return None, (jsonify({'error': 'Forbidden'}), 403)
    if share.password_hash and not _share_guest_ok(token):
        return None, (jsonify({'error': 'Forbidden'}), 403)
    att = KanbanAttachment.query.get_or_404(attachment_id)
    try:
        share_board_id = int(share.resource_id)
    except (TypeError, ValueError):
        return None, (jsonify({'error': 'Forbidden'}), 403)
    if att.card.list.board_id != share_board_id:
        return None, (jsonify({'error': 'Forbidden'}), 403)
    return att, None


@kanban_bp.route('/share/<token>/attachments/<int:attachment_id>/preview')
def share_preview_attachment(token, attachment_id):
    att, err = _get_share_attachment(token, attachment_id)
    if err:
        return err
    if att.url and not att.storage_path:
        return redirect(att.url)
    if not att.storage_path or not os.path.isfile(att.storage_path):
        return jsonify({'error': 'Not found'}), 404
    mime = att.mime_type or 'application/octet-stream'
    if mime.startswith('image/') or mime == 'application/pdf':
        return send_file(att.storage_path, mimetype=mime)
    return send_file(
        att.storage_path,
        as_attachment=True,
        download_name=att.original_filename or att.filename,
    )


@kanban_bp.route('/share/<token>/attachments/<int:attachment_id>/download')
def share_download_attachment(token, attachment_id):
    att, err = _get_share_attachment(token, attachment_id)
    if err:
        return err
    if att.url and not att.storage_path:
        return redirect(att.url)
    if not att.storage_path or not os.path.isfile(att.storage_path):
        return jsonify({'error': 'Not found'}), 404
    return send_file(
        att.storage_path,
        as_attachment=True,
        download_name=att.original_filename or att.filename,
    )


@kanban_bp.route('/api/attachments/<int:attachment_id>', methods=['DELETE'])
@login_or_share_required
def api_delete_attachment(attachment_id):
    att = KanbanAttachment.query.get_or_404(attachment_id)
    card = att.card
    board = card.list.board
    if not _can_edit_board_ctx(board):
        return jsonify({'error': 'Forbidden'}), 403
    if card.cover_attachment_id == att.id:
        card.cover_attachment_id = None
    try:
        if att.storage_path and os.path.isfile(att.storage_path):
            os.remove(att.storage_path)
    except OSError:
        pass
    db.session.delete(att)
    db.session.commit()
    payload = _serialize_card_detail(card, share_token=_share_token_from_request())
    _emit_board(board.id, 'card_updated', payload)
    return jsonify({'success': True, 'card': payload})


# ── Members / Activity / Templates / Filter ─────────────────────────────

@kanban_bp.route('/api/boards/<int:board_id>/members', methods=['GET', 'POST'])
@login_required
@check_module_access('module_kanban')
def api_board_members(board_id):
    board, err = _require_board_view(board_id)
    if err:
        return err
    if request.method == 'GET':
        return jsonify({'members': _serialize_board_members(board)})
    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    user_id = int(data['user_id'])
    role = (data.get('role') or 'member').strip()
    if role not in ('owner', 'admin', 'member'):
        role = 'member'
    existing = KanbanBoardMember.query.filter_by(board_id=board.id, user_id=user_id).first()
    if existing:
        existing.role = role
    else:
        db.session.add(KanbanBoardMember(board_id=board.id, user_id=user_id, role=role))
    _log_activity(board.id, 'member_added', str(user_id))
    db.session.commit()
    _emit_board(board.id, 'members_updated', {'board_id': board.id})
    return jsonify({'success': True})


@kanban_bp.route('/api/boards/<int:board_id>/members/<int:user_id>', methods=['DELETE'])
@login_required
@check_module_access('module_kanban')
def api_remove_member(board_id, user_id):
    board, err = _require_board_view(board_id)
    if err:
        return err
    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403
    m = KanbanBoardMember.query.filter_by(board_id=board.id, user_id=user_id).first()
    if m and m.role != 'owner':
        db.session.delete(m)
        db.session.commit()
        _emit_board(board.id, 'members_updated', {'board_id': board.id})
    return jsonify({'success': True})


@kanban_bp.route('/api/boards/<int:board_id>/activity')
@login_or_share_required
def api_board_activity(board_id):
    board, err = _require_board_view(board_id)
    if err:
        return err
    card_id = request.args.get('card_id', type=int)
    q = KanbanActivity.query.filter_by(board_id=board.id)
    if card_id:
        q = q.filter_by(card_id=card_id)
    rows = q.order_by(KanbanActivity.created_at.desc()).limit(50).all()
    return jsonify({
        'activities': [
            {
                'id': a.id,
                'action': a.action,
                'action_label': _activity_label(a.action),
                'detail': a.detail,
                'card_id': a.card_id,
                'user': _user_brief(a.user),
                'created_at': a.created_at.isoformat() if a.created_at else None,
                'created_at_display': a.created_at.strftime('%d.%m.%Y, %H:%M') if a.created_at else None,
            }
            for a in rows
        ]
    })


def _activity_label(action: str) -> str:
    labels = {
        'board_created': 'Board erstellt',
        'board_closed': 'Board geschlossen',
        'board_reopened': 'Board wieder geöffnet',
        'list_created': 'Liste erstellt',
        'list_updated': 'Liste aktualisiert',
        'list_deleted': 'Liste gelöscht',
        'card_created': 'Karte erstellt',
        'card_updated': 'Karte aktualisiert',
        'card_moved': 'Karte verschoben',
        'card_archived': 'Karte archiviert',
        'card_restored': 'Karte wiederhergestellt',
        'card_completed': 'Karte als erledigt markiert',
        'card_uncompleted': 'Erledigt-Status entfernt',
        'attachment_added': 'Anhang hinzugefügt',
        'member_added': 'Mitglied hinzugefügt',
        'label_created': 'Label erstellt',
    }
    return labels.get(action or '', action or 'Aktivität')


@kanban_bp.route('/api/boards/<int:board_id>/filter', methods=['GET', 'POST'])
@login_or_share_required
def api_filter_cards(board_id):
    board, err = _require_board_view(board_id)
    if err:
        return err
    actor_id = _actor_user_id(board)

    # Accept query string or JSON body
    data = request.get_json(silent=True) or {}
    q = (data.get('q') if 'q' in data else request.args.get('q') or '').strip().lower()
    label_ids = data.get('label_ids') or []
    if not label_ids and request.args.get('label_id'):
        label_ids = [request.args.get('label_id', type=int)]
    label_ids = [int(x) for x in label_ids if x is not None]
    assignee_ids = data.get('assignee_ids') or []
    if not assignee_ids and request.args.get('assignee_id'):
        assignee_ids = [request.args.get('assignee_id', type=int)]
    assignee_ids = [int(x) for x in assignee_ids if x is not None]

    no_members = bool(data.get('no_members'))
    assigned_to_me = bool(data.get('assigned_to_me'))
    completed = data.get('completed')  # True | False | None
    if completed is None and request.args.get('completed') is not None:
        completed = request.args.get('completed') in ('1', 'true', 'yes')
    no_labels = bool(data.get('no_labels'))

    due = data.get('due') or request.args.get('due')  # none|overdue|day|week|month
    activity = data.get('activity')  # week|two_weeks|four_weeks|none_four_weeks

    matching = []
    now = portal_now_naive()
    from datetime import timedelta
    for lst in board.lists:
        if lst.archived_at:
            continue
        for card in lst.cards:
            if card.archived_at:
                continue
            if q:
                hay = f"{card.title or ''} {card.description or ''}".lower()
                label_names = ' '.join((cl.label.name or '') for cl in card.card_labels if cl.label).lower()
                member_names = ' '.join(
                    ((a.user.full_name if a.user else '') or (a.user.email if a.user else '') or '')
                    for a in card.assignees
                ).lower()
                if q not in hay and q not in label_names and q not in member_names:
                    continue
            if no_members and card.assignees:
                continue
            if assigned_to_me and not any(a.user_id == actor_id for a in card.assignees):
                continue
            if assignee_ids and not any(a.user_id in assignee_ids for a in card.assignees):
                continue
            if completed is True and not card.completed_at:
                continue
            if completed is False and card.completed_at:
                continue
            if no_labels and card.card_labels:
                continue
            if label_ids and not any(cl.label_id in label_ids for cl in card.card_labels):
                continue
            if due == 'none' and card.due_date:
                continue
            if due == 'overdue' and (not card.due_date or card.due_date >= now):
                continue
            if due == 'day' and (not card.due_date or card.due_date < now or card.due_date > now + timedelta(days=1)):
                continue
            if due == 'week' and (not card.due_date or card.due_date < now or card.due_date > now + timedelta(days=7)):
                continue
            if due == 'month' and (not card.due_date or card.due_date < now or card.due_date > now + timedelta(days=30)):
                continue
            if activity:
                stamp = card.updated_at or card.created_at
                if activity == 'week' and (not stamp or stamp < now - timedelta(days=7)):
                    continue
                if activity == 'two_weeks' and (not stamp or stamp < now - timedelta(days=14)):
                    continue
                if activity == 'four_weeks' and (not stamp or stamp < now - timedelta(days=28)):
                    continue
                if activity == 'none_four_weeks' and stamp and stamp >= now - timedelta(days=28):
                    continue
            matching.append(card.id)
    return jsonify({'card_ids': matching})


@kanban_bp.route('/api/templates', methods=['GET', 'POST'])
@login_required
@check_module_access('module_kanban')
def api_templates():
    if request.method == 'GET':
        rows = KanbanBoardTemplate.query.filter(
            db.or_(
                KanbanBoardTemplate.is_global.is_(True),
                KanbanBoardTemplate.created_by == current_user.id,
            )
        ).order_by(KanbanBoardTemplate.name).all()
        return jsonify({
            'templates': [
                {'id': t.id, 'name': t.name, 'description': t.description, 'is_global': t.is_global}
                for t in rows
            ]
        })
    data = request.get_json(silent=True) or {}
    board_id = data.get('board_id')
    board = KanbanBoard.query.get_or_404(int(board_id))
    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403
    payload = {
        'lists': [{'title': l.title} for l in board.lists if not l.archived_at],
        'labels': [{'name': lb.name, 'color': lb.color} for lb in board.labels],
    }
    tmpl = KanbanBoardTemplate(
        name=(data.get('name') or f'Vorlage: {board.title}').strip(),
        description=(data.get('description') or '').strip() or None,
        payload_json=json.dumps(payload),
        created_by=current_user.id,
        is_global=bool(data.get('is_global')) and getattr(current_user, 'is_admin', False),
    )
    db.session.add(tmpl)
    db.session.commit()
    return jsonify({'success': True, 'id': tmpl.id}), 201


# ── Shares ─────────────────────────────────────────────────────────────

def _serialize_kanban_share(share: PublicShare) -> dict:
    data = serialize_share_link(share)
    creator = User.query.get(share.created_by) if share.created_by else None
    data['created_by'] = _user_brief(creator)
    data['created_at'] = share.created_at.isoformat() if share.created_at else None
    data['created_at_display'] = share.created_at.strftime('%d.%m.%Y %H:%M') if share.created_at else None
    data['mode_label'] = 'Bearbeiten' if share.mode == 'edit' else 'Nur ansehen'
    return data


@kanban_bp.route('/api/boards/<int:board_id>/shares', methods=['GET', 'POST'])
@login_required
@check_module_access('module_kanban')
def api_board_shares(board_id):
    board, err = _require_board_view(board_id)
    if err:
        return err
    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403

    if request.method == 'GET':
        shares = get_shares_for_resource('kanban_board', board.id)
        pw_map = session.get('kanban_share_passwords') or {}
        out = []
        for s in shares:
            row = _serialize_kanban_share(s)
            known = pw_map.get(str(s.id))
            if known and s.password_hash:
                row['password'] = known
            out.append(row)
        return jsonify({'shares': out})

    data = request.get_json(silent=True) or {}
    mode = (data.get('mode') or 'view').strip().lower()
    if mode not in ('view', 'edit'):
        mode = 'view'
    password = (data.get('password') or '').strip() or None
    expires_at = None
    if data.get('expires_at'):
        try:
            expires_at = datetime.fromisoformat(str(data['expires_at']).replace('Z', ''))
        except ValueError:
            pass
    share = PublicShare(
        resource_type='kanban_board',
        resource_id=board.id,
        mode=mode,
        token=generate_unique_share_token(),
        enabled=True,
        password_hash=generate_password_hash(password) if password else None,
        expires_at=expires_at,
        label=(data.get('label') or '').strip() or None,
        created_by=current_user.id,
    )
    db.session.add(share)
    db.session.commit()
    payload = _serialize_kanban_share(share)
    if password:
        payload['password'] = password
        pw_map = session.get('kanban_share_passwords') or {}
        pw_map[str(share.id)] = password
        session['kanban_share_passwords'] = pw_map
        session.modified = True
    return jsonify({'success': True, 'share': payload}), 201


@kanban_bp.route('/api/boards/<int:board_id>/shares/<int:share_id>', methods=['PATCH', 'DELETE'])
@login_required
@check_module_access('module_kanban')
def api_board_share_detail(board_id, share_id):
    board, err = _require_board_view(board_id)
    if err:
        return err
    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403

    share = PublicShare.query.filter_by(
        id=share_id,
        resource_type='kanban_board',
        resource_id=board.id,
    ).first_or_404()

    if request.method == 'DELETE':
        pw_map = session.get('kanban_share_passwords') or {}
        pw_map.pop(str(share.id), None)
        session['kanban_share_passwords'] = pw_map
        session.modified = True
        db.session.delete(share)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    if 'mode' in data:
        mode = (data.get('mode') or 'view').strip().lower()
        if mode in ('view', 'edit'):
            share.mode = mode
    new_password = None
    if data.get('clear_password'):
        share.password_hash = None
        pw_map = session.get('kanban_share_passwords') or {}
        pw_map.pop(str(share.id), None)
        session['kanban_share_passwords'] = pw_map
        session.modified = True
    elif 'password' in data:
        raw = (data.get('password') or '').strip()
        if raw:
            share.password_hash = generate_password_hash(raw)
            new_password = raw
            pw_map = session.get('kanban_share_passwords') or {}
            pw_map[str(share.id)] = raw
            session['kanban_share_passwords'] = pw_map
            session.modified = True
    if 'enabled' in data:
        share.enabled = bool(data.get('enabled'))
    if 'expires_at' in data:
        raw_exp = data.get('expires_at')
        if not raw_exp:
            share.expires_at = None
        else:
            try:
                share.expires_at = datetime.fromisoformat(str(raw_exp).replace('Z', ''))
            except ValueError:
                pass
    db.session.commit()
    payload = _serialize_kanban_share(share)
    if new_password:
        payload['password'] = new_password
    else:
        known = (session.get('kanban_share_passwords') or {}).get(str(share.id))
        if known and share.password_hash:
            payload['password'] = known
    return jsonify({'success': True, 'share': payload})


@kanban_bp.route('/share/<token>', methods=['GET', 'POST'])
def public_share(token):
    share = get_share_by_token(token)
    if not share or share.resource_type != 'kanban_board' or share_is_expired(share):
        return render_template('kanban/share_unavailable.html'), 404
    board = KanbanBoard.query.get(share.resource_id)
    if not board or board.closed_at:
        return render_template('kanban/share_unavailable.html'), 404

    if share.password_hash and not _share_guest_ok(token):
        if request.method == 'POST':
            pwd = request.form.get('password') or ''
            if check_password_hash(share.password_hash, pwd):
                session[f'share_auth_{token}'] = True
                return redirect(url_for('kanban.public_share', token=token))
            flash(translate('kanban.share.wrong_password'), 'danger')
        return render_template('kanban/share_auth.html', token=token, board=board)

    session['kanban_share_token'] = token
    session.modified = True
    can_edit_share = share.mode == 'edit'
    cover_url = _board_cover_url(board)
    return render_template(
        'kanban/board.html',
        board=board,
        board_json=_serialize_board(board, full=True, share_token=token),
        can_edit=can_edit_share,
        can_manage=False,
        background_css=_board_background_css(board),
        background_image_url=cover_url,
        backgrounds=BOARD_BACKGROUNDS,
        onlyoffice_enabled=False,
        share_token=token,
        is_share=True,
    )
