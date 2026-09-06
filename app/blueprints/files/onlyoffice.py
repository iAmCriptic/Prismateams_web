"""ONLYOFFICE debug, presence, lock, and editor routes."""

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

# ONLYOFFICE Routes
@files_bp.route('/api/onlyoffice-debug', methods=['GET'])
@login_required
@check_module_access('module_files')
def onlyoffice_debug():
    """Debug endpoint to show OnlyOffice configuration and URLs."""
    from flask import abort, url_for
    if not current_app.debug:
        abort(404)
    from urllib.parse import quote
    
    # Get a test file if available
    test_file = File.query.filter(File.original_name.like('%.docx')).first()
    if not test_file:
        test_file = File.query.first()
    
    debug_info = {
        'config': {
            'ONLYOFFICE_ENABLED': current_app.config.get('ONLYOFFICE_ENABLED', False),
            'ONLYOFFICE_DOCUMENT_SERVER_URL': current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice'),
            'ONLYOFFICE_PUBLIC_URL': current_app.config.get('ONLYOFFICE_PUBLIC_URL', ''),
            'ONLYOFFICE_SECRET_KEY_SET': bool(current_app.config.get('ONLYOFFICE_SECRET_KEY', '').strip()),
        },
        'request_info': {
            'scheme': request.scheme,
            'host': request.host,
            'url': request.url,
            'base_url': request.url_root,
        }
    }
    
    if test_file:
        # Generate URLs like in edit_onlyoffice
        from app.utils.onlyoffice import generate_onlyoffice_access_token
        access_token = generate_onlyoffice_access_token(test_file.id, current_user.id)
        public_url = current_app.config.get('ONLYOFFICE_PUBLIC_URL', '').strip()
        
        if public_url:
            public_url = public_url.rstrip('/')
            from urllib.parse import quote
            base_url = url_for('files.onlyoffice_document', file_id=test_file.id)
            encoded_token = quote(access_token, safe='')
            document_url = f"{public_url}{base_url}?token={encoded_token}"
        else:
            from urllib.parse import quote
            base_url = url_for('files.onlyoffice_document', file_id=test_file.id, _external=True)
            encoded_token = quote(access_token, safe='')
            document_url = f"{base_url}?token={encoded_token}"
        
        debug_info['test_file'] = {
            'id': test_file.id,
            'name': test_file.original_name,
            'file_path': test_file.file_path,
            'document_url': document_url,
            'access_token_length': len(access_token),
        }
        
        # Check file permissions
        import stat
        file_path = test_file.file_path if os.path.isabs(test_file.file_path) else os.path.join(os.getcwd(), test_file.file_path)
        if os.path.exists(file_path):
            try:
                file_stat = os.stat(file_path)
                debug_info['test_file']['permissions'] = {
                    'exists': True,
                    'readable': os.access(file_path, os.R_OK),
                    'permissions_octal': oct(stat.S_IMODE(file_stat.st_mode)),
                    'owner_uid': file_stat.st_uid,
                    'group_gid': file_stat.st_gid,
                }
            except Exception as e:
                debug_info['test_file']['permissions'] = {'error': str(e)}
        else:
            debug_info['test_file']['permissions'] = {'exists': False}
    
    return jsonify(debug_info)


