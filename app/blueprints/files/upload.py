"""Nested-path helpers, upload, and conflict checks."""

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

def _child_folders_by_name(parent_id, cache):
    """Prefetch live children of one parent into ``cache[parent_id]``."""
    if parent_id not in cache:
        cache[parent_id] = {
            f.name: f
            for f in Folder.query.filter_by(parent_id=parent_id)
            .filter(Folder.deleted_at.is_(None))
            .all()
        }
    return cache[parent_id]


def _ensure_nested_upload_folder_path(
    root_folder_id, path_parts, files_view, team_id, created_by, children_cache=None
):
    """Walk or create nested folders for a relative upload path.

    Children of each parent are loaded once and reused across files in the same upload.
    """
    cache = children_cache if children_cache is not None else {}
    current_parent_id = root_folder_id
    parent_obj_cache = {}
    for folder_name in path_parts:
        folder_name_clean = secure_filename(folder_name)
        if not folder_name_clean:
            continue
        siblings = _child_folders_by_name(current_parent_id, cache)
        existing = siblings.get(folder_name_clean)
        if existing:
            current_parent_id = existing.id
            continue
        parent_for_space = None
        if current_parent_id:
            parent_for_space = parent_obj_cache.get(current_parent_id)
            if parent_for_space is None:
                parent_for_space = Folder.query.get(current_parent_id)
                if parent_for_space:
                    parent_obj_cache[current_parent_id] = parent_for_space
        new_folder = Folder(
            name=folder_name_clean,
            parent_id=current_parent_id,
            created_by=created_by,
            space=resolve_space_for_parent(parent_for_space, files_view or 'public'),
            team_id=resolve_team_id_for_parent(parent_for_space, files_view, team_id),
        )
        db.session.add(new_folder)
        db.session.flush()
        siblings[folder_name_clean] = new_folder
        cache[new_folder.id] = {}
        parent_obj_cache[new_folder.id] = new_folder
        current_parent_id = new_folder.id
    return current_parent_id


