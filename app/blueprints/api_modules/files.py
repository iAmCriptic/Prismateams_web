import os
import secrets
from datetime import datetime

from flask import jsonify, request, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.models.file import File, FileVersion, Folder
from app.models.settings import SystemSettings
from app.utils.access_control import has_module_access
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


def _generate_unique_share_token():
    token = secrets.token_urlsafe(32)
    while File.query.filter_by(share_token=token).first() or Folder.query.filter_by(share_token=token).first():
        token = secrets.token_urlsafe(32)
    return token


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


def _delete_folder_recursive(folder):
    for file_obj in list(folder.files):
        _remove_file_from_storage(file_obj)
        db.session.delete(file_obj)
    for subfolder in list(folder.subfolders):
        _delete_folder_recursive(subfolder)
    db.session.delete(folder)


def register_files_routes(api_bp, require_api_auth):
    @api_bp.route("/files", methods=["GET"])
    @login_required
    def get_files():
        folder_id = request.args.get("folder_id", type=int)
        files = File.query.filter_by(folder_id=folder_id, is_current=True).order_by(File.name).all()
        return jsonify([{
            "id": file.id,
            "name": file.name,
            "size": file.file_size,
            "mime_type": file.mime_type,
            "version": file.version_number,
            "uploaded_by": file.uploader.full_name,
            "uploaded_at": file.created_at.isoformat(),
        } for file in files])

    @api_bp.route("/folders", methods=["GET"])
    @login_required
    def get_folders():
        parent_id = request.args.get("parent_id", type=int)
        folders = Folder.query.filter_by(parent_id=parent_id).order_by(Folder.name).all()
        return jsonify([{
            "id": folder.id,
            "name": folder.name,
            "created_at": folder.created_at.isoformat(),
        } for folder in folders])

    @api_bp.route("/files/recent", methods=["GET"])
    @require_api_auth
    def get_recent_files():
        files = File.query.filter_by(uploaded_by=current_user.id).order_by(File.updated_at.desc()).limit(3).all()
        return jsonify([{
            "id": file.id,
            "name": file.name,
            "original_name": file.original_name,
            "updated_at": file.updated_at.isoformat(),
            "mime_type": file.mime_type,
            "url": url_for("files.view_file", file_id=file.id),
        } for file in files])

    @api_bp.route("/files/<int:file_id>/details", methods=["GET"])
    @require_api_auth
    def get_file_details(file_id):
        if not _check_files_access():
            return _files_access_denied_response()

        file_obj = File.query.get_or_404(file_id)
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
                "created_at": file_obj.created_at.strftime("%d.%m.%Y %H:%M"),
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

    @api_bp.route("/files/<int:file_id>/download", methods=["GET"])
    @require_api_auth
    def api_download_file(file_id):
        if not _check_files_access():
            return _files_access_denied_response()

        file_obj = File.query.get_or_404(file_id)
        file_path = _resolve_path(file_obj.file_path)
        if not os.path.exists(file_path):
            return jsonify({"success": False, "error": "Datei nicht gefunden"}), 404

        return send_file(file_path, as_attachment=True, download_name=file_obj.original_name, mimetype=file_obj.mime_type or "application/octet-stream")

    @api_bp.route("/files/<int:file_id>/content", methods=["GET"])
    @require_api_auth
    def get_file_content(file_id):
        if not _check_files_access():
            return _files_access_denied_response()

        file_obj = File.query.get_or_404(file_id)
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

    @api_bp.route("/files/<int:file_id>/content", methods=["PUT"])
    @require_api_auth
    def update_file_content(file_id):
        if not _check_files_access():
            return _files_access_denied_response()
        guest_error = _ensure_not_guest_for_write()
        if guest_error:
            return guest_error

        file_obj = File.query.get_or_404(file_id)
        ext = os.path.splitext(file_obj.original_name)[1].lower()
        if ext not in EDITABLE_EXTENSIONS:
            return jsonify({"success": False, "error": "Dateityp nicht editierbar"}), 400

        data = request.get_json(silent=True) or {}
        content = data.get("content")
        if content is None:
            return jsonify({"success": False, "error": "content ist erforderlich"}), 400

        # version snapshot
        db.session.add(FileVersion(
            file_id=file_obj.id,
            version_number=file_obj.version_number,
            file_path=file_obj.file_path,
            file_size=file_obj.file_size,
            uploaded_by=file_obj.uploaded_by,
        ))

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{file_obj.original_name}"
        relative_path = os.path.join("uploads", "files", filename)
        absolute_path = os.path.abspath(relative_path)
        os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
        with open(absolute_path, "w", encoding="utf-8") as f:
            f.write(content)

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

    @api_bp.route("/files/<int:file_id>/rename", methods=["POST"])
    @require_api_auth
    def api_rename_file(file_id):
        data = request.get_json(silent=True) or {}
        new_name = (data.get("new_name") or "").strip()
        if not new_name or "/" in new_name or "\\" in new_name:
            return jsonify({"success": False, "error": "Ungültiger Dateiname"}), 400

        file_obj = File.query.get_or_404(file_id)
        existing = File.query.filter_by(name=new_name, folder_id=file_obj.folder_id, is_current=True).first()
        if existing and existing.id != file_obj.id:
            return jsonify({"success": False, "error": "Dateiname existiert bereits im Zielordner"}), 409

        file_obj.name = new_name
        db.session.commit()
        return jsonify({"success": True, "file": {"id": file_obj.id, "name": file_obj.name}})

    @api_bp.route("/folders/<int:folder_id>/rename", methods=["POST"])
    @require_api_auth
    def api_rename_folder(folder_id):
        data = request.get_json(silent=True) or {}
        new_name = (data.get("new_name") or "").strip()
        if not new_name or "/" in new_name or "\\" in new_name:
            return jsonify({"success": False, "error": "Ungültiger Ordnername"}), 400

        folder = Folder.query.get_or_404(folder_id)
        folder.name = new_name
        db.session.commit()
        return jsonify({"success": True, "folder": {"id": folder.id, "name": folder.name}})

    @api_bp.route("/files/move", methods=["POST"])
    @require_api_auth
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
            if not target_folder:
                return jsonify({"success": False, "error": "Zielordner nicht gefunden"}), 404

        if item_type == "file":
            file_obj = File.query.get(item_id)
            if not file_obj or not file_obj.is_current:
                return jsonify({"success": False, "error": "Datei nicht gefunden"}), 404
            if file_obj.folder_id == target_folder_id:
                return jsonify({"success": True, "no_change": True}), 200
            conflict = File.query.filter(
                File.id != file_obj.id,
                File.name == file_obj.name,
                File.folder_id.is_(target_folder_id) if target_folder_id is None else File.folder_id == target_folder_id,
                File.is_current == True,
            ).first()
            if conflict:
                return jsonify({"success": False, "error": "Namenskonflikt im Zielordner"}), 409
            file_obj.folder_id = target_folder_id
            db.session.commit()
            return jsonify({"success": True}), 200

        folder = Folder.query.get(item_id)
        if not folder:
            return jsonify({"success": False, "error": "Ordner nicht gefunden"}), 404
        if folder.id == target_folder_id:
            return jsonify({"success": False, "error": "Ungültige Zielstruktur"}), 400
        if target_folder and _is_folder_descendant(target_folder, folder.id):
            return jsonify({"success": False, "error": "Ordner kann nicht in Unterordner verschoben werden"}), 400
        if folder.parent_id == target_folder_id:
            return jsonify({"success": True, "no_change": True}), 200

        folder.parent_id = target_folder_id
        db.session.commit()
        return jsonify({"success": True}), 200

    @api_bp.route("/files/<int:file_id>", methods=["DELETE"])
    @require_api_auth
    def api_delete_file(file_id):
        if not _check_files_access():
            return _files_access_denied_response()
        guest_error = _ensure_not_guest_for_write()
        if guest_error:
            return guest_error

        file_obj = File.query.get_or_404(file_id)
        _remove_file_from_storage(file_obj)
        db.session.delete(file_obj)
        db.session.commit()
        return jsonify({"success": True}), 200

    @api_bp.route("/folders/<int:folder_id>", methods=["DELETE"])
    @require_api_auth
    def api_delete_folder(folder_id):
        if not _check_files_access():
            return _files_access_denied_response()
        guest_error = _ensure_not_guest_for_write()
        if guest_error:
            return guest_error

        folder = Folder.query.get_or_404(folder_id)
        _delete_folder_recursive(folder)
        db.session.commit()
        return jsonify({"success": True}), 200

    @api_bp.route("/files/<int:file_id>/share", methods=["POST"])
    @require_api_auth
    def api_create_file_share(file_id):
        if not _check_files_access():
            return _files_access_denied_response()
        if not _is_sharing_enabled():
            return jsonify({"success": False, "error": "Freigaben sind deaktiviert"}), 403
        guest_error = _ensure_not_guest_for_write()
        if guest_error:
            return guest_error

        data = request.get_json(silent=True) or {}
        password = (data.get("password") or "").strip()
        expires_at = (data.get("expires_at") or "").strip()
        share_mode = (data.get("share_mode") or "").strip().lower()
        share_mode = "view" if share_mode == "view" else "edit"

        file_obj = File.query.get_or_404(file_id)
        file_obj.share_enabled = True
        file_obj.share_token = _generate_unique_share_token()
        file_obj.share_password_hash = generate_password_hash(password) if password else None
        file_obj.share_expires_at = datetime.fromisoformat(expires_at) if expires_at else None
        file_obj.share_name = None
        file_obj.share_mode = share_mode
        db.session.commit()

        share_url = url_for("files.public_share", token=file_obj.share_token, _external=True)
        return jsonify({"success": True, "share_url": share_url}), 200

    @api_bp.route("/folders/<int:folder_id>/share", methods=["POST"])
    @require_api_auth
    def api_create_folder_share(folder_id):
        if not _check_files_access():
            return _files_access_denied_response()
        if not _is_sharing_enabled():
            return jsonify({"success": False, "error": "Freigaben sind deaktiviert"}), 403
        guest_error = _ensure_not_guest_for_write()
        if guest_error:
            return guest_error

        data = request.get_json(silent=True) or {}
        password = (data.get("password") or "").strip()
        expires_at = (data.get("expires_at") or "").strip()
        share_mode = (data.get("share_mode") or "").strip().lower()
        share_mode = "view" if share_mode == "view" else "edit"

        folder = Folder.query.get_or_404(folder_id)
        folder.share_enabled = True
        folder.share_token = _generate_unique_share_token()
        folder.share_password_hash = generate_password_hash(password) if password else None
        folder.share_expires_at = datetime.fromisoformat(expires_at) if expires_at else None
        folder.share_name = None
        folder.share_mode = share_mode
        db.session.commit()

        share_url = url_for("files.public_share", token=folder.share_token, _external=True)
        return jsonify({"success": True, "share_url": share_url}), 200

    @api_bp.route("/files/<int:file_id>/share-settings", methods=["GET"])
    @require_api_auth
    def api_get_file_share_settings(file_id):
        if not _check_files_access():
            return _files_access_denied_response()
        file_obj = File.query.get_or_404(file_id)
        if not file_obj.share_enabled or not file_obj.share_token:
            return jsonify({"success": False, "error": "Keine aktive Freigabe"}), 404
        share_url = url_for("files.public_share", token=file_obj.share_token, _external=True)
        return jsonify({
            "success": True,
            "item": {
                "type": "file",
                "id": file_obj.id,
                "name": file_obj.name,
                "share_url": share_url,
                "has_password": file_obj.share_password_hash is not None,
                "expires_at": file_obj.share_expires_at.isoformat() if file_obj.share_expires_at else None,
                "share_name": file_obj.share_name,
                "share_mode": "view" if file_obj.share_mode == "view" else "edit",
            },
        }), 200

    @api_bp.route("/folders/<int:folder_id>/share-settings", methods=["GET"])
    @require_api_auth
    def api_get_folder_share_settings(folder_id):
        if not _check_files_access():
            return _files_access_denied_response()
        folder = Folder.query.get_or_404(folder_id)
        if not folder.share_enabled or not folder.share_token:
            return jsonify({"success": False, "error": "Keine aktive Freigabe"}), 404
        share_url = url_for("files.public_share", token=folder.share_token, _external=True)
        return jsonify({
            "success": True,
            "item": {
                "type": "folder",
                "id": folder.id,
                "name": folder.name,
                "share_url": share_url,
                "has_password": folder.share_password_hash is not None,
                "expires_at": folder.share_expires_at.isoformat() if folder.share_expires_at else None,
                "share_name": folder.share_name,
                "share_mode": "view" if folder.share_mode == "view" else "edit",
            },
        }), 200

    @api_bp.route("/files/<int:file_id>/share-settings", methods=["POST"])
    @require_api_auth
    def api_update_file_share(file_id):
        if not _check_files_access():
            return _files_access_denied_response()
        guest_error = _ensure_not_guest_for_write()
        if guest_error:
            return guest_error

        file_obj = File.query.get_or_404(file_id)
        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "").strip().lower()
        if action == "disable":
            file_obj.share_enabled = False
            file_obj.share_token = None
            file_obj.share_password_hash = None
            file_obj.share_expires_at = None
            file_obj.share_name = None
            file_obj.share_mode = "edit"
        else:
            password = (data.get("password") or "").strip()
            expires_at = (data.get("expires_at") or "").strip()
            share_mode = (data.get("share_mode") or "").strip().lower()
            share_mode = "view" if share_mode == "view" else "edit"
            if password:
                file_obj.share_password_hash = generate_password_hash(password)
            file_obj.share_expires_at = datetime.fromisoformat(expires_at) if expires_at else None
            file_obj.share_mode = share_mode
        db.session.commit()
        return jsonify({"success": True}), 200

    @api_bp.route("/folders/<int:folder_id>/share-settings", methods=["POST"])
    @require_api_auth
    def api_update_folder_share(folder_id):
        if not _check_files_access():
            return _files_access_denied_response()
        guest_error = _ensure_not_guest_for_write()
        if guest_error:
            return guest_error

        folder = Folder.query.get_or_404(folder_id)
        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "").strip().lower()
        if action == "disable":
            folder.share_enabled = False
            folder.share_token = None
            folder.share_password_hash = None
            folder.share_expires_at = None
            folder.share_name = None
            folder.share_mode = "edit"
        else:
            password = (data.get("password") or "").strip()
            expires_at = (data.get("expires_at") or "").strip()
            share_mode = (data.get("share_mode") or "").strip().lower()
            share_mode = "view" if share_mode == "view" else "edit"
            if password:
                folder.share_password_hash = generate_password_hash(password)
            folder.share_expires_at = datetime.fromisoformat(expires_at) if expires_at else None
            folder.share_mode = share_mode
        db.session.commit()
        return jsonify({"success": True}), 200

    @api_bp.route("/folders/<int:folder_id>/dropbox/enable", methods=["POST"])
    @require_api_auth
    def api_enable_dropbox(folder_id):
        if not _check_files_access():
            return _files_access_denied_response()
        guest_error = _ensure_not_guest_for_write()
        if guest_error:
            return guest_error

        folder = Folder.query.get_or_404(folder_id)
        folder.is_dropbox = True
        folder.dropbox_token = _generate_unique_dropbox_token()
        db.session.commit()
        return jsonify({
            "success": True,
            "dropbox_url": url_for("files.dropbox_upload", token=folder.dropbox_token, _external=True),
        }), 200

    @api_bp.route("/folders/<int:folder_id>/dropbox", methods=["GET"])
    @require_api_auth
    def api_get_dropbox_settings(folder_id):
        if not _check_files_access():
            return _files_access_denied_response()

        folder = Folder.query.get_or_404(folder_id)
        if not folder.is_dropbox or not folder.dropbox_token:
            return jsonify({"success": False, "error": "Briefkasten ist nicht aktiv"}), 404
        return jsonify({
            "success": True,
            "folder": {
                "id": folder.id,
                "name": folder.name,
                "dropbox_url": url_for("files.dropbox_upload", token=folder.dropbox_token, _external=True),
                "has_password": folder.dropbox_password_hash is not None,
            },
        }), 200

    @api_bp.route("/folders/<int:folder_id>/dropbox", methods=["POST"])
    @require_api_auth
    def api_update_dropbox_settings(folder_id):
        if not _check_files_access():
            return _files_access_denied_response()
        guest_error = _ensure_not_guest_for_write()
        if guest_error:
            return guest_error

        folder = Folder.query.get_or_404(folder_id)
        if not folder.is_dropbox:
            return jsonify({"success": False, "error": "Briefkasten ist nicht aktiv"}), 404

        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "").strip().lower()
        if action == "set_password":
            password = (data.get("password") or "").strip()
            if not password:
                return jsonify({"success": False, "error": "Passwort fehlt"}), 400
            folder.dropbox_password_hash = generate_password_hash(password)
        elif action == "remove_password":
            folder.dropbox_password_hash = None
        elif action == "regenerate_token":
            folder.dropbox_token = _generate_unique_dropbox_token()
        else:
            return jsonify({"success": False, "error": "Ungültige Aktion"}), 400

        db.session.commit()
        return jsonify({
            "success": True,
            "dropbox_url": url_for("files.dropbox_upload", token=folder.dropbox_token, _external=True),
            "has_password": folder.dropbox_password_hash is not None,
        }), 200

    @api_bp.route("/folders/<int:folder_id>/dropbox/disable", methods=["POST"])
    @require_api_auth
    def api_disable_dropbox(folder_id):
        if not _check_files_access():
            return _files_access_denied_response()
        guest_error = _ensure_not_guest_for_write()
        if guest_error:
            return guest_error

        folder = Folder.query.get_or_404(folder_id)
        folder.is_dropbox = False
        folder.dropbox_token = None
        folder.dropbox_password_hash = None
        db.session.commit()
        return jsonify({"success": True}), 200

