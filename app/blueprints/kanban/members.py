"""Members, activity, filters, templates, and public shares."""

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
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app import db
from app.models.comment import Comment
from app.models.public_share import PublicShare
from app.models.kanban import (
    KanbanActivity,
    KanbanActivityRead,
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
from app.utils.access_control import check_module_access, has_module_access
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

# ── Members / Activity / Templates / Filter ─────────────────────────────

@kanban_bp.route('/api/boards/<int:board_id>/members', methods=['GET', 'POST'])
@login_required
@check_module_access('module_kanban')
def api_board_members(board_id):
    board, err = _require_board_view(board_id)
    if err:
        return err
    if request.method == 'GET':
        return jsonify({
            'members': _serialize_board_members(board),
            'can_manage': can_manage_board(current_user, board),
            'visibility': board.visibility,
            'team_name': board.team.name if (board.team or board.team_id) else None,
            'created_by': board.created_by,
        })
    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data['user_id'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'User ID required'}), 400

    target_user = User.query.get(user_id)
    if not target_user or not target_user.is_active:
        return jsonify({'error': 'User not found or inactive'}), 404

    role = (data.get('role') or 'member').strip().lower()
    if role not in ('owner', 'admin', 'member'):
        role = 'member'
    existing = KanbanBoardMember.query.filter_by(board_id=board.id, user_id=user_id).first()
    is_update = existing is not None
    if existing:
        existing.role = role
    else:
        db.session.add(KanbanBoardMember(board_id=board.id, user_id=user_id, role=role))
    role_labels = {'owner': 'Inhaber', 'admin': 'Administrator', 'member': 'Mitglied'}
    user_name = target_user.full_name or target_user.email
    act_type = 'member_updated' if is_update else 'member_added'
    _log_activity(board.id, act_type, f"{user_id}::{user_name} ({role_labels.get(role, role)})")
    db.session.commit()
    _emit_board(board.id, 'members_updated', {'board_id': board.id})
    return jsonify({
        'success': True,
        'members': _serialize_board_members(board),
    })


@kanban_bp.route('/api/boards/<int:board_id>/candidate_users')
@login_required
@check_module_access('module_kanban')
def api_candidate_users(board_id):
    board, err = _require_board_view(board_id)
    if err:
        return err
    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403

    q = (request.args.get('q') or '').strip().lower()
    all_users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    existing_roles = get_board_member_roles(board)

    candidates = []
    for u in all_users:
        if not has_module_access(u, 'module_kanban'):
            continue
        display_name = u.full_name or u.email or f'User {u.id}'
        search_haystack = f"{display_name} {u.email or ''}".lower()
        if q and q not in search_haystack:
            continue
        brief = _user_brief(u)
        if not brief:
            continue
        brief['is_member'] = u.id in existing_roles
        brief['current_role'] = existing_roles.get(u.id)
        candidates.append(brief)

    return jsonify({'users': candidates})


