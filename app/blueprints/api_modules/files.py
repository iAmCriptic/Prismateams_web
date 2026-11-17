import os
import secrets
from datetime import datetime

from flask import jsonify, request, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.blueprints.files.helpers import _disk_safe_upload_basename
from app.models.file import File, FileVersion, Folder
from app.models.settings import SystemSettings
from app.utils.access_control import (
    guest_has_file_access,
    guest_has_folder_access,
    has_module_access,
)
from app.utils.common import format_datetime
from app.utils.private_files import (
    can_edit_file,
    can_edit_folder,
    can_view_file,
    can_view_folder,
    sanitize_files_item_name,
)
from werkzeug.security import generate_password_hash


EDITABLE_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".xml", ".csv", ".log"}


def _files_access_denied_response():
    return jsonify({"success": False, "error": "Kein Zugriff auf Dateien-Modul"}), 403


def _check_files_access():
    return has_module_access(current_user, "module_files")


def _is_guest():
    return bool(getattr(current_user, "is_guest", False))


def _ensure_not_guest_for_write():
    if _is_guest():
        return jsonify({"success": False, "error": "Gast-Accounts dürfen diese Aktion nicht ausführen"}), 403
    return None


def _ensure_can_view_file(file_obj):
    if getattr(file_obj, "deleted_at", None) is not None:
        return jsonify({"success": False, "error": "Datei nicht gefunden"}), 404
    if _is_guest():
        if not guest_has_file_access(current_user, file_obj):
            return jsonify({"success": False, "error": "Kein Zugriff auf diese Datei"}), 403
        return None
    if not can_view_file(file_obj, current_user):
        return jsonify({"success": False, "error": "Kein Zugriff auf diese Datei"}), 403
    return None


def _ensure_can_edit_file(file_obj):
    guest_error = _ensure_not_guest_for_write()
    if guest_error:
        return guest_error
    if getattr(file_obj, "deleted_at", None) is not None:
        return jsonify({"success": False, "error": "Datei nicht gefunden"}), 404
    if not can_edit_file(file_obj, current_user):
        return jsonify({"success": False, "error": "Keine Bearbeitungsberechtigung für diese Datei"}), 403
    return None


def _ensure_can_edit_folder(folder, *, allow_root=False):
    guest_error = _ensure_not_guest_for_write()
    if guest_error:
        return guest_error
    if getattr(folder, "deleted_at", None) is not None:
        return jsonify({"success": False, "error": "Ordner nicht gefunden"}), 404
    if not allow_root and (
        getattr(folder, "is_personal_root", False) or getattr(folder, "is_team_root", False)
    ):
        return jsonify({"success": False, "error": "Stammordner können nicht geändert oder gelöscht werden"}), 403
    if not can_edit_folder(folder, current_user):
        return jsonify({"success": False, "error": "Keine Bearbeitungsberechtigung für diesen Ordner"}), 403
    return None


def _resolve_path(path_value):
    return path_value if os.path.isabs(path_value) else os.path.join(os.getcwd(), path_value)


