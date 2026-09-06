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
