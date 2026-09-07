"""Shared helpers for the files module."""

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
)

def _paginate_browse_items(subfolders, files, offset=0, limit=FILES_BROWSE_PAGE_SIZE):
    """Folders first, then files — slice for lazy loading."""
    folders = list(subfolders or [])
    file_list = list(files or [])
    combined = [('folder', f) for f in folders] + [('file', f) for f in file_list]
    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or FILES_BROWSE_PAGE_SIZE))
    window = combined[offset:offset + limit]
    out_folders = [item for kind, item in window if kind == 'folder']
    out_files = [item for kind, item in window if kind == 'file']
    has_more = (offset + limit) < len(combined)
    return out_folders, out_files, has_more, len(combined)

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


def _safe_referrer_or(fallback_url):
    """
    Redirect-Ziel nur bei internem/same-origin Referer, sonst Fallback.

    Verhindert Open-Redirect über manipulierten Referer-Header.
    """
    from urllib.parse import urlparse

    ref = (request.referrer or '').strip()
    if not ref:
        return fallback_url

    parsed = urlparse(ref)
    # Relative interne Pfade
    if not parsed.scheme and not parsed.netloc:
        if ref.startswith('/') and not ref.startswith('//'):
            return ref
        return fallback_url

    # Absolute URL nur bei gleicher Origin
    if parsed.scheme in {'http', 'https'} and (parsed.netloc or '').lower() == (request.host or '').lower():
        path = parsed.path or '/'
        query = f'?{parsed.query}' if parsed.query else ''
        return f'{path}{query}'

    return fallback_url


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
    return _response_with_nosniff(send_file(
        file_path,
        mimetype=media_mimetype(file_ext),
        as_attachment=False,
        conditional=True,
    ))


def _response_with_nosniff(response):
    """Verhindert MIME-Sniffing bei Downloads/Inline-Auslieferung."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


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
    if not is_allowed_upload_filename(existing_file.name):
        raise ValueError('disallowed_extension')

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
    safe_name = _disk_safe_upload_basename(existing_file.name or existing_file.original_name)
    filename = f"{timestamp}_{safe_name}"
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

def _disk_safe_upload_basename(original_name: str) -> str:
    """Basename + secure_filename für Disk-Pfade (kein Path Traversal)."""
    raw = (original_name or '').replace('\\', '/').split('/')[-1].strip()
    safe = secure_filename(raw)
    if not safe or safe in {'.', '..'}:
        safe = 'file'
    return safe


def _process_file_upload(file, original_name, folder_id, user_id, space='public', team_id=None):
    """Helper function to process a single file upload."""
    if not is_allowed_upload_filename(original_name):
        raise ValueError('disallowed_extension')

    display_name = (original_name or '').replace('\\', '/').split('/')[-1].strip() or 'file'
    safe_name = _disk_safe_upload_basename(display_name)
    if not is_allowed_upload_filename(safe_name):
        raise ValueError('disallowed_extension')

    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"{timestamp}_{safe_name}"
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
        name=display_name,
        original_name=display_name,
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


__all__ = [
    '_paginate_browse_items',
    '_safe_referrer_or',
    'media_kind',
    'media_mimetype',
    '_file_extension',
    '_mimetype_for_extension',
    '_send_inline_media',
    '_response_with_nosniff',
    '_split_filename_parts',
    '_generate_unique_filename_in_folder',
    '_create_new_file_version',
    '_resolve_absolute_file_path',
    '_normalize_preview_text',
    '_extract_preview_from_zip_xml',
    'build_file_preview_text',
    'build_markdown_preview_html',
    '_is_markdown_extension',
    '_render_view_content',
    '_normalize_share_mode',
    '_parse_share_expires',
    '_share_bot_session_key',
    '_validate_share_edit_bot',
    '_mailbox_bot_session_key',
    '_mailbox_bot_template_context',
    '_validate_mailbox_bot',
    '_get_public_share_context',
    '_upsert_public_share',
    '_disable_public_share',
    '_is_guest_user',
    '_get_guest_accessible_folder_ids',
    '_get_safe_folder_url',
    '_files_view_kwargs',
    '_request_team_id',
    '_resolve_create_parent',
    '_files_context_url',
    '_redirect_to_files_context',
    '_get_safe_file_back_url',
    '_disk_safe_upload_basename',
    '_process_file_upload',
    '_is_sharing_enabled',
    '_is_dropbox_enabled',
    '_dropbox_password_hash',
    '_check_share_access',
    '_is_descendant_folder',
    '_resolve_shared_file',
    '_build_public_share_breadcrumb',
    '_build_share_gate_preview_context',
]
