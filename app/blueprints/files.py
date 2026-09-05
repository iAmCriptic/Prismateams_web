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
import os
import shutil
import logging
import secrets
import requests
import re
import zipfile

files_bp = Blueprint('files', __name__)

MAX_FILE_VERSIONS = 3
MAX_FILE_PREVIEW_CHARS = 240

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
VIDEO_EXTS = {'.mp4', '.webm', '.mov', '.avi', '.m4v', '.ogv'}
AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.oga', '.opus'}
BROWSER_MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS
TEXT_VIEWABLE_EXTS = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}

_MEDIA_MIME_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
    '.gif': 'image/gif',
    '.bmp': 'image/bmp',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.mov': 'video/quicktime',
    '.avi': 'video/x-msvideo',
    '.m4v': 'video/x-m4v',
    '.ogv': 'video/ogg',
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.flac': 'audio/flac',
    '.ogg': 'audio/ogg',
    '.m4a': 'audio/mp4',
    '.aac': 'audio/aac',
    '.oga': 'audio/ogg',
    '.opus': 'audio/opus',
}


def media_kind(ext):
    """Return 'image', 'video', 'audio', or None for a file extension."""
    file_ext = (ext or '').lower()
    if file_ext and not file_ext.startswith('.'):
        file_ext = f'.{file_ext}'
    if file_ext in IMAGE_EXTS:
        return 'image'
    if file_ext in VIDEO_EXTS:
        return 'video'
    if file_ext in AUDIO_EXTS:
        return 'audio'
    return None


def media_mimetype(ext):
    """MIME type for browser-previewable media extensions."""
    file_ext = (ext or '').lower()
    if file_ext and not file_ext.startswith('.'):
        file_ext = f'.{file_ext}'
    return _MEDIA_MIME_TYPES.get(file_ext, 'application/octet-stream')


def _file_extension(filename):
    return os.path.splitext(filename or '')[1].lower()


def _mimetype_for_extension(ext):
    """MIME type for downloads and inline serving."""
    file_ext = (ext or '').lower()
    if file_ext in {'.md', '.markdown'}:
        return 'text/markdown'
    if file_ext == '.txt':
        return 'text/plain'
    if file_ext == '.pdf':
        return 'application/pdf'
    if file_ext in _MEDIA_MIME_TYPES:
        return _MEDIA_MIME_TYPES[file_ext]
    return 'application/octet-stream'


def _send_inline_media(file_obj):
    """Send media file inline for browser preview (supports Range requests)."""
    file_ext = _file_extension(file_obj.original_name)
    kind = media_kind(file_ext)
    if not kind:
        abort(404)
    file_path = _resolve_absolute_file_path(file_obj.file_path)
    if not file_path or not os.path.exists(file_path):
        abort(404)
    return send_file(
        file_path,
        mimetype=media_mimetype(file_ext),
        as_attachment=False,
        conditional=True,
    )


def _split_filename_parts(filename):
    """Split filename into base and extension."""
    base, extension = os.path.splitext(filename or '')
    return base or (filename or ''), extension


def _generate_unique_filename_in_folder(filename, folder_id):
    """Generate a non-conflicting filename for a folder."""
    base, extension = _split_filename_parts(filename)
    candidate = filename
    suffix = 1

    while File.query.filter_by(name=candidate, folder_id=folder_id, is_current=True).first():
        candidate = f"{base} ({suffix}){extension}"
        suffix += 1

    return candidate


