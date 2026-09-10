"""Serve, download, edit, preview, and view file routes."""

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

@files_bp.route('/serve-pdf/<int:file_id>')
@login_required
@check_module_access('module_files')
def serve_pdf(file_id):
    """Serve a PDF file for inline viewing (without forcing download)."""
    file = File.query.get_or_404(file_id)
    if not _is_guest_user() and not can_view_file(file, current_user) and not current_user.is_admin:
        flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
        return redirect(url_for('files.index'))
    
    # Ensure we have an absolute path
    if not os.path.isabs(file.file_path):
        file_path = os.path.join(os.getcwd(), file.file_path)
    else:
        file_path = file.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        flash(f'Datei "{file.original_name}" wurde nicht gefunden.', 'danger')
        return redirect(url_for('files.index'))
    
    # Only serve PDFs
    file_ext = os.path.splitext(file.original_name)[1].lower()
    if file_ext != '.pdf':
        flash('Diese Route ist nur für PDF-Dateien.', 'danger')
        return redirect(url_for('files.index'))
    
    return _response_with_nosniff(send_file(file_path, mimetype='application/pdf'))


@files_bp.route('/serve-media/<int:file_id>')
@login_required
@check_module_access('module_files')
def serve_media(file_id):
    """Serve image/video/audio inline for browser preview."""
    file = File.query.get_or_404(file_id)
    if not _can_serve_file_media(file):
        abort(403)
    return _send_inline_media(file)


def _can_serve_file_media(file):
    if _is_guest_user():
        from app.utils.access_control import guest_has_file_access
        return guest_has_file_access(current_user, file)
    return bool(can_view_file(file, current_user) or current_user.is_admin)


@files_bp.route('/thumb/<int:file_id>')
@login_required
@check_module_access('module_files')
def serve_thumb(file_id):
    """Small WebP preview for the files grid (not the full original)."""
    file = File.query.get_or_404(file_id)
    if not _can_serve_file_media(file):
        abort(403)
    return _send_image_preview(file)


@files_bp.route('/download/<int:file_id>')
@login_required
@check_module_access('module_files')
def download_file(file_id):
    """Download a file."""
    file = File.query.get_or_404(file_id)
    if not _is_guest_user() and not can_view_file(file, current_user) and not current_user.is_admin:
        flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
        return redirect(url_for('files.index'))
    
    # Ensure we have an absolute path
    if not os.path.isabs(file.file_path):
        file_path = os.path.join(os.getcwd(), file.file_path)
    else:
        file_path = file.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        flash(f'Datei "{file.original_name}" wurde nicht gefunden.', 'danger')
        return redirect(url_for('files.index'))

    file_ext = _file_extension(file.original_name)
    mimetype = _mimetype_for_extension(file_ext)

    return _response_with_nosniff(send_file(
        file_path, 
        as_attachment=True, 
        download_name=file.original_name,
        mimetype=mimetype
    ))


@files_bp.route('/download-version/<int:version_id>')
@login_required
@check_module_access('module_files')
def download_version(version_id):
    """Download a specific file version."""
    version = FileVersion.query.get_or_404(version_id)
    file = File.query.get_or_404(version.file_id)
    if not _is_guest_user() and not can_view_file(file, current_user) and not current_user.is_admin:
        flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
        return redirect(url_for('files.index'))
    
    # Ensure we have an absolute path
    if not os.path.isabs(version.file_path):
        file_path = os.path.join(os.getcwd(), version.file_path)
    else:
        file_path = version.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        flash(f'Datei-Version "{file.original_name} v{version.version_number}" wurde nicht gefunden.', 'danger')
        return redirect(url_for('files.index'))

    file_ext = _file_extension(file.original_name)
    mimetype = _mimetype_for_extension(file_ext)

    # Create versioned filename
    name_without_ext = os.path.splitext(file.original_name)[0]
    versioned_filename = f"{name_without_ext}_v{version.version_number}{file_ext}"
    
    return _response_with_nosniff(send_file(
        file_path, 
        as_attachment=True, 
        download_name=versioned_filename,
        mimetype=mimetype
    ))