def _file_type_from_extension(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".md":
        return "Markdown"
    if ext == ".txt":
        return "Text"
    if ext == ".pdf":
        return "PDF"
    if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        return "Bild"
    return "Datei"


def _is_folder_descendant(candidate_folder, ancestor_folder_id):
    current = candidate_folder
    while current:
        if current.id == ancestor_folder_id:
            return True
        current = current.parent
    return False


def _is_sharing_enabled():
    setting = SystemSettings.query.filter_by(key="files_sharing_enabled").first()
    return bool(setting and str(setting.value).lower() == "true")


from app.utils.public_share import (
    create_share_link,
    disable_share_link,
    is_resource_shared,
    normalize_share_mode,
    serialize_share_settings,
    upsert_share_link,
)


def _generate_unique_dropbox_token():
    token = secrets.token_urlsafe(32)
    while Folder.query.filter_by(dropbox_token=token).first():
        token = secrets.token_urlsafe(32)
    return token


def _remove_file_from_storage(file_obj):
    file_path = _resolve_path(file_obj.file_path)
    if os.path.exists(file_path):
        os.remove(file_path)
    for version in file_obj.versions:
        version_path = _resolve_path(version.file_path)
        if os.path.exists(version_path):
            os.remove(version_path)
    try:
        from app.utils.file_thumbnails import purge_thumbnails_for_file
        purge_thumbnails_for_file(file_obj.id)
    except Exception:
        pass
    try:
        from app.utils.files_trash_retention import _delete_shares_and_acls
        _delete_shares_and_acls("file", file_obj.id)
    except Exception:
        pass


def _delete_folder_recursive(folder):
    for file_obj in list(folder.files):
        _remove_file_from_storage(file_obj)
        db.session.delete(file_obj)
    for subfolder in list(folder.subfolders):
        _delete_folder_recursive(subfolder)
    try:
        from app.utils.files_trash_retention import _delete_shares_and_acls
        _delete_shares_and_acls("folder", folder.id)
    except Exception:
        pass
    db.session.delete(folder)


def get_files():
    if not _check_files_access():
        return _files_access_denied_response()
    folder_id = request.args.get("folder_id", type=int)
    files = File.query.filter_by(folder_id=folder_id, is_current=True).filter(File.deleted_at.is_(None)).order_by(File.name).all()
    if _is_guest():
        files = [file for file in files if guest_has_file_access(current_user, file)]
    else:
        files = [file for file in files if can_view_file(file, current_user)]
    return jsonify([{
        "id": file.id,
        "name": file.name,
        "size": file.file_size,
        "mime_type": file.mime_type,
        "version": file.version_number,
        "uploaded_by": file.uploader.full_name,
        "uploaded_at": file.created_at.isoformat(),
    } for file in files])

def get_folders():
    if not _check_files_access():
        return _files_access_denied_response()
    parent_id = request.args.get("parent_id", type=int)
    folders = Folder.query.filter_by(parent_id=parent_id).filter(Folder.deleted_at.is_(None)).order_by(Folder.name).all()
    folders = [
        folder for folder in folders
        if not folder.is_personal_root
        and not getattr(folder, "is_team_root", False)
        and (guest_has_folder_access(current_user, folder) if _is_guest() else can_view_folder(folder, current_user))
    ]
    return jsonify([{
        "id": folder.id,
        "name": folder.name,
        "created_at": folder.created_at.isoformat(),
    } for folder in folders])

def get_recent_files():
    if not _check_files_access():
        return _files_access_denied_response()
    files = (
        File.query.filter_by(uploaded_by=current_user.id)
        .filter(File.deleted_at.is_(None))
        .order_by(File.updated_at.desc())
        .limit(10)
        .all()
    )
    if _is_guest():
        files = [f for f in files if guest_has_file_access(current_user, f)][:3]
    else:
        files = [f for f in files if can_view_file(f, current_user)][:3]
    return jsonify([{
        "id": file.id,
        "name": file.name,
        "original_name": file.original_name,
        "updated_at": file.updated_at.isoformat(),
        "mime_type": file.mime_type,
        "url": url_for("files.view_file", file_id=file.id),
    } for file in files])

def get_file_details(file_id):
    if not _check_files_access():
        return _files_access_denied_response()

    file_obj = File.query.get_or_404(file_id)
    access_err = _ensure_can_view_file(file_obj)
    if access_err:
        return access_err
    versions = FileVersion.query.filter_by(file_id=file_obj.id).order_by(FileVersion.version_number.desc()).all()
    file_size_str = f"{file_obj.file_size / (1024 * 1024):.1f} MB" if file_obj.file_size > 1024 * 1024 else f"{file_obj.file_size / 1024:.1f} KB"
    ext = os.path.splitext(file_obj.original_name)[1].lower()
    is_editable = ext in EDITABLE_EXTENSIONS
    is_viewable = ext in EDITABLE_EXTENSIONS
    return jsonify({
        "success": True,
        "file": {
            "id": file_obj.id,
            "name": file_obj.original_name,
            "size": file_size_str,
            "type": _file_type_from_extension(file_obj.original_name),
            "uploader": file_obj.uploader.full_name,
            "created_at": format_datetime(file_obj.created_at),
            "version": file_obj.version_number,
            "is_editable": is_editable,
            "is_viewable": is_viewable,
        },
        "versions": [{
            "id": version.id,
            "version_number": version.version_number,
            "is_current": version.version_number == file_obj.version_number,
        } for version in versions],
        "actions": {
            "download_url": url_for("api.api_download_file", file_id=file_obj.id),
            "view_url": url_for("files.view_file", file_id=file_obj.id) if is_viewable else None,
            "edit_url": url_for("files.edit_file", file_id=file_obj.id) if is_editable else None,
        },
    }), 200

def api_download_file(file_id):
    if not _check_files_access():
        return _files_access_denied_response()

    file_obj = File.query.get_or_404(file_id)
    access_err = _ensure_can_view_file(file_obj)
    if access_err:
        return access_err
    file_path = _resolve_path(file_obj.file_path)
    if not os.path.exists(file_path):
        return jsonify({"success": False, "error": "Datei nicht gefunden"}), 404

    return send_file(file_path, as_attachment=True, download_name=file_obj.original_name, mimetype=file_obj.mime_type or "application/octet-stream")

def get_file_content(file_id):
    if not _check_files_access():
        return _files_access_denied_response()

    file_obj = File.query.get_or_404(file_id)
    access_err = _ensure_can_view_file(file_obj)
    if access_err:
        return access_err
    ext = os.path.splitext(file_obj.original_name)[1].lower()
    if ext not in EDITABLE_EXTENSIONS:
        return jsonify({"success": False, "error": "Dateityp nicht editierbar"}), 400

    file_path = _resolve_path(file_obj.file_path)
    if not os.path.exists(file_path):
        return jsonify({"success": False, "error": "Datei nicht gefunden"}), 404

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({
        "success": True,
        "file": {
            "id": file_obj.id,
            "name": file_obj.name,
            "original_name": file_obj.original_name,
            "version": file_obj.version_number,
            "mime_type": file_obj.mime_type,
            "updated_at": file_obj.updated_at.isoformat() if file_obj.updated_at else None,
        },
        "content": content,
    }), 200

def update_file_content(file_id):
    if not _check_files_access():
        return _files_access_denied_response()

    file_obj = File.query.get_or_404(file_id)
    access_err = _ensure_can_edit_file(file_obj)
    if access_err:
        return access_err
    ext = os.path.splitext(file_obj.original_name)[1].lower()
    if ext not in EDITABLE_EXTENSIONS:
        return jsonify({"success": False, "error": "Dateityp nicht editierbar"}), 400

    data = request.get_json(silent=True) or {}
    content = data.get("content")
    if content is None:
        return jsonify({"success": False, "error": "content ist erforderlich"}), 400
    from app.utils.file_storage_limits import check_upload_allowed
    ok_quota, _code, quota_err = check_upload_allowed(
        current_user.id, len(str(content).encode("utf-8"))
    )
    if not ok_quota:
        return jsonify({"success": False, "error": quota_err or "Speicherkontingent überschritten"}), 400

    from app.utils import file_edit_lock as file_edit_lock_util
    from app.blueprints.files._bp import MAX_FILE_VERSIONS

    active_lock = file_edit_lock_util.get_active_lock(file_obj.id)
    if active_lock and active_lock.locked_by != current_user.id:
        return jsonify({"success": False, "error": "Datei wird gerade von einem anderen Nutzer bearbeitet"}), 409

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = _disk_safe_upload_basename(file_obj.original_name)
    filename = f"{timestamp}_{secrets.token_hex(6)}_{safe_name}"
    base_dir = os.path.abspath(os.path.join("uploads", "files"))
    absolute_path = os.path.abspath(os.path.join(base_dir, filename))
    if os.path.commonpath([base_dir, absolute_path]) != base_dir:
        return jsonify({"success": False, "error": "Ungültiger Dateipfad"}), 400
    os.makedirs(base_dir, exist_ok=True)
    with open(absolute_path, "w", encoding="utf-8") as f:
        f.write(content)

    versions = FileVersion.query.filter_by(file_id=file_obj.id).order_by(
        FileVersion.version_number.desc()
    ).all()
    if len(versions) >= MAX_FILE_VERSIONS:
        oldest = versions[-1]
        oldest_path = _resolve_path(oldest.file_path)
        if os.path.exists(oldest_path):
            os.remove(oldest_path)
        db.session.delete(oldest)

    # version snapshot
    db.session.add(FileVersion(
        file_id=file_obj.id,
        version_number=file_obj.version_number,
        file_path=file_obj.file_path,
        file_size=file_obj.file_size,
        uploaded_by=file_obj.uploaded_by,
    ))

    file_obj.file_path = absolute_path
    file_obj.file_size = os.path.getsize(absolute_path)
    file_obj.version_number += 1
    file_obj.uploaded_by = current_user.id
    file_obj.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "success": True,
        "file": {
            "id": file_obj.id,
            "version": file_obj.version_number,
            "updated_at": file_obj.updated_at.isoformat(),
        },
    }), 200

