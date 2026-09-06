"""Board CRUD, export/import, background, and lists."""

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