@kanban_bp.route('/api/boards/<int:board_id>/members/<int:user_id>', methods=['DELETE'])
@login_required
@check_module_access('module_kanban')
def api_remove_member(board_id, user_id):
    board, err = _require_board_view(board_id)
    if err:
        return err
    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403
    if user_id == board.created_by:
        return jsonify({'error': 'Der Board-Ersteller kann nicht entfernt werden'}), 400
    m = KanbanBoardMember.query.filter_by(board_id=board.id, user_id=user_id).first()
    if m:
        target_user = User.query.get(user_id)
        user_name = (target_user.full_name or target_user.email) if target_user else str(user_id)
        db.session.delete(m)
        _log_activity(board.id, 'member_removed', f"{user_id}::{user_name}")
        db.session.commit()
        _emit_board(board.id, 'members_updated', {'board_id': board.id})
    return jsonify({
        'success': True,
        'members': _serialize_board_members(board),
    })


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
    rows = q.order_by(KanbanActivity.created_at.desc()).limit(100).all()
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
        'board_updated': 'Board aktualisiert',
        'list_created': 'Liste erstellt',
        'list_updated': 'Liste aktualisiert',
        'list_deleted': 'Liste gelöscht',
        'card_created': 'Karte erstellt',
        'card_updated': 'Karte aktualisiert',
        'card_deleted': 'Karte gelöscht',
        'card_moved': 'Karte verschoben',
        'card_archived': 'Karte archiviert',
        'card_restored': 'Karte wiederhergestellt',
        'card_completed': 'Karte als erledigt markiert',
        'card_uncompleted': 'Erledigt-Status entfernt',
        'attachment_added': 'Anhang hinzugefügt',
        'attachment_deleted': 'Anhang gelöscht',
        'checklist_added': 'Checkliste hinzugefügt',
        'checklist_deleted': 'Checkliste gelöscht',
        'checklist_item_added': 'Checklisten-Eintrag hinzugefügt',
        'checklist_item_deleted': 'Checklisten-Eintrag gelöscht',
        'checklist_item_completed': 'Checklisten-Eintrag erledigt',
        'checklist_item_uncompleted': 'Checklisten-Eintrag unerledigt',
        'checklist_assignee_added': 'Checklisten-Aufgabe zugewiesen',
        'checklist_assignee_removed': 'Checklisten-Zuweisung entfernt',
        'label_created': 'Label erstellt',
        'label_added': 'Label zugewiesen',
        'label_removed': 'Label entfernt',
        'assignee_added': 'Mitglied zugewiesen',
        'assignee_removed': 'Mitgliedszuweisung entfernt',
        'member_added': 'Mitglied hinzugefügt',
        'member_updated': 'Mitgliederrolle geändert',
        'member_removed': 'Mitglied entfernt',
        'comment_added': 'Kommentar hinzugefügt',
        'custom_field_created': 'Feld erstellt',
        'custom_field_deleted': 'Feld gelöscht',
        'custom_field_category_deleted': 'Feld-Kategorie gelöscht',
        'custom_field_value_updated': 'Feldwert aktualisiert',
        'custom_field_value_cleared': 'Feldwert entfernt',
        'cover_updated': 'Titelbild gesetzt',
        'cover_removed': 'Titelbild entfernt',
        'background_removed': 'Board-Hintergrund entfernt',
        'poll_deleted': 'Abstimmung gelöscht',
        'due_date_cleared': 'Fälligkeitsdatum entfernt',
        'due_date_updated': 'Fälligkeitsdatum aktualisiert',
    }
    return labels.get(action or '', action or 'Aktivität')


def _relative_time_de(dt) -> str:
    if not dt:
        return ''
    now = datetime.utcnow()
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 0 or seconds < 45:
        return 'gerade eben'
    minutes = seconds // 60
    if minutes < 60:
        return 'vor 1 Minute' if minutes == 1 else f'vor {minutes} Minuten'
    hours = minutes // 60
    if hours < 24:
        return 'vor 1 Stunde' if hours == 1 else f'vor {hours} Stunden'
    days = hours // 24
    if days == 1:
        return f'Gestern, {dt.strftime("%H:%M")}'
    if days < 7:
        return f'vor {days} Tagen'
    return dt.strftime('%d.%m.%Y, %H:%M')


