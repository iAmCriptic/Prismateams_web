"""Shared helpers for the kanban module."""

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
from sqlalchemy.orm import joinedload, selectinload
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

_COMMENT_COUNT_CHUNK = 500


def _card_board_summary_load_options():
    """Collections needed for card tiles on the board (same JSON as before)."""
    return (
        selectinload(KanbanCard.card_labels).joinedload(KanbanCardLabel.label),
        selectinload(KanbanCard.assignees).joinedload(KanbanCardAssignee.user),
        selectinload(KanbanCard.checklists).selectinload(KanbanChecklist.items),
        selectinload(KanbanCard.attachments),
        selectinload(KanbanCard.votes),
    )


def _board_full_load_options():
    cards = selectinload(KanbanBoard.lists).selectinload(KanbanList.cards)
    return (
        joinedload(KanbanBoard.team),
        selectinload(KanbanBoard.labels),
        selectinload(KanbanBoard.members).joinedload(KanbanBoardMember.user),
        selectinload(KanbanBoard.custom_fields),
        selectinload(KanbanBoard.custom_field_categories),
        cards.options(*_card_board_summary_load_options()),
    )


def _list_full_load_options():
    return (
        joinedload(KanbanList.board),
        selectinload(KanbanList.cards).options(*_card_board_summary_load_options()),
    )


def _card_detail_load_options():
    return (
        joinedload(KanbanCard.list).joinedload(KanbanList.board),
        selectinload(KanbanCard.card_labels).joinedload(KanbanCardLabel.label),
        selectinload(KanbanCard.assignees).joinedload(KanbanCardAssignee.user),
        selectinload(KanbanCard.checklists)
        .selectinload(KanbanChecklist.items)
        .joinedload(KanbanChecklistItem.assignee),
        selectinload(KanbanCard.attachments),
        selectinload(KanbanCard.votes),
        selectinload(KanbanCard.field_values),
        selectinload(KanbanCard.enabled_fields).joinedload(KanbanCardFieldEnabled.field),
        selectinload(KanbanCard.local_fields),
    )


def _reload_with_options(model, obj, *options):
    """Re-fetch obj with eager loaders. Identity map keeps the same instance."""
    if obj is None or getattr(obj, 'id', None) is None:
        return obj
    loaded = db.session.get(
        model,
        obj.id,
        options=list(options),
        populate_existing=True,
    )
    return loaded or obj


def _kanban_comment_counts(card_ids) -> dict[int, int]:
    """One GROUP BY per chunk instead of Comment.count() per card."""
    ids = []
    seen = set()
    for raw in card_ids or ():
        if raw is None:
            continue
        cid = int(raw)
        if cid in seen:
            continue
        seen.add(cid)
        ids.append(cid)
    if not ids:
        return {}
    counts: dict[int, int] = {}
    for offset in range(0, len(ids), _COMMENT_COUNT_CHUNK):
        chunk = ids[offset:offset + _COMMENT_COUNT_CHUNK]
        rows = (
            db.session.query(Comment.content_id, db.func.count(Comment.id))
            .filter(
                Comment.content_type == 'kanban_card',
                Comment.content_id.in_(chunk),
                Comment.is_deleted.is_(False),
            )
            .group_by(Comment.content_id)
            .all()
        )
        for content_id, cnt in rows:
            counts[int(content_id)] = int(cnt)
    return counts


def _visible_cards_in_list(lst: KanbanList, include_archived_cards: bool = False) -> list[KanbanCard]:
    return [c for c in lst.cards if include_archived_cards or not c.archived_at]


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


def _kanban_sse_url(board_id, is_share=False):
    """SSE-URL nur mit Redis; sonst pollt der Client inkrementell."""
    if is_share or not current_app.config.get('REDIS_ENABLED'):
        return ''
    return url_for('sse.kanban_events', board_id=board_id)


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


def _serialize_card_summary(
    card: KanbanCard,
    share_token: str | None = None,
    *,
    comment_count: int | None = None,
    comment_counts: dict[int, int] | None = None,
) -> dict:
    actor_id = _actor_user_id(card.list.board if card.list else None)
    cover = None
    if card.cover_attachment_id:
        att = next((a for a in card.attachments if a.id == card.cover_attachment_id), None)
        if not att:
            att = KanbanAttachment.query.get(card.cover_attachment_id)
        if att:
            cover = _serialize_attachment(att, share_token=share_token)
    if comment_count is None:
        if comment_counts is not None:
            comment_count = comment_counts.get(card.id, 0)
        else:
            comment_count = _kanban_comment_counts([card.id]).get(card.id, 0)
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
    card = _reload_with_options(KanbanCard, card, *_card_detail_load_options())
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
    *,
    comment_counts: dict[int, int] | None = None,
    already_loaded: bool = False,
) -> dict:
    if not already_loaded:
        lst = _reload_with_options(KanbanList, lst, *_list_full_load_options())
    cards = _visible_cards_in_list(lst, include_archived_cards)
    if comment_counts is None:
        comment_counts = _kanban_comment_counts([c.id for c in cards])
    return {
        'id': lst.id,
        'title': lst.title,
        'position': lst.position,
        'archived': bool(lst.archived_at),
        'card_count': len(cards),
        'cards': [
            _serialize_card_summary(c, share_token=share_token, comment_counts=comment_counts)
            for c in cards
        ],
    }


def _serialize_board(
    board: KanbanBoard,
    *,
    full: bool = False,
    share_token: str | None = None,
) -> dict:
    if full:
        board = _reload_with_options(KanbanBoard, board, *_board_full_load_options())
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
        lists = [lst for lst in board.lists if not lst.archived_at]
        comment_counts = _kanban_comment_counts([
            card.id
            for lst in lists
            for card in _visible_cards_in_list(lst)
        ])
        data['lists'] = [
            _serialize_list(
                lst,
                share_token=share_token,
                comment_counts=comment_counts,
                already_loaded=True,
            )
            for lst in lists
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


__all__ = [
    '_share_token_from_request',
    '_get_valid_share_for_board',
    '_actor_user_id',
    '_enqueue_kanban_notify',
    '_can_view_board_ctx',
    '_can_edit_board_ctx',
    '_can_manage_board_ctx',
    'kanban_board_cover_url',
    'login_or_share_required',
    '_kanban_sse_url',
    '_emit_board',
    '_log_activity',
    '_upload_root',
    '_boards_upload_root',
    '_board_cover_file_path',
    '_board_cover_url',
    '_board_background_css',
    '_delete_board_cover_file',
    '_serialize_board_members',
    '_user_brief',
    '_attachment_url',
    '_serialize_attachment',
    '_checklist_progress',
    '_serialize_checklist_item',
    '_serialize_card_summary',
    '_parse_custom_field_options',
    '_serialize_custom_field',
    '_serialize_card_detail',
    '_serialize_list',
    '_serialize_board',
    '_require_board_view',
    '_require_board_edit',
    '_require_board_manage',
    '_track_view',
    '_share_guest_ok',
    '_user_kanban_teams',
    '_user_may_use_team',
]