@files_bp.route('/edit/<int:file_id>', methods=['GET', 'POST'])
@login_required
@check_module_access('module_files')
def edit_file(file_id):
    """Edit a text file online."""
    file = File.query.get_or_404(file_id)
    
    # Für Gast-Accounts: Bearbeiten nur mit edit-Freigabe (nicht view/dropbox)
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
    
    # Check if file is editable (text file)
    editable_extensions = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}
    file_ext = os.path.splitext(file.original_name)[1].lower()
    is_markdown = _is_markdown_extension(file_ext)
    
    if file_ext not in editable_extensions:
        flash('Dieser Dateityp kann nicht online bearbeitet werden.', 'warning')
        return redirect(_get_safe_file_back_url(file, guest_accessible_folder_ids))
    
    if request.method == 'POST':
        wants_json = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in (request.headers.get('Accept') or '')
        )
        # Exclusive lock only for Markdown (OnlyOffice stays collaborative).
        if is_markdown and not file_edit_lock_util.user_holds_lock(file.id, current_user.id):
            blocker = file_edit_lock_util.get_active_lock(file.id)
            locker_name = None
            if blocker:
                locker = blocker.locker or User.query.get(blocker.locked_by)
                locker_name = (locker.full_name if locker else None) or 'einem anderen Nutzer'
            msg = (
                f'Die Datei wird gerade von {locker_name} bearbeitet und kann nicht gespeichert werden.'
                if locker_name
                else 'Sie halten keinen Bearbeitungs-Lock für diese Datei.'
            )
            if wants_json:
                return jsonify({
                    'success': False,
                    'error': msg,
                    'locked': True,
                    'lock': file_edit_lock_util.serialize_lock(blocker, include_session=False),
                }), 409
            flash(msg, 'warning')
            return redirect(url_for('files.edit_file', file_id=file.id))

        content = request.form.get('content', '')
        
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
        
        # Kein Newline-Transform auf Windows, sonst entstehen doppelte Leerzeilen.
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        
        # Store absolute path in database
        absolute_filepath = os.path.abspath(filepath)
        
        file.file_path = absolute_filepath
        file.file_size = os.path.getsize(absolute_filepath)
        file.version_number += 1
        file.uploaded_by = current_user.id
        file.updated_at = datetime.utcnow()
        
        db.session.commit()

        if wants_json:
            return jsonify({'success': True, 'message': 'Datei wurde gespeichert.'})
        
        flash('Datei wurde gespeichert.', 'success')
        return redirect(_get_safe_file_back_url(file, guest_accessible_folder_ids))
    
    # Read file content
    try:
        # Ensure we have an absolute path
        if not os.path.isabs(file.file_path):
            file_path = os.path.join(os.getcwd(), file.file_path)
        else:
            file_path = file.file_path
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        flash(f'Fehler beim Lesen der Datei: {str(e)}', 'danger')
        return redirect(_get_safe_file_back_url(file, guest_accessible_folder_ids))

    # Exclusive soft-lock only for Markdown files.
    # OnlyOffice documents (docx/xlsx/pptx/…) stay collaborative.
    edit_locked = False
    lock_info = None
    edit_session_key = None
    if is_markdown:
        lock, blocker = file_edit_lock_util.acquire(file.id, current_user.id)
        edit_locked = lock is None
        if lock:
            lock_info = file_edit_lock_util.serialize_lock(lock, include_session=True)
            edit_session_key = lock.session_key
            db.session.commit()
        else:
            lock_info = file_edit_lock_util.serialize_lock(blocker, include_session=False)
    
    return render_template(
        'files/edit.html',
        file=file,
        content=content,
        back_url=_get_safe_file_back_url(file, guest_accessible_folder_ids),
        is_markdown=is_markdown,
        edit_locked=edit_locked,
        lock_info=lock_info,
        edit_session_key=edit_session_key,
    )


@files_bp.route('/preview/<int:file_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def preview_file(file_id):
    """Vorschau fuer Editor mit demselben Interpreter wie /view."""
    file = File.query.get_or_404(file_id)
    viewable_extensions = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}
    file_ext = os.path.splitext(file.original_name)[1].lower()

    if file_ext not in viewable_extensions:
        return jsonify({'error': translate('files.errors.file_type_not_supported')}), 400

    content = request.form.get('content', '')
    processed_content = _render_view_content(content, file_ext)
    return jsonify({'html': processed_content})