def _format_notification_text(activity: KanbanActivity, current_user) -> tuple[str, bool]:
    """Generates natural language notification text and returns (text, is_for_me)."""
    action = activity.action
    detail = activity.detail or ''
    is_me = bool(activity.user_id and activity.user_id == current_user.id)
    actor_name = activity.user.full_name if (activity.user and activity.user.full_name) else (
        activity.user.email if activity.user else 'Jemand'
    )

    prefix = "Du hast" if is_me else "Hat"
    is_for_me = False

    # Check for target user patterns like "user_id::User Name"
    target_id = None
    target_name = detail
    rest = ''
    if '::' in detail:
        parts = detail.split('::')
        try:
            target_id = int(parts[0].strip())
            target_name = parts[1].strip()
            if len(parts) > 2:
                rest = '::'.join(parts[2:]).strip()
        except (ValueError, TypeError):
            pass

    my_name = (current_user.full_name or '').lower().strip()
    my_email = (current_user.email or '').lower().strip()
    t_name_lower = (target_name or '').lower().strip()

    user_matches_target = (target_id is not None and target_id == current_user.id) or (
        bool(t_name_lower) and (
            (bool(my_name) and (t_name_lower == my_name or t_name_lower.startswith(my_name))) or
            (bool(my_email) and t_name_lower == my_email)
        )
    )

    if user_matches_target and not is_me:
        is_for_me = True

    if action == 'member_added':
        if user_matches_target:
            return ("Hat Sie zum Board hinzugefügt", True) if not is_me else ("Du wurdest zum Board hinzugefügt", False)
        return (f"{prefix} {target_name or detail} zum Board hinzugefügt", False)

    elif action == 'member_removed':
        if user_matches_target:
            return ("Hat Sie vom Board entfernt", True) if not is_me else ("Du wurdest vom Board entfernt", False)
        return (f"{prefix} {target_name or detail} vom Board entfernt", False)

    elif action == 'member_updated':
        if user_matches_target:
            return (f"Hat Ihre Rolle geändert ({rest or target_name})", True) if not is_me else (f"Deine Rolle wurde geändert ({rest or target_name})", False)
        return (f"{prefix} die Rolle von {target_name} geändert", False)

    elif action == 'assignee_added':
        if user_matches_target:
            return ("Hat Sie dieser Karte zugewiesen", True) if not is_me else ("Du hast dich dieser Karte zugewiesen", False)
        return (f"{prefix} {target_name} dieser Karte zugewiesen", False)

    elif action == 'assignee_removed':
        if user_matches_target:
            return ("Hat Ihre Zuweisung zu dieser Karte entfernt", True) if not is_me else ("Du hast deine Zuweisung entfernt", False)
        return (f"{prefix} {target_name} von dieser Karte entfernt", False)

    elif action == 'checklist_assignee_added':
        parts = detail.split('::')
        item_text = parts[3].strip() if len(parts) > 3 else (rest or 'Aufgabe')
        cl_name = parts[2].strip() if len(parts) > 2 else 'Checkliste'
        if user_matches_target:
            return (f"Hat Ihnen '{item_text}' auf der Checkliste '{cl_name}' zugewiesen", True) if not is_me else (f"Du hast dir '{item_text}' zugewiesen", False)
        return (f"{prefix} {target_name} '{item_text}' auf der Checkliste '{cl_name}' zugewiesen", False)

    elif action == 'checklist_assignee_removed':
        parts = detail.split('::')
        item_text = parts[3].strip() if len(parts) > 3 else (rest or 'Aufgabe')
        cl_name = parts[2].strip() if len(parts) > 2 else 'Checkliste'
        if user_matches_target:
            return (f"Hat Ihre Zuweisung für '{item_text}' auf '{cl_name}' entfernt", True) if not is_me else (f"Du hast deine Zuweisung für '{item_text}' entfernt", False)
        return (f"{prefix} die Zuweisung von {target_name} für '{item_text}' entfernt", False)

    elif action == 'attachment_added':
        return (f"{prefix} '{detail}' angehängt", False)

    elif action == 'attachment_deleted':
        return (f"{prefix} Anhang '{detail}' gelöscht", False)

    elif action == 'card_moved':
        if '→' in detail:
            src, dst = detail.split('→', 1)
            return (f"{prefix} die Karte nach '{dst.strip()}' verschoben", False)
        return (f"{prefix} die Karte nach '{detail}' verschoben", False)

    elif action == 'card_created':
        return (f"{prefix} die Karte erstellt", False)

    elif action == 'card_completed':
        return (f"{prefix} die Karte als erledigt markiert", False)

    elif action == 'card_uncompleted':
        return (f"{prefix} die Karte wieder als offen markiert", False)

    elif action == 'checklist_added':
        return (f"{prefix} Checkliste '{detail}' hinzugefügt", False)

    elif action == 'checklist_deleted':
        return (f"{prefix} Checkliste '{detail}' gelöscht", False)

    elif action == 'checklist_item_added':
        return (f"{prefix} '{detail}' zur Checkliste hinzugefügt", False)

    elif action == 'checklist_item_completed':
        return (f"{prefix} '{detail}' erledigt", False)

    elif action == 'checklist_item_uncompleted':
        return (f"{prefix} '{detail}' wieder als offen markiert", False)

    elif action == 'comment_added':
        return (f"{prefix} einen Kommentar hinterlassen: \"{detail}\"", False)

    elif action == 'due_date_updated':
        return (f"{prefix} das Fälligkeitsdatum aktualisiert", False)

    elif action == 'due_date_cleared':
        return (f"{prefix} das Fälligkeitsdatum entfernt", False)

    elif action == 'label_added':
        return (f"{prefix} Label '{detail}' zugewiesen", False)

    elif action == 'label_removed':
        return (f"{prefix} Label '{detail}' entfernt", False)

    elif action == 'card_updated':
        return (f"{prefix} die Karte aktualisiert", False)

    return (f"{prefix} {_activity_label(action)}: {detail}" if detail else f"{prefix} {_activity_label(action)}", False)


def _get_unread_notifications_count(board_id: int, user_id: int) -> int:
    try:
        from sqlalchemy import select
        read_subq = select(KanbanActivityRead.activity_id).filter_by(user_id=user_id)
        return (
            KanbanActivity.query
            .filter(KanbanActivity.board_id == board_id)
            .filter(KanbanActivity.user_id != user_id)
            .filter(KanbanActivity.id.not_in(read_subq))
            .count()
        )
    except Exception:
        return 0


