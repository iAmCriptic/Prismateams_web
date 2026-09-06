"""Cards, labels, assignees, checklists, custom fields, and votes."""

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