def _create_new_file_version(existing_file, uploaded_file, user_id):
    """Create a new version for an existing file."""
    version_number = existing_file.version_number + 1

    old_version = FileVersion(
        file_id=existing_file.id,
        version_number=existing_file.version_number,
        file_path=os.path.abspath(existing_file.file_path),
        file_size=existing_file.file_size,
        uploaded_by=existing_file.uploaded_by
    )
    db.session.add(old_version)

    versions = FileVersion.query.filter_by(file_id=existing_file.id).order_by(
        FileVersion.version_number.desc()
    ).all()

    if len(versions) >= MAX_FILE_VERSIONS:
        oldest = versions[-1]
        if os.path.exists(oldest.file_path):
            os.remove(oldest.file_path)
        db.session.delete(oldest)

    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"{timestamp}_{existing_file.name}"
    filepath = os.path.join('uploads', 'files', filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    uploaded_file.save(filepath)

    absolute_filepath = os.path.abspath(filepath)
    existing_file.file_path = absolute_filepath
    existing_file.file_size = os.path.getsize(absolute_filepath)
    existing_file.version_number = version_number
    existing_file.uploaded_by = user_id
    existing_file.updated_at = datetime.utcnow()

    return version_number


def _resolve_absolute_file_path(file_path):
    """Resolve file path to absolute path."""
    if not file_path:
        return None
    if os.path.isabs(file_path):
        return file_path
    return os.path.join(os.getcwd(), file_path)


def _normalize_preview_text(text, max_chars=MAX_FILE_PREVIEW_CHARS):
    """Normalize whitespace and limit preview text length."""
    if not text:
        return ''
    normalized = re.sub(r'\s+', ' ', text).strip()
    if len(normalized) > max_chars:
        return normalized[:max_chars - 1].rstrip() + '…'
    return normalized


def _extract_preview_from_zip_xml(file_path, xml_candidates):
    """Extract text preview from zipped XML-based document formats."""
    try:
        with zipfile.ZipFile(file_path, 'r') as archive:
            for member in xml_candidates:
                if member not in archive.namelist():
                    continue
                with archive.open(member) as stream:
                    raw_xml = stream.read().decode('utf-8', errors='ignore')
                # Remove tags and decode common XML entities.
                text = re.sub(r'<[^>]+>', ' ', raw_xml)
                text = (
                    text.replace('&nbsp;', ' ')
                    .replace('&amp;', '&')
                    .replace('&lt;', '<')
                    .replace('&gt;', '>')
                    .replace('&quot;', '"')
                )
                preview = _normalize_preview_text(text)
                if preview:
                    return preview
    except Exception:
        return ''
    return ''


def build_file_preview_text(file):
    """Build a short preview text for supported file types."""
    file_ext = os.path.splitext(file.original_name or file.name or '')[1].lower()
    if not file_ext:
        return ''

    if file_ext in {'.pdf'}:
        # PDF gets a visual iframe preview in template.
        return ''

    file_path = _resolve_absolute_file_path(file.file_path)
    if not file_path or not os.path.exists(file_path):
        return ''

    try:
        if file_ext in {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as handle:
                return _normalize_preview_text(handle.read(MAX_FILE_PREVIEW_CHARS * 3))

        if file_ext in {'.docx', '.docm'}:
            return _extract_preview_from_zip_xml(file_path, ['word/document.xml'])

        if file_ext in {'.pptx', '.pptm'}:
            slide_candidates = [f'ppt/slides/slide{i}.xml' for i in range(1, 4)]
            return _extract_preview_from_zip_xml(file_path, slide_candidates)

        if file_ext in {'.odt', '.odp'}:
            return _extract_preview_from_zip_xml(file_path, ['content.xml'])
    except Exception:
        return ''

    return ''


def build_markdown_preview_html(file):
    """Build rendered markdown HTML preview for markdown files."""
    file_ext = os.path.splitext(file.original_name or file.name or '')[1].lower()
    if file_ext not in {'.md', '.markdown'}:
        return ''

    file_path = _resolve_absolute_file_path(file.file_path)
    if not file_path or not os.path.exists(file_path):
        return ''

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as handle:
            # Keep preview light-weight while preserving markdown structure.
            markdown_source = handle.read(2500)
        from app.utils.markdown import process_markdown
        rendered = process_markdown(markdown_source, wiki_mode=False)
        return rendered or ''
    except Exception:
        return ''


def _is_markdown_extension(file_ext):
    """Return whether the extension is a markdown format."""
    return file_ext in {'.md', '.markdown'}


def _render_view_content(content, file_ext):
    """Render file content with the same interpreter used by /view."""
    if _is_markdown_extension(file_ext):
        try:
            from app.utils.markdown import process_markdown
            return process_markdown(content, wiki_mode=False)
        except Exception as exc:
            current_app.logger.error(f"Markdown processing error: {exc}")
            return content
    return content


def _normalize_share_mode(raw_mode):
    """Normalize share mode input to supported values."""
    return normalize_share_mode(raw_mode)


def _parse_share_expires(raw_value):
    if not raw_value or not str(raw_value).strip():
        return None
    return datetime.fromisoformat(str(raw_value).strip())


def _share_bot_session_key(token):
    return f'share_bot_verified_{token}'


def _validate_share_edit_bot(token):
    from app.utils.bot_protection import is_enabled_for, validate_bot_protection

    if not is_enabled_for('share_edit'):
        return True
    if session.get(_share_bot_session_key(token)):
        return True
    ok, _err = validate_bot_protection(request, 'share_edit')
    if ok:
        session[_share_bot_session_key(token)] = True
    return ok


def _mailbox_bot_session_key(token):
    return f'mailbox_bot_verified_{token}'


def _mailbox_bot_template_context(token=None):
    from app.utils.bot_protection import get_template_context as get_bot_template_context

    bot_ctx = get_bot_template_context()
    bot_ctx['bot_context'] = 'mailbox'
    already = bool(token and session.get(_mailbox_bot_session_key(token)))
    bot_ctx['show_bot'] = bot_ctx.get('bot_enabled_mailbox', False) and not already
    return bot_ctx


def _validate_mailbox_bot(token):
    from app.utils.bot_protection import is_enabled_for, validate_bot_protection

    if not is_enabled_for('mailbox'):
        return True
    if session.get(_mailbox_bot_session_key(token)):
        return True
    ok, _err = validate_bot_protection(request, 'mailbox')
    if ok:
        session[_mailbox_bot_session_key(token)] = True
    return ok


def _get_public_share_context(token):
    """Return (share, item) for an enabled, non-expired public share."""
    share = get_share_by_token(token)
    if not share or share_is_expired(share):
        return None, None
    item = resolve_resource(share)
    if not item:
        return None, None
    return share, item


def _upsert_public_share(resource_type, resource, mode, *, password='', expires_at_raw='', label=None):
    """Legacy helper — prefer create_share_link for multi-link creates."""
    from app.utils.public_share import upsert_share_link
    created_by = resource.uploaded_by if resource_type == 'file' else resource.created_by
    return upsert_share_link(
        resource_type,
        resource,
        mode,
        created_by=created_by,
        password=password,
        expires_at_raw=expires_at_raw,
        label=label,
    )


def _disable_public_share(resource_type, resource, mode):
    share = get_share_for_mode(resource_type, resource.id, mode)
    if share:
        share.enabled = False
    sync_legacy_share_flags(resource_type, resource)


def _is_guest_user():
    return bool(getattr(current_user, 'is_guest', False))


def _get_guest_accessible_folder_ids():
    """Return accessible folder ids for current guest user."""
    if not _is_guest_user():
        return set()
    from app.utils.access_control import get_guest_accessible_items
    _, accessible_folders = get_guest_accessible_items(current_user)
    return {folder.id for folder in accessible_folders}


def _get_safe_folder_url(folder_id, accessible_folder_ids=None, view=None):
    """Resolve safe folder redirect target for user/guest context."""
    folder = None
    if folder_id:
        folder = Folder.query.get(folder_id)
    view_kwargs = _files_view_kwargs(view, folder=folder)
    if not folder_id:
        return url_for('files.index', **view_kwargs)

    # Persönlicher Stamm / Team-Stamm = virtuelle Root → Index
    if folder is not None and (
        getattr(folder, 'is_personal_root', False) or getattr(folder, 'is_team_root', False)
    ):
        return url_for('files.index', **view_kwargs)

    if _is_guest_user():
        accessible_ids = accessible_folder_ids
        if accessible_ids is None:
            accessible_ids = _get_guest_accessible_folder_ids()
        if folder_id not in accessible_ids:
            return url_for('files.index', **view_kwargs)

    return url_for('files.browse_folder', folder_id=folder_id, **view_kwargs)


def _files_view_kwargs(view=None, folder=None, team_id=None):
    """Preserve ?view= (and team_id) for redirects after file/folder mutations."""
    if _is_guest_user():
        return {}
    private_enabled = is_private_folders_enabled()
    team_enabled = is_team_folders_enabled()
    raw = view if view is not None else (request.form.get('view') or request.args.get('view'))
    if not raw:
        raw = session.get('files_last_view')
    if not raw and folder is not None:
        space = (getattr(folder, 'space', None) or 'public').lower()
        if space == 'personal':
            raw = 'ablage'
        elif space == 'team':
            raw = 'team'
        else:
            raw = 'public'
    files_view = normalize_view(raw, private_enabled=private_enabled, team_enabled=team_enabled)
    kwargs = {'view': files_view} if files_view else {}
    if files_view == 'team':
        tid = parse_team_id(team_id) if team_id is not None else _request_team_id(folder)
        if tid:
            kwargs['team_id'] = tid
    return kwargs


def _request_team_id(folder=None):
    raw = request.form.get('team_id') or request.args.get('team_id') or session.get('files_last_team_id')
    team_id = parse_team_id(raw)
    if not team_id and folder is not None:
        team_id = getattr(folder, 'team_id', None)
    return team_id


def _resolve_create_parent(files_view, folder_id, team_id=None):
    """Resolve parent folder for create/upload at a view root."""
    if folder_id:
        return folder_id, Folder.query.get(folder_id)
    if files_view == 'ablage' and is_private_folders_enabled():
        folder_id = resolve_default_parent_for_view('ablage', current_user.id)
        return folder_id, Folder.query.get(folder_id) if folder_id else None
    if files_view == 'team' and is_team_folders_enabled() and team_id:
        if not user_may_use_file_team(current_user, team_id):
            return None, None
        folder_id = resolve_default_parent_for_view('team', current_user.id, team_id=team_id)
        return folder_id, Folder.query.get(folder_id) if folder_id else None
    return None, None


def _files_context_url(folder_id=None, folder=None):
    """Build URL back to the folder the user was browsing (with correct ?view=)."""
    target_id = folder_id
    target_folder = folder

    raw_return = (request.form.get('return_folder_id') or '').strip()
    if raw_return:
        try:
            target_id = int(raw_return)
            target_folder = Folder.query.get(target_id)
        except (TypeError, ValueError):
            pass

    if target_folder is None and target_id:
        target_folder = Folder.query.get(target_id)

    view_kwargs = _files_view_kwargs(folder=target_folder)

    # Ablage-/Team-Root: Stammordner ist virtuell
    if target_folder is not None and (
        getattr(target_folder, 'is_personal_root', False)
        or getattr(target_folder, 'is_team_root', False)
    ):
        return url_for('files.index', **view_kwargs)

    if target_id:
        return url_for('files.browse_folder', folder_id=target_id, **view_kwargs)
    return url_for('files.index', **view_kwargs)


def _redirect_to_files_context(folder_id=None, folder=None):
    """Redirect back to the folder the user was browsing (with correct ?view=)."""
    return redirect(_files_context_url(folder_id=folder_id, folder=folder))


def _get_safe_file_back_url(file_obj, accessible_folder_ids=None, view=None):
    """Resolve safe return URL from file views/editors."""
    return _get_safe_folder_url(
        file_obj.folder_id if file_obj else None,
        accessible_folder_ids=accessible_folder_ids,
        view=view,
    )


@files_bp.route('/')
@login_required
@check_module_access('module_files')
def index():
    """File manager root view."""
    return browse_folder(None)


@files_bp.route('/folder/<int:folder_id>')
@login_required
@check_module_access('module_files')
def browse_folder(folder_id):
    """Browse a specific folder."""
    accessible_folder_ids = set()
    is_guest = _is_guest_user()
    private_enabled = is_private_folders_enabled() and not is_guest
    team_enabled = is_team_folders_enabled() and not is_guest
    spaces_enabled = (private_enabled or team_enabled)
    files_team_id = parse_team_id(request.args.get('team_id')) if not is_guest else None
    # Gäste behalten die alte Root-Ansicht ohne Sidebar-Nav
    if is_guest:
        files_view = None
    else:
        files_view = normalize_view(
            request.args.get('view'),
            private_enabled=private_enabled,
            team_enabled=team_enabled,
        )

    # Öffentliche / Team-Ordner landen ohne ?view= default in Ablage → kein Zugriff.
    if not is_guest and not request.args.get('view') and folder_id:
        target = Folder.query.get(folder_id)
        if target and target.deleted_at is None:
            if team_enabled and ((getattr(target, 'space', None) or '') == 'team' or getattr(target, 'is_team_root', False)):
                tid = getattr(target, 'team_id', None)
                if tid:
                    return redirect(url_for('files.browse_folder', folder_id=folder_id, view='team', team_id=tid))
            if private_enabled and files_view == 'ablage':
                personal_root = ensure_personal_root(current_user.id)
                if not folder_is_under_personal_root(target, personal_root.id):
                    return redirect(url_for('files.browse_folder', folder_id=folder_id, view='public'))

    if files_view == 'team':
        if not files_team_id:
            files_team_id = parse_team_id(session.get('files_last_team_id'))
        if not user_may_use_file_team(current_user, files_team_id):
            flash('Sie haben keinen Zugriff auf diese Team-Ablage.', 'danger')
            fallback = 'ablage' if private_enabled else 'public'
            return redirect(url_for('files.index', view=fallback))

    if not is_guest and files_view:
        session['files_last_view'] = files_view
        session['files_last_folder_id'] = folder_id
        if files_view == 'team' and files_team_id:
            session['files_last_team_id'] = files_team_id
        elif files_view != 'team':
            session.pop('files_last_team_id', None)

    # Gast-Accounts: Nur Freigabelinks anzeigen
    if is_guest:
        from app.utils.access_control import get_guest_accessible_items, get_guest_directly_shared_folders
        accessible_files, accessible_folders = get_guest_accessible_items(current_user)
        accessible_folder_ids = {folder.id for folder in accessible_folders}
        
        # Filtere nach aktuell angezeigtem Ordner
        current_folder = None
        if folder_id:
            # Prüfe ob Gast Zugriff auf diesen Ordner hat
            folder_with_access = next((f for f in accessible_folders if f.id == folder_id), None)
            if not folder_with_access:
                flash('Sie haben keinen Zugriff auf diesen Ordner.', 'danger')
                return redirect(url_for('files.index'))
            current_folder = folder_with_access
        
        # Zeige nur zugängliche Unterordner des aktuellen Ordners
        if folder_id:
            subfolders = [f for f in accessible_folders if f.parent_id == folder_id]
        else:
            # Root zeigt explizit freigegebene Ordner als Einstiegspunkte
            # sowie Fallback-Roots (wenn ein Parent nicht zugänglich ist).
            directly_shared_folders = get_guest_directly_shared_folders(current_user)
            root_like_folders = [
                f for f in accessible_folders
                if f.parent_id is None or f.parent_id not in accessible_folder_ids
            ]
            unique_folders = {}
            for folder in directly_shared_folders + root_like_folders:
                unique_folders[folder.id] = folder
            subfolders = list(unique_folders.values())
        
        # Zeige nur zugängliche Dateien im aktuellen Ordner
        # (get_guest_accessible_items gibt bereits alle Dateien inkl. Unterordnern zurück)
        if folder_id:
            files = [f for f in accessible_files if f.folder_id == folder_id]
        else:
            # Root zeigt auch direkt freigegebene Dateien, wenn ihr Ordner nicht zugänglich ist
            files = [
                f for f in accessible_files
                if f.folder_id is None or f.folder_id not in accessible_folder_ids
            ]
        
        # Sortiere
        subfolders = sorted(subfolders, key=lambda x: x.name)
        files = sorted(files, key=lambda x: x.name)
    elif spaces_enabled:
        if files_view == 'ablage':
            ensure_personal_root(current_user.id)
        if files_view == 'team' and files_team_id:
            ensure_team_root(files_team_id, current_user.id)
        result = list_view_contents(files_view, folder_id, current_user, team_id=files_team_id)
        current_folder, subfolders, files, _view_key = result
        if current_folder == 'forbidden':
            flash('Sie haben keinen Zugriff auf diesen Ordner.', 'danger')
            view_kwargs = {'view': files_view}
            if files_view == 'team' and files_team_id:
                view_kwargs['team_id'] = files_team_id
            return redirect(url_for('files.index', **view_kwargs))
    else:
        # Ohne Private-/Team-Ordner: Public-Baum + optional Papierkorb (Sidebar bleibt)
        current_folder = None
        if files_view == 'trash':
            subfolders = (
                Folder.query.filter(
                    Folder.deleted_at.isnot(None),
                    Folder.created_by == current_user.id,
                    Folder.is_personal_root.is_(False),
                    Folder.is_team_root.is_(False),
                )
                .order_by(Folder.deleted_at.desc())
                .all()
            )
            files = (
                File.query.filter(
                    File.deleted_at.isnot(None),
                    File.uploaded_by == current_user.id,
                    File.is_current.is_(True),
                )
                .order_by(File.deleted_at.desc())
                .all()
            )
        else:
            if folder_id:
                current_folder = Folder.query.get_or_404(folder_id)
                if current_folder.deleted_at is not None:
                    flash('Dieser Ordner wurde gelöscht.', 'warning')
                    return redirect(url_for('files.index', view=files_view or 'public'))
                if (getattr(current_folder, 'space', None) or '') == 'team' or getattr(current_folder, 'is_team_root', False):
                    flash('Sie haben keinen Zugriff auf diesen Ordner.', 'danger')
                    return redirect(url_for('files.index', view='public'))

            # Get subfolders
            if folder_id:
                subfolders = Folder.query.filter(
                    Folder.parent_id == folder_id,
                    Folder.deleted_at.is_(None),
                    Folder.is_personal_root.is_(False),
                    Folder.is_team_root.is_(False),
                ).order_by(Folder.name).all()
            else:
                subfolders = Folder.query.filter(
                    Folder.parent_id.is_(None),
                    Folder.deleted_at.is_(None),
                    Folder.is_personal_root.is_(False),
                    Folder.is_team_root.is_(False),
                    Folder.space != 'team',
                ).order_by(Folder.name).all()

            if folder_id:
                files = File.query.filter(
                    File.folder_id == folder_id,
                    File.is_current.is_(True),
                    File.deleted_at.is_(None),
                ).order_by(File.name).all()
            else:
                files = File.query.filter(
                    File.folder_id.is_(None),
                    File.is_current.is_(True),
                    File.deleted_at.is_(None),
                    File.space != 'team',
                ).order_by(File.name).all()

            if files is None:
                files = []
    
    # Build breadcrumbs starting from root to current folder
    breadcrumb_folders = []
    view_kwargs = {'view': files_view} if files_view else {}
    if files_view == 'team' and files_team_id:
        view_kwargs['team_id'] = files_team_id
    if current_folder and current_folder != 'forbidden':
        ancestors = []
        node = current_folder
        personal_root_id = None
        team_root_id = None
        if private_enabled and files_view == 'ablage':
            personal_root_id = ensure_personal_root(current_user.id).id
        if team_enabled and files_view == 'team' and files_team_id:
            team_root = ensure_team_root(files_team_id, current_user.id)
            team_root_id = team_root.id if team_root else None
        while node:
            if personal_root_id and node.id == personal_root_id:
                break
            if team_root_id and node.id == team_root_id:
                break
            ancestors.append(node)
            node = node.parent
        ancestors.reverse()
        if _is_guest_user():
            ancestors = [folder for folder in ancestors if folder.id in accessible_folder_ids]
        breadcrumb_folders = [
            {
                'id': folder.id,
                'name': folder.name,
                'url': url_for('files.browse_folder', folder_id=folder.id, **view_kwargs)
            }
            for folder in ancestors
        ]

    # Feature flags
    dropbox_setting = SystemSettings.query.filter_by(key='files_dropbox_enabled').first()
    sharing_setting = SystemSettings.query.filter_by(key='files_sharing_enabled').first()
    files_dropbox_enabled = (dropbox_setting and str(dropbox_setting.value).lower() == 'true') or False
    files_sharing_enabled = (sharing_setting and str(sharing_setting.value).lower() == 'true') or False

    from app.utils.document_formats import get_create_type_map
    create_types = get_create_type_map()
    
    # Check ONLYOFFICE availability
    from app.utils.onlyoffice import is_onlyoffice_enabled
    onlyoffice_available = is_onlyoffice_enabled()

    file_preview_map = {file.id: build_file_preview_text(file) for file in files}
    file_preview_html_map = {file.id: build_markdown_preview_html(file) for file in files}

    # Uploader names for list view
    # Eager-load uploaders for list view (relationship) + map fallback
    for f in files:
        try:
            _ = f.uploader
        except Exception:
            pass
    uploader_ids = {f.uploaded_by for f in files if f.uploaded_by}
    creator_ids = {folder.created_by for folder in subfolders if folder.created_by}
    user_ids = uploader_ids | creator_ids
    users_by_id = {
        u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    root_url = url_for('files.index', **view_kwargs) if view_kwargs else url_for('files.index')

    folder_favorites = []
    favorite_folder_ids = set()
    if not is_guest:
        folder_favorites = list_folder_favorites(current_user, url_for)
        favorite_folder_ids = {f['id'] for f in folder_favorites}

    nav_teams = user_file_teams(current_user) if team_enabled else []
    files_team_name = None
    if files_view == 'team' and files_team_id:
        files_team_name = next((t.name for t in nav_teams if t.id == files_team_id), None)

    from app.utils.webdav import is_webdav_enabled
    files_webdav_enabled = is_webdav_enabled()
    webdav_url = f"{request.url_root.rstrip('/')}/webdav"

    return render_template(
        'files/index.html',
        current_folder=current_folder if current_folder != 'forbidden' else None,
        subfolders=subfolders,
        files=files,
        file_preview_map=file_preview_map,
        file_preview_html_map=file_preview_html_map,
        files_dropbox_enabled=files_dropbox_enabled,
        files_sharing_enabled=files_sharing_enabled,
        files_private_folders_enabled=private_enabled,
        files_team_folders_enabled=team_enabled,
        files_webdav_enabled=files_webdav_enabled,
        webdav_url=webdav_url,
        files_nav_teams=nav_teams,
        files_team_id=files_team_id,
        files_team_name=files_team_name,
        files_view=files_view,
        create_types=create_types,
        onlyoffice_available=onlyoffice_available,
        breadcrumb_folders=breadcrumb_folders,
        users_by_id=users_by_id,
        files_root_url=root_url,
        is_trash_view=(files_view == 'trash'),
        folder_favorites=folder_favorites,
        favorite_folder_ids=favorite_folder_ids,
        files_max_upload_bytes=(
            resolve_limits_for_user(current_user.id)['max_file_size']
            if not is_guest else get_global_max_file_size()
        ),
    )


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
        return redirect(request.referrer or url_for('files.index'))
    
    folder_name = request.form.get('folder_name', '').strip()
    parent_id = request.form.get('parent_id')
    files_view = normalize_view(request.form.get('view') or request.args.get('view'))
    team_id = _request_team_id()
    
    folder_name = sanitize_files_item_name(folder_name)
    if not folder_name:
        flash('Bitte geben Sie einen Ordnernamen ein.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    parent_id = int(parent_id) if parent_id else None
    private_enabled = is_private_folders_enabled()
    team_enabled = is_team_folders_enabled()
    if (private_enabled or team_enabled) and files_view == 'trash':
        flash('Im Papierkorb können keine Ordner erstellt werden.', 'warning')
        return redirect(url_for('files.index', view='trash'))

    parent_id, parent_folder = _resolve_create_parent(files_view, parent_id, team_id)
    if files_view == 'team' and team_enabled and not parent_folder:
        flash('Keine Berechtigung für diese Team-Ablage.', 'danger')
        return redirect(request.referrer or url_for('files.index'))

    if (private_enabled or team_enabled) and parent_folder and not can_edit_folder(parent_folder, current_user):
        flash('Keine Berechtigung für diesen Ordner.', 'danger')
        return redirect(request.referrer or url_for('files.index'))

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
        return redirect(request.referrer or url_for('files.index'))
    
    file = File.query.get_or_404(file_id)
    new_name = sanitize_files_item_name(request.form.get('new_name', ''))
    
    if not new_name:
        flash('Neuer Dateiname darf nicht leer sein.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Prüfe ob bereits eine Datei mit diesem Namen im selben Ordner existiert
    existing_file = File.query.filter_by(
        name=new_name,
        folder_id=file.folder_id,
        is_current=True
    ).first()
    
    if existing_file and existing_file.id != file.id:
        flash(f'Eine Datei mit dem Namen "{new_name}" existiert bereits in diesem Ordner.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
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
        return redirect(request.referrer or url_for('files.index'))
    
    folder = Folder.query.get_or_404(folder_id)
    if getattr(folder, 'is_personal_root', False) or getattr(folder, 'is_team_root', False):
        flash('Dieser Stammordner kann nicht umbenannt werden.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    new_name = sanitize_files_item_name(request.form.get('new_name', ''))
    
    if not new_name:
        flash('Neuer Ordnername darf nicht leer sein.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
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
        return redirect(request.referrer or url_for('files.index'))

    folder = Folder.query.get_or_404(folder_id)
    raw_color = (request.form.get('color') or '').strip().lower()
    clear_color = (request.form.get('clear_color') or '').strip() == '1'

    if clear_color or not raw_color:
        folder.color = None
    elif re.fullmatch(r'#[0-9a-f]{6}', raw_color):
        folder.color = raw_color
    else:
        flash('Ungültige Farbe. Bitte wählen Sie eine HEX-Farbe.', 'danger')
        return redirect(request.referrer or url_for('files.index'))

    db.session.commit()
    flash('Ordnerfarbe wurde aktualisiert.', 'success')
    return redirect(request.referrer or url_for('files.index'))


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
        return redirect(request.referrer or url_for('files.index'))
    
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
        return redirect(request.referrer or url_for('files.index'))

    if not filename:
        flash('Bitte geben Sie einen Dateinamen ein.', 'danger')
        return redirect(request.referrer or url_for('files.index'))

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
        return redirect(request.referrer or url_for('files.index'))

    if not parent_folder and folder_id:
        parent_folder = Folder.query.get(folder_id)
    if (private_enabled or team_enabled) and parent_folder and not can_edit_folder(parent_folder, current_user):
        flash('Keine Berechtigung für diesen Ordner.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
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
        return redirect(request.referrer or url_for('files.index'))
    
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
        return redirect(request.referrer or url_for('files.index'))
    
    if not filename:
        flash('Bitte geben Sie einen Dateinamen ein.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Validate file type against admin format setting
    if file_type not in allowed_types:
        flash('Ungültiger Dateityp.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
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
        return redirect(request.referrer or url_for('files.index'))

    if not parent_folder and folder_id:
        parent_folder = Folder.query.get(folder_id)
    if (private_enabled or team_enabled) and parent_folder and not can_edit_folder(parent_folder, current_user):
        flash('Keine Berechtigung für diesen Ordner.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
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
        return redirect(request.referrer or url_for('files.index'))
    except Exception as e:
        logging.error(f"Fehler beim Erstellen der Office-Datei: {e}")
        flash(f'Fehler beim Erstellen der Datei: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
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

    # Gast-Accounts können nur in freigegebenen Ordnern hochladen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        folder_id = request.form.get('folder_id')
        folder_id = int(folder_id) if folder_id else None
        
        # Prüfe ob Gast Zugriff auf diesen Ordner hat
        if folder_id:
            from app.utils.access_control import get_guest_accessible_items
            accessible_files, accessible_folders = get_guest_accessible_items(current_user)
            folder_with_access = next((f for f in accessible_folders if f.id == folder_id), None)
            if not folder_with_access:
                flash('Sie haben keinen Zugriff auf diesen Ordner.', 'danger')
                return _finish(request.referrer or url_for('files.index'))
        else:
            flash('Gast-Accounts können nur in freigegebenen Ordnern Dateien hochladen.', 'danger')
            return _finish(request.referrer or url_for('files.index'))
    
    folder_id = request.form.get('folder_id')
    folder_id = int(folder_id) if folder_id else None
    conflict_strategy = request.form.get('conflict_strategy', '').strip().lower()
    files_view = normalize_view(request.form.get('view') or request.args.get('view'))
    team_id = _request_team_id()
    folder_id, upload_parent = _resolve_create_parent(files_view, folder_id, team_id)
    if files_view == 'team' and is_team_folders_enabled() and not upload_parent:
        flash('Keine Berechtigung für diese Team-Ablage.', 'danger')
        return _finish(request.referrer or url_for('files.index'))
    
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
                
                # Determine target folder - create subfolders if needed
                target_folder_id = folder_id
                if len(file_path_parts) > 1:
                    # Create folder structure
                    current_parent_id = folder_id
                    for folder_name in file_path_parts[:-1]:
                        folder_name_clean = secure_filename(folder_name)
                        if not folder_name_clean:
                            continue
                        
                        # Check if folder exists
                        existing_folder = Folder.query.filter_by(
                            name=folder_name_clean,
                            parent_id=current_parent_id
                        ).first()
                        
                        if not existing_folder:
                            # Create new folder
                            parent_for_space = Folder.query.get(current_parent_id) if current_parent_id else None
                            new_folder = Folder(
                                name=folder_name_clean,
                                parent_id=current_parent_id,
                                created_by=current_user.id,
                                space=resolve_space_for_parent(parent_for_space, files_view or 'public'),
                                team_id=resolve_team_id_for_parent(parent_for_space, files_view, team_id),
                            )
                            db.session.add(new_folder)
                            db.session.flush()  # Get the ID
                            current_parent_id = new_folder.id
                        else:
                            current_parent_id = existing_folder.id
                    
                    target_folder_id = current_parent_id
                
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
        return _finish(request.referrer or url_for('files.index'))

    uploaded_files = [f for f in request.files.getlist('file') if f and f.filename]
    if not uploaded_files:
        flash('Keine Datei ausgewählt.', 'danger')
        return _finish(request.referrer or url_for('files.index'))

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
            if not original_name:
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
            return _finish(request.referrer or url_for('files.index'))

        original_name = secure_filename(file.filename)
        if not original_name:
            flash('Ungültiger Dateiname.', 'danger')
            return _finish(request.referrer or url_for('files.index'))

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


def _process_file_upload(file, original_name, folder_id, user_id, space='public', team_id=None):
    """Helper function to process a single file upload."""
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"{timestamp}_{original_name}"
    filepath = os.path.join('uploads', 'files', filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    file.save(filepath)
    
    # Store absolute path in database
    absolute_filepath = os.path.abspath(filepath)

    if folder_id:
        parent = Folder.query.get(folder_id)
        if parent:
            if parent.space:
                space = parent.space
            team_id = getattr(parent, 'team_id', None)
    
    new_file = File(
        name=original_name,
        original_name=original_name,
        folder_id=folder_id,
        uploaded_by=user_id,
        file_path=absolute_filepath,
        file_size=os.path.getsize(absolute_filepath),
        mime_type=file.content_type,
        version_number=1,
        is_current=True,
        space=space or 'public',
        team_id=team_id,
    )
    db.session.add(new_file)
    return new_file


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
    
    return send_file(file_path, mimetype='application/pdf')


@files_bp.route('/serve-media/<int:file_id>')
@login_required
@check_module_access('module_files')
def serve_media(file_id):
    """Serve image/video/audio inline for browser preview."""
    file = File.query.get_or_404(file_id)
    if _is_guest_user():
        from app.utils.access_control import guest_has_file_access
        if not guest_has_file_access(current_user, file):
            abort(403)
    elif not can_view_file(file, current_user) and not current_user.is_admin:
        abort(403)
    return _send_inline_media(file)


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

    return send_file(
        file_path, 
        as_attachment=True, 
        download_name=file.original_name,
        mimetype=mimetype
    )


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
    
    return send_file(
        file_path, 
        as_attachment=True, 
        download_name=versioned_filename,
        mimetype=mimetype
    )


@files_bp.route('/edit/<int:file_id>', methods=['GET', 'POST'])
@login_required
@check_module_access('module_files')
def edit_file(file_id):
    """Edit a text file online."""
    file = File.query.get_or_404(file_id)
    
    # Für Gast-Accounts: Prüfe ob Zugriff über Freigabelink besteht
    guest_accessible_folder_ids = None
    if _is_guest_user():
        from app.utils.access_control import guest_has_file_access
        if not guest_has_file_access(current_user, file):
            flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
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
        filename = f"{timestamp}_{file.original_name}"
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


@files_bp.route('/delete/<int:file_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def delete_file(file_id):
    """Soft-delete a file (or hard-delete when already in trash / purge)."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Dateien löschen.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    file = File.query.get_or_404(file_id)
    folder_id = file.folder_id
    files_view = normalize_view(request.form.get('view') or request.args.get('view'))
    purge = request.form.get('purge') == '1' or request.form.get('action') == 'purge'
    spaces_on = is_files_spaces_enabled()

    if spaces_on and not can_edit_file(file, current_user) and file.uploaded_by != current_user.id:
        flash('Keine Berechtigung.', 'danger')
        return redirect(request.referrer or url_for('files.index'))

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
        return redirect(request.referrer or url_for('files.index'))
    
    folder = Folder.query.get_or_404(folder_id)
    if folder.is_personal_root or getattr(folder, 'is_team_root', False):
        flash('Dieser Stammordner kann nicht gelöscht werden.', 'danger')
        return redirect(request.referrer or url_for('files.index'))

    parent_id = folder.parent_id
    files_view = normalize_view(request.form.get('view') or request.args.get('view'))
    purge = request.form.get('purge') == '1' or request.form.get('action') == 'purge'
    spaces_on = is_files_spaces_enabled()

    if spaces_on and not can_edit_folder(folder, current_user) and folder.created_by != current_user.id:
        flash('Keine Berechtigung.', 'danger')
        return redirect(request.referrer or url_for('files.index'))

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

        return send_file(
            tmp_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='application/zip',
        )
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


# Briefkasten (Dropbox) Routes
@files_bp.route('/folder/<int:folder_id>/make-dropbox', methods=['POST'])
@login_required
@check_module_access('module_files')
def make_dropbox(folder_id):
    """Aktiviere Briefkasten für einen Ordner (legt public_shares-Eintrag an)."""
    if not _is_dropbox_enabled():
        flash('Briefkästen sind deaktiviert.', 'warning')
        return redirect(request.referrer or url_for('files.browse_folder', folder_id=folder_id))

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


# =========================
# Sharing (Freigaben)
# =========================

def _is_sharing_enabled() -> bool:
    setting = SystemSettings.query.filter_by(key='files_sharing_enabled').first()
    return (setting and str(setting.value).lower() == 'true') or False


def _is_dropbox_enabled() -> bool:
    setting = SystemSettings.query.filter_by(key='files_dropbox_enabled').first()
    return (setting and str(setting.value).lower() == 'true') or False


def _dropbox_password_hash(share, folder):
    if share and share.password_hash:
        return share.password_hash
    return getattr(folder, 'dropbox_password_hash', None)


def _check_share_access(token):
    """Prüft PublicShare-Token; gibt (item, guest_name, share) zurück."""
    share, item = _get_public_share_context(token)
    if not share or not item:
        return None, None, None

    if share.password_hash and not session.get(f'share_auth_{token}'):
        return None, None, share

    share_mode = normalize_share_mode(share.mode)
    guest_name = session.get(f'share_guest_name_{token}')
    if share_mode == 'edit' and not guest_name:
        return None, None, share

    return item, guest_name, share


def _is_descendant_folder(candidate_folder, root_folder):
    """Prüft, ob candidate_folder innerhalb root_folder liegt (inkl. root)."""
    current = candidate_folder
    while current:
        if current.id == root_folder.id:
            return True
        if not current.parent_id:
            break
        current = Folder.query.get(current.parent_id)
    return False


def _resolve_shared_file(item, file_id):
    """Datei unter Freigabe auflösen (direkt oder in Ordner inkl. Unterordner)."""
    file = File.query.filter_by(id=file_id, is_current=True).first()
    if not file:
        return None
    if isinstance(item, File):
        return file if item.id == file.id else None
    if isinstance(item, Folder):
        if not file.folder or not _is_descendant_folder(file.folder, item):
            return None
        return file
    return None


def _build_public_share_breadcrumb(root_folder, current_folder, token):
    """Baut Breadcrumbs relativ zum freigegebenen Root-Ordner."""
    chain = []
    cursor = current_folder
    while cursor:
        chain.append(cursor)
        if cursor.id == root_folder.id:
            break
        if not cursor.parent_id:
            chain = []
            break
        cursor = Folder.query.get(cursor.parent_id)

    chain.reverse()
    breadcrumbs = []
    for folder in chain:
        breadcrumbs.append({
            'id': folder.id,
            'name': folder.name,
            'url': url_for('files.public_share', token=token, folder_id=folder.id),
        })
    return breadcrumbs


def _build_share_gate_preview_context(share, item):
    """Vorschau-Kontext für vorgeschaltete Freigabe-Seiten (Name/Passwort)."""
    if share.resource_type == 'folder':
        preview_subfolders = Folder.query.filter_by(parent_id=item.id).order_by(Folder.name).limit(12).all()
        preview_files = File.query.filter_by(folder_id=item.id, is_current=True).order_by(File.name).limit(24).all()
        return {
            'preview_item_type': 'folder',
            'preview_folder': item,
            'preview_subfolders': preview_subfolders,
            'preview_files': preview_files,
        }

    return {
        'preview_item_type': 'file',
        'preview_folder': None,
        'preview_subfolders': [],
        'preview_files': [item],
    }


VALID_SHARE_MODES_CREATE = frozenset({'view', 'edit', 'dropbox'})


@files_bp.route('/file/<int:file_id>/share', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_file_share(file_id):
    if not _is_sharing_enabled():
        flash('Freigaben sind deaktiviert.', 'warning')
        return redirect(request.referrer or url_for('files.index'))
    file = File.query.get_or_404(file_id)
    modes = [normalize_share_mode(m) for m in request.form.getlist('share_modes')]
    modes = list(dict.fromkeys(m for m in modes if m in ('view', 'edit')))
    if not modes:
        mode = normalize_share_mode(request.form.get('mode') or request.form.get('share_mode') or '')
        if mode in ('view', 'edit'):
            modes = [mode]
    if not modes:
        flash('Bitte mindestens einen Link-Typ auswählen.', 'warning')
        return redirect(request.referrer or url_for('files.index'))

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
    return redirect(request.referrer or url_for('files.index'))


@files_bp.route('/folder/<int:folder_id>/share', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_folder_share(folder_id):
    if not _is_sharing_enabled() and not _is_dropbox_enabled():
        flash('Freigaben sind deaktiviert.', 'warning')
        return redirect(request.referrer or url_for('files.index'))
    folder = Folder.query.get_or_404(folder_id)
    modes = [normalize_share_mode(m) for m in request.form.getlist('share_modes')]
    single = normalize_share_mode(request.form.get('mode') or request.form.get('share_mode') or '')
    if single in VALID_SHARE_MODES_CREATE:
        modes.append(single)
    modes = list(dict.fromkeys(m for m in modes if m in VALID_SHARE_MODES_CREATE))
    if not modes:
        flash('Bitte mindestens einen Link-Typ auswählen.', 'warning')
        return redirect(request.referrer or url_for('files.index'))

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
    return redirect(request.referrer or url_for('files.index'))


@files_bp.route('/file/<int:file_id>/share-settings')
@login_required
@check_module_access('module_files')
def file_share_settings(file_id):
    file = File.query.get_or_404(file_id)
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
    _handle_share_settings_update('file', file)
    db.session.commit()
    flash('Freigabe aktualisiert.', 'success')
    return redirect(request.referrer or url_for('files.index'))


@files_bp.route('/folder/<int:folder_id>/share-settings', methods=['POST'])
@login_required
@check_module_access('module_files')
def update_folder_share(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    _handle_share_settings_update('folder', folder)
    db.session.commit()
    flash('Freigabe aktualisiert.', 'success')
    return redirect(request.referrer or url_for('files.index'))


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
    return send_file(file_path, as_attachment=True, download_name=shared_file.original_name)


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
    return send_file(file_path, mimetype='application/pdf')


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
    return send_file(file_path, as_attachment=True, download_name=file.original_name)


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
    return send_file(file_path, mimetype='application/pdf')


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
        from app.utils.access_control import guest_has_file_access
        if not guest_has_file_access(current_user, file_obj):
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
        from app.utils.access_control import guest_has_file_access
        if not guest_has_file_access(current_user, file_obj):
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
    
    # Für Gast-Accounts: Prüfe ob Zugriff über Freigabelink besteht
    guest_accessible_folder_ids = None
    if _is_guest_user():
        from app.utils.access_control import guest_has_file_access
        if not guest_has_file_access(current_user, file):
            flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
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
    
    # Check for access token (REQUIRED for OnlyOffice access)
    access_token = request.args.get('token')
    # Log full token info to verify it's complete
    if access_token:
        token_length = len(access_token)
        token_preview = access_token[:8] + '...' + access_token[-4:] if token_length > 12 else access_token
        logging.info(f"ONLYOFFICE document request - file_id: {file_id}, token_length: {token_length}, token_preview: {token_preview}, full_token: {access_token}")
    else:
        logging.warning(f"ONLYOFFICE document request - file_id: {file_id}, NO TOKEN in request!")
    logging.info(f"ONLYOFFICE request details - method: {request.method}, remote_addr: {request.remote_addr}, referer: {request.headers.get('Referer', 'None')}, user_agent: {request.headers.get('User-Agent', 'Unknown')}")
    
    # Token is REQUIRED - OnlyOffice cannot use session cookies
    if not access_token:
        logging.error(f"ONLYOFFICE document access denied - NO TOKEN provided for file {file_id}. OnlyOffice Document Server cannot use session cookies!")
        # Return JSON error, NOT HTML redirect
        return jsonify({'error': 'Access token required'}), 403
    
    # Validate token
    from app.utils.onlyoffice import validate_onlyoffice_access_token
    if not validate_onlyoffice_access_token(access_token, file_id):
        logging.error(f"ONLYOFFICE document access denied - INVALID TOKEN for file {file_id}")
        return jsonify({'error': 'Invalid access token'}), 403
    
    logging.info(f"ONLYOFFICE document access granted via token for file {file_id}")
    
    file = File.query.get_or_404(file_id)
    logging.info(f"ONLYOFFICE document request - file_id: {file_id}, file: {file.original_name}, token_present: {bool(access_token)}")
    
    # Additional security: if no token, verify user has access to file
    if not access_token and current_user.is_authenticated:
        # Check if user has access to this file
        # (User must own the file or have access through folder permissions)
        if file.uploaded_by != current_user.id:
            # Check folder access if file is in a folder
            if file.folder_id:
                folder = Folder.query.get(file.folder_id)
                if not folder or folder.created_by != current_user.id:
                    logging.warning(f"ONLYOFFICE access denied - user {current_user.id} has no access to file {file_id}")
                    return jsonify({'error': 'Access denied'}), 403
            else:
                logging.warning(f"ONLYOFFICE access denied - user {current_user.id} has no access to file {file_id}")
                return jsonify({'error': 'Access denied'}), 403
    
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
    
    # Log ALL requests to this endpoint
    logging.info(f"ONLYOFFICE share document endpoint called - method: {request.method}, token: {token[:8]}..., file_id: {file_id}, remote_addr: {request.remote_addr}")
    
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        logging.warning(f"ONLYOFFICE share document request rejected - OnlyOffice not enabled")
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    share, item = _get_public_share_context(token)
    if not share or not item:
        logging.warning(f"ONLYOFFICE share document access denied - Invalid share token: {token[:8]}...")
        return jsonify({'error': 'Invalid share token'}), 403

    if share.resource_type == 'folder':
        file = _resolve_shared_file(item, file_id)
        if not file:
            return jsonify({'error': 'File not found in share'}), 404
    else:
        # Direkt freigegebene Datei
        if item.id != file_id:
            logging.warning(f"ONLYOFFICE share document access denied - File ID mismatch: expected {item.id}, got {file_id}")
            return jsonify({'error': 'File ID mismatch'}), 403
        file = item
    
    logging.info(f"ONLYOFFICE share document access granted - file_id: {file_id}, file: {file.original_name}")
    
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
        from app.utils.access_control import guest_has_file_access
        if not guest_has_file_access(current_user, file):
            return jsonify({'success': False, 'error': 'Kein Zugriff'}), 403

    payload = request.get_json(silent=True) or {}
    return _onlyoffice_forcesave_response(payload.get('key'))


@files_bp.route('/share/<token>/api/onlyoffice-forcesave/<int:file_id>', methods=['POST'])
def share_onlyoffice_forcesave(token, file_id):
    """Force-save an open OnlyOffice document for a share guest."""
    item, guest_name, _share = _check_share_access(token)
    if not item or not guest_name:
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
def onlyoffice_save(file_id):
    """Save document from ONLYOFFICE."""
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    file = File.query.get_or_404(file_id)
    
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
    filename = f"{timestamp}_{file.original_name}"
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
    
    item, guest_name, _share = _check_share_access(token)
    if not item or not guest_name:
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
    filename = f"{timestamp}_{file.original_name}"
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
    filename = f"{timestamp}_{file.original_name}"
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
        logging.info(f"ONLYOFFICE callback received - status: {status}, key: {key}")

        if status in (2, 6):
            file_id = request.args.get('file_id')
            if file_id:
                try:
                    file_id = int(file_id)
                    file = File.query.get(file_id)
                    if file:
                        _onlyoffice_handle_save_callback(file, data)
                except (ValueError, TypeError) as e:
                    logging.error(f"ONLYOFFICE callback: Invalid file_id: {e}")
                except Exception as e:
                    logging.error(f"ONLYOFFICE callback: Error saving file: {e}")
            else:
                logging.warning("ONLYOFFICE callback: No file_id provided in callback URL")

        return _onlyoffice_cors_response({'error': 0})[0]
    except Exception as e:
        logging.error(f"ONLYOFFICE callback error: {e}")
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
        logging.warning(f"ONLYOFFICE share callback: Invalid share token: {token}")
        return jsonify({'error': 'Invalid share token'}), 403

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

        status = data.get('status')
        
        logging.info(f"ONLYOFFICE share callback received - status: {status}")

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
                    filename = f"{timestamp}_{file.original_name}"
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



