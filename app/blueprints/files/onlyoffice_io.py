"""ONLYOFFICE document, save, forcesave, and callback routes."""

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify, current_app, session, abort, get_flashed_messages
from flask_login import login_required, current_user
from app.utils.i18n import get_current_language, translate
from app import db
from app.models.file import File, FileVersion, Folder, ResourceACL
from app.utils import file_edit_lock as file_edit_lock_util
from app.models.user import User
from app.models.settings import SystemSettings
from app.utils.notifications import send_file_notification
from app.utils.access_control import check_module_access
from app.utils.dashboard_events import emit_dashboard_update
from app.utils.file_storage_limits import (
    check_upload_allowed,
    format_bytes_de,
    get_global_max_file_size,
    resolve_limits_for_user,
    usage_payload_for_user,
)
from app.utils.private_files import (
    apply_space_to_folder_tree,
    can_edit_file,
    can_edit_folder,
    can_manage_acl,
    can_view_file,
    can_view_folder,
    ensure_personal_root,
    ensure_team_root,
    folder_is_under_personal_root,
    hard_delete_file_disk_and_db,
    hard_delete_folder_recursive,
    is_files_spaces_enabled,
    is_private_folders_enabled,
    is_team_folders_enabled,
    list_acl_for_resource,
    list_folder_favorites,
    list_move_destinations,
    list_view_contents,
    normalize_view,
    parse_team_id,
    remove_acl,
    resolve_default_parent_for_view,
    resolve_space_for_parent,
    resolve_team_id_for_parent,
    restore_file,
    restore_folder,
    serialize_acl_row,
    soft_delete_file,
    soft_delete_folder,
    toggle_folder_favorite,
    upsert_acl,
    user_file_teams,
    user_may_use_file_team,
    sanitize_files_item_name,
    FOLDER_FAVORITES_MAX,
)
from app.models.public_share import PublicShare
from app.utils.public_share import (
    create_share_link,
    delete_share_by_id,
    disable_share_by_id,
    enable_share_by_id,
    generate_unique_share_token,
    get_share_by_token,
    get_share_for_mode,
    get_shares_for_resource,
    is_resource_shared,
    log_share_access,
    normalize_share_mode,
    resolve_dropbox_folder,
    resolve_resource,
    serialize_share_link,
    serialize_share_settings,
    share_is_expired,
    sync_legacy_share_flags,
    update_share_link,
)
from app.utils.onlyoffice_presence import (
    heartbeat_session as oo_heartbeat_session,
    leave_session as oo_leave_session,
    presence_for_folder,
    upsert_session as oo_upsert_session,
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from flask import url_for as flask_url_for
from app.utils.upload_policy import is_allowed_upload_filename
import os
import shutil
import logging
import secrets
import requests
import re
import zipfile

from app.blueprints.files._bp import (
    FILES_BROWSE_PAGE_SIZE,
    MAX_FILE_PREVIEW_CHARS,
    MAX_FILE_VERSIONS,
    files_bp,
)
from app.blueprints.files.helpers import *  # noqa: F401,F403

@files_bp.route('/api/onlyoffice-document/<int:file_id>', methods=['GET', 'HEAD', 'OPTIONS'])
def onlyoffice_document(file_id):
    """Serve document to ONLYOFFICE editor."""
    # IMPORTANT: This endpoint must NOT require login, as OnlyOffice Document Server
    # cannot send session cookies. It uses token-based authentication instead.
    
    # Handle OPTIONS request for CORS preflight
    if request.method == 'OPTIONS':
        onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
        response = jsonify({})
        if onlyoffice_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(onlyoffice_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
        else:
            # OnlyOffice läuft auf demselben Server - verwende Request-Origin
            origin = request.headers.get('Origin', '*')
            if origin == 'null' or not origin or origin == '*':
                origin = f"{request.scheme}://{request.host}"
        
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response
    
    # Log ALL requests to this endpoint (including failed ones)
    logging.info(f"ONLYOFFICE document endpoint called - method: {request.method}, file_id: {file_id}, remote_addr: {request.remote_addr}, user_agent: {request.headers.get('User-Agent', 'Unknown')}")
    
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        logging.warning(f"ONLYOFFICE document request rejected - OnlyOffice not enabled")
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    # Access token is REQUIRED — OnlyOffice Document Server cannot use session cookies
    access_token = request.args.get('token')
    if access_token:
        import hashlib
        token_fp = hashlib.sha256(access_token.encode('utf-8')).hexdigest()[:12]
        logging.info(
            'ONLYOFFICE document request - file_id=%s token_fp=%s remote=%s',
            file_id,
            token_fp,
            request.remote_addr,
        )
    else:
        logging.warning(
            'ONLYOFFICE document request - file_id=%s NO TOKEN remote=%s',
            file_id,
            request.remote_addr,
        )

    if not access_token:
        logging.error(
            'ONLYOFFICE document access denied - NO TOKEN for file %s',
            file_id,
        )
        return jsonify({'error': 'Access token required'}), 403

    from app.utils.onlyoffice import validate_onlyoffice_access_token
    if not validate_onlyoffice_access_token(access_token, file_id):
        logging.error(
            'ONLYOFFICE document access denied - INVALID TOKEN for file %s',
            file_id,
        )
        return jsonify({'error': 'Invalid access token'}), 403

    logging.info('ONLYOFFICE document access granted via token for file %s', file_id)

    file = File.query.get_or_404(file_id)
    logging.info(
        'ONLYOFFICE document request - file_id=%s name=%s',
        file_id,
        file.original_name,
    )

    # Ensure we have an absolute path
    if not os.path.isabs(file.file_path):
        file_path = os.path.join(os.getcwd(), file.file_path)
    else:
        file_path = file.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        logging.error(f"ONLYOFFICE file not found: {file_path} (file_id: {file_id}, original_name: {file.original_name})")
        return jsonify({'error': 'File not found'}), 404
    
    logging.info(f"ONLYOFFICE serving file: {file.original_name} from {file_path} (size: {os.path.getsize(file_path)} bytes)")
    
    # Determine MIME type
    file_ext = os.path.splitext(file.original_name)[1].lower()
    mime_types = {
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.doc': 'application/msword',
        '.odt': 'application/vnd.oasis.opendocument.text',
        '.rtf': 'application/rtf',
        '.txt': 'text/plain',
        '.md': 'text/markdown',
        '.markdown': 'text/markdown',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xls': 'application/vnd.ms-excel',
        '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
        '.csv': 'text/csv',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.ppt': 'application/vnd.ms-powerpoint',
        '.odp': 'application/vnd.oasis.opendocument.presentation',
        '.pdf': 'application/pdf'
    }
    mimetype = mime_types.get(file_ext, 'application/octet-stream')
    
    # Create response with CORS headers for cross-origin requests
    response = send_file(
        file_path,
        mimetype=mimetype,
        download_name=file.original_name,
        as_attachment=False
    )
    
    # Add CORS headers to allow OnlyOffice (auch wenn auf demselben Server über Proxy)
    # OnlyOffice läuft über einen Proxy, daher benötigen wir CORS-Header
    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    if onlyoffice_url.startswith('http'):
        # Extract origin from OnlyOffice URL
        from urllib.parse import urlparse
        parsed = urlparse(onlyoffice_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
    else:
        # OnlyOffice läuft auf demselben Server, aber über Proxy - verwende Request-Origin
        origin = request.headers.get('Origin', '*')
        if origin == 'null' or not origin or origin == '*':
            # Fallback: verwende die aktuelle Request-URL als Origin
            origin = f"{request.scheme}://{request.host}"
    
    response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    return response


@files_bp.route('/share/<token>/api/onlyoffice-document/<int:file_id>', methods=['GET', 'HEAD', 'OPTIONS'])
def share_onlyoffice_document(token, file_id):
    """Serve document to ONLYOFFICE editor (Gast-Zugriff)."""
    # Handle OPTIONS request for CORS preflight
    if request.method == 'OPTIONS':
        onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
        response = jsonify({})
        if onlyoffice_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(onlyoffice_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
        else:
            # OnlyOffice läuft auf demselben Server - verwende Request-Origin
            origin = request.headers.get('Origin', '*')
            if origin == 'null' or not origin or origin == '*':
                origin = f"{request.scheme}://{request.host}"
        
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response
    
    logging.info(
        'ONLYOFFICE share document - method=%s share=%s… file_id=%s remote=%s',
        request.method,
        token[:8] if token else '',
        file_id,
        request.remote_addr,
    )
    
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        logging.warning('ONLYOFFICE share document request rejected - OnlyOffice not enabled')
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404

    # Short-lived JWT minted only after share password/guest gate (DS has no session cookies)
    from app.utils.onlyoffice import validate_onlyoffice_access_token
    access_token = request.args.get('token')
    if not access_token or not validate_onlyoffice_access_token(
        access_token, file_id, share_token=token
    ):
        logging.warning(
            'ONLYOFFICE share document denied - missing/invalid access token file_id=%s',
            file_id,
        )
        return jsonify({'error': 'Access token required'}), 403
    
    share, item = _get_public_share_context(token)
    if not share or not item:
        logging.warning('ONLYOFFICE share document access denied - Invalid share token')
        return jsonify({'error': 'Invalid share token'}), 403

    if share.resource_type == 'folder':
        file = _resolve_shared_file(item, file_id)
        if not file:
            return jsonify({'error': 'File not found in share'}), 404
    else:
        # Direkt freigegebene Datei
        if item.id != file_id:
            logging.warning(
                'ONLYOFFICE share document access denied - File ID mismatch: expected %s, got %s',
                item.id,
                file_id,
            )
            return jsonify({'error': 'File ID mismatch'}), 403
        file = item
    
    logging.info(
        'ONLYOFFICE share document access granted - file_id=%s name=%s',
        file_id,
        file.original_name,
    )
    
    # Ensure we have an absolute path
    if not os.path.isabs(file.file_path):
        file_path = os.path.join(os.getcwd(), file.file_path)
    else:
        file_path = file.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    # Determine MIME type
    file_ext = os.path.splitext(file.original_name)[1].lower()
    mime_types = {
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.doc': 'application/msword',
        '.odt': 'application/vnd.oasis.opendocument.text',
        '.rtf': 'application/rtf',
        '.txt': 'text/plain',
        '.md': 'text/markdown',
        '.markdown': 'text/markdown',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xls': 'application/vnd.ms-excel',
        '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
        '.csv': 'text/csv',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.ppt': 'application/vnd.ms-powerpoint',
        '.odp': 'application/vnd.oasis.opendocument.presentation',
        '.pdf': 'application/pdf'
    }
    mimetype = mime_types.get(file_ext, 'application/octet-stream')
    
    # Create response with CORS headers for cross-origin requests
    response = send_file(
        file_path,
        mimetype=mimetype,
        download_name=file.original_name,
        as_attachment=False
    )
    
    # Add CORS headers to allow OnlyOffice (auch wenn auf demselben Server über Proxy)
    # OnlyOffice läuft über einen Proxy, daher benötigen wir CORS-Header
    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    if onlyoffice_url.startswith('http'):
        # Extract origin from OnlyOffice URL
        from urllib.parse import urlparse
        parsed = urlparse(onlyoffice_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
    else:
        # OnlyOffice läuft auf demselben Server, aber über Proxy - verwende Request-Origin
        origin = request.headers.get('Origin', '*')
        if origin == 'null' or not origin or origin == '*':
            # Fallback: verwende die aktuelle Request-URL als Origin
            origin = f"{request.scheme}://{request.host}"
    
    response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    return response


def _onlyoffice_forcesave_response(document_key):
    """Ask the Document Server to persist the current editor state (status 6)."""
    from app.utils.onlyoffice import send_onlyoffice_command

    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404

    key = (document_key or '').strip()
    if not key or len(key) > 128:
        return jsonify({'success': False, 'error': 'invalid_key'}), 400

    ok, error_code, detail = send_onlyoffice_command('forcesave', key)
    logging.info(
        'ONLYOFFICE forcesave key=%s ok=%s error_code=%s detail=%s',
        key, ok, error_code, detail,
    )
    return jsonify({'success': ok, 'error_code': error_code, 'detail': detail})


@files_bp.route('/api/onlyoffice-forcesave/<int:file_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def onlyoffice_forcesave(file_id):
    """Force-save an open OnlyOffice document for a logged-in user."""
    file = File.query.get_or_404(file_id)
    if _is_guest_user():
        from app.utils.access_control import GUEST_EDIT_MODES, guest_has_file_access
        if not guest_has_file_access(current_user, file, modes=GUEST_EDIT_MODES):
            return jsonify({'success': False, 'error': 'Kein Zugriff'}), 403
    elif not can_edit_file(file, current_user) and not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Kein Zugriff'}), 403

    payload = request.get_json(silent=True) or {}
    return _onlyoffice_forcesave_response(payload.get('key'))


@files_bp.route('/share/<token>/api/onlyoffice-forcesave/<int:file_id>', methods=['POST'])
def share_onlyoffice_forcesave(token, file_id):
    """Force-save an open OnlyOffice document for a share guest."""
    item, guest_name, share = _check_share_access(token)
    if not item or not guest_name or not share:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    if normalize_share_mode(share.mode) != 'edit':
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    if isinstance(item, Folder):
        file = _resolve_shared_file(item, file_id)
        if not file:
            return jsonify({'success': False, 'error': 'File not found in share'}), 404
    else:
        if item.id != file_id:
            return jsonify({'success': False, 'error': 'File ID mismatch'}), 403

    payload = request.get_json(silent=True) or {}
    return _onlyoffice_forcesave_response(payload.get('key'))


@files_bp.route('/api/onlyoffice-save/<int:file_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def onlyoffice_save(file_id):
    """Save document from ONLYOFFICE."""
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    file = File.query.get_or_404(file_id)

    if _is_guest_user():
        from app.utils.access_control import GUEST_EDIT_MODES, guest_has_file_access
        if not guest_has_file_access(current_user, file, modes=GUEST_EDIT_MODES):
            return jsonify({'error': 'Access denied'}), 403
    elif not can_edit_file(file, current_user) and not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403
    
    # Get file content from request
    if 'file' not in request.files:
        return jsonify({'error': 'No file in request'}), 400
    
    uploaded_file = request.files['file']
    
    # Save current version to history
    version = FileVersion(
        file_id=file.id,
        version_number=file.version_number,
        file_path=os.path.abspath(file.file_path),
        file_size=file.file_size,
        uploaded_by=file.uploaded_by
    )
    db.session.add(version)
    
    # Delete oldest version if needed
    versions = FileVersion.query.filter_by(file_id=file.id).order_by(
        FileVersion.version_number.desc()
    ).all()
    
    if len(versions) >= MAX_FILE_VERSIONS:
        oldest = versions[-1]
        if os.path.exists(oldest.file_path):
            os.remove(oldest.file_path)
        db.session.delete(oldest)
    
    # Save new version
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    safe_name = _disk_safe_upload_basename(file.original_name)
    filename = f"{timestamp}_{safe_name}"
    filepath = os.path.join('uploads', 'files', filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    uploaded_file.save(filepath)
    
    # Store absolute path in database
    absolute_filepath = os.path.abspath(filepath)
    
    file.file_path = absolute_filepath
    file.file_size = os.path.getsize(absolute_filepath)
    file.version_number += 1
    file.uploaded_by = current_user.id
    file.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    # Send notification
    try:
        send_file_notification(file.id, 'modified')
    except Exception as e:
        logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")
    
    return jsonify({'success': True, 'message': 'File saved successfully'})


@files_bp.route('/share/<token>/api/onlyoffice-save/<int:file_id>', methods=['POST'])
def share_onlyoffice_save(token, file_id):
    """Save document from ONLYOFFICE (Gast-Zugriff)."""
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    item, guest_name, share = _check_share_access(token)
    if not item or not guest_name or not share:
        return jsonify({'error': 'Access denied'}), 403
    if normalize_share_mode(share.mode) != 'edit':
        return jsonify({'error': 'Access denied'}), 403
    
    # Prüfe ob es eine Datei aus einem Ordner ist oder direkt freigegebene Datei
    if isinstance(item, Folder):
        file = _resolve_shared_file(item, file_id)
        if not file:
            return jsonify({'error': 'File not found in share'}), 404
    else:
        # Direkt freigegebene Datei
        if item.id != file_id:
            return jsonify({'error': 'File ID mismatch'}), 403
        file = item
    
    # Get file content from request
    if 'file' not in request.files:
        return jsonify({'error': 'No file in request'}), 400
    
    uploaded_file = request.files['file']
    
    # Get anonymous user for guest edits
    anonymous_user = User.query.filter_by(email='anonymous@system.local').first()
    if not anonymous_user:
        anonymous_user = User(
            email='anonymous@system.local',
            first_name=guest_name,
            last_name='',
            password_hash='',
            is_active=True,
            is_admin=False,
            is_email_confirmed=True
        )
        db.session.add(anonymous_user)
        db.session.flush()
    
    # Save current version to history
    version = FileVersion(
        file_id=file.id,
        version_number=file.version_number,
        file_path=os.path.abspath(file.file_path),
        file_size=file.file_size,
        uploaded_by=file.uploaded_by
    )
    db.session.add(version)
    
    # Delete oldest version if needed
    versions = FileVersion.query.filter_by(file_id=file.id).order_by(
        FileVersion.version_number.desc()
    ).all()
    
    if len(versions) >= MAX_FILE_VERSIONS:
        oldest = versions[-1]
        if os.path.exists(oldest.file_path):
            os.remove(oldest.file_path)
        db.session.delete(oldest)
    
    # Save new version
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    safe_name = _disk_safe_upload_basename(file.original_name)
    filename = f"{timestamp}_{safe_name}"
    filepath = os.path.join('uploads', 'files', filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    uploaded_file.save(filepath)
    
    # Store absolute path in database
    absolute_filepath = os.path.abspath(filepath)
    
    file.file_path = absolute_filepath
    file.file_size = os.path.getsize(absolute_filepath)
    file.version_number += 1
    file.uploaded_by = anonymous_user.id
    file.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'File saved successfully'})


def _onlyoffice_cors_response(payload, status_code=200):
    """Return JSON response with ONLYOFFICE CORS headers."""
    response = jsonify(payload)
    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    if onlyoffice_url.startswith('http'):
        from urllib.parse import urlparse
        parsed = urlparse(onlyoffice_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response, status_code


def _onlyoffice_validate_callback_payload():
    """Validate ONLYOFFICE callback JWT and return signed payload."""
    from app.utils.onlyoffice import verify_onlyoffice_callback_token

    data = request.get_json()
    if not data:
        return None, _onlyoffice_cors_response({'error': 'No data received'}, 400)

    ok, signed_payload, reason = verify_onlyoffice_callback_token(
        data,
        request.headers.get('Authorization', '')
    )
    if not ok:
        logging.warning("ONLYOFFICE callback rejected: %s", reason)
        return None, _onlyoffice_cors_response({'error': 'Unauthorized callback'}, 403)

    payload = signed_payload if isinstance(signed_payload, dict) else data
    return payload, None


def _download_onlyoffice_saved_content(saved_file_url):
    """Download saved content from ONLYOFFICE with SSRF safeguards."""
    from app.utils.onlyoffice import is_onlyoffice_callback_download_url_allowed

    is_allowed, reason = is_onlyoffice_callback_download_url_allowed(saved_file_url)
    if not is_allowed:
        logging.warning("ONLYOFFICE callback URL blocked (%s): %s", reason, saved_file_url)
        return None

    try:
        response = requests.get(saved_file_url, timeout=15, allow_redirects=False)
        if response.status_code != 200:
            logging.warning("ONLYOFFICE callback download failed: status=%s", response.status_code)
            return None
        return response.content
    except Exception as exc:
        logging.error("ONLYOFFICE callback download error: %s", exc)
        return None


def _onlyoffice_save_callback_file(file, saved_content, increment_version=True):
    """Persist document bytes received from an OnlyOffice callback."""
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    safe_name = _disk_safe_upload_basename(file.original_name)
    filename = f"{timestamp}_{safe_name}"
    filepath = os.path.join('uploads', 'files', filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, 'wb') as f:
        f.write(saved_content)

    absolute_filepath = os.path.abspath(filepath)

    if increment_version:
        version = FileVersion(
            file_id=file.id,
            version_number=file.version_number,
            file_path=os.path.abspath(file.file_path),
            file_size=file.file_size,
            uploaded_by=file.uploaded_by
        )
        db.session.add(version)

        versions = FileVersion.query.filter_by(file_id=file.id).order_by(
            FileVersion.version_number.desc()
        ).all()
        if len(versions) >= MAX_FILE_VERSIONS:
            oldest = versions[-1]
            if os.path.exists(oldest.file_path):
                os.remove(oldest.file_path)
            db.session.delete(oldest)

        file.file_path = absolute_filepath
        file.file_size = os.path.getsize(absolute_filepath)
        file.version_number += 1
        file.updated_at = datetime.utcnow()
        db.session.commit()
        logging.info(
            "ONLYOFFICE: File %s saved (new version %s)",
            file.id,
            file.version_number,
        )
    else:
        old_file_path = file.file_path
        file.file_path = absolute_filepath
        file.file_size = os.path.getsize(absolute_filepath)
        file.updated_at = datetime.utcnow()
        db.session.commit()

        if old_file_path != absolute_filepath and os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
            except Exception as e:
                logging.warning("Could not delete old file %s: %s", old_file_path, e)

        logging.info(
            "ONLYOFFICE: File %s updated in place (version %s)",
            file.id,
            file.version_number,
        )

    try:
        send_file_notification(file.id, 'modified')
    except Exception as e:
        logging.error("Fehler beim Senden der Datei-Benachrichtigung: %s", e)


def _onlyoffice_handle_save_callback(file, payload):
    """
    Handle OnlyOffice callback statuses that include saved document content.

    Status 2 = document ready for saving (user closed editor)
    Status 6 = force save while editing
    """
    status = payload.get('status')
    if status not in (2, 6):
        return False

    saved_file_url = payload.get('url')
    if not saved_file_url:
        logging.warning("ONLYOFFICE callback: status %s without download URL for file %s", status, file.id)
        return False

    saved_content = _download_onlyoffice_saved_content(saved_file_url)
    if not saved_content:
        return False

    _onlyoffice_save_callback_file(file, saved_content, increment_version=True)
    return True


@files_bp.route('/onlyoffice-callback', methods=['POST', 'OPTIONS'])
def onlyoffice_callback():
    """Handle callbacks from ONLYOFFICE Document Server."""
    if request.method == 'OPTIONS':
        return _onlyoffice_cors_response({})[0]

    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404

    try:
        data, error_response = _onlyoffice_validate_callback_payload()
        if error_response:
            return error_response

        status = data.get('status')
        key = data.get('key')
        logging.info('ONLYOFFICE callback received - status: %s, key: %s', status, key)

        if status in (2, 6):
            from app.utils.onlyoffice import onlyoffice_document_key_matches_resource

            file_id_raw = request.args.get('file_id')
            if not file_id_raw:
                logging.warning('ONLYOFFICE callback: No file_id provided in callback URL')
                return _onlyoffice_cors_response({'error': 'file_id required'}, 400)

            try:
                file_id = int(file_id_raw)
            except (ValueError, TypeError) as e:
                logging.error('ONLYOFFICE callback: Invalid file_id: %s', e)
                return _onlyoffice_cors_response({'error': 'invalid file_id'}, 400)

            if not onlyoffice_document_key_matches_resource(key, 'file', file_id):
                logging.warning(
                    'ONLYOFFICE callback: key/file_id mismatch key=%s file_id=%s',
                    key,
                    file_id,
                )
                return _onlyoffice_cors_response({'error': 'key mismatch'}, 403)

            file = File.query.get(file_id)
            if not file:
                logging.warning('ONLYOFFICE callback: file %s not found', file_id)
                return _onlyoffice_cors_response({'error': 'file not found'}, 404)

            try:
                _onlyoffice_handle_save_callback(file, data)
            except Exception as e:
                logging.error('ONLYOFFICE callback: Error saving file: %s', e)

        return _onlyoffice_cors_response({'error': 0})[0]
    except Exception as e:
        logging.error('ONLYOFFICE callback error: %s', e)
        return _onlyoffice_cors_response({'error': 'callback_error'}, 500)


@files_bp.route('/share/<token>/onlyoffice-callback', methods=['POST', 'OPTIONS'])
def share_onlyoffice_callback(token):
    """Handle callbacks from ONLYOFFICE Document Server (Gast-Zugriff)."""
    if request.method == 'OPTIONS':
        return _onlyoffice_cors_response({})[0]
    
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    share, item = _get_public_share_context(token)
    if not share or not item:
        logging.warning('ONLYOFFICE share callback: Invalid share token')
        return jsonify({'error': 'Invalid share token'}), 403
    if normalize_share_mode(share.mode) != 'edit':
        logging.warning('ONLYOFFICE share callback: share is not edit mode')
        return jsonify({'error': 'Access denied'}), 403

    guest_name = session.get(f'share_guest_name_{token}') or 'Gast'
    
    # Get file_id from callback URL parameter
    file_id = request.args.get('file_id')
    if not file_id:
        return jsonify({'error': 'File ID required'}), 400
    
    try:
        file_id = int(file_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid file ID'}), 400
    
    # Prüfe ob es eine Datei aus einem Ordner ist oder direkt freigegebene Datei
    if isinstance(item, Folder):
        file = _resolve_shared_file(item, file_id)
        if not file:
            return jsonify({'error': 'File not found in share'}), 404
    else:
        # Direkt freigegebene Datei
        if item.id != file_id:
            return jsonify({'error': 'File ID mismatch'}), 403
        file = item
    
    try:
        data, error_response = _onlyoffice_validate_callback_payload()
        if error_response:
            return error_response

        from app.utils.onlyoffice import onlyoffice_document_key_matches_resource
        key = data.get('key')
        if not onlyoffice_document_key_matches_resource(key, 'file', file_id):
            logging.warning(
                'ONLYOFFICE share callback: key/file_id mismatch key=%s file_id=%s',
                key,
                file_id,
            )
            return _onlyoffice_cors_response({'error': 'key mismatch'}, 403)

        status = data.get('status')
        
        logging.info('ONLYOFFICE share callback received - status: %s', status)

        if status in (2, 6):
            saved_file_url = data.get('url')
            
            if saved_file_url:
                saved_content = _download_onlyoffice_saved_content(saved_file_url)

                if saved_content:
                    # Get anonymous user for guest edits
                    anonymous_user = User.query.filter_by(email='anonymous@system.local').first()
                    if not anonymous_user:
                        anonymous_user = User(
                            email='anonymous@system.local',
                            first_name=guest_name,
                            last_name='',
                            password_hash='',
                            is_active=True,
                            is_admin=False,
                            is_email_confirmed=True
                        )
                        db.session.add(anonymous_user)
                        db.session.flush()

                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    safe_name = _disk_safe_upload_basename(file.original_name)
                    filename = f"{timestamp}_{safe_name}"
                    filepath = os.path.join('uploads', 'files', filename)
                    
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    
                    with open(filepath, 'wb') as f:
                        f.write(saved_content)
                    
                    absolute_filepath = os.path.abspath(filepath)
                    
                    version = FileVersion(
                        file_id=file.id,
                        version_number=file.version_number,
                        file_path=os.path.abspath(file.file_path),
                        file_size=file.file_size,
                        uploaded_by=file.uploaded_by
                    )
                    db.session.add(version)
                    
                    versions = FileVersion.query.filter_by(file_id=file.id).order_by(
                        FileVersion.version_number.desc()
                    ).all()
                    
                    if len(versions) >= MAX_FILE_VERSIONS:
                        oldest = versions[-1]
                        if os.path.exists(oldest.file_path):
                            os.remove(oldest.file_path)
                        db.session.delete(oldest)
                    
                    file.file_path = absolute_filepath
                    file.file_size = os.path.getsize(absolute_filepath)
                    file.version_number += 1
                    file.uploaded_by = anonymous_user.id
                    file.updated_at = datetime.utcnow()
                    
                    db.session.commit()
                    
                    logging.info(
                        "ONLYOFFICE: Shared file %s saved (version %s) by guest %s",
                        file.id,
                        file.version_number,
                        guest_name,
                    )
        
        return _onlyoffice_cors_response({'error': 0})[0]
        
    except Exception as e:
        logging.error(f"ONLYOFFICE callback error (share): {e}")
        return _onlyoffice_cors_response({'error': 'callback_error'}, 500)
