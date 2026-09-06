"""Briefkasten (dropbox) routes."""

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


# Briefkasten (Dropbox) Routes
@files_bp.route('/folder/<int:folder_id>/make-dropbox', methods=['POST'])
@login_required
@check_module_access('module_files')
def make_dropbox(folder_id):
    """Aktiviere Briefkasten für einen Ordner (legt public_shares-Eintrag an)."""
    if not _is_dropbox_enabled():
        flash('Briefkästen sind deaktiviert.', 'warning')
        return redirect(_safe_referrer_or(url_for('files.browse_folder', folder_id=folder_id)))

    folder = Folder.query.get_or_404(folder_id)
    create_share_link(
        'folder',
        folder,
        'dropbox',
        created_by=current_user.id,
        label=request.form.get('label', 'Briefkasten'),
        password=request.form.get('password', ''),
        expires_at_raw=request.form.get('expires_at', ''),
    )
    db.session.commit()

    flash(f'Briefkasten für Ordner "{folder.name}" wurde aktiviert.', 'success')
    return redirect(url_for('files.browse_folder', folder_id=folder_id))


@files_bp.route('/folder/<int:folder_id>/dropbox-settings', methods=['GET', 'POST'])
@login_required
@check_module_access('module_files')
def dropbox_settings(folder_id):
    """Briefkasten-Einstellungen anzeigen und bearbeiten."""
    folder = Folder.query.get_or_404(folder_id)
    
    if not folder.is_dropbox:
        flash('Dieser Ordner ist kein Briefkasten.', 'danger')
        return redirect(url_for('files.browse_folder', folder_id=folder_id))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'set_password':
            password = request.form.get('password', '').strip()
            if password:
                folder.dropbox_password_hash = generate_password_hash(password)
                db.session.commit()
                flash('Passwort wurde gesetzt.', 'success')
            else:
                flash('Bitte geben Sie ein Passwort ein.', 'danger')
        
        elif action == 'remove_password':
            folder.dropbox_password_hash = None
            db.session.commit()
            flash('Passwort wurde entfernt.', 'success')
        
        elif action == 'regenerate_token':
            # Generate new token
            token = secrets.token_urlsafe(32)
            while Folder.query.filter_by(dropbox_token=token).first():
                token = secrets.token_urlsafe(32)
            folder.dropbox_token = token
            db.session.commit()
            flash('Link wurde neu generiert.', 'success')
        
        # Redirect back to folder view
        return redirect(url_for('files.browse_folder', folder_id=folder_id))
    
    # GET: Return JSON for AJAX call
    dropbox_url = url_for('files.dropbox_upload', token=folder.dropbox_token, _external=True)
    return jsonify({
        'success': True,
        'folder': {
            'id': folder.id,
            'name': folder.name,
            'dropbox_url': dropbox_url,
            'has_password': folder.dropbox_password_hash is not None
        }
    })


@files_bp.route('/folder/<int:folder_id>/disable-dropbox', methods=['POST'])
@login_required
@check_module_access('module_files')
def disable_dropbox(folder_id):
    """Deaktiviere alle Briefkästen für einen Ordner."""
    folder = Folder.query.get_or_404(folder_id)

    for share in get_shares_for_resource('folder', folder.id):
        if share.mode == 'dropbox':
            share.enabled = False
    sync_legacy_share_flags('folder', folder)
    db.session.commit()

    flash(f'Briefkasten für Ordner "{folder.name}" wurde deaktiviert.', 'success')
    return redirect(url_for('files.browse_folder', folder_id=folder_id))


def _dropbox_name_session_key(token):
    return f'dropbox_guest_name_{token}'


def _dropbox_upload_ids_session_key(token):
    return f'dropbox_uploaded_ids_{token}'


def _get_dropbox_session_uploads(token, folder_id):
    raw_ids = session.get(_dropbox_upload_ids_session_key(token), [])
    if not isinstance(raw_ids, list):
        return []

    ids = []
    for value in raw_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []

    files = File.query.filter(
        File.id.in_(ids),
        File.folder_id == folder_id,
        File.is_current.is_(True)
    ).all()
    by_id = {f.id: f for f in files}
    ordered = [by_id[file_id] for file_id in reversed(ids) if file_id in by_id]
    return ordered


@files_bp.route('/dropbox/<token>', methods=['GET', 'POST'])
def dropbox_upload(token):
    """Öffentliche Upload-Seite für Briefkasten (ohne Login)."""
    share, folder = resolve_dropbox_folder(token)
    if not folder:
        abort(404)

    bot_ctx = _mailbox_bot_template_context(token)
    password_hash = _dropbox_password_hash(share, folder)
    if password_hash:
        if request.method == 'POST' and 'password' in request.form:
            if not _validate_mailbox_bot(token):
                flash('Bot-Schutz-Prüfung fehlgeschlagen. Bitte erneut versuchen.', 'danger')
                return render_template(
                    'files/dropbox_auth.html',
                    token=token,
                    folder_name=folder.name,
                    **bot_ctx,
                )
            password = request.form.get('password', '')
            if check_password_hash(password_hash, password):
                session[f'dropbox_auth_{token}'] = True
                if share:
                    log_share_access(share, 'password_auth', request)
                    db.session.commit()
                return redirect(url_for('files.dropbox_upload', token=token))
            flash('Ungültiges Passwort.', 'danger')
        elif not session.get(f'dropbox_auth_{token}'):
            return render_template(
                'files/dropbox_auth.html',
                token=token,
                folder_name=folder.name,
                **bot_ctx,
            )

    name_session_key = _dropbox_name_session_key(token)
    guest_name = session.get(name_session_key)
    if request.method == 'POST' and 'guest_name' in request.form:
        if not _validate_mailbox_bot(token):
            flash('Bot-Schutz-Prüfung fehlgeschlagen. Bitte erneut versuchen.', 'danger')
            return render_template(
                'files/dropbox_upload.html',
                token=token,
                folder=folder,
                guest_name=None,
                require_name_overlay=True,
                session_uploads=[],
                files_max_upload_bytes=get_global_max_file_size(),
                **bot_ctx,
            )
        submitted_name = request.form.get('guest_name', '').strip()
        if not submitted_name:
            flash('Bitte geben Sie einen Namen ein.', 'danger')
        else:
            session[name_session_key] = submitted_name
            guest_name = submitted_name
            return redirect(url_for('files.dropbox_upload', token=token))

    if share and request.method == 'GET':
        log_share_access(share, 'page_view', request, guest_name=guest_name)
        db.session.commit()

    session_uploads = _get_dropbox_session_uploads(token, folder.id)
    return render_template(
        'files/dropbox_upload.html',
        token=token,
        folder=folder,
        guest_name=guest_name,
        require_name_overlay=not bool(guest_name),
        session_uploads=session_uploads,
        files_max_upload_bytes=get_global_max_file_size(),
        **bot_ctx,
    )