@files_bp.route('/api/onlyoffice-diagnose', methods=['GET'])
@login_required
@check_module_access('module_files')
def onlyoffice_diagnose():
    """Diagnose OnlyOffice Document Server connectivity."""
    import requests
    from urllib.parse import urljoin
    
    results = {
        'onlyoffice_enabled': current_app.config.get('ONLYOFFICE_ENABLED', False),
        'onlyoffice_url': current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice'),
        'tests': {}
    }
    
    if not results['onlyoffice_enabled']:
        return jsonify(results)
    
    onlyoffice_url = results['onlyoffice_url']
    
    # Test 1: Direct connection to OnlyOffice on port 8080
    try:
        response = requests.get('http://127.0.0.1:8080/welcome/', timeout=5)
        results['tests']['direct_8080'] = {
            'status': 'success' if response.status_code == 200 else 'failed',
            'status_code': response.status_code,
            'content_type': response.headers.get('Content-Type', ''),
            'message': 'OnlyOffice is reachable on port 8080' if response.status_code == 200 else f'OnlyOffice returned status {response.status_code}'
        }
    except requests.exceptions.ConnectionError:
        results['tests']['direct_8080'] = {
            'status': 'failed',
            'message': 'Cannot connect to OnlyOffice on port 8080. Is the Docker container running?'
        }
    except Exception as e:
        results['tests']['direct_8080'] = {
            'status': 'error',
            'message': f'Error: {str(e)}'
        }
    
    # Test 2: OnlyOffice API via Nginx proxy
    if onlyoffice_url.startswith('http'):
        api_url = f"{onlyoffice_url.rstrip('/')}/web-apps/apps/api/documents/api.js"
    else:
        scheme = request.scheme
        host = request.host
        if not onlyoffice_url.startswith('/'):
            onlyoffice_url = '/' + onlyoffice_url
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{scheme}://{host}{onlyoffice_url}/web-apps/apps/api/documents/api.js"
    
    try:
        response = requests.get(api_url, timeout=5)
        content_type = response.headers.get('Content-Type', '')
        is_javascript = 'javascript' in content_type.lower() or response.text.strip().startswith(('var ', 'function ', '!function', '(function'))
        is_html = '<html' in response.text.lower() or '<!doctype' in response.text.lower()
        
        results['tests']['api_via_nginx'] = {
            'status': 'success' if is_javascript and not is_html else 'failed',
            'status_code': response.status_code,
            'content_type': content_type,
            'url': api_url,
            'is_javascript': is_javascript,
            'is_html': is_html,
            'content_preview': response.text[:200] if len(response.text) > 0 else '(empty)',
            'message': 'API file is correctly served as JavaScript' if is_javascript and not is_html else 'API file is NOT served as JavaScript (likely HTML error page)'
        }
    except Exception as e:
        results['tests']['api_via_nginx'] = {
            'status': 'error',
            'url': api_url,
            'message': f'Error accessing API via Nginx: {str(e)}'
        }
    
    # Test 3: OnlyOffice welcome page via Nginx
    if onlyoffice_url.startswith('http'):
        welcome_url = f"{onlyoffice_url.rstrip('/')}/welcome/"
    else:
        welcome_url = f"{scheme}://{host}{onlyoffice_url}/welcome/"
    
    try:
        response = requests.get(welcome_url, timeout=5)
        results['tests']['welcome_via_nginx'] = {
            'status': 'success' if response.status_code == 200 else 'failed',
            'status_code': response.status_code,
            'content_type': response.headers.get('Content-Type', ''),
            'url': welcome_url,
            'message': 'Welcome page is accessible via Nginx' if response.status_code == 200 else f'Welcome page returned status {response.status_code}'
        }
    except Exception as e:
        results['tests']['welcome_via_nginx'] = {
            'status': 'error',
            'url': welcome_url,
            'message': f'Error accessing welcome page via Nginx: {str(e)}'
        }
    
    return jsonify(results)


@files_bp.route('/api/presence')
@login_required
@check_module_access('module_files')
def api_files_presence():
    folder_id_raw = request.args.get('folder_id')
    folder_id = None
    if folder_id_raw not in (None, '', 'null', 'None'):
        try:
            folder_id = int(folder_id_raw)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Ungültige Ordner-ID'}), 400
    return jsonify({'success': True, 'presence': presence_for_folder(folder_id)})


