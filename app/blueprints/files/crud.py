"""Folder/file CRUD, move, and empty-file creation."""

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

@files_bp.route('/api/storage-usage')
@login_required
@check_module_access('module_files')
def api_storage_usage():
    """Aktueller Speicherverbrauch und Limits des eingeloggten Nutzers."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        max_size = get_global_max_file_size()
        return jsonify({
            'quota_enabled': False,
            'max_file_size': max_size,
            'max_file_label': format_bytes_de(max_size),
        }), 200
    return jsonify(usage_payload_for_user(current_user.id))


@files_bp.route('/create-folder', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_folder():
    """Create a new folder."""
    # Gast-Accounts können keine Ordner erstellen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Ordner erstellen.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    folder_name = request.form.get('folder_name', '').strip()
    parent_id = request.form.get('parent_id')
    files_view = normalize_view(request.form.get('view') or request.args.get('view'))
    team_id = _request_team_id()
    
    folder_name = sanitize_files_item_name(folder_name)
    if not folder_name:
        flash('Bitte geben Sie einen Ordnernamen ein.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    parent_id = int(parent_id) if parent_id else None
    private_enabled = is_private_folders_enabled()
    team_enabled = is_team_folders_enabled()
    if (private_enabled or team_enabled) and files_view == 'trash':
        flash('Im Papierkorb können keine Ordner erstellt werden.', 'warning')
        return redirect(url_for('files.index', view='trash'))

    parent_id, parent_folder = _resolve_create_parent(files_view, parent_id, team_id)
    if files_view == 'team' and team_enabled and not parent_folder:
        flash('Keine Berechtigung für diese Team-Ablage.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    if (private_enabled or team_enabled) and parent_folder and not can_edit_folder(parent_folder, current_user):
        flash('Keine Berechtigung für diesen Ordner.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    space = resolve_space_for_parent(parent_folder, files_view or 'public')
    resolved_team_id = resolve_team_id_for_parent(parent_folder, files_view, team_id)
    
    new_folder = Folder(
        name=folder_name,
        parent_id=parent_id,
        created_by=current_user.id,
        space=space,
        team_id=resolved_team_id,
        is_personal_root=False,
        is_team_root=False,
    )
    db.session.add(new_folder)
    db.session.commit()
    
    flash(f'Ordner "{folder_name}" wurde erstellt.', 'success')
    view_kwargs = _files_view_kwargs(files_view, folder=parent_folder or new_folder, team_id=resolved_team_id)
    
    if parent_id and not (
        (parent_folder and parent_folder.is_personal_root and files_view == 'ablage')
        or (parent_folder and getattr(parent_folder, 'is_team_root', False) and files_view == 'team')
    ):
        return redirect(url_for('files.browse_folder', folder_id=parent_id, **view_kwargs))
    return redirect(url_for('files.index', **view_kwargs))

@files_bp.route('/file/<int:file_id>/rename', methods=['POST'])
@login_required
@check_module_access('module_files')
def rename_file(file_id):
    """Benennt eine Datei um."""
    # Gast-Accounts können keine Dateien umbenennen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Dateien umbenennen.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    file = File.query.get_or_404(file_id)
    new_name = sanitize_files_item_name(request.form.get('new_name', ''))
    
    if not new_name:
        flash('Neuer Dateiname darf nicht leer sein.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    # Prüfe ob bereits eine Datei mit diesem Namen im selben Ordner existiert
    existing_file = File.query.filter_by(
        name=new_name,
        folder_id=file.folder_id,
        is_current=True
    ).first()
    
    if existing_file and existing_file.id != file.id:
        flash(f'Eine Datei mit dem Namen "{new_name}" existiert bereits in diesem Ordner.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    file.name = new_name
    db.session.commit()
    flash('Datei wurde umbenannt.', 'success')
    return _redirect_to_files_context(folder_id=file.folder_id)


@files_bp.route('/folder/<int:folder_id>/rename', methods=['POST'])
@login_required
@check_module_access('module_files')
def rename_folder(folder_id):
    """Benennt einen Ordner um."""
    # Gast-Accounts können keine Ordner umbenennen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Ordner umbenennen.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    folder = Folder.query.get_or_404(folder_id)
    if getattr(folder, 'is_personal_root', False) or getattr(folder, 'is_team_root', False):
        flash('Dieser Stammordner kann nicht umbenannt werden.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    new_name = sanitize_files_item_name(request.form.get('new_name', ''))
    
    if not new_name:
        flash('Neuer Ordnername darf nicht leer sein.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    folder.name = new_name
    db.session.commit()
    flash('Ordner wurde umbenannt.', 'success')

    # Zurück in den Ordner, in dem der umbenannte Ordner angezeigt wird (Parent bzw. Root)
    return _redirect_to_files_context(folder_id=folder.parent_id)


@files_bp.route('/folder/<int:folder_id>/color', methods=['POST'])
@login_required
@check_module_access('module_files')
def update_folder_color(folder_id):
    """Update folder color for quick visual labeling."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Ordnerfarben ändern.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    folder = Folder.query.get_or_404(folder_id)
    raw_color = (request.form.get('color') or '').strip().lower()
    clear_color = (request.form.get('clear_color') or '').strip() == '1'

    if clear_color or not raw_color:
        folder.color = None
    elif re.fullmatch(r'#[0-9a-f]{6}', raw_color):
        folder.color = raw_color
    else:
        flash('Ungültige Farbe. Bitte wählen Sie eine HEX-Farbe.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    db.session.commit()
    flash('Ordnerfarbe wurde aktualisiert.', 'success')
    return redirect(_safe_referrer_or(url_for('files.index')))


def _is_folder_descendant(candidate_folder, ancestor_folder_id):
    """Check whether candidate_folder is a descendant of ancestor_folder_id."""
    current = candidate_folder
    while current:
        if current.id == ancestor_folder_id:
            return True
        current = current.parent
    return False


@files_bp.route('/move', methods=['POST'])
@login_required
@check_module_access('module_files')
def move_item():
    """Move file or folder into another folder."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({
            'success': False,
            'error': translate('files.index.errors.move_guest_not_allowed')
        }), 403

    payload = request.get_json(silent=True) or request.form
    item_type = (payload.get('item_type') or '').strip().lower()
    item_id_raw = payload.get('item_id')
    target_folder_raw = payload.get('target_folder_id')

    if item_type not in {'file', 'folder'}:
        return jsonify({
            'success': False,
            'error': translate('files.index.errors.move_invalid_request')
        }), 400

    try:
        item_id = int(item_id_raw)
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'error': translate('files.index.errors.move_invalid_request')
        }), 400

    target_folder_id = None
    if target_folder_raw not in (None, '', 'null'):
        try:
            target_folder_id = int(target_folder_raw)
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'error': translate('files.index.errors.move_invalid_target')
            }), 400

    target_folder = None
    if target_folder_id is not None:
        target_folder = Folder.query.get(target_folder_id)
        if not target_folder:
            return jsonify({
                'success': False,
                'error': translate('files.index.errors.move_target_not_found')
            }), 404

    files_view = normalize_view(
        payload.get('view') or request.args.get('view') or session.get('files_last_view')
    )
    move_team_id = parse_team_id(payload.get('team_id')) or _request_team_id(target_folder)
    if target_folder_id is None:
        if files_view == 'ablage' and is_private_folders_enabled():
            personal_root = ensure_personal_root(current_user.id)
            target_folder_id = personal_root.id
            target_folder = personal_root
        elif files_view == 'team' and is_team_folders_enabled() and user_may_use_file_team(current_user, move_team_id):
            team_root = ensure_team_root(move_team_id, current_user.id)
            if team_root:
                target_folder_id = team_root.id
                target_folder = team_root

    if target_folder and (is_files_spaces_enabled() or (getattr(target_folder, 'space', None) == 'team')):
        if not can_edit_folder(target_folder, current_user) and not current_user.is_admin:
            return jsonify({
                'success': False,
                'error': translate('files.index.errors.move_not_allowed')
            }), 403

    target_space = resolve_space_for_parent(target_folder, files_view or 'public')
    target_team_id = resolve_team_id_for_parent(target_folder, files_view, move_team_id)

    if item_type == 'file':
        file = File.query.get(item_id)
        if not file or not file.is_current or file.deleted_at is not None:
            return jsonify({
                'success': False,
                'error': translate('files.index.errors.move_item_not_found')
            }), 404

        if not can_edit_file(file, current_user) and not current_user.is_admin:
            return jsonify({
                'success': False,
                'error': translate('files.index.errors.move_not_allowed')
            }), 403

        if file.folder_id == target_folder_id:
            return jsonify({'success': True, 'no_change': True}), 200

        name_conflict = File.query.filter(
            File.id != file.id,
            File.name == file.name,
            File.folder_id.is_(target_folder_id) if target_folder_id is None else File.folder_id == target_folder_id,
            File.is_current == True,
            File.deleted_at.is_(None),
        ).first()
        if name_conflict:
            return jsonify({
                'success': False,
                'error': translate('files.index.errors.move_name_conflict')
            }), 409

        file.folder_id = target_folder_id
        file.space = target_space
        file.team_id = target_team_id
        db.session.commit()
        return jsonify({'success': True}), 200

    folder = Folder.query.get(item_id)
    if not folder or folder.deleted_at is not None:
        return jsonify({
            'success': False,
            'error': translate('files.index.errors.move_item_not_found')
        }), 404

    if getattr(folder, 'is_personal_root', False) or getattr(folder, 'is_team_root', False):
        return jsonify({
            'success': False,
            'error': translate('files.index.errors.move_invalid_request')
        }), 400

    if not can_edit_folder(folder, current_user) and not current_user.is_admin:
        return jsonify({
            'success': False,
            'error': translate('files.index.errors.move_not_allowed')
        }), 403

    if folder.id == target_folder_id:
        return jsonify({
            'success': False,
            'error': translate('files.index.errors.move_cycle_folder')
        }), 400

    if target_folder and _is_folder_descendant(target_folder, folder.id):
        return jsonify({
            'success': False,
            'error': translate('files.index.errors.move_cycle_folder')
        }), 400

    if folder.parent_id == target_folder_id:
        return jsonify({'success': True, 'no_change': True}), 200

    folder_name_conflict = Folder.query.filter(
        Folder.id != folder.id,
        Folder.name == folder.name,
        Folder.parent_id.is_(target_folder_id) if target_folder_id is None else Folder.parent_id == target_folder_id,
        Folder.deleted_at.is_(None),
        Folder.is_personal_root.is_(False),
        Folder.is_team_root.is_(False),
    ).first()
    if folder_name_conflict:
        return jsonify({
            'success': False,
            'error': translate('files.index.errors.move_name_conflict')
        }), 409

    folder.parent_id = target_folder_id
    apply_space_to_folder_tree(folder, target_space, target_team_id)
    db.session.commit()
    return jsonify({'success': True}), 200


@files_bp.route('/api/move-destinations')
@login_required
@check_module_access('module_files')
def api_move_destinations():
    """Folder trees per space for the move picker."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({
            'success': False,
            'error': translate('files.index.errors.move_guest_not_allowed')
        }), 403

    exclude_folder_id = None
    raw_exclude = request.args.get('exclude_folder_id')
    if raw_exclude not in (None, '', 'null'):
        try:
            exclude_folder_id = int(raw_exclude)
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'error': translate('files.index.errors.move_invalid_request')
            }), 400

    spaces = list_move_destinations(current_user, exclude_folder_id=exclude_folder_id)
    nav_labels = {
        'ablage': translate('files.index.nav.ablage'),
        'public': translate('files.index.nav.public'),
        'team': translate('files.index.nav.team'),
    }
    payload = []
    for space in spaces:
        label = space.get('label')
        if label in ('ablage', 'public'):
            display_label = nav_labels.get(label, label)
        else:
            display_label = label
        payload.append({
            'key': space['key'],
            'view': space['view'],
            'team_id': space.get('team_id'),
            'root_folder_id': space.get('root_folder_id'),
            'label': display_label,
            'color': space.get('color'),
            'folders': space.get('folders') or [],
        })

    return jsonify({'success': True, 'spaces': payload}), 200