@files_bp.route('/dropbox/<token>/upload', methods=['POST'])
def dropbox_upload_file(token):
    """Öffentlicher Upload-Endpoint für Briefkasten (ohne Login)."""
    share, folder = resolve_dropbox_folder(token)
    if not folder:
        abort(404)

    if not _validate_mailbox_bot(token):
        return jsonify({'success': False, 'error': 'Bot-Schutz-Prüfung fehlgeschlagen.'}), 403

    password_hash = _dropbox_password_hash(share, folder)
    if password_hash:
        if not session.get(f'dropbox_auth_{token}'):
            password = request.form.get('password', '')
            if not check_password_hash(password_hash, password):
                flash('Ungültiges Passwort.', 'danger')
                return redirect(url_for('files.dropbox_upload', token=token))
            session[f'dropbox_auth_{token}'] = True
            if share:
                log_share_access(share, 'password_auth', request)
    
    max_size = get_global_max_file_size()
    uploaded_count = 0
    skipped_count = 0
    uploader_name = session.get(_dropbox_name_session_key(token)) or request.form.get('uploader_name', '').strip() or 'Anonym'
    uploaded_file_ids = []
    
    # Handle single file or multiple files
    if 'file' in request.files:
        files = request.files.getlist('file')
        for file in files:
            if not file.filename:
                continue
            
            # Check file size
            file.seek(0, 2)  # Seek to end
            file_size = file.tell()
            file.seek(0)  # Reset to beginning
            
            if file_size > max_size:
                skipped_count += 1
                continue

            # Optional: Kontingent des Briefkasten-Besitzers
            owner_id = getattr(folder, 'created_by', None)
            if owner_id:
                ok, _code, _msg = check_upload_allowed(owner_id, file_size)
                if not ok:
                    skipped_count += 1
                    continue
            
            # Process filename with date suffix if duplicate
            original_name = secure_filename(file.filename)
            if not original_name or not is_allowed_upload_filename(original_name):
                skipped_count += 1
                continue
            file_name = original_name
            
            # Check for duplicate
            existing_file = File.query.filter_by(
                name=file_name,
                folder_id=folder.id,
                is_current=True
            ).first()
            
            if existing_file:
                # Add date suffix
                date_str = datetime.utcnow().strftime('%Y-%m-%d')
                name_without_ext, ext = os.path.splitext(original_name)
                file_name = f"{name_without_ext}_V{date_str}{ext}"
                
                # Check if this name also exists, append number if needed
                counter = 1
                while File.query.filter_by(name=file_name, folder_id=folder.id, is_current=True).first():
                    file_name = f"{name_without_ext}_V{date_str}_{counter}{ext}"
                    counter += 1
            
            try:
                # Create a special user entry for anonymous uploads or use uploader name
                # For now, we'll use a placeholder user or create a system user
                # Check if there's a system/anonymous user
                anonymous_user = User.query.filter_by(email='anonymous@system.local').first()
                if not anonymous_user:
                    # Create anonymous user if needed
                    anonymous_user = User(
                        email='anonymous@system.local',
                        first_name=uploader_name,
                        last_name='',
                        password_hash='',  # No password needed
                        is_active=True,
                        is_admin=False,
                        is_email_confirmed=True
                    )
                    db.session.add(anonymous_user)
                    db.session.flush()
                
                new_file = _process_file_upload(file, file_name, folder.id, anonymous_user.id)
                db.session.flush()
                if new_file and new_file.id:
                    uploaded_file_ids.append(new_file.id)
                uploaded_count += 1
            except Exception as e:
                logging.error(f"Fehler beim Hochladen von {file_name}: {e}")
                skipped_count += 1
        
        if share and uploaded_count > 0:
            log_share_access(share, 'upload', request, guest_name=uploader_name)

        db.session.commit()
        if uploaded_file_ids:
            upload_ids_key = _dropbox_upload_ids_session_key(token)
            current_ids = session.get(upload_ids_key, [])
            if not isinstance(current_ids, list):
                current_ids = []
            current_ids.extend(uploaded_file_ids)
            # Keep list bounded to avoid oversized sessions.
            session[upload_ids_key] = current_ids[-200:]
        
        if uploaded_count > 0:
            flash(f'{uploaded_count} Datei(en) wurden erfolgreich hochgeladen.', 'success')
        if skipped_count > 0:
            flash(f'{skipped_count} Datei(en) wurden übersprungen (zu groß oder Fehler).', 'warning')
    
    return redirect(url_for('files.dropbox_upload', token=token))
