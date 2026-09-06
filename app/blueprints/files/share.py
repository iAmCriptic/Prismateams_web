"""Public share create/update and guest share views."""

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

VALID_SHARE_MODES_CREATE = frozenset({'view', 'edit', 'dropbox'})


def _can_manage_file_share(file_obj):
    return bool(current_user.is_admin or can_edit_file(file_obj, current_user))


def _can_manage_folder_share(folder):
    return bool(current_user.is_admin or can_edit_folder(folder, current_user))


def _can_read_file_share_settings(file_obj):
    return bool(current_user.is_admin or can_view_file(file_obj, current_user))


def _can_read_folder_share_settings(folder):
    return bool(current_user.is_admin or can_view_folder(folder, current_user))


@files_bp.route('/file/<int:file_id>/share', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_file_share(file_id):
    if not _is_sharing_enabled():
        flash('Freigaben sind deaktiviert.', 'warning')
        return redirect(_safe_referrer_or(url_for('files.index')))
    file = File.query.get_or_404(file_id)
    if not _can_manage_file_share(file):
        flash('Sie haben keine Berechtigung, diese Datei freizugeben.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    modes = [normalize_share_mode(m) for m in request.form.getlist('share_modes')]
    modes = list(dict.fromkeys(m for m in modes if m in ('view', 'edit')))
    if not modes:
        mode = normalize_share_mode(request.form.get('mode') or request.form.get('share_mode') or '')
        if mode in ('view', 'edit'):
            modes = [mode]
    if not modes:
        flash('Bitte mindestens einen Link-Typ auswählen.', 'warning')
        return redirect(_safe_referrer_or(url_for('files.index')))

    for mode in modes:
        create_share_link(
            'file',
            file,
            mode,
            created_by=current_user.id,
            password=request.form.get(f'password_{mode}', '') or request.form.get('password', ''),
            expires_at_raw=request.form.get(f'expires_at_{mode}', '') or request.form.get('expires_at', ''),
            label=request.form.get(f'label_{mode}', '') or request.form.get('label', ''),
        )
    db.session.commit()
    flash('Freigabe erstellt.', 'success')
    return redirect(_safe_referrer_or(url_for('files.index')))


@files_bp.route('/folder/<int:folder_id>/share', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_folder_share(folder_id):
    if not _is_sharing_enabled() and not _is_dropbox_enabled():
        flash('Freigaben sind deaktiviert.', 'warning')
        return redirect(_safe_referrer_or(url_for('files.index')))
    folder = Folder.query.get_or_404(folder_id)
    if not _can_manage_folder_share(folder):
        flash('Sie haben keine Berechtigung, diesen Ordner freizugeben.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    modes = [normalize_share_mode(m) for m in request.form.getlist('share_modes')]
    single = normalize_share_mode(request.form.get('mode') or request.form.get('share_mode') or '')
    if single in VALID_SHARE_MODES_CREATE:
        modes.append(single)
    modes = list(dict.fromkeys(m for m in modes if m in VALID_SHARE_MODES_CREATE))
    if not modes:
        flash('Bitte mindestens einen Link-Typ auswählen.', 'warning')
        return redirect(_safe_referrer_or(url_for('files.index')))

    for mode in modes:
        if mode == 'dropbox':
            if not _is_dropbox_enabled():
                continue
        elif not _is_sharing_enabled():
            continue
        create_share_link(
            'folder',
            folder,
            mode,
            created_by=current_user.id,
            password=request.form.get(f'password_{mode}', '') or request.form.get('password', ''),
            expires_at_raw=request.form.get(f'expires_at_{mode}', '') or request.form.get('expires_at', ''),
            label=request.form.get(f'label_{mode}', '') or request.form.get('label', ''),
        )
    db.session.commit()
    flash('Freigabe erstellt.', 'success')
    return redirect(_safe_referrer_or(url_for('files.index')))


@files_bp.route('/file/<int:file_id>/share-settings')
@login_required
@check_module_access('module_files')
def file_share_settings(file_id):
    file = File.query.get_or_404(file_id)
    if not _can_read_file_share_settings(file):
        return jsonify({'success': False, 'error': 'Keine Berechtigung'}), 403
    return jsonify({
        'success': True,
        'item': serialize_share_settings(
            'file', file.id, file.name, dropbox_enabled=False
        ),
    })


@files_bp.route('/folder/<int:folder_id>/share-settings')
@login_required
@check_module_access('module_files')
def folder_share_settings(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    if not _can_read_folder_share_settings(folder):
        return jsonify({'success': False, 'error': 'Keine Berechtigung'}), 403
    return jsonify({
        'success': True,
        'item': serialize_share_settings(
            'folder', folder.id, folder.name, dropbox_enabled=_is_dropbox_enabled()
        ),
    })


def _handle_share_settings_update(resource_type, resource):
    action = (request.form.get('action') or '').strip().lower()
    if action == 'disable_all':
        for share in get_shares_for_resource(resource_type, resource.id):
            share.enabled = False
        sync_legacy_share_flags(resource_type, resource)
        return

    if action == 'add_link':
        mode = normalize_share_mode(request.form.get('mode'))
        if mode == 'dropbox' and (resource_type != 'folder' or not _is_dropbox_enabled()):
            return
        if mode in ('view', 'edit') and not _is_sharing_enabled():
            return
        create_share_link(
            resource_type,
            resource,
            mode,
            created_by=current_user.id,
            password=request.form.get('password', ''),
            expires_at_raw=request.form.get('expires_at', ''),
            label=request.form.get('label', ''),
        )
        return

    share_id_raw = request.form.get('share_id')
    share = None
    if share_id_raw:
        try:
            share = PublicShare.query.get(int(share_id_raw))
        except (TypeError, ValueError):
            share = None
        if share and (share.resource_type != resource_type or share.resource_id != resource.id):
            share = None

    if action == 'disable' and share:
        disable_share_by_id(share.id)
        return

    if action == 'enable' and share:
        enable_share_by_id(share.id)
        return

    if action == 'delete' and share:
        delete_share_by_id(share.id)
        return

    if action == 'regenerate' and share:
        update_share_link(share, regenerate_token=True)
        return

    if action == 'update' and share:
        clear_pw = request.form.get('clear_password') in ('1', 'true', 'on')
        enabled = request.form.get('enabled') in ('1', 'true', 'on')
        update_share_link(
            share,
            password=request.form.get('password'),
            clear_password=clear_pw,
            expires_at_raw=request.form.get('expires_at', ''),
            label=request.form.get('label'),
            enabled=enabled,
        )
        return

    # Legacy actions
    if action in ('disable_view', 'disable_edit'):
        mode = 'view' if action == 'disable_view' else 'edit'
        from app.utils.public_share import disable_share_link
        disable_share_link(resource_type, resource, mode)
        return

    if action in ('create_view', 'create_edit', 'create_dropbox'):
        mode = action.replace('create_', '')
        if mode == 'dropbox' and (resource_type != 'folder' or not _is_dropbox_enabled()):
            return
        if mode in ('view', 'edit') and not _is_sharing_enabled():
            return
        create_share_link(
            resource_type,
            resource,
            mode,
            created_by=current_user.id,
            password=request.form.get(f'password_{mode}', '') or request.form.get('password', ''),
            expires_at_raw=request.form.get(f'expires_at_{mode}', '') or request.form.get('expires_at', ''),
            label=request.form.get('label', ''),
        )
        return

    for mode in ('view', 'edit', 'dropbox'):
        share = get_share_for_mode(resource_type, resource.id, mode)
        if not share or not share.enabled:
            continue
        password = request.form.get(f'password_{mode}', '').strip()
        expires_raw = request.form.get(f'expires_at_{mode}', '')
        if password:
            share.password_hash = generate_password_hash(password)
        if expires_raw is not None:
            share.expires_at = _parse_share_expires(expires_raw)
    sync_legacy_share_flags(resource_type, resource)


@files_bp.route('/file/<int:file_id>/share-settings', methods=['POST'])
@login_required
@check_module_access('module_files')
def update_file_share(file_id):
    file = File.query.get_or_404(file_id)
    if not _can_manage_file_share(file):
        flash('Sie haben keine Berechtigung, diese Freigabe zu ändern.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    _handle_share_settings_update('file', file)
    db.session.commit()
    flash('Freigabe aktualisiert.', 'success')
    return redirect(_safe_referrer_or(url_for('files.index')))


@files_bp.route('/folder/<int:folder_id>/share-settings', methods=['POST'])
@login_required
@check_module_access('module_files')
def update_folder_share(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    if not _can_manage_folder_share(folder):
        flash('Sie haben keine Berechtigung, diese Freigabe zu ändern.', 'danger')
        return redirect(_safe_referrer_or(url_for('files.index')))
    _handle_share_settings_update('folder', folder)
    db.session.commit()
    flash('Freigabe aktualisiert.', 'success')
    return redirect(_safe_referrer_or(url_for('files.index')))


@files_bp.route('/share/<token>', methods=['GET', 'POST'])
def public_share(token):
    share, item = _get_public_share_context(token)
    if not share or not item:
        flash('Freigabe existiert nicht mehr oder ist abgelaufen.', 'danger')
        return redirect(url_for('files.index'))

    share_mode = normalize_share_mode(share.mode)
    from app.utils.bot_protection import get_template_context as get_bot_template_context

    bot_ctx = get_bot_template_context()
    bot_ctx['bot_context'] = 'share_edit'
    bot_ctx['show_bot'] = bot_ctx.get('bot_enabled_share_edit', False) and share_mode == 'edit'
    gate_preview_ctx = _build_share_gate_preview_context(share, item)

    if share.password_hash:
        session_key = f'share_auth_{token}'
        if request.method == 'POST' and 'password' in request.form:
            if share_mode == 'edit' and not _validate_share_edit_bot(token):
                flash('Bot-Schutz-Prüfung fehlgeschlagen. Bitte erneut versuchen.', 'danger')
                return render_template(
                    'files/share_auth.html',
                    token=token,
                    item=item,
                    share_mode=share_mode,
                    **bot_ctx,
                )
            if check_password_hash(share.password_hash, request.form.get('password', '')):
                session[session_key] = True
                log_share_access(share, 'password_auth', request)
                db.session.commit()
                return redirect(url_for('files.public_share', token=token))
            flash('Ungültiges Passwort.', 'danger')
        elif not session.get(session_key):
            return render_template(
                'files/share_auth.html',
                token=token,
                item=item,
                share_mode=share_mode,
                **bot_ctx,
            )

    guest_name_key = f'share_guest_name_{token}'
    guest_name = session.get(guest_name_key)

    if share_mode == 'edit' and request.method == 'POST' and 'guest_name' in request.form:
        if not _validate_share_edit_bot(token):
            flash('Bot-Schutz-Prüfung fehlgeschlagen. Bitte erneut versuchen.', 'danger')
            return render_template(
                'files/share_name.html',
                token=token,
                item=item,
                share_mode=share_mode,
                **gate_preview_ctx,
                **bot_ctx,
            )
        guest_name = request.form.get('guest_name', '').strip()
        if guest_name:
            session[guest_name_key] = guest_name
            log_share_access(share, 'guest_name', request, guest_name=guest_name)
            db.session.commit()
            return redirect(url_for('files.public_share', token=token))
        flash('Bitte geben Sie einen Namen ein.', 'danger')

    if share_mode == 'edit' and not guest_name:
        return render_template(
            'files/share_name.html',
            token=token,
            item=item,
            share_mode=share_mode,
            **gate_preview_ctx,
            **bot_ctx,
        )

    log_share_access(share, 'page_view', request, guest_name=guest_name)
    db.session.commit()

    from app.utils.onlyoffice import is_onlyoffice_enabled
    onlyoffice_available = is_onlyoffice_enabled()

    if share.resource_type == 'file':
        return render_template(
            'files/share.html',
            item_type='file',
            file=item,
            token=token,
            guest_name=guest_name,
            onlyoffice_available=onlyoffice_available,
            share_mode=share_mode,
            **bot_ctx,
        )

    requested_folder_id = request.args.get('folder_id', type=int)
    active_folder = item
    if requested_folder_id:
        requested_folder = Folder.query.get_or_404(requested_folder_id)
        if _is_descendant_folder(requested_folder, item):
            active_folder = requested_folder
        else:
            flash('Der angeforderte Unterordner ist nicht Teil dieser Freigabe.', 'warning')
            return redirect(url_for('files.public_share', token=token))

    folder_files = File.query.filter_by(folder_id=active_folder.id, is_current=True).order_by(File.name).all()
    subfolders = Folder.query.filter_by(parent_id=active_folder.id).order_by(Folder.name).all()
    breadcrumb_folders = _build_public_share_breadcrumb(item, active_folder, token)
    can_edit = share_mode == 'edit'

    return render_template(
        'files/share.html',
        item_type='folder',
        folder=item,
        current_share_folder=active_folder,
        subfolders=subfolders,
        breadcrumb_folders=breadcrumb_folders,
        folder_files=folder_files,
        token=token,
        guest_name=guest_name,
        onlyoffice_available=onlyoffice_available,
        share_mode=share_mode,
        can_edit=can_edit,
        **bot_ctx,
    )


@files_bp.route('/share/<token>/download', methods=['GET'])
def public_share_download(token):
    """Download für direkt freigegebene Datei."""
    share = get_share_by_token(token) or abort(404)
    item, guest_name, _access_share = _check_share_access(token)
    if not item or share.resource_type != 'file':
        flash('Zugriff verweigert.', 'danger')
        return redirect(url_for('files.public_share', token=token))

    shared_file = item
    log_share_access(share, 'download', request, guest_name=guest_name)
    db.session.commit()
    file_path = shared_file.file_path if os.path.isabs(shared_file.file_path) else os.path.join(os.getcwd(), shared_file.file_path)
    return _response_with_nosniff(send_file(file_path, as_attachment=True, download_name=shared_file.original_name))


@files_bp.route('/share/<token>/view', methods=['GET'])
def public_share_view(token):
    """Browser-Ansicht für direkt freigegebene Datei (PDF/Text/Markdown)."""
    share = get_share_by_token(token) or abort(404)
    item, guest_name, _access_share = _check_share_access(token)
    if not item or share.resource_type != 'file':
        flash('Zugriff verweigert.', 'danger')
        return redirect(url_for('files.public_share', token=token))

    file = item
    file_ext = _file_extension(file.original_name)
    back_url = url_for('files.public_share', token=token)
    download_url = url_for('files.public_share_download', token=token)
    if file_ext == '.pdf':
        log_share_access(share, 'view_pdf', request, guest_name=guest_name)
        db.session.commit()
        return render_template(
            'files/view.html',
            file=file,
            is_pdf=True,
            back_url=back_url,
            pdf_src=url_for('files.public_share_pdf', token=token),
            download_url=download_url,
            public_share=True,
        )

    kind = media_kind(file_ext)
    if kind:
        file_path = _resolve_absolute_file_path(file.file_path)
        if not file_path or not os.path.exists(file_path):
            flash(f'Datei "{file.original_name}" wurde nicht gefunden.', 'danger')
            return redirect(back_url)
        log_share_access(share, 'view_media', request, guest_name=guest_name)
        db.session.commit()
        return render_template(
            'files/view.html',
            file=file,
            is_pdf=False,
            is_image=kind == 'image',
            is_video=kind == 'video',
            is_audio=kind == 'audio',
            media_kind=kind,
            back_url=back_url,
            media_src=url_for('files.public_share_media', token=token),
            download_url=download_url,
            public_share=True,
        )

    if file_ext not in TEXT_VIEWABLE_EXTS:
        flash('Dieser Dateityp kann nicht angezeigt werden.', 'warning')
        return redirect(back_url)

    try:
        file_path = file.file_path if os.path.isabs(file.file_path) else os.path.join(os.getcwd(), file.file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        flash(f'Fehler beim Lesen der Datei: {str(e)}', 'danger')
        return redirect(back_url)

    processed_content = _render_view_content(content, file_ext)
    log_share_access(share, 'view_file', request, guest_name=guest_name)
    db.session.commit()
    return render_template(
        'files/view.html',
        file=file,
        content=content,
        processed_content=processed_content,
        is_markdown=_is_markdown_extension(file_ext),
        is_pdf=False,
        back_url=back_url,
        download_url=download_url,
        public_share=True,
    )


@files_bp.route('/share/<token>/pdf', methods=['GET'])
def public_share_pdf(token):
    """PDF-Stream für direkt freigegebene Datei."""
    share = get_share_by_token(token) or abort(404)
    item, guest_name, _access_share = _check_share_access(token)
    if not item or share.resource_type != 'file':
        abort(404)
    file = item
    file_ext = os.path.splitext(file.original_name)[1].lower()
    if file_ext != '.pdf':
        abort(404)
    file_path = file.file_path if os.path.isabs(file.file_path) else os.path.join(os.getcwd(), file.file_path)
    if not os.path.exists(file_path):
        abort(404)
    log_share_access(share, 'view_pdf', request, guest_name=guest_name)
    db.session.commit()
    return _response_with_nosniff(send_file(file_path, mimetype='application/pdf'))


@files_bp.route('/share/<token>/media', methods=['GET'])
def public_share_media(token):
    """Media-Stream für direkt freigegebene Datei."""
    share = get_share_by_token(token) or abort(404)
    item, guest_name, _access_share = _check_share_access(token)
    if not item or share.resource_type != 'file':
        abort(404)
    file = item
    if not media_kind(_file_extension(file.original_name)):
        abort(404)
    log_share_access(share, 'view_media', request, guest_name=guest_name)
    db.session.commit()
    return _send_inline_media(file)


@files_bp.route('/share/<token>/file/<int:file_id>/download', methods=['GET'])
def public_share_folder_file_download(token, file_id):
    """Download für Datei in freigegebenem Ordner (auch Unterordner)."""
    share = get_share_by_token(token) or abort(404)
    if share.resource_type != 'folder':
        abort(404)
    shared_root = resolve_resource(share) or abort(404)
    file = File.query.filter_by(id=file_id, is_current=True).first_or_404()
    if not _is_descendant_folder(file.folder, shared_root):
        abort(404)

    item, guest_name, _access_share = _check_share_access(token)
    if not item:
        flash('Zugriff verweigert.', 'danger')
        return redirect(url_for('files.public_share', token=token))

    log_share_access(share, 'download', request, guest_name=guest_name)
    db.session.commit()
    file_path = file.file_path if os.path.isabs(file.file_path) else os.path.join(os.getcwd(), file.file_path)
    return _response_with_nosniff(send_file(file_path, as_attachment=True, download_name=file.original_name))


@files_bp.route('/share/<token>/file/<int:file_id>/view', methods=['GET'])
def public_share_folder_file_view(token, file_id):
    """Browser-Ansicht für Datei in freigegebenem Ordner."""
    share = get_share_by_token(token) or abort(404)
    if share.resource_type != 'folder':
        abort(404)
    shared_root = resolve_resource(share) or abort(404)
    file = File.query.filter_by(id=file_id, is_current=True).first_or_404()
    if not _is_descendant_folder(file.folder, shared_root):
        abort(404)

    item, guest_name, _access_share = _check_share_access(token)
    if not item:
        flash('Zugriff verweigert.', 'danger')
        return redirect(url_for('files.public_share', token=token))

    file_ext = _file_extension(file.original_name)
    back_url = url_for('files.public_share', token=token, folder_id=file.folder_id)
    download_url = url_for('files.public_share_folder_file_download', token=token, file_id=file.id)
    if file_ext == '.pdf':
        log_share_access(share, 'view_pdf', request, guest_name=guest_name)
        db.session.commit()
        return render_template(
            'files/view.html',
            file=file,
            is_pdf=True,
            back_url=back_url,
            pdf_src=url_for('files.public_share_folder_file_pdf', token=token, file_id=file.id),
            download_url=download_url,
            public_share=True,
        )

    kind = media_kind(file_ext)
    if kind:
        file_path = _resolve_absolute_file_path(file.file_path)
        if not file_path or not os.path.exists(file_path):
            flash(f'Datei "{file.original_name}" wurde nicht gefunden.', 'danger')
            return redirect(back_url)
        log_share_access(share, 'view_media', request, guest_name=guest_name)
        db.session.commit()
        return render_template(
            'files/view.html',
            file=file,
            is_pdf=False,
            is_image=kind == 'image',
            is_video=kind == 'video',
            is_audio=kind == 'audio',
            media_kind=kind,
            back_url=back_url,
            media_src=url_for('files.public_share_folder_file_media', token=token, file_id=file.id),
            download_url=download_url,
            public_share=True,
        )

    if file_ext not in TEXT_VIEWABLE_EXTS:
        flash('Dieser Dateityp kann nicht angezeigt werden.', 'warning')
        return redirect(back_url)

    try:
        file_path = file.file_path if os.path.isabs(file.file_path) else os.path.join(os.getcwd(), file.file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        flash(f'Fehler beim Lesen der Datei: {str(e)}', 'danger')
        return redirect(back_url)

    processed_content = _render_view_content(content, file_ext)
    log_share_access(share, 'view_file', request, guest_name=guest_name)
    db.session.commit()
    return render_template(
        'files/view.html',
        file=file,
        content=content,
        processed_content=processed_content,
        is_markdown=_is_markdown_extension(file_ext),
        is_pdf=False,
        back_url=back_url,
        download_url=download_url,
        public_share=True,
    )


@files_bp.route('/share/<token>/file/<int:file_id>/pdf', methods=['GET'])
def public_share_folder_file_pdf(token, file_id):
    """PDF-Stream für Datei in freigegebenem Ordner."""
    share = get_share_by_token(token) or abort(404)
    if share.resource_type != 'folder':
        abort(404)
    shared_root = resolve_resource(share) or abort(404)
    file = File.query.filter_by(id=file_id, is_current=True).first_or_404()
    if not _is_descendant_folder(file.folder, shared_root):
        abort(404)
    file_ext = _file_extension(file.original_name)
    if file_ext != '.pdf':
        abort(404)
    item, guest_name, _access_share = _check_share_access(token)
    if not item:
        abort(404)
    file_path = file.file_path if os.path.isabs(file.file_path) else os.path.join(os.getcwd(), file.file_path)
    if not os.path.exists(file_path):
        abort(404)
    log_share_access(share, 'view_pdf', request, guest_name=guest_name)
    db.session.commit()
    return _response_with_nosniff(send_file(file_path, mimetype='application/pdf'))


@files_bp.route('/share/<token>/file/<int:file_id>/media', methods=['GET'])
def public_share_folder_file_media(token, file_id):
    """Media-Stream für Datei in freigegebenem Ordner."""
    share = get_share_by_token(token) or abort(404)
    if share.resource_type != 'folder':
        abort(404)
    shared_root = resolve_resource(share) or abort(404)
    file = File.query.filter_by(id=file_id, is_current=True).first_or_404()
    if not _is_descendant_folder(file.folder, shared_root):
        abort(404)
    if not media_kind(_file_extension(file.original_name)):
        abort(404)
    item, guest_name, _access_share = _check_share_access(token)
    if not item:
        abort(404)
    log_share_access(share, 'view_media', request, guest_name=guest_name)
    db.session.commit()
    return _send_inline_media(file)


@files_bp.route('/share/<token>/upload', methods=['POST'])
def public_share_upload(token):
    share = get_share_by_token(token) or abort(404)
    if normalize_share_mode(share.mode) != 'edit':
        flash('Upload ist fuer diese Freigabe nicht erlaubt.', 'warning')
        return redirect(url_for('files.public_share', token=token))
    if not _validate_share_edit_bot(token):
        flash('Bot-Schutz-Prüfung fehlgeschlagen. Bitte erneut versuchen.', 'danger')
        return redirect(url_for('files.public_share', token=token))

    item, guest_name, _access_share = _check_share_access(token)
    if not item or share.resource_type != 'folder':
        flash('Zugriff verweigert.', 'danger')
        return redirect(url_for('files.public_share', token=token))

    requested_folder_id = request.form.get('folder_id', type=int)
    shared_folder = item
    if requested_folder_id:
        target_folder = Folder.query.get_or_404(requested_folder_id)
        if not _is_descendant_folder(target_folder, item):
            flash('Ungültiger Zielordner für Upload.', 'danger')
            return redirect(url_for('files.public_share', token=token))
        shared_folder = target_folder
    if share.password_hash and not session.get(f'share_auth_{token}'):
        password = request.form.get('password', '')
        if not check_password_hash(share.password_hash, password):
            flash('Ungültiges Passwort.', 'danger')
            return redirect(url_for('files.public_share', token=token))
        session[f'share_auth_{token}'] = True

    uploader_name = request.form.get('uploader_name', '').strip() or guest_name or 'Anonym'
    if 'file' in request.files:
        files = request.files.getlist('file')
        for f in files:
            if not f.filename:
                continue
            # Derive unique name
            original_name = secure_filename(f.filename)
            if not original_name or not is_allowed_upload_filename(original_name):
                continue
            name = original_name
            existing = File.query.filter_by(name=name, folder_id=shared_folder.id, is_current=True).first()
            if existing:
                date_str = datetime.utcnow().strftime('%Y-%m-%d')
                base, ext = os.path.splitext(original_name)
                name = f"{base}_V{date_str}{ext}"
            anonymous_user = User.query.filter_by(email='anonymous@system.local').first()
            if not anonymous_user:
                anonymous_user = User(
                    email='anonymous@system.local',
                    first_name=uploader_name,
                    last_name='',
                    password_hash='',
                    is_active=True,
                    is_admin=False,
                    is_email_confirmed=True
                )
                db.session.add(anonymous_user)
                db.session.flush()
            _process_file_upload(f, name, shared_folder.id, anonymous_user.id)
        log_share_access(share, 'upload', request, guest_name=uploader_name)
        db.session.commit()
        flash('Upload abgeschlossen.', 'success')
    return redirect(url_for('files.public_share', token=token))


@files_bp.route('/share/<token>/create-folder', methods=['POST'])
def public_share_create_folder(token):
    share = get_share_by_token(token) or abort(404)
    if normalize_share_mode(share.mode) != 'edit':
        flash('Ordner erstellen ist fuer diese Freigabe nicht erlaubt.', 'warning')
        return redirect(url_for('files.public_share', token=token))
    if not _validate_share_edit_bot(token):
        flash('Bot-Schutz-Prüfung fehlgeschlagen. Bitte erneut versuchen.', 'danger')
        return redirect(url_for('files.public_share', token=token))

    item, guest_name, _access_share = _check_share_access(token)
    if not item or share.resource_type != 'folder':
        flash('Zugriff verweigert.', 'danger')
        return redirect(url_for('files.public_share', token=token))

    folder_name = sanitize_files_item_name(request.form.get('folder_name', ''))
    if not folder_name:
        flash('Bitte geben Sie einen Ordnernamen ein.', 'danger')
        return redirect(url_for('files.public_share', token=token))

    parent_id = request.form.get('parent_id', type=int)
    parent_folder = item
    if parent_id:
        requested_parent = Folder.query.get_or_404(parent_id)
        if not _is_descendant_folder(requested_parent, item):
            flash('Ungültiger Zielordner.', 'danger')
            return redirect(url_for('files.public_share', token=token))
        parent_folder = requested_parent

    existing_folder = Folder.query.filter_by(parent_id=parent_folder.id, name=folder_name).first()
    if existing_folder:
        flash(f'Ein Ordner mit dem Namen "{folder_name}" existiert bereits.', 'warning')
        return redirect(url_for('files.public_share', token=token, folder_id=parent_folder.id))

    uploader_name = request.form.get('uploader_name', '').strip() or guest_name or 'Anonym'
    anonymous_user = User.query.filter_by(email='anonymous@system.local').first()
    if not anonymous_user:
        anonymous_user = User(
            email='anonymous@system.local',
            first_name=uploader_name,
            last_name='',
            password_hash='',
            is_active=True,
            is_admin=False,
            is_email_confirmed=True
        )
        db.session.add(anonymous_user)
        db.session.flush()
    elif uploader_name:
        anonymous_user.first_name = uploader_name

    new_folder = Folder(
        name=folder_name,
        parent_id=parent_folder.id,
        created_by=anonymous_user.id
    )
    db.session.add(new_folder)
    log_share_access(share, 'create_folder', request, guest_name=uploader_name)
    db.session.commit()
    flash(f'Ordner "{folder_name}" wurde erstellt.', 'success')
    return redirect(url_for('files.public_share', token=token, folder_id=parent_folder.id))
