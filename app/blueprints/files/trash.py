"""Delete/restore, bulk ops, zip download, ACL, and favorites."""

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

@files_bp.route('/delete/<int:file_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def delete_file(file_id):
    """Soft-delete a file (or hard-delete when already in trash / purge)."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Dateien löschen.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    file = File.query.get_or_404(file_id)
    folder_id = file.folder_id
    files_view = normalize_view(request.form.get('view') or request.args.get('view'))
    purge = request.form.get('purge') == '1' or request.form.get('action') == 'purge'
    spaces_on = is_files_spaces_enabled()

    if spaces_on and not can_edit_file(file, current_user) and file.uploaded_by != current_user.id:
        flash('Keine Berechtigung.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    if purge or (file.deleted_at is not None) or not spaces_on:
        hard_delete_file_disk_and_db(file, os)
        db.session.commit()
        flash(f'Datei "{file.original_name}" wurde endgültig gelöscht.', 'success')
        if spaces_on:
            return redirect(url_for('files.index', **_files_view_kwargs('trash')))
        if folder_id:
            return redirect(url_for('files.browse_folder', folder_id=folder_id))
        return redirect(url_for('files.index'))

    soft_delete_file(file, current_user.id)
    db.session.commit()
    
    flash(f'Datei "{file.original_name}" wurde in den Papierkorb verschoben.', 'success')
    view_kwargs = _files_view_kwargs(files_view, folder=file.folder)
    if folder_id:
        return redirect(url_for('files.browse_folder', folder_id=folder_id, **view_kwargs))
    return redirect(url_for('files.index', **view_kwargs))


@files_bp.route('/restore-file/<int:file_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def restore_file_route(file_id):
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Keine Berechtigung.', 'danger')
        return redirect(url_for('files.index'))
    file = File.query.get_or_404(file_id)
    if file.uploaded_by != current_user.id and not current_user.is_admin:
        flash('Keine Berechtigung.', 'danger')
        return redirect(url_for('files.index', view='trash'))
    restore_file(file)
    db.session.commit()
    flash(f'Datei "{file.original_name}" wurde wiederhergestellt.', 'success')
    return redirect(url_for('files.index', view='trash'))


@files_bp.route('/delete-folder/<int:folder_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def delete_folder(folder_id):
    """Soft-delete a folder (or hard-delete from trash)."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Ordner löschen.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    
    folder = Folder.query.get_or_404(folder_id)
    if folder.is_personal_root or getattr(folder, 'is_team_root', False):
        flash('Dieser Stammordner kann nicht gelöscht werden.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    parent_id = folder.parent_id
    files_view = normalize_view(request.form.get('view') or request.args.get('view'))
    purge = request.form.get('purge') == '1' or request.form.get('action') == 'purge'
    spaces_on = is_files_spaces_enabled()

    if spaces_on and not can_edit_folder(folder, current_user) and folder.created_by != current_user.id:
        flash('Keine Berechtigung.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))

    if purge or (folder.deleted_at is not None) or not spaces_on:
        hard_delete_folder_recursive(folder, os)
        db.session.commit()
        flash(f'Ordner "{folder.name}" wurde endgültig gelöscht.', 'success')
        if spaces_on:
            return redirect(url_for('files.index', **_files_view_kwargs('trash')))
        if parent_id:
            return redirect(url_for('files.browse_folder', folder_id=parent_id))
        return redirect(url_for('files.index'))

    soft_delete_folder(folder, current_user.id)
    db.session.commit()
    
    flash(f'Ordner "{folder.name}" wurde in den Papierkorb verschoben.', 'success')
    view_kwargs = _files_view_kwargs(files_view, folder=folder)
    if parent_id:
        parent = Folder.query.get(parent_id)
        if parent and (
            (parent.is_personal_root and files_view == 'ablage')
            or (getattr(parent, 'is_team_root', False) and files_view == 'team')
        ):
            return redirect(url_for('files.index', **view_kwargs))
        return redirect(url_for('files.browse_folder', folder_id=parent_id, **view_kwargs))
    return redirect(url_for('files.index', **view_kwargs))


@files_bp.route('/restore-folder/<int:folder_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def restore_folder_route(folder_id):
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Keine Berechtigung.', 'danger')
        return redirect(url_for('files.index'))
    folder = Folder.query.get_or_404(folder_id)
    if folder.created_by != current_user.id and not current_user.is_admin:
        flash('Keine Berechtigung.', 'danger')
        return redirect(url_for('files.index', view='trash'))
    restore_folder(folder)
    db.session.commit()
    flash(f'Ordner "{folder.name}" wurde wiederhergestellt.', 'success')
    return redirect(url_for('files.index', view='trash'))


def _abs_disk_path(stored_path):
    if not stored_path:
        return None
    if os.path.isabs(stored_path):
        return stored_path
    return os.path.join(os.getcwd(), stored_path)


def _parse_bulk_items(payload):
    raw = (payload or {}).get('items') or []
    if not isinstance(raw, list):
        return []
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        itype = (entry.get('type') or '').strip().lower()
        try:
            iid = int(entry.get('id'))
        except (TypeError, ValueError):
            continue
        if itype in ('file', 'folder') and iid > 0:
            items.append({'type': itype, 'id': iid})
    return items


def _user_can_delete_file(file_obj):
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return False
    if getattr(current_user, 'is_admin', False):
        return True
    if file_obj.uploaded_by == current_user.id:
        return True
    return can_edit_file(file_obj, current_user)


def _user_can_delete_folder(folder):
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return False
    if getattr(folder, 'is_personal_root', False) or getattr(folder, 'is_team_root', False):
        return False
    if getattr(current_user, 'is_admin', False):
        return True
    if folder.created_by == current_user.id:
        return True
    return can_edit_folder(folder, current_user)


def _user_can_view_file_item(file_obj):
    return (
        can_view_file(file_obj, current_user)
        or file_obj.uploaded_by == current_user.id
        or current_user.is_admin
    )


def _user_can_view_folder_item(folder):
    return (
        can_view_folder(folder, current_user)
        or folder.created_by == current_user.id
        or current_user.is_admin
    )


def _collect_folder_files_for_zip(folder, prefix, out_entries, skipped, limit=2000):
    """Recursively collect (arcname, abs_path) for zip; mutates out_entries."""
    if len(out_entries) >= limit:
        return
    for child in Folder.query.filter_by(parent_id=folder.id).filter(Folder.deleted_at.is_(None)).all():
        if not _user_can_view_folder_item(child):
            skipped.append(child.name)
            continue
        child_prefix = f'{prefix}{child.name}/' if prefix else f'{child.name}/'
        _collect_folder_files_for_zip(child, child_prefix, out_entries, skipped, limit=limit)
        if len(out_entries) >= limit:
            return
    for f in File.query.filter_by(folder_id=folder.id, is_current=True).filter(File.deleted_at.is_(None)).all():
        if len(out_entries) >= limit:
            return
        if not _user_can_view_file_item(f):
            skipped.append(f.original_name or f.name)
            continue
        abs_path = _abs_disk_path(f.file_path)
        if not abs_path or not os.path.isfile(abs_path):
            skipped.append(f.original_name or f.name)
            continue
        arc = f'{prefix}{f.original_name or f.name}'
        out_entries.append((arc, abs_path))


@files_bp.route('/api/bulk-delete', methods=['POST'])
@login_required
@check_module_access('module_files')
def api_bulk_delete():
    """Soft-delete or purge multiple files/folders."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'success': False, 'error': 'Gast-Accounts können nichts löschen.'}), 403

    payload = request.get_json(silent=True) or {}
    items = _parse_bulk_items(payload)
    if not items:
        return jsonify({'success': False, 'error': 'Keine Elemente ausgewählt.'}), 400

    purge = bool(payload.get('purge'))
    deleted = 0
    skipped = []

    for item in items:
        if item['type'] == 'file':
            file_obj = File.query.get(item['id'])
            if not file_obj:
                skipped.append(f'Datei #{item["id"]}')
                continue
            if not _user_can_delete_file(file_obj):
                skipped.append(file_obj.original_name or file_obj.name)
                continue
            if purge or file_obj.deleted_at is not None or not is_files_spaces_enabled():
                hard_delete_file_disk_and_db(file_obj, os)
            else:
                soft_delete_file(file_obj, current_user.id)
            deleted += 1
        else:
            folder = Folder.query.get(item['id'])
            if not folder:
                skipped.append(f'Ordner #{item["id"]}')
                continue
            if not _user_can_delete_folder(folder):
                skipped.append(folder.name)
                continue
            if purge or folder.deleted_at is not None or not is_files_spaces_enabled():
                hard_delete_folder_recursive(folder, os)
            else:
                soft_delete_folder(folder, current_user.id)
            deleted += 1

    db.session.commit()
    return jsonify({
        'success': deleted > 0,
        'deleted': deleted,
        'skipped': skipped[:20],
        'message': f'{deleted} Element(e) gelöscht.' if deleted else 'Nichts gelöscht.',
    })


@files_bp.route('/api/bulk-restore', methods=['POST'])
@login_required
@check_module_access('module_files')
def api_bulk_restore():
    """Restore multiple files/folders from trash."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'success': False, 'error': 'Keine Berechtigung.'}), 403

    payload = request.get_json(silent=True) or {}
    items = _parse_bulk_items(payload)
    if not items:
        return jsonify({'success': False, 'error': 'Keine Elemente ausgewählt.'}), 400

    restored = 0
    skipped = []
    for item in items:
        if item['type'] == 'file':
            file_obj = File.query.get(item['id'])
            if not file_obj or file_obj.deleted_at is None:
                skipped.append(f'Datei #{item["id"]}')
                continue
            if file_obj.uploaded_by != current_user.id and not current_user.is_admin:
                skipped.append(file_obj.original_name or file_obj.name)
                continue
            restore_file(file_obj)
            restored += 1
        else:
            folder = Folder.query.get(item['id'])
            if not folder or folder.deleted_at is None:
                skipped.append(f'Ordner #{item["id"]}')
                continue
            if folder.created_by != current_user.id and not current_user.is_admin:
                skipped.append(folder.name)
                continue
            restore_folder(folder)
            restored += 1

    db.session.commit()
    return jsonify({
        'success': restored > 0,
        'restored': restored,
        'skipped': skipped[:20],
        'message': f'{restored} Element(e) wiederhergestellt.' if restored else 'Nichts wiederhergestellt.',
    })


@files_bp.route('/api/download-zip', methods=['POST'])
@login_required
@check_module_access('module_files')
def api_download_zip():
    """Build a ZIP from selected files/folders and stream it."""
    import tempfile
    from datetime import datetime as dt

    payload = request.get_json(silent=True) or {}
    items = _parse_bulk_items(payload)
    if not items:
        return jsonify({'success': False, 'error': 'Keine Elemente ausgewählt.'}), 400

    entries = []
    skipped = []
    used_names = set()

    def _unique_arc(name):
        base = name or 'Datei'
        if base not in used_names:
            used_names.add(base)
            return base
        stem, ext = os.path.splitext(base)
        n = 2
        while f'{stem} ({n}){ext}' in used_names:
            n += 1
        out = f'{stem} ({n}){ext}'
        used_names.add(out)
        return out

    for item in items:
        if item['type'] == 'file':
            file_obj = File.query.get(item['id'])
            if not file_obj or file_obj.deleted_at is not None:
                skipped.append(f'Datei #{item["id"]}')
                continue
            if not _user_can_view_file_item(file_obj):
                skipped.append(file_obj.original_name or file_obj.name)
                continue
            abs_path = _abs_disk_path(file_obj.file_path)
            if not abs_path or not os.path.isfile(abs_path):
                skipped.append(file_obj.original_name or file_obj.name)
                continue
            arc = _unique_arc(file_obj.original_name or file_obj.name)
            entries.append((arc, abs_path))
        else:
            folder = Folder.query.get(item['id'])
            if not folder or folder.deleted_at is not None:
                skipped.append(f'Ordner #{item["id"]}')
                continue
            if not _user_can_view_folder_item(folder):
                skipped.append(folder.name)
                continue
            prefix = f'{folder.name}/'
            used_names.add(prefix.rstrip('/'))
            _collect_folder_files_for_zip(folder, prefix, entries, skipped)

    if not entries:
        return jsonify({
            'success': False,
            'error': 'Keine herunterladbaren Dateien gefunden.',
            'skipped': skipped[:20],
        }), 400

    tmp = tempfile.NamedTemporaryFile(prefix='prismateams-zip-', suffix='.zip', delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        with zipfile.ZipFile(tmp_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for arcname, abs_path in entries:
                try:
                    zf.write(abs_path, arcname=arcname)
                except OSError:
                    skipped.append(arcname)
        stamp = dt.utcnow().strftime('%Y%m%d-%H%M%S')
        download_name = f'Dateien-{stamp}.zip'

        from flask import after_this_request

        @after_this_request
        def _cleanup_zip(response):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return response

        return _response_with_nosniff(send_file(
            tmp_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='application/zip',
        ))
    except Exception as e:
        logging.error(f'ZIP-Erstellung fehlgeschlagen: {e}')
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return jsonify({'success': False, 'error': 'ZIP konnte nicht erstellt werden.'}), 500


@files_bp.route('/api/resource-acl/<resource_type>/<int:resource_id>', methods=['GET', 'POST', 'DELETE'])
@login_required
@check_module_access('module_files')
def resource_acl_api(resource_type, resource_id):
    """Manage internal user/team/all ACL shares."""
    from app.models.team import Team

    if resource_type not in ('file', 'folder'):
        return jsonify({'success': False, 'error': 'Ungültiger Typ.'}), 400
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'success': False, 'error': 'Keine Berechtigung.'}), 403

    if resource_type == 'file':
        resource = File.query.get_or_404(resource_id)
        if resource.deleted_at is not None:
            return jsonify({'success': False, 'error': 'Gelöschte Datei.'}), 400
        resource_space = getattr(resource, 'space', None) or 'public'
        own_team_id = getattr(resource, 'team_id', None)
    else:
        resource = Folder.query.get_or_404(resource_id)
        if resource.deleted_at is not None or resource.is_personal_root:
            return jsonify({'success': False, 'error': 'Ungültiger Ordner.'}), 400
        resource_space = getattr(resource, 'space', None) or 'public'
        own_team_id = getattr(resource, 'team_id', None)

    can_share = can_manage_acl(resource, resource_type, current_user)
    acl_allowed = resource_space != 'public'

    if request.method == 'GET':
        rows = list_acl_for_resource(resource_type, resource_id)
        teams_payload = []
        users_payload = []
        if can_share and acl_allowed:
            users_payload = [
                {'id': u.id, 'full_name': u.full_name, 'username': u.full_name}
                for u in User.query.filter(
                    User.is_active.is_(True),
                    User.is_guest.is_(False),
                    User.id != current_user.id,
                ).order_by(User.first_name, User.last_name).limit(200).all()
            ]
            if is_team_folders_enabled():
                for t in Team.query.order_by(Team.name).all():
                    if own_team_id and t.id == own_team_id:
                        continue
                    teams_payload.append({
                        'id': t.id,
                        'name': t.name,
                        'color': t.color,
                    })
        return jsonify({
            'success': True,
            'entries': [serialize_acl_row(r) for r in rows],
            'is_owner': can_share,
            'acl_allowed': acl_allowed,
            'users': users_payload,
            'teams': teams_payload,
        })

    if resource_space == 'public':
        return jsonify({
            'success': False,
            'error': 'Public-Dateien können nicht intern freigegeben werden (sind bereits für alle sichtbar).',
        }), 400

    if not can_share:
        return jsonify({'success': False, 'error': 'Nur Eigentümer oder Teammitglieder können freigeben.'}), 403

    if request.method == 'DELETE':
        payload = request.get_json(silent=True) or {}
        if payload.get('grantee_team_id') not in (None, '', 'null'):
            try:
                team_grantee = int(payload.get('grantee_team_id'))
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'Ungültiges Team.'}), 400
            remove_acl(resource_type, resource_id, None, grantee_team_id=team_grantee)
            db.session.commit()
            return jsonify({'success': True})
        grantee = payload.get('grantee_user_id', '__missing__')
        if grantee == '__missing__':
            return jsonify({'success': False, 'error': 'grantee_user_id fehlt.'}), 400
        grantee_id = None if grantee in (None, '', 'all') else int(grantee)
        remove_acl(resource_type, resource_id, grantee_id)
        db.session.commit()
        return jsonify({'success': True})

    payload = request.get_json(silent=True) or {}
    share_all = bool(payload.get('share_all'))
    permission = payload.get('permission') or 'view'
    if share_all:
        upsert_acl(resource_type, resource_id, None, permission, current_user.id)
    elif payload.get('grantee_team_id'):
        try:
            team_grantee = int(payload.get('grantee_team_id'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Ungültiges Team.'}), 400
        if own_team_id and team_grantee == own_team_id:
            return jsonify({
                'success': False,
                'error': 'Dieses Team hat die Ablage bereits.',
            }), 400
        if not Team.query.get(team_grantee):
            return jsonify({'success': False, 'error': 'Team nicht gefunden.'}), 404
        upsert_acl(
            resource_type,
            resource_id,
            None,
            permission,
            current_user.id,
            grantee_team_id=team_grantee,
        )
    else:
        grantee_user_id = payload.get('grantee_user_id')
        if not grantee_user_id:
            return jsonify({'success': False, 'error': 'Benutzer fehlt.'}), 400
        grantee_user_id = int(grantee_user_id)
        if grantee_user_id == current_user.id:
            return jsonify({
                'success': False,
                'error': 'Du kannst nicht mit dir selbst freigeben.',
            }), 400
        upsert_acl(resource_type, resource_id, grantee_user_id, permission, current_user.id)
    db.session.commit()
    rows = list_acl_for_resource(resource_type, resource_id)
    return jsonify({'success': True, 'entries': [serialize_acl_row(r) for r in rows]})


@files_bp.route('/api/folder-favorite/<int:folder_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def folder_favorite_api(folder_id):
    """Toggle a folder favorite (max FOLDER_FAVORITES_MAX)."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'success': False, 'error': 'Keine Berechtigung.'}), 403

    ok, favorited, error, count = toggle_folder_favorite(current_user, folder_id)
    if not ok:
        return jsonify({
            'success': False,
            'error': error or 'Favorit konnte nicht geändert werden.',
            'favorited': favorited,
            'count': count,
            'max': FOLDER_FAVORITES_MAX,
        }), 400

    favorites = list_folder_favorites(current_user, url_for)
    return jsonify({
        'success': True,
        'favorited': favorited,
        'count': count,
        'max': FOLDER_FAVORITES_MAX,
        'favorites': favorites,
    })


@files_bp.route('/api/file-details/<int:file_id>')
@login_required
@check_module_access('module_files')
def get_file_details(file_id):
    """Get file details for the side menu."""
    file = File.query.get_or_404(file_id)
    
    # Get file versions
    versions = FileVersion.query.filter_by(file_id=file.id).order_by(
        FileVersion.version_number.desc()
    ).all()
    
    # Format file size
    if file.file_size > 1024*1024:
        file_size_str = f"{file.file_size / (1024*1024):.1f} MB"
    else:
        file_size_str = f"{file.file_size / 1024:.1f} KB"
    
    # Get file type
    file_ext = os.path.splitext(file.original_name)[1].lower()
    if file_ext == '.md':
        file_type = 'Markdown'
    elif file_ext == '.txt':
        file_type = 'Text'
    elif file_ext == '.pdf':
        file_type = 'PDF'
    elif file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        file_type = 'Bild'
    else:
        file_type = 'Datei'
    
    # Check if file is editable
    editable_extensions = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}
    is_editable = file_ext in editable_extensions
    
    # Check if file is viewable
    viewable_extensions = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}
    is_viewable = file_ext in viewable_extensions
    
    return jsonify({
        'success': True,
        'file': {
            'id': file.id,
            'name': file.original_name,
            'size': file_size_str,
            'type': file_type,
            'uploader': file.uploader.full_name,
            'created_at': file.created_at.strftime('%d.%m.%Y %H:%M'),
            'version': file.version_number,
            'is_editable': is_editable,
            'is_viewable': is_viewable
        },
        'versions': [
            {
                'id': version.id,
                'version_number': version.version_number,
                'is_current': version.version_number == file.version_number,
                'download_url': url_for('files.download_version', version_id=version.id)
            }
            for version in versions
        ],
        'actions': {
            'download_url': url_for('files.download_file', file_id=file.id),
            'view_url': url_for('files.view_file', file_id=file.id) if is_viewable else None,
            'edit_url': url_for('files.edit_file', file_id=file.id) if is_editable else None
        }
    })