@files_bp.route('/link-preview', methods=['POST'])
@login_required
@check_module_access('module_files')
def link_preview():
    """JSON unfurl card for Markdown link hover previews."""
    from app.utils.link_preview import build_link_preview

    payload = request.get_json(silent=True) or {}
    url = payload.get('url') or request.form.get('url') or ''
    return jsonify(build_link_preview(url))


@files_bp.route('/view/<int:file_id>')
@login_required
@check_module_access('module_files')
def view_file(file_id):
    """View a file in fullscreen mode (for markdown/text/PDF files)."""
    file = File.query.get_or_404(file_id)
    
    # Für Gast-Accounts: Prüfe ob Zugriff über Freigabelink besteht
    guest_accessible_folder_ids = None
    if _is_guest_user():
        from app.utils.access_control import guest_has_file_access
        if not guest_has_file_access(current_user, file):
            flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
            return redirect(url_for('files.index'))
        guest_accessible_folder_ids = _get_guest_accessible_folder_ids()
    elif not can_view_file(file, current_user) and not current_user.is_admin:
        flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
        return redirect(url_for('files.index'))
    else:
        try:
            from app.utils.notifications import mark_in_app_notifications_read
            mark_in_app_notifications_read(
                current_user.id,
                notification_type='file',
                source_id=file_id,
                commit=True,
            )
        except Exception:
            pass
    
    # Merke View/Ordner für „Schließen“ zurück in denselben Kontext
    view_arg = request.args.get('view')
    if not _is_guest_user():
        private_enabled = is_private_folders_enabled()
        team_enabled = is_team_folders_enabled()
        files_view = normalize_view(
            view_arg or session.get('files_last_view'),
            private_enabled=private_enabled,
            team_enabled=team_enabled,
        )
        if files_view:
            session['files_last_view'] = files_view
        if files_view == 'team' and getattr(file, 'team_id', None):
            session['files_last_team_id'] = file.team_id
        if file.folder_id:
            session['files_last_folder_id'] = file.folder_id
    else:
        files_view = None

    back_url = _get_safe_file_back_url(file, guest_accessible_folder_ids, view=files_view if not _is_guest_user() else None)

    file_ext = _file_extension(file.original_name)
    
    # Handle PDF files - display in browser
    if file_ext == '.pdf':
        # Ensure we have an absolute path
        if not os.path.isabs(file.file_path):
            file_path = os.path.join(os.getcwd(), file.file_path)
        else:
            file_path = file.file_path
        
        # Check if file exists
        if not os.path.exists(file_path):
            flash(f'Datei "{file.original_name}" wurde nicht gefunden.', 'danger')
            return redirect(back_url)
        
        # Return PDF for inline viewing (similar to manuals)
        return render_template(
            'files/view.html',
            file=file,
            is_pdf=True,
            back_url=back_url
        )

    kind = media_kind(file_ext)
    if kind:
        file_path = _resolve_absolute_file_path(file.file_path)
        if not file_path or not os.path.exists(file_path):
            flash(f'Datei "{file.original_name}" wurde nicht gefunden.', 'danger')
            return redirect(back_url)
        return render_template(
            'files/view.html',
            file=file,
            is_pdf=False,
            is_image=kind == 'image',
            is_video=kind == 'video',
            is_audio=kind == 'audio',
            media_kind=kind,
            back_url=back_url,
        )
    
    # Handle text/markdown files (existing logic)
    if file_ext not in TEXT_VIEWABLE_EXTS:
        flash('Dieser Dateityp kann nicht angezeigt werden.', 'warning')
        return redirect(back_url)
    
    # Read file content
    try:
        # Ensure we have an absolute path
        if not os.path.isabs(file.file_path):
            file_path = os.path.join(os.getcwd(), file.file_path)
        else:
            file_path = file.file_path
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        flash(f'Fehler beim Lesen der Datei: {str(e)}', 'danger')
        return redirect(back_url)
    
    is_markdown = _is_markdown_extension(file_ext)
    processed_content = _render_view_content(content, file_ext)
    if is_markdown:
        current_app.logger.info(f"Markdown processed. Table detected: {'<table>' in processed_content}")
    
    return render_template(
        'files/view.html',
        file=file,
        content=content,
        processed_content=processed_content,
        is_markdown=is_markdown,
        is_pdf=False,
        back_url=back_url
    )