@kanban_bp.route('/api/boards/<int:board_id>/notifications')
@login_required
@check_module_access('module_kanban')
def api_board_notifications(board_id):
    board, err = _require_board_view(board_id)
    if err:
        return err

    unread_only = request.args.get('unread_only') in ('1', 'true', 'True')
    limit = min(request.args.get('limit', 50, type=int), 100)

    try:
        read_ids = set(
            r[0] for r in db.session.query(KanbanActivityRead.activity_id)
            .filter_by(user_id=current_user.id)
            .all()
        )
    except Exception:
        read_ids = set()

    q = (
        KanbanActivity.query
        .filter_by(board_id=board.id)
        .options(
            joinedload(KanbanActivity.user),
            joinedload(KanbanActivity.card).joinedload(KanbanCard.list),
        )
        .order_by(KanbanActivity.created_at.desc())
    )

    rows = q.limit(limit * 2 if unread_only else limit).all()

    items = []
    for a in rows:
        is_own = bool(a.user_id and a.user_id == current_user.id)
        is_read = is_own or (a.id in read_ids)
        if unread_only and is_read:
            continue

        action_text, is_for_me = _format_notification_text(a, current_user)
        card_obj = a.card
        list_title = card_obj.list.title if (card_obj and card_obj.list) else None

        items.append({
            'id': a.id,
            'board_id': board.id,
            'board_title': board.title,
            'card_id': a.card_id,
            'card_title': card_obj.title if card_obj else None,
            'list_title': list_title,
            'actor': _user_brief(a.user),
            'action': a.action,
            'action_text': action_text,
            'detail': a.detail,
            'is_read': is_read,
            'is_own': is_own,
            'is_for_me': is_for_me,
            'created_at': a.created_at.isoformat() if a.created_at else None,
            'created_at_relative': _relative_time_de(a.created_at),
            'created_at_display': a.created_at.strftime('%d.%m.%Y, %H:%M') if a.created_at else None,
        })
        if len(items) >= limit:
            break

    unread_count = _get_unread_notifications_count(board.id, current_user.id)

    return jsonify({
        'notifications': items,
        'unread_count': unread_count,
    })


@kanban_bp.route('/api/boards/<int:board_id>/notifications/mark_read', methods=['POST'])
@login_required
@check_module_access('module_kanban')
def api_mark_notifications_read(board_id):
    board, err = _require_board_view(board_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    activity_id = data.get('activity_id')
    mark_all = data.get('all', False)
    now = portal_now_naive()

    if mark_all:
        activities = KanbanActivity.query.filter_by(board_id=board.id).all()
        existing_read_ids = {
            r[0] for r in db.session.query(KanbanActivityRead.activity_id)
            .filter_by(user_id=current_user.id)
            .filter(KanbanActivityRead.activity_id.in_([a.id for a in activities]))
            .all()
        } if activities else set()
        for a in activities:
            if a.id not in existing_read_ids:
                db.session.add(KanbanActivityRead(activity_id=a.id, user_id=current_user.id, read_at=now))
        db.session.commit()
    elif activity_id:
        try:
            aid = int(activity_id)
            existing = KanbanActivityRead.query.filter_by(activity_id=aid, user_id=current_user.id).first()
            if not existing:
                db.session.add(KanbanActivityRead(activity_id=aid, user_id=current_user.id, read_at=now))
                db.session.commit()
        except (ValueError, TypeError):
            pass

    unread_count = _get_unread_notifications_count(board.id, current_user.id)
    return jsonify({
        'success': True,
        'unread_count': unread_count,
    })


@kanban_bp.route('/api/boards/<int:board_id>/notifications/count')
@login_required
@check_module_access('module_kanban')
def api_board_notifications_count(board_id):
    board, err = _require_board_view(board_id)
    if err:
        return err
    count = _get_unread_notifications_count(board.id, current_user.id)
    return jsonify({'unread_count': count})


@kanban_bp.route('/api/boards/unread_counts')
@login_required
@check_module_access('module_kanban')
def api_boards_unread_counts():
    try:
        from sqlalchemy import func, select
        boards = accessible_boards_query(current_user, include_closed=False).with_entities(KanbanBoard.id).all()
        board_ids = [b[0] for b in boards]
        if not board_ids:
            return jsonify({'unread_counts': {}})
        read_subq = select(KanbanActivityRead.activity_id).filter_by(user_id=current_user.id)
        counts = (
            db.session.query(KanbanActivity.board_id, func.count(KanbanActivity.id))
            .filter(KanbanActivity.board_id.in_(board_ids))
            .filter(KanbanActivity.user_id != current_user.id)
            .filter(KanbanActivity.id.not_in(read_subq))
            .group_by(KanbanActivity.board_id)
            .all()
        )
        return jsonify({'unread_counts': {str(bid): cnt for bid, cnt in counts if cnt > 0}})
    except Exception as e:
        return jsonify({'unread_counts': {}, 'error': str(e)}), 500


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
        kanban_sse_url='',
    )