@files_bp.route('/api/onlyoffice-presence', methods=['POST'])
@login_required
@check_module_access('module_files')
def api_onlyoffice_presence():
    payload = request.get_json(silent=True) or {}
    action = (payload.get('action') or 'heartbeat').strip().lower()
    session_key = (payload.get('session_key') or '').strip()
    if action == 'leave':
        if session_key:
            oo_leave_session(session_key)
            db.session.commit()
        return jsonify({'success': True})
    if action == 'heartbeat':
        if not session_key:
            return jsonify({'success': False, 'error': 'session_key fehlt'}), 400
        row = oo_heartbeat_session(session_key)
        if not row:
            return jsonify({'success': False, 'error': 'Session unbekannt'}), 404
        db.session.commit()
        return jsonify({'success': True, 'session_key': row.session_key})
    try:
        file_id = int(payload.get('file_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'file_id fehlt'}), 400
    file_obj = File.query.get_or_404(file_id)
    if _is_guest_user():
        from app.utils.access_control import GUEST_EDIT_MODES, guest_has_file_access
        if not guest_has_file_access(current_user, file_obj, modes=GUEST_EDIT_MODES):
            return jsonify({'success': False, 'error': 'Kein Zugriff'}), 403
    display_name = current_user.full_name if current_user.is_authenticated else 'Gast'
    avatar = getattr(current_user, 'profile_picture', None) if current_user.is_authenticated else None
    row = oo_upsert_session(
        file_id=file_id,
        session_key=session_key or None,
        user_id=current_user.id if current_user.is_authenticated else None,
        guest_key=None,
        display_name=display_name,
        avatar_filename=avatar,
    )
    db.session.commit()
    return jsonify({'success': True, 'session_key': row.session_key})


@files_bp.route('/api/edit-lock', methods=['POST'])
@login_required
@check_module_access('module_files')
def api_file_edit_lock():
    """Acquire / heartbeat / release exclusive Markdown editor locks."""
    payload = request.get_json(silent=True) or {}
    action = (payload.get('action') or 'heartbeat').strip().lower()
    session_key = (payload.get('session_key') or '').strip()

    if action == 'leave':
        ok = False
        if session_key:
            ok = file_edit_lock_util.release(session_key, current_user.id)
        elif payload.get('file_id') is not None:
            try:
                file_id = int(payload.get('file_id'))
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'file_id fehlt'}), 400
            ok = file_edit_lock_util.release_for_file(file_id, current_user.id)
        if ok:
            db.session.commit()
        return jsonify({'success': True, 'released': ok})

    if action == 'heartbeat':
        if not session_key:
            return jsonify({'success': False, 'error': 'session_key fehlt'}), 400
        lock = file_edit_lock_util.heartbeat(session_key, current_user.id)
        if not lock:
            return jsonify({'success': False, 'error': 'Lock unbekannt oder abgelaufen'}), 404
        db.session.commit()
        return jsonify({'success': True, 'lock': file_edit_lock_util.serialize_lock(lock)})

    if action == 'status':
        try:
            file_id = int(payload.get('file_id'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'file_id fehlt'}), 400
        lock = file_edit_lock_util.get_active_lock(file_id)
        held_by_me = bool(lock and lock.locked_by == current_user.id)
        return jsonify({
            'success': True,
            'locked': bool(lock),
            'held_by_me': held_by_me,
            'lock': file_edit_lock_util.serialize_lock(lock, include_session=held_by_me),
        })

    # Default: acquire / join — Markdown only
    try:
        file_id = int(payload.get('file_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'file_id fehlt'}), 400
    file_obj = File.query.get_or_404(file_id)
    file_ext = os.path.splitext(file_obj.original_name)[1].lower()
    if not _is_markdown_extension(file_ext):
        return jsonify({
            'success': False,
            'error': 'Edit-Lock gilt nur für Markdown-Dateien.',
        }), 400
    if _is_guest_user():
        from app.utils.access_control import GUEST_EDIT_MODES, guest_has_file_access
        if not guest_has_file_access(current_user, file_obj, modes=GUEST_EDIT_MODES):
            return jsonify({'success': False, 'error': 'Kein Zugriff'}), 403

    lock, blocker = file_edit_lock_util.acquire(
        file_id,
        current_user.id,
        session_key=session_key or None,
    )
    if not lock:
        return jsonify({
            'success': False,
            'locked': True,
            'error': 'Datei wird gerade von einem anderen Nutzer bearbeitet.',
            'lock': file_edit_lock_util.serialize_lock(blocker, include_session=False),
        }), 409
    db.session.commit()
    return jsonify({'success': True, 'lock': file_edit_lock_util.serialize_lock(lock)})


@files_bp.route('/edit-onlyoffice/<int:file_id>')
@login_required
@check_module_access('module_files')
def edit_onlyoffice(file_id):
    """Edit a file using ONLYOFFICE editor."""
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        flash('ONLYOFFICE ist nicht aktiviert.', 'warning')
        return redirect(url_for('files.index'))
    
    file = File.query.get_or_404(file_id)
    
    # Für Gast-Accounts: OnlyOffice-Edit nur mit edit-Freigabe
    guest_accessible_folder_ids = None
    if _is_guest_user():
        from app.utils.access_control import GUEST_EDIT_MODES, guest_has_file_access
        if not guest_has_file_access(current_user, file, modes=GUEST_EDIT_MODES):
            flash('Sie haben keine Bearbeitungsrechte für diese Datei.', 'danger')
            return redirect(url_for('files.index'))
        guest_accessible_folder_ids = _get_guest_accessible_folder_ids()
    elif not can_edit_file(file, current_user) and not current_user.is_admin:
        flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
        return redirect(url_for('files.index'))
    
    # Check if file type is supported by ONLYOFFICE
    from app.utils.onlyoffice import is_onlyoffice_file_type, get_onlyoffice_document_type, get_onlyoffice_file_type, generate_onlyoffice_token
    file_ext = os.path.splitext(file.original_name)[1].lower()
    
    if not is_onlyoffice_file_type(file_ext):
        flash('Dieser Dateityp wird von ONLYOFFICE nicht unterstützt.', 'warning')
        return redirect(_get_safe_file_back_url(file, guest_accessible_folder_ids))
    
    # Get document type and file type
    document_type = get_onlyoffice_document_type(file_ext)
    file_type = get_onlyoffice_file_type(file_ext)
    
    # Generate unique document key for versioning
    from app.utils.onlyoffice import build_onlyoffice_document_key, resolve_storage_path
    file_path = resolve_storage_path(file.file_path)
    document_key = build_onlyoffice_document_key('file', file.id, file.version_number, file_path)
    
    # Generate access token for OnlyOffice to access the document
    from app.utils.onlyoffice import generate_onlyoffice_access_token
    access_token = generate_onlyoffice_access_token(file.id, current_user.id)
    
    # Build document URL - use public URL if OnlyOffice is on different server
    public_url = current_app.config.get('ONLYOFFICE_PUBLIC_URL', '').strip()
    if public_url:
        # Use configured public URL (required when OnlyOffice runs on different server)
        public_url = public_url.rstrip('/')
        # Build URL manually to ensure token is included as query parameter
        # IMPORTANT: Use urllib.parse.quote to properly encode the token
        from urllib.parse import quote
        base_url = url_for('files.onlyoffice_document', file_id=file.id)
        encoded_token = quote(access_token, safe='')
        document_url = f"{public_url}{base_url}?token={encoded_token}"
        callback_url = f"{public_url}{url_for('files.onlyoffice_callback', file_id=file.id)}"
    else:
        # Use _external=True (works if OnlyOffice is on same server or accessible via same domain)
        from urllib.parse import quote
        base_url = url_for('files.onlyoffice_document', file_id=file.id, _external=True)
        encoded_token = quote(access_token, safe='')
        document_url = f"{base_url}?token={encoded_token}"
        callback_url = url_for('files.onlyoffice_callback', file_id=file.id, _external=True)
    
    # Log URLs for debugging
    logging.info(f"ONLYOFFICE document_url: {document_url}")
    logging.info(f"ONLYOFFICE callback_url: {callback_url}")
    logging.info(f"ONLYOFFICE access_token: {access_token[:8]}... (length: {len(access_token)})")
    
    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    
    # Build full URL to ONLYOFFICE API
    if onlyoffice_url.startswith('http'):
        # Absolute URL - normalize (remove trailing slash if present)
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{onlyoffice_url}/web-apps/apps/api/documents/api.js"
    else:
        # Relative path - use request host and scheme
        scheme = request.scheme
        host = request.host
        # Ensure onlyoffice_url starts with /
        if not onlyoffice_url.startswith('/'):
            onlyoffice_url = '/' + onlyoffice_url
        # Remove trailing slash
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{scheme}://{host}{onlyoffice_url}/web-apps/apps/api/documents/api.js"
    
    # Build editor configuration for token generation
    user_image = None
    if current_user.is_authenticated and getattr(current_user, 'profile_picture', None):
        try:
            user_image = url_for('settings.profile_picture', filename=current_user.profile_picture, _external=True)
        except Exception:
            user_image = None

    editor_config = {
        "document": {
            "fileType": file_type,
            "key": document_key,
            "title": file.name,
            "url": document_url
        },
        "documentType": document_type,
        "editorConfig": {
            "callbackUrl": callback_url,
            "mode": "edit",
            "user": {
                "id": str(current_user.id),
                "name": current_user.full_name
            },
            "customization": {
                "uiTheme": (
                    "theme-contrast-dark"
                    if getattr(current_user, "oled_mode", False)
                    else ("theme-dark" if getattr(current_user, "dark_mode", False) else "theme-classic-light")
                )
            },
        }
    }
    if user_image:
        editor_config["editorConfig"]["user"]["image"] = user_image
    
    # Generate token if secret key is configured
    token = generate_onlyoffice_token(editor_config)
    
    # Log token status for debugging
    if token:
        logging.debug(f"ONLYOFFICE token generated for file {file.id}")
    else:
        secret_key = current_app.config.get('ONLYOFFICE_SECRET_KEY', '')
        if secret_key:
            logging.warning(f"ONLYOFFICE token generation failed for file {file.id} (secret key is set)")
        else:
            logging.debug(f"ONLYOFFICE token not generated for file {file.id} (no secret key configured)")
    
    # Calculate return URL
    return_url = _get_safe_file_back_url(file, guest_accessible_folder_ids)
    
    # Get user accent color/style
    accent_color = current_user.accent_color if current_user.is_authenticated else '#0d6efd'
    accent_style = current_user.accent_style if current_user.is_authenticated else 'linear-gradient(45deg, #0d6efd, #0d6efd)'
    
    current_language = get_current_language()

    ua = (request.user_agent.string or '').lower()
    is_mobile_ua = any(x in ua for x in ('iphone', 'ipod', 'android', 'mobile', 'ipad'))
    force_desktop = request.args.get('desktop') == '1'
    theme_dark = bool(getattr(current_user, 'dark_mode', False))
    theme_oled = bool(getattr(current_user, 'oled_mode', False))
    onlyoffice_ui_theme = editor_config["editorConfig"]["customization"]["uiTheme"]
    
    return render_template(
        'files/edit_onlyoffice.html',
        file=file,
        document_key=document_key,
        document_type=document_type,
        file_type=file_type,
        document_url=document_url,
        callback_url=callback_url,
        onlyoffice_api_url=api_url,
        onlyoffice_url=onlyoffice_url,
        token=token or '',  # Pass empty string instead of None
        guest_mode=False,
        return_url=return_url,
        download_url=url_for('files.download_file', file_id=file.id),
        accent_color=accent_color,
        accent_style=accent_style,
        current_language=current_language,
        user_image=user_image or '',
        presence_enabled=True,
        is_mobile_client=is_mobile_ua and not force_desktop,
        theme_dark=theme_dark,
        theme_oled=theme_oled,
        onlyoffice_ui_theme=onlyoffice_ui_theme,
        forcesave_url=url_for('files.onlyoffice_forcesave', file_id=file.id),
    )


@files_bp.route('/share/<token>/edit-onlyoffice')
def share_edit_onlyoffice(token):
    """Edit a shared file using ONLYOFFICE editor (Gast-Zugriff)."""
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        flash('ONLYOFFICE ist nicht aktiviert.', 'warning')
        return redirect(url_for('files.public_share', token=token))
    
    share = get_share_by_token(token)
    if not share or normalize_share_mode(share.mode) != 'edit':
        flash('Bearbeiten ist fuer diese Freigabe nicht erlaubt.', 'warning')
        return redirect(url_for('files.public_share', token=token))
    if not _validate_share_edit_bot(token):
        flash('Bot-Schutz-Prüfung fehlgeschlagen. Bitte erneut versuchen.', 'danger')
        return redirect(url_for('files.public_share', token=token))

    item, guest_name, _access_share = _check_share_access(token)
    if not item:
        flash('Bitte geben Sie zuerst Ihren Namen ein.', 'warning')
        return redirect(url_for('files.public_share', token=token))

    log_share_access(share, 'onlyoffice_edit', request, guest_name=guest_name)
    db.session.commit()
    
    # Prüfe ob eine spezifische Datei aus einem Ordner bearbeitet werden soll
    file_id = request.args.get('file_id')
    if file_id:
        try:
            file_id = int(file_id)
            file = _resolve_shared_file(item, file_id)
            if not file:
                abort(404)
        except (ValueError, TypeError):
            flash('Ungültige Datei-ID.', 'danger')
            return redirect(url_for('files.public_share', token=token))
    else:
        # Direkt freigegebene Datei
        if not isinstance(item, File):
            flash('Ordner können nicht mit ONLYOFFICE bearbeitet werden. Bitte wählen Sie eine Datei aus.', 'warning')
            return redirect(url_for('files.public_share', token=token))
        file = item
    
    # Check if file type is supported by ONLYOFFICE
    from app.utils.onlyoffice import is_onlyoffice_file_type, get_onlyoffice_document_type, get_onlyoffice_file_type, generate_onlyoffice_token
    file_ext = os.path.splitext(file.original_name)[1].lower()
    
    if not is_onlyoffice_file_type(file_ext):
        flash('Dieser Dateityp wird von ONLYOFFICE nicht unterstützt.', 'warning')
        return redirect(url_for('files.public_share', token=token))
    
    # Get document type and file type
    document_type = get_onlyoffice_document_type(file_ext)
    file_type = get_onlyoffice_file_type(file_ext)
    
    # Generate unique document key for versioning
    from app.utils.onlyoffice import build_onlyoffice_document_key, resolve_storage_path
    file_path = resolve_storage_path(file.file_path)
    document_key = build_onlyoffice_document_key('file', file.id, file.version_number, file_path)
    
    # Build document URL with token and file_id (guest_name ist in Session)
    # Share endpoints don't need additional token as they use share_token
    public_url = current_app.config.get('ONLYOFFICE_PUBLIC_URL', '').strip()
    if public_url:
        # Use configured public URL (required when OnlyOffice runs on different server)
        public_url = public_url.rstrip('/')
        document_url = f"{public_url}{url_for('files.share_onlyoffice_document', token=token, file_id=file.id)}"
        callback_url = f"{public_url}{url_for('files.share_onlyoffice_callback', token=token, file_id=file.id)}"
    else:
        # Use _external=True (works if OnlyOffice is on same server or accessible via same domain)
        document_url = url_for('files.share_onlyoffice_document', token=token, file_id=file.id, _external=True)
        callback_url = url_for('files.share_onlyoffice_callback', token=token, file_id=file.id, _external=True)
    
    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    
    # Build full URL to ONLYOFFICE API
    if onlyoffice_url.startswith('http'):
        # Absolute URL - normalize (remove trailing slash if present)
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{onlyoffice_url}/web-apps/apps/api/documents/api.js"
    else:
        # Relative path - use request host and scheme
        scheme = request.scheme
        host = request.host
        # Ensure onlyoffice_url starts with /
        if not onlyoffice_url.startswith('/'):
            onlyoffice_url = '/' + onlyoffice_url
        # Remove trailing slash
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{scheme}://{host}{onlyoffice_url}/web-apps/apps/api/documents/api.js"
    
    # Build editor configuration for token generation
    editor_config = {
        "document": {
            "fileType": file_type,
            "key": document_key,
            "title": file.name,
            "url": document_url
        },
        "documentType": document_type,
        "editorConfig": {
            "callbackUrl": callback_url,
            "mode": "edit",
            "user": {
                "id": f"guest_{token}",
                "name": guest_name
            },
            "customization": {
                "uiTheme": "theme-classic-light"
            },
        }
    }
    
    # Generate token if secret key is configured
    onlyoffice_token = generate_onlyoffice_token(editor_config)
    
    # Log token status for debugging
    if onlyoffice_token:
        logging.debug(f"ONLYOFFICE token generated for shared file {file.id}")
    else:
        secret_key = current_app.config.get('ONLYOFFICE_SECRET_KEY', '')
        if secret_key:
            logging.warning(f"ONLYOFFICE token generation failed for shared file {file.id} (secret key is set)")
        else:
            logging.debug(f"ONLYOFFICE token not generated for shared file {file.id} (no secret key configured)")
    
    # Calculate return URL for shared files
    return_url = url_for('files.public_share', token=token)
    if request.args.get('file_id'):
        download_url = url_for('files.public_share_folder_file_download', token=token, file_id=file.id)
    else:
        download_url = url_for('files.public_share_download', token=token)
    
    # For guest users, use default accent color
    accent_color = '#0d6efd'
    accent_style = 'linear-gradient(45deg, #0d6efd, #0d6efd)'
    
    current_language = get_current_language()
    
    return render_template(
        'files/edit_onlyoffice.html',
        file=file,
        document_key=document_key,
        document_type=document_type,
        file_type=file_type,
        document_url=document_url,
        callback_url=callback_url,
        onlyoffice_api_url=api_url,
        onlyoffice_url=onlyoffice_url,
        token=onlyoffice_token or '',  # Pass empty string instead of None
        guest_mode=True,
        guest_name=guest_name,
        share_token=token,
        return_url=return_url,
        download_url=download_url,
        accent_color=accent_color,
        accent_style=accent_style,
        current_language=current_language,
        user_image='',
        presence_enabled=True,
        is_mobile_client=False,
        theme_dark=False,
        theme_oled=False,
        onlyoffice_ui_theme='theme-classic-light',
        forcesave_url=url_for('files.share_onlyoffice_forcesave', token=token, file_id=file.id),
    )