def api_rename_file(file_id):
    if not _check_files_access():
        return _files_access_denied_response()
    file_obj = File.query.get_or_404(file_id)
    access_err = _ensure_can_edit_file(file_obj)
    if access_err:
        return access_err

    data = request.get_json(silent=True) or {}
    new_name = sanitize_files_item_name(data.get("new_name"))
    if not new_name:
        return jsonify({"success": False, "error": "Ungültiger Dateiname"}), 400

    existing = (
        File.query.filter_by(name=new_name, folder_id=file_obj.folder_id, is_current=True)
        .filter(File.deleted_at.is_(None))
        .first()
    )
    if existing and existing.id != file_obj.id:
        return jsonify({"success": False, "error": "Dateiname existiert bereits im Zielordner"}), 409

    file_obj.name = new_name
    db.session.commit()
    return jsonify({"success": True, "file": {"id": file_obj.id, "name": file_obj.name}})

def api_rename_folder(folder_id):
    if not _check_files_access():
        return _files_access_denied_response()
    folder = Folder.query.get_or_404(folder_id)
    access_err = _ensure_can_edit_folder(folder)
    if access_err:
        return access_err

    data = request.get_json(silent=True) or {}
    new_name = sanitize_files_item_name(data.get("new_name"))
    if not new_name:
        return jsonify({"success": False, "error": "Ungültiger Ordnername"}), 400

    folder.name = new_name
    db.session.commit()
    return jsonify({"success": True, "folder": {"id": folder.id, "name": folder.name}})