@files_bp.route('/upload', methods=['POST'])
@login_required
@check_module_access('module_files')
def upload_file():
    """Upload a file or folder."""

    def _ajax_upload():
        return request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _finish(url):
        """Redirect for normal form posts; JSON for XHR uploads (toast UI)."""
        if _ajax_upload():
            flashes = get_flashed_messages(with_categories=True)
            messages = [{'category': cat, 'text': msg} for cat, msg in flashes]
            cats = {m['category'] for m in messages}
            return jsonify({
                'success': 'danger' not in cats,
                'messages': messages,
                'redirect_url': url,
            })
        return redirect(url)

    # Gast-Accounts: Upload nur in Ordnern mit edit-/dropbox-Freigabe (nicht view-only)
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        folder_id = request.form.get('folder_id')
        folder_id = int(folder_id) if folder_id else None

        if folder_id:
            from app.utils.access_control import GUEST_WRITE_MODES, guest_has_folder_access
            target_folder = Folder.query.get(folder_id)
            if not target_folder or not guest_has_folder_access(
                current_user, target_folder, modes=GUEST_WRITE_MODES
            ):
                flash(
                    'Keine Upload-Berechtigung für diesen Ordner '
                    '(nur Bearbeiten- oder Dropbox-Freigaben).',
                    'danger',
                )
                return _finish(_safe_referrer_or(url_for('files.index')))
        else:
            flash('Gast-Accounts können nur in freigegebenen Ordnern Dateien hochladen.', 'danger')
            return _finish(_safe_referrer_or(url_for('files.index')))
    
    folder_id = request.form.get('folder_id')
    folder_id = int(folder_id) if folder_id else None
    conflict_strategy = request.form.get('conflict_strategy', '').strip().lower()
    files_view = normalize_view(request.form.get('view') or request.args.get('view'))
    team_id = _request_team_id()
    folder_id, upload_parent = _resolve_create_parent(files_view, folder_id, team_id)
    if files_view == 'team' and is_team_folders_enabled() and not upload_parent:
        flash('Keine Berechtigung für diese Team-Ablage.', 'danger')
        return _finish(_safe_referrer_or(url_for('files.index')))
    
    limits = resolve_limits_for_user(current_user.id)
    max_size = limits['max_file_size']
    pending_bytes = 0
    
    # Check for folder upload
    if 'folder_upload' in request.files:
        folder_files = request.files.getlist('folder_upload')
        if folder_files and folder_files[0].filename:
            uploaded_count = 0
            skipped_count = 0
            skipped_files = []
            folder_children_cache = {}
            
            for file in folder_files:
                if not file.filename:
                    continue
                
                # Check file size
                file.seek(0, 2)  # Seek to end
                file_size = file.tell()
                file.seek(0)  # Reset to beginning
                
                ok, _code, err_msg = check_upload_allowed(
                    current_user.id, file_size, pending_bytes=pending_bytes
                )
                if not ok:
                    skipped_count += 1
                    skipped_files.append(file.filename)
                    continue
                
                # Process file path to maintain folder structure
                file_path_parts = file.filename.replace('\\', '/').split('/')
                file_name = secure_filename(file_path_parts[-1])
                if not file_name or not is_allowed_upload_filename(file_name):
                    skipped_count += 1
                    skipped_files.append(file.filename)
                    continue
                
                # Determine target folder - create subfolders if needed
                target_folder_id = folder_id
                if len(file_path_parts) > 1:
                    target_folder_id = _ensure_nested_upload_folder_path(
                        folder_id,
                        file_path_parts[:-1],
                        files_view,
                        team_id,
                        current_user.id,
                        folder_children_cache,
                    )
                
                # Process file upload
                try:
                    existing_file = File.query.filter_by(
                        name=file_name,
                        folder_id=target_folder_id,
                        is_current=True
                    ).first()
                    
                    if existing_file:
                        if conflict_strategy == 'version':
                            _create_new_file_version(existing_file, file, current_user.id)
                            uploaded_count += 1
                            pending_bytes += file_size
                        elif conflict_strategy == 'separate':
                            unique_name = _generate_unique_filename_in_folder(file_name, target_folder_id)
                            _process_file_upload(file, unique_name, target_folder_id, current_user.id)
                            uploaded_count += 1
                            pending_bytes += file_size
                        else:
                            skipped_count += 1
                            skipped_files.append(file_name)
                    else:
                        _process_file_upload(file, file_name, target_folder_id, current_user.id)
                        uploaded_count += 1
                        pending_bytes += file_size
                except Exception as e:
                    logging.error(f"Fehler beim Hochladen von {file_name}: {e}")
                    skipped_count += 1
                    skipped_files.append(file.filename)
            
            db.session.commit()
            
            try:
                recent_uploads = File.query.filter_by(
                    uploaded_by=current_user.id,
                    folder_id=folder_id
                ).order_by(File.created_at.desc()).limit(max(uploaded_count, 1)).all()
                for f in recent_uploads[:uploaded_count]:
                    try:
                        send_file_notification(f.id, 'new')
                    except Exception as e:
                        logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")
            except Exception as e:
                logging.error(f"Fehler beim Senden von Benachrichtigungen: {e}")
            
            # Flash messages
            if uploaded_count > 0:
                flash(f'{uploaded_count} Datei(en) wurden hochgeladen.', 'success')
            if skipped_count > 0:
                flash(f'{skipped_count} Datei(en) wurden übersprungen (zu groß, Kontingent oder Fehler).', 'warning')
                if skipped_files:
                    flash(f'Übersprungene Dateien: {", ".join(skipped_files[:5])}{"..." if len(skipped_files) > 5 else ""}', 'info')
            if uploaded_count == 0 and skipped_count > 0:
                flash(f'Kein Upload möglich. Dateien ggf. zu groß (max. {format_bytes_de(max_size)}) oder Speicherkontingent voll.', 'danger')
            
            if folder_id:
                return _finish(_files_context_url(folder_id=folder_id))
            return _finish(_files_context_url())
    
    # Single/multi file upload
    if 'file' not in request.files:
        flash('Keine Datei ausgewählt.', 'danger')
        return _finish(_safe_referrer_or(url_for('files.index')))

    uploaded_files = [f for f in request.files.getlist('file') if f and f.filename]
    if not uploaded_files:
        flash('Keine Datei ausgewählt.', 'danger')
        return _finish(_safe_referrer_or(url_for('files.index')))

    if len(uploaded_files) > 1:
        uploaded_count = 0
        skipped_count = 0
        skipped_files = []

        for uploaded_file in uploaded_files:
            uploaded_file.seek(0, 2)
            file_size = uploaded_file.tell()
            uploaded_file.seek(0)
            ok, _code, err_msg = check_upload_allowed(
                current_user.id, file_size, pending_bytes=pending_bytes
            )
            if not ok:
                skipped_count += 1
                skipped_files.append(uploaded_file.filename)
                continue

            original_name = secure_filename(uploaded_file.filename)
            if not original_name or not is_allowed_upload_filename(original_name):
                skipped_count += 1
                skipped_files.append(uploaded_file.filename)
                continue

            existing_file = File.query.filter_by(
                name=original_name,
                folder_id=folder_id,
                is_current=True
            ).first()

            if existing_file:
                if conflict_strategy == 'version':
                    _create_new_file_version(existing_file, uploaded_file, current_user.id)
                    uploaded_count += 1
                    pending_bytes += file_size
                    continue
                if conflict_strategy == 'separate':
                    unique_name = _generate_unique_filename_in_folder(original_name, folder_id)
                    _process_file_upload(uploaded_file, unique_name, folder_id, current_user.id)
                    uploaded_count += 1
                    pending_bytes += file_size
                    continue

                skipped_count += 1
                skipped_files.append(original_name)
                continue

            _process_file_upload(uploaded_file, original_name, folder_id, current_user.id)
            uploaded_count += 1
            pending_bytes += file_size

        db.session.commit()

        if uploaded_count > 0:
            try:
                recent_uploads = File.query.filter_by(
                    uploaded_by=current_user.id,
                    folder_id=folder_id
                ).order_by(File.created_at.desc()).limit(uploaded_count).all()
                for recent_file in recent_uploads:
                    try:
                        send_file_notification(recent_file.id, 'new')
                    except Exception as e:
                        logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")
            except Exception as e:
                logging.error(f"Fehler beim Senden von Datei-Benachrichtigungen: {e}")

        try:
            recent_files = File.query.filter_by(
                uploaded_by=current_user.id
            ).order_by(File.updated_at.desc()).limit(3).all()

            files_data = [{
                'id': file.id,
                'name': file.name,
                'original_name': file.original_name,
                'updated_at': file.updated_at.isoformat(),
                'mime_type': file.mime_type,
                'url': flask_url_for('files.view_file', file_id=file.id)
            } for file in recent_files]

            emit_dashboard_update(current_user.id, 'files_update', {'files': files_data})
        except Exception as e:
            logging.error(f"Fehler beim Senden der Dashboard-Updates für Dateien: {e}")

        if uploaded_count > 0:
            flash(f'{uploaded_count} Datei(en) wurden hochgeladen.', 'success')
        if skipped_count > 0:
            flash(f'{skipped_count} Datei(en) wurden übersprungen.', 'warning')
            if skipped_files:
                preview = ", ".join(skipped_files[:5])
                flash(f'Übersprungene Dateien: {preview}{"..." if len(skipped_files) > 5 else ""}', 'info')
        if uploaded_count == 0 and skipped_count > 0:
            flash(f'Kein Upload möglich. Dateien ggf. zu groß (max. {format_bytes_de(max_size)}) oder Speicherkontingent voll.', 'danger')
    else:
        file = uploaded_files[0]

        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning

        ok, _code, err_msg = check_upload_allowed(current_user.id, file_size)
        if not ok:
            flash(err_msg or f'Datei ist zu groß (max. {format_bytes_de(max_size)}).', 'danger')
            return _finish(_safe_referrer_or(url_for('files.index')))

        original_name = secure_filename(file.filename)
        if not original_name:
            flash('Ungültiger Dateiname.', 'danger')
            return _finish(_safe_referrer_or(url_for('files.index')))
        if not is_allowed_upload_filename(original_name):
            flash('Dieser Dateityp ist nicht erlaubt.', 'danger')
            return _finish(_safe_referrer_or(url_for('files.index')))

        # Check if file with same name exists in folder
        existing_file = File.query.filter_by(
            name=original_name,
            folder_id=folder_id,
            is_current=True
        ).first()

        if existing_file:
            if conflict_strategy == 'version':
                version_number = _create_new_file_version(existing_file, file, current_user.id)
                db.session.commit()

                try:
                    send_file_notification(existing_file.id, 'modified')
                except Exception as e:
                    logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")

                try:
                    recent_files = File.query.filter_by(
                        uploaded_by=current_user.id
                    ).order_by(File.updated_at.desc()).limit(3).all()

                    files_data = [{
                        'id': file.id,
                        'name': file.name,
                        'original_name': file.original_name,
                        'updated_at': file.updated_at.isoformat(),
                        'mime_type': file.mime_type,
                        'url': flask_url_for('files.view_file', file_id=file.id)
                    } for file in recent_files]

                    emit_dashboard_update(current_user.id, 'files_update', {'files': files_data})
                except Exception as e:
                    logging.error(f"Fehler beim Senden der Dashboard-Updates für Dateien: {e}")

                flash(f'Datei "{original_name}" wurde aktualisiert (Version {version_number}).', 'success')
            elif conflict_strategy == 'separate':
                unique_name = _generate_unique_filename_in_folder(original_name, folder_id)
                _process_file_upload(file, unique_name, folder_id, current_user.id)
                db.session.commit()
                flash(f'Datei "{unique_name}" wurde als separate Datei hochgeladen.', 'success')
            else:
                overwrite = request.form.get('overwrite')
                if overwrite != 'yes':
                    flash(f'Datei "{original_name}" existiert bereits. Bitte Konfliktstrategie wählen.', 'danger')
                    if _ajax_upload():
                        return jsonify({
                            'success': False,
                            'messages': [{'category': 'danger', 'text': f'Datei "{original_name}" existiert bereits.'}],
                            'conflict': True,
                        }), 409
                    flash(f'Datei "{original_name}" existiert bereits. Möchten Sie sie überschreiben?', 'warning')
                    return render_template(
                        'files/confirm_overwrite.html',
                        filename=original_name,
                        folder_id=folder_id
                    )

                version_number = _create_new_file_version(existing_file, file, current_user.id)
                db.session.commit()

                try:
                    send_file_notification(existing_file.id, 'modified')
                except Exception as e:
                    logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")

                try:
                    recent_files = File.query.filter_by(
                        uploaded_by=current_user.id
                    ).order_by(File.updated_at.desc()).limit(3).all()

                    files_data = [{
                        'id': file.id,
                        'name': file.name,
                        'original_name': file.original_name,
                        'updated_at': file.updated_at.isoformat(),
                        'mime_type': file.mime_type,
                        'url': flask_url_for('files.view_file', file_id=file.id)
                    } for file in recent_files]

                    emit_dashboard_update(current_user.id, 'files_update', {'files': files_data})
                except Exception as e:
                    logging.error(f"Fehler beim Senden der Dashboard-Updates für Dateien: {e}")

                flash(f'Datei "{original_name}" wurde aktualisiert (Version {version_number}).', 'success')
        else:
            # Create new file
            _process_file_upload(file, original_name, folder_id, current_user.id)
            db.session.commit()

            # Sende Benachrichtigung für neue Datei
            new_file = File.query.filter_by(
                name=original_name,
                folder_id=folder_id,
                uploaded_by=current_user.id
            ).order_by(File.created_at.desc()).first()
            if new_file:
                try:
                    send_file_notification(new_file.id, 'new')
                except Exception as e:
                    logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")

                # Sende Dashboard-Update an den Benutzer
                try:
                    recent_files = File.query.filter_by(
                        uploaded_by=current_user.id
                    ).order_by(File.updated_at.desc()).limit(3).all()

                    files_data = [{
                        'id': file.id,
                        'name': file.name,
                        'original_name': file.original_name,
                        'updated_at': file.updated_at.isoformat(),
                        'mime_type': file.mime_type,
                        'url': flask_url_for('files.view_file', file_id=file.id)
                    } for file in recent_files]

                    emit_dashboard_update(current_user.id, 'files_update', {'files': files_data})
                except Exception as e:
                    logging.error(f"Fehler beim Senden der Dashboard-Updates für Dateien: {e}")

            flash(f'Datei "{original_name}" wurde hochgeladen.', 'success')
    
    return _finish(_files_context_url(folder_id=folder_id))


@files_bp.route('/upload-conflicts', methods=['POST'])
@login_required
@check_module_access('module_files')
def upload_conflicts():
    """Return file names that already exist in target folder."""
    payload = request.get_json(silent=True) or {}
    raw_folder_id = payload.get('folder_id')
    raw_names = payload.get('filenames') or []

    try:
        folder_id = int(raw_folder_id) if raw_folder_id not in (None, '', 'null') else None
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Ungültiger Ordner.'}), 400

    candidate_names = []
    for raw_name in raw_names:
        clean_name = secure_filename(str(raw_name or ''))
        if clean_name:
            candidate_names.append(clean_name)

    if not candidate_names:
        return jsonify({'success': True, 'conflicts': []})

    query = File.query.filter(File.is_current.is_(True), File.name.in_(candidate_names))
    if folder_id is None:
        query = query.filter(File.folder_id.is_(None))
    else:
        query = query.filter(File.folder_id == folder_id)

    conflicts = sorted({file.name for file in query.all()})
    return jsonify({'success': True, 'conflicts': conflicts})
