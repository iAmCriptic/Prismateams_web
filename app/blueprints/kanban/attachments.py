"""Attachments, OnlyOffice, preview, and download."""

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
    onlyoffice_url = get_onlyoffice_document_server_url()
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
        flash('Euro-Office ist nicht aktiviert.', 'warning')
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
        flash('Dieser Dateityp wird von Euro-Office nicht unterstützt.', 'warning')
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

    onlyoffice_url = get_onlyoffice_document_server_url()
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
        onlyoffice_document_key_matches_resource,
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
    key = payload.get('key')
    if not onlyoffice_document_key_matches_resource(key, 'kanban_att', attachment_id):
        logging.warning(
            'Kanban OnlyOffice callback: key/attachment mismatch key=%s attachment_id=%s',
            key,
            attachment_id,
        )
        return _kanban_oo_cors({'error': 'key mismatch'}, 403)[0]

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