def api_move_item():
    if not _check_files_access():
        return _files_access_denied_response()
    guest_error = _ensure_not_guest_for_write()
    if guest_error:
        return guest_error

    payload = request.get_json(silent=True) or {}
    item_type = (payload.get("item_type") or "").strip().lower()
    item_id = payload.get("item_id")
    target_folder_id = payload.get("target_folder_id")

    if item_type not in {"file", "folder"}:
        return jsonify({"success": False, "error": "item_type muss file oder folder sein"}), 400
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Ungültige item_id"}), 400

    if target_folder_id in (None, "", "null"):
        target_folder_id = None
        target_folder = None
    else:
        try:
            target_folder_id = int(target_folder_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Ungültige target_folder_id"}), 400
        target_folder = Folder.query.get(target_folder_id)
        if not target_folder or getattr(target_folder, "deleted_at", None) is not None:
            return jsonify({"success": False, "error": "Zielordner nicht gefunden"}), 404
        if not can_edit_folder(target_folder, current_user):
            return jsonify({"success": False, "error": "Keine Berechtigung für Zielordner"}), 403

    if item_type == "file":
        file_obj = File.query.get(item_id)
        if not file_obj or not file_obj.is_current or getattr(file_obj, "deleted_at", None) is not None:
            return jsonify({"success": False, "error": "Datei nicht gefunden"}), 404
        if not can_edit_file(file_obj, current_user):
            return jsonify({"success": False, "error": "Keine Bearbeitungsberechtigung für diese Datei"}), 403
        if file_obj.folder_id == target_folder_id:
            return jsonify({"success": True, "no_change": True}), 200
        conflict = File.query.filter(
            File.id != file_obj.id,
            File.name == file_obj.name,
            File.folder_id.is_(target_folder_id) if target_folder_id is None else File.folder_id == target_folder_id,
            File.is_current == True,
            File.deleted_at.is_(None),
        ).first()
        if conflict:
            return jsonify({"success": False, "error": "Namenskonflikt im Zielordner"}), 409
        file_obj.folder_id = target_folder_id
        from app.utils.private_files import resolve_space_for_parent, resolve_team_id_for_parent
        file_obj.space = resolve_space_for_parent(target_folder, file_obj.space or "public")
        file_obj.team_id = resolve_team_id_for_parent(target_folder, file_obj.space, getattr(target_folder, "team_id", None))
        db.session.commit()
        return jsonify({"success": True}), 200

    folder = Folder.query.get(item_id)
    if not folder or getattr(folder, "deleted_at", None) is not None:
        return jsonify({"success": False, "error": "Ordner nicht gefunden"}), 404
    access_err = _ensure_can_edit_folder(folder)
    if access_err:
        return access_err
    if folder.id == target_folder_id:
        return jsonify({"success": False, "error": "Ungültige Zielstruktur"}), 400
    if target_folder and _is_folder_descendant(target_folder, folder.id):
        return jsonify({"success": False, "error": "Ordner kann nicht in Unterordner verschoben werden"}), 400
    if folder.parent_id == target_folder_id:
        return jsonify({"success": True, "no_change": True}), 200

    folder.parent_id = target_folder_id
    from app.utils.private_files import apply_space_to_folder_tree, resolve_space_for_parent, resolve_team_id_for_parent
    target_space = resolve_space_for_parent(target_folder, folder.space or "public")
    target_team_id = resolve_team_id_for_parent(target_folder, target_space, getattr(target_folder, "team_id", None))
    apply_space_to_folder_tree(folder, target_space, target_team_id)
    db.session.commit()
    return jsonify({"success": True}), 200

def api_delete_file(file_id):
    if not _check_files_access():
        return _files_access_denied_response()

    file_obj = File.query.get_or_404(file_id)
    access_err = _ensure_can_edit_file(file_obj)
    if access_err:
        return access_err
    _remove_file_from_storage(file_obj)
    db.session.delete(file_obj)
    db.session.commit()
    return jsonify({"success": True}), 200

def api_delete_folder(folder_id):
    if not _check_files_access():
        return _files_access_denied_response()

    folder = Folder.query.get_or_404(folder_id)
    access_err = _ensure_can_edit_folder(folder)
    if access_err:
        return access_err
    _delete_folder_recursive(folder)
    db.session.commit()
    return jsonify({"success": True}), 200

def api_create_file_share(file_id):
    if not _check_files_access():
        return _files_access_denied_response()
    if not _is_sharing_enabled():
        return jsonify({"success": False, "error": "Freigaben sind deaktiviert"}), 403

    file_obj = File.query.get_or_404(file_id)
    access_err = _ensure_can_edit_file(file_obj)
    if access_err:
        return access_err

    data = request.get_json(silent=True) or {}
    modes = data.get("share_modes") or [data.get("share_mode") or "edit"]
    if isinstance(modes, str):
        modes = [modes]
    modes = list(dict.fromkeys(normalize_share_mode(m) for m in modes if m))
    if not modes:
        return jsonify({"success": False, "error": "Mindestens ein Link-Typ erforderlich"}), 400
    links = []
    for mode in modes:
        if mode == "dropbox":
            continue
        passwords = data.get(f"password_{mode}") or data.get("password") or ""
        expires = data.get(f"expires_at_{mode}") or data.get("expires_at") or ""
        label = data.get(f"label_{mode}") or data.get("label") or ""
        share = create_share_link(
            "file",
            file_obj,
            mode,
            created_by=current_user.id,
            password=passwords,
            expires_at_raw=expires,
            label=label,
        )
        links.append({"id": share.id, "mode": mode, "share_url": url_for("files.public_share", token=share.token, _external=True)})
    db.session.commit()
    return jsonify({"success": True, "links": links}), 200

def api_create_folder_share(folder_id):
    if not _check_files_access():
        return _files_access_denied_response()
    if not _is_sharing_enabled():
        return jsonify({"success": False, "error": "Freigaben sind deaktiviert"}), 403

    folder = Folder.query.get_or_404(folder_id)
    access_err = _ensure_can_edit_folder(folder)
    if access_err:
        return access_err

    data = request.get_json(silent=True) or {}
    modes = data.get("share_modes") or [data.get("share_mode") or "edit"]
    if isinstance(modes, str):
        modes = [modes]
    modes = list(dict.fromkeys(normalize_share_mode(m) for m in modes if m))
    if not modes:
        return jsonify({"success": False, "error": "Mindestens ein Link-Typ erforderlich"}), 400
    links = []
    for mode in modes:
        passwords = data.get(f"password_{mode}") or data.get("password") or ""
        expires = data.get(f"expires_at_{mode}") or data.get("expires_at") or ""
        label = data.get(f"label_{mode}") or data.get("label") or ""
        share = create_share_link(
            "folder",
            folder,
            mode,
            created_by=current_user.id,
            password=passwords,
            expires_at_raw=expires,
            label=label,
        )
        from app.utils.public_share import share_url
        links.append({"id": share.id, "mode": mode, "share_url": share_url(share)})
    db.session.commit()
    return jsonify({"success": True, "links": links}), 200

def api_get_file_share_settings(file_id):
    if not _check_files_access():
        return _files_access_denied_response()
    file_obj = File.query.get_or_404(file_id)
    access_err = _ensure_can_edit_file(file_obj)
    if access_err:
        return access_err
    return jsonify({"success": True, "item": serialize_share_settings("file", file_obj.id, file_obj.name, dropbox_enabled=False)}), 200

def api_get_folder_share_settings(folder_id):
    if not _check_files_access():
        return _files_access_denied_response()
    folder = Folder.query.get_or_404(folder_id)
    access_err = _ensure_can_edit_folder(folder)
    if access_err:
        return access_err
    dropbox_setting = SystemSettings.query.filter_by(key="files_dropbox_enabled").first()
    dropbox_enabled = (dropbox_setting and str(dropbox_setting.value).lower() == "true") or False
    return jsonify({"success": True, "item": serialize_share_settings("folder", folder.id, folder.name, dropbox_enabled=dropbox_enabled)}), 200

def api_update_file_share(file_id):
    if not _check_files_access():
        return _files_access_denied_response()

    from app.models.public_share import PublicShare
    from app.utils.public_share import get_share_for_mode, sync_legacy_share_flags

    file_obj = File.query.get_or_404(file_id)
    access_err = _ensure_can_edit_file(file_obj)
    if access_err:
        return access_err
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    if action == "disable_all":
        for share in PublicShare.query.filter_by(resource_type="file", resource_id=file_obj.id).all():
            share.enabled = False
        sync_legacy_share_flags("file", file_obj)
    elif action in ("disable_view", "disable_edit"):
        disable_share_link("file", file_obj, "view" if action == "disable_view" else "edit")
    else:
        for mode in ("view", "edit"):
            if data.get(f"update_{mode}") or data.get("share_mode") == mode:
                upsert_share_link(
                    "file",
                    file_obj,
                    mode,
                    created_by=current_user.id,
                    password=data.get(f"password_{mode}") or data.get("password") or "",
                    expires_at_raw=data.get(f"expires_at_{mode}") or data.get("expires_at") or "",
                )
    db.session.commit()
    return jsonify({"success": True}), 200

def api_update_folder_share(folder_id):
    if not _check_files_access():
        return _files_access_denied_response()

    from app.models.public_share import PublicShare
    from app.utils.public_share import sync_legacy_share_flags

    folder = Folder.query.get_or_404(folder_id)
    access_err = _ensure_can_edit_folder(folder)
    if access_err:
        return access_err
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    if action == "disable_all":
        for share in PublicShare.query.filter_by(resource_type="folder", resource_id=folder.id).all():
            share.enabled = False
        sync_legacy_share_flags("folder", folder)
    elif action in ("disable_view", "disable_edit"):
        disable_share_link("folder", folder, "view" if action == "disable_view" else "edit")
    else:
        for mode in ("view", "edit"):
            if data.get(f"update_{mode}") or data.get("share_mode") == mode:
                upsert_share_link(
                    "folder",
                    folder,
                    mode,
                    created_by=current_user.id,
                    password=data.get(f"password_{mode}") or data.get("password") or "",
                    expires_at_raw=data.get(f"expires_at_{mode}") or data.get("expires_at") or "",
                )
    db.session.commit()
    return jsonify({"success": True}), 200

def api_enable_dropbox(folder_id):
    if not _check_files_access():
        return _files_access_denied_response()

    folder = Folder.query.get_or_404(folder_id)
    access_err = _ensure_can_edit_folder(folder)
    if access_err:
        return access_err
    share = create_share_link(
        "folder",
        folder,
        "dropbox",
        created_by=current_user.id,
        label="Briefkasten",
    )
    db.session.commit()
    return jsonify({
        "success": True,
        "dropbox_url": url_for("files.dropbox_upload", token=share.token, _external=True),
    }), 200

def api_get_dropbox_settings(folder_id):
    if not _check_files_access():
        return _files_access_denied_response()

    folder = Folder.query.get_or_404(folder_id)
    access_err = _ensure_can_edit_folder(folder)
    if access_err:
        return access_err
    from app.utils.public_share import get_share_for_mode
    share = get_share_for_mode("folder", folder.id, "dropbox")
    active_token = (share.token if share else None) or folder.dropbox_token
    if not folder.is_dropbox or not active_token:
        return jsonify({"success": False, "error": "Briefkasten ist nicht aktiv"}), 404
    has_pw = (share.password_hash is not None) if share else (folder.dropbox_password_hash is not None)
    return jsonify({
        "success": True,
        "folder": {
            "id": folder.id,
            "name": folder.name,
            "dropbox_url": url_for("files.dropbox_upload", token=active_token, _external=True),
            "has_password": has_pw,
        },
    }), 200

def api_update_dropbox_settings(folder_id):
    if not _check_files_access():
        return _files_access_denied_response()

    folder = Folder.query.get_or_404(folder_id)
    access_err = _ensure_can_edit_folder(folder)
    if access_err:
        return access_err
    if not folder.is_dropbox:
        return jsonify({"success": False, "error": "Briefkasten ist nicht aktiv"}), 404

    from app.utils.public_share import apply_dropbox_settings_action, get_share_for_mode

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    ok, err_msg = apply_dropbox_settings_action(
        folder,
        action,
        password=data.get("password") or "",
    )
    if not ok:
        return jsonify({"success": False, "error": err_msg or "Ungültige Aktion"}), 400

    db.session.commit()
    share = get_share_for_mode("folder", folder.id, "dropbox")
    active_token = (share.token if share else None) or folder.dropbox_token
    has_pw = (share.password_hash is not None) if share else (folder.dropbox_password_hash is not None)
    return jsonify({
        "success": True,
        "dropbox_url": url_for("files.dropbox_upload", token=active_token, _external=True),
        "has_password": has_pw,
    }), 200

def api_disable_dropbox(folder_id):
    if not _check_files_access():
        return _files_access_denied_response()

    folder = Folder.query.get_or_404(folder_id)
    access_err = _ensure_can_edit_folder(folder)
    if access_err:
        return access_err
    from app.utils.public_share import disable_dropbox_shares
    disable_dropbox_shares(folder)
    db.session.commit()
    return jsonify({"success": True}), 200

def register_files_routes(api_bp, require_api_auth):
    """Bind module-level views onto the API blueprint."""
    def _bind(rule, view, methods, auth):
        api_bp.add_url_rule(rule, view.__name__, auth(view), methods=methods)

    _bind('/files', get_files, ['GET'], require_api_auth)
    _bind('/folders', get_folders, ['GET'], require_api_auth)
    _bind('/files/recent', get_recent_files, ['GET'], require_api_auth)
    _bind('/files/<int:file_id>/details', get_file_details, ['GET'], require_api_auth)
    _bind('/files/<int:file_id>/download', api_download_file, ['GET'], require_api_auth)
    _bind('/files/<int:file_id>/content', get_file_content, ['GET'], require_api_auth)
    _bind('/files/<int:file_id>/content', update_file_content, ['PUT'], require_api_auth)
    _bind('/files/<int:file_id>/rename', api_rename_file, ['POST'], require_api_auth)
    _bind('/folders/<int:folder_id>/rename', api_rename_folder, ['POST'], require_api_auth)
    _bind('/files/move', api_move_item, ['POST'], require_api_auth)
    _bind('/files/<int:file_id>', api_delete_file, ['DELETE'], require_api_auth)
    _bind('/folders/<int:folder_id>', api_delete_folder, ['DELETE'], require_api_auth)
    _bind('/files/<int:file_id>/share', api_create_file_share, ['POST'], require_api_auth)
    _bind('/folders/<int:folder_id>/share', api_create_folder_share, ['POST'], require_api_auth)
    _bind('/files/<int:file_id>/share-settings', api_get_file_share_settings, ['GET'], require_api_auth)
    _bind('/folders/<int:folder_id>/share-settings', api_get_folder_share_settings, ['GET'], require_api_auth)
    _bind('/files/<int:file_id>/share-settings', api_update_file_share, ['POST'], require_api_auth)
    _bind('/folders/<int:folder_id>/share-settings', api_update_folder_share, ['POST'], require_api_auth)
    _bind('/folders/<int:folder_id>/dropbox/enable', api_enable_dropbox, ['POST'], require_api_auth)
    _bind('/folders/<int:folder_id>/dropbox', api_get_dropbox_settings, ['GET'], require_api_auth)
    _bind('/folders/<int:folder_id>/dropbox', api_update_dropbox_settings, ['POST'], require_api_auth)
    _bind('/folders/<int:folder_id>/dropbox/disable', api_disable_dropbox, ['POST'], require_api_auth)