@files_bp.route('/create-file', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_file():
    """Create a new text or markdown file."""
    # Gast-Accounts können keine Dateien erstellen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Dateien erstellen.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    filename = request.form.get('filename', '').strip()
    content = request.form.get('content', '')
    file_type = request.form.get('file_type', 'txt')
    folder_id = request.form.get('folder_id')
    folder_id = int(folder_id) if folder_id else None
    files_view = normalize_view(
        request.form.get('view') or request.args.get('view') or session.get('files_last_view')
    )
    team_id = _request_team_id()
    private_enabled = is_private_folders_enabled()
    team_enabled = is_team_folders_enabled()
    folder_id, parent_folder = _resolve_create_parent(files_view, folder_id, team_id)
    if files_view == 'team' and team_enabled and not parent_folder:
        flash('Keine Berechtigung für diese Team-Ablage.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    if not filename:
        flash('Bitte geben Sie einen Dateinamen ein.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    # Add file extension
    if file_type == 'md' and not filename.endswith('.md'):
        filename += '.md'
    elif file_type == 'txt' and not filename.endswith('.txt'):
        filename += '.txt'

    # Check if file with same name exists in folder
    existing_file = File.query.filter_by(
        name=filename,
        folder_id=folder_id,
        is_current=True
    ).first()

    if existing_file:
        flash(f'Datei "{filename}" existiert bereits in diesem Ordner.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    if not parent_folder and folder_id:
        parent_folder = Folder.query.get(folder_id)
    if (private_enabled or team_enabled) and parent_folder and not can_edit_folder(parent_folder, current_user):
        flash('Keine Berechtigung für diesen Ordner.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    space = resolve_space_for_parent(parent_folder, files_view or 'public')
    resolved_team_id = resolve_team_id_for_parent(parent_folder, files_view, team_id)

    # Create file
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    stored_filename = f"{timestamp}_{filename}"
    filepath = os.path.join('uploads', 'files', stored_filename)

    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Write content to file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    # Store absolute path in database
    absolute_filepath = os.path.abspath(filepath)

    new_file = File(
        name=filename,
        original_name=filename,
        folder_id=folder_id,
        uploaded_by=current_user.id,
        file_path=absolute_filepath,
        file_size=os.path.getsize(absolute_filepath),
        mime_type='text/plain' if file_type == 'txt' else 'text/markdown',
        version_number=1,
        is_current=True,
        space=space,
        team_id=resolved_team_id,
    )
    db.session.add(new_file)
    db.session.commit()

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
    
    flash(f'Datei "{filename}" wurde erstellt.', 'success')
    return redirect(_files_context_url(folder_id=folder_id, folder=parent_folder))


@files_bp.route('/create-office-file', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_office_file():
    """Create a new empty document (Office OOXML or OpenDocument, per admin setting)."""
    from app.utils.document_formats import (
        create_empty_document,
        get_allowed_create_types,
        get_create_type_map,
    )

    # Gast-Accounts können keine Office-Dateien erstellen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Dateien erstellen.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    filename = request.form.get('filename', '').strip()
    create_types = get_create_type_map()
    allowed_types = get_allowed_create_types()
    file_type = (request.form.get('file_type') or create_types['document']).strip().lower()
    folder_id = request.form.get('folder_id')
    folder_id = int(folder_id) if folder_id else None
    files_view = normalize_view(
        request.form.get('view') or request.args.get('view') or session.get('files_last_view')
    )
    team_id = _request_team_id()
    private_enabled = is_private_folders_enabled()
    team_enabled = is_team_folders_enabled()
    folder_id, parent_folder = _resolve_create_parent(files_view, folder_id, team_id)
    if files_view == 'team' and team_enabled and not parent_folder:
        flash('Keine Berechtigung für diese Team-Ablage.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    if not filename:
        flash('Bitte geben Sie einen Dateinamen ein.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    # Validate file type against admin format setting
    if file_type not in allowed_types:
        flash('Ungültiger Dateityp.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    # Add file extension if not present
    if not filename.endswith(f'.{file_type}'):
        filename += f'.{file_type}'
    
    # Check if file with same name exists in folder
    existing_file = File.query.filter_by(
        name=filename,
        folder_id=folder_id,
        is_current=True
    ).first()
    
    if existing_file:
        flash(f'Datei "{filename}" existiert bereits in diesem Ordner.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    if not parent_folder and folder_id:
        parent_folder = Folder.query.get(folder_id)
    if (private_enabled or team_enabled) and parent_folder and not can_edit_folder(parent_folder, current_user):
        flash('Keine Berechtigung für diesen Ordner.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    space = resolve_space_for_parent(parent_folder, files_view or 'public')
    resolved_team_id = resolve_team_id_for_parent(parent_folder, files_view, team_id)
    
    # Create empty document
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    stored_filename = f"{timestamp}_{filename}"
    filepath = os.path.join('uploads', 'files', stored_filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    try:
        mime_type = create_empty_document(filepath, file_type)
    except ImportError:
        flash(
            'Fehler: Erforderliche Bibliothek nicht installiert. '
            'Bitte installieren Sie python-docx, openpyxl und python-pptx.',
            'danger',
        )
        return redirect(_safe_referrer_or(url_for('files.index')))
    except Exception as e:
        logging.error(f"Fehler beim Erstellen der Office-Datei: {e}")
        flash(f'Fehler beim Erstellen der Datei: {str(e)}', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    # Store absolute path in database
    absolute_filepath = os.path.abspath(filepath)
    
    new_file = File(
        name=filename,
        original_name=filename,
        folder_id=folder_id,
        uploaded_by=current_user.id,
        file_path=absolute_filepath,
        file_size=os.path.getsize(absolute_filepath),
        mime_type=mime_type,
        version_number=1,
        is_current=True,
        space=space,
        team_id=resolved_team_id,
    )
    db.session.add(new_file)
    db.session.commit()
    
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
    
    flash(f'Datei "{filename}" wurde erstellt.', 'success')
    return redirect(_files_context_url(folder_id=folder_id, folder=parent_folder))
