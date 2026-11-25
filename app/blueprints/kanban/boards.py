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
    _generate_board_public_id,
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
        public_id=_generate_board_public_id(),
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
    from app.utils.trello_client import get_trello_session_auth

    trello_auth = get_trello_session_auth()

    try:
        fmt = detect_import_format(f.filename, raw)
        if fmt == 'zip':
            boards, errors = import_boards_from_zip(
                raw=raw,
                user=current_user,
                visibility=visibility,
                team_id=team_id,
                trello_auth=trello_auth,
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
            trello_auth=trello_auth,
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
        candidate_files = _collect_board_file_paths(board)
        db.session.delete(board)
        db.session.commit()
        _cleanup_unreferenced_kanban_files(candidate_files)
        return jsonify({'success': True})

    if not can_manage_board(current_user, board):
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        board.title = (data['title'] or board.title).strip() or board.title
    if 'description' in data:
        board.description = (data.get('description') or '').strip() or None
    if 'visibility' in data or 'team_id' in data:
        raw_vis = (data.get('visibility') if 'visibility' in data else board.visibility) or VISIBILITY_PRIVATE
        new_vis = str(raw_vis).strip().lower()
        new_team_id = data.get('team_id') if 'team_id' in data else board.team_id
        if new_vis.startswith('team:'):
            try:
                new_team_id = int(new_vis.split(':', 1)[1])
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid team'}), 400
            new_vis = VISIBILITY_TEAM
        if new_vis not in (VISIBILITY_PRIVATE, VISIBILITY_TEAM, VISIBILITY_PUBLIC):
            return jsonify({'error': 'Invalid visibility'}), 400
        if not visibility_allowed(new_vis, current_user):
            return jsonify({'error': 'Visibility not allowed'}), 400
        if new_team_id in ('', None):
            new_team_id = None
        else:
            try:
                new_team_id = int(new_team_id)
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid team'}), 400
        if new_vis == VISIBILITY_TEAM:
            if not new_team_id:
                return jsonify({'error': 'Team required'}), 400
            if not Team.query.get(new_team_id):
                return jsonify({'error': 'Team not found'}), 404
            if not _user_may_use_team(current_user, new_team_id):
                return jsonify({'error': 'Forbidden'}), 403
        else:
            new_team_id = None

        vis_changed = (board.visibility != new_vis) or (board.team_id != new_team_id)
        board.visibility = new_vis
        board.team_id = new_team_id
        if vis_changed:
            if new_vis == VISIBILITY_PRIVATE and getattr(current_user, 'id', None):
                existing_member = KanbanBoardMember.query.filter_by(
                    board_id=board.id,
                    user_id=current_user.id,
                ).first()
                if existing_member is None:
                    db.session.add(KanbanBoardMember(
                        board_id=board.id,
                        user_id=current_user.id,
                        role='owner',
                    ))
                elif existing_member.role not in ('owner', 'admin'):
                    existing_member.role = 'owner'
            _log_activity(board.id, 'board_updated', json.dumps({
                'visibility': board.visibility,
                'team_id': board.team_id,
            }))
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
    board, err = _require_board_manage(board_id)
    if err:
        return err

    if request.method == 'DELETE':
        _delete_board_cover_file(board)
        _log_activity(board.id, 'background_removed')
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
    lst, err = _require_list_edit(list_id)
    if err:
        return err
    board = lst.board

    if request.method == 'DELETE':
        board_id = board.id
        lst_title = lst.title
        candidate_files = _collect_list_file_paths(lst.id)
        db.session.delete(lst)
        _log_activity(board_id, 'list_deleted', detail=lst_title)
        db.session.commit()
        _cleanup_unreferenced_kanban_files(candidate_files)
        _emit_board(board_id, 'list_deleted', {'id': list_id})
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        new_title = (data['title'] or lst.title).strip() or lst.title
        if new_title != lst.title:
            _log_activity(board.id, 'list_updated', detail=f'{lst.title} → {new_title}')
            lst.title = new_title
    if 'archived' in data:
        lst.archived_at = portal_now_naive() if data['archived'] else None
    if 'position' in data:
        try:
            lst.position = int(data['position'])
        except (TypeError, ValueError):
            pass
    if 'default_custom_field_ids' in data:
        raw_ids = data.get('default_custom_field_ids') or []
        if not isinstance(raw_ids, list):
            raw_ids = []
        parsed_ids = []
        for x in raw_ids:
            try:
                parsed_ids.append(int(x))
            except (TypeError, ValueError):
                continue
        valid_ids = {
            f.id
            for f in KanbanCustomField.query.filter_by(board_id=board.id, card_id=None).all()
        }
        lst.set_default_custom_field_ids([fid for fid in parsed_ids if fid in valid_ids])
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
    raw_order = data.get('order')
    if raw_order is None:
        raw_order = []
    elif not isinstance(raw_order, list):
        return jsonify({'error': 'order must be a list'}), 400
    order = _parse_int_list(raw_order)
    for i, lid in enumerate(order):
        lst = KanbanList.query.filter_by(id=lid, board_id=board.id).first()
        if lst:
            lst.position = i
    db.session.commit()
    _emit_board(board.id, 'lists_reordered', {'order': order})
    return jsonify({'success': True})


@kanban_bp.route('/api/lists/<int:list_id>/copy', methods=['POST'])
@login_required
@check_module_access('module_kanban')
def api_copy_list(list_id):
    from app.utils.kanban_transfer import copy_list

    source_list = db.session.get(KanbanList, list_id)
    if not source_list or source_list.archived_at:
        return jsonify({'error': 'Not found'}), 404
    _, err = _require_board_edit(source_list.board_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    target_board_id = data.get('target_board_id') or source_list.board_id
    target_board, target_err = _require_board_edit(target_board_id)
    if target_err:
        return target_err

    new_list = copy_list(
        source_list,
        target_board,
        current_user.id,
        title=data.get('title'),
        position=data.get('position'),
    )
    _log_activity(target_board.id, 'list_created', new_list.title)
    db.session.commit()

    payload = _serialize_list(new_list, share_token=_share_token_from_request())
    _emit_board(target_board.id, 'list_created', payload)
    return jsonify({'success': True, 'list': payload, 'target_board_id': target_board.id}), 201


@kanban_bp.route('/api/lists/<int:list_id>/move', methods=['POST'])
@login_required
@check_module_access('module_kanban')
def api_move_list(list_id):
    from app.utils.kanban_transfer import move_list_to_board

    lst = db.session.get(KanbanList, list_id)
    if not lst or lst.archived_at:
        return jsonify({'error': 'Not found'}), 404
    source_board_id = lst.board_id
    _, err = _require_board_edit(source_board_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    target_board_id = data.get('target_board_id') or source_board_id
    target_board, target_err = _require_board_edit(target_board_id)
    if target_err:
        return target_err

    move_list_to_board(lst, target_board, position=data.get('position'))
    db.session.commit()

    payload = _serialize_list(lst, share_token=_share_token_from_request())
    if source_board_id != target_board.id:
        _emit_board(source_board_id, 'list_deleted', {'id': lst.id})
        _emit_board(target_board.id, 'list_created', payload)
    else:
        _emit_board(target_board.id, 'list_updated', payload)
    return jsonify({'success': True, 'list': payload, 'target_board_id': target_board.id})


@kanban_bp.route('/api/boards/<int:board_id>/copy', methods=['POST'])
@login_required
@check_module_access('module_kanban')
def api_copy_board(board_id):
    from app.utils.kanban_transfer import copy_board

    source_board, err = _require_board_view(board_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    vis = data.get('visibility') or source_board.visibility
    if not visibility_allowed(vis, current_user):
        vis = VISIBILITY_PRIVATE
    team_id = data.get('team_id') if 'team_id' in data else source_board.team_id
    if vis != VISIBILITY_TEAM:
        team_id = None

    new_board = copy_board(
        source_board,
        current_user.id,
        title=data.get('title'),
        visibility=vis,
        team_id=team_id,
    )
    _log_activity(new_board.id, 'board_created', new_board.title)
    db.session.commit()
    return jsonify({
        'success': True,
        'board': _serialize_board(new_board, full=False),
        'board_url': url_for('kanban.board', board_id=new_board.public_id or new_board.id),
    }), 201


@kanban_bp.route('/api/boards/<int:board_id>/move', methods=['POST'])
@login_required
@check_module_access('module_kanban')
def api_move_board(board_id):
    board, err = _require_board_manage(board_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    vis = (data.get('visibility') or board.visibility).strip()
    if vis not in (VISIBILITY_PRIVATE, VISIBILITY_TEAM, VISIBILITY_PUBLIC):
        return jsonify({'error': 'Invalid visibility'}), 400
    if not visibility_allowed(vis, current_user):
        return jsonify({'error': 'Visibility not allowed'}), 403

    board.visibility = vis
    if vis == VISIBILITY_TEAM:
        raw_tid = data.get('team_id')
        try:
            board.team_id = int(raw_tid) if raw_tid else None
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid team_id'}), 400
    else:
        board.team_id = None

    if 'position' in data and data.get('position') is not None:
        try:
            board.position = int(data.get('position'))
        except (TypeError, ValueError):
            pass

    db.session.commit()
    return jsonify({'success': True, 'board': _serialize_board(board, full=False)})


@kanban_bp.route('/api/transfer-targets')
@login_required
@check_module_access('module_kanban')
def api_transfer_targets():
    """Return editable boards with their active lists and cards for copy/move modals."""
    include_cards = request.args.get('include_cards') == '1'
    boards = (
        accessible_boards_query(current_user, include_closed=False)
        .order_by(KanbanBoard.position.asc(), KanbanBoard.title.asc())
        .all()
    )
    out = []
    for b in boards:
        if not can_edit_board(current_user, b):
            continue
        lists_data = []
        for l in sorted([x for x in b.lists if not x.archived_at], key=lambda x: x.position):
            entry = {'id': l.id, 'title': l.title}
            if include_cards:
                entry['cards'] = [
                    {'id': c.id, 'title': c.title}
                    for c in sorted([k for k in l.cards if not k.archived_at], key=lambda k: k.position)
                ]
            lists_data.append(entry)
        out.append({
            'id': b.id,
            'public_id': b.public_id,
            'title': b.title,
            'lists': lists_data,
        })
    allowed_vis = get_allowed_visibilities(current_user)
    teams_q = Team.query.order_by(Team.name.asc()).all()
    if not getattr(current_user, 'is_admin', False):
        member_tids = {
            tm.team_id for tm in TeamMember.query.filter_by(user_id=current_user.id).all()
        }
        teams_q = [t for t in teams_q if t.id in member_tids]
    return jsonify({
        'boards': out,
        'allowed_visibilities': allowed_vis,
        'teams': [{'id': t.id, 'name': t.name} for t in teams_q],
    })
