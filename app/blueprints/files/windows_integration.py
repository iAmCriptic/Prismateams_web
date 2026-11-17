"""Windows native integration API routes on files_bp (for backwards compatibility).

Delegates to app.blueprints.api_modules.windows for path resolution and credentials.
"""

from __future__ import annotations

import logging
from flask import jsonify, request
from flask_login import current_user

from app.blueprints.files._bp import files_bp
from app.blueprints.api_modules.windows import (
    resolve_webdav_path_to_file,
    _get_active_user,
    _ph,
)
from app.models.app_password import AppPassword, MAX_PER_USER
from app.models.excalidraw import ExcalidrawDrawing
from app import db
from app.utils.access_control import has_module_access
from app.utils.onlyoffice import is_onlyoffice_file_type
from app.utils.webdav.flags import is_webdav_enabled
import os
from flask import url_for

logger = logging.getLogger(__name__)


@files_bp.route("/api/windows/resolve-path", methods=["GET"])
def resolve_windows_file_path():
    user = _get_active_user()
    if not user:
        return jsonify({"success": False, "error": "Authentifizierung erforderlich"}), 401
    if not has_module_access(user, "module_files"):
        return jsonify({"success": False, "error": "Keine Berechtigung für das Dateien-Modul"}), 403

    raw_path = request.args.get("path", "").strip()
    if not raw_path:
        return jsonify({"success": False, "error": "Missing path parameter"}), 400

    file_obj = resolve_webdav_path_to_file(raw_path, user)
    filename = os.path.basename(raw_path.replace("\\", "/"))
    ext = os.path.splitext(filename)[1].lower()

    if file_obj:
        is_onlyoffice = is_onlyoffice_file_type(ext)
        from flask import current_app
        onlyoffice_enabled = current_app.config.get("ONLYOFFICE_ENABLED", False)

        if is_onlyoffice and onlyoffice_enabled:
            action = "edit_onlyoffice"
            edit_url = url_for("files.edit_onlyoffice", file_id=file_obj.id)
        else:
            action = "show"
            edit_url = url_for("files.index", folder_id=file_obj.folder_id or 0)

        return jsonify({
            "success": True,
            "found": True,
            "resource": "file",
            "file_id": file_obj.id,
            "filename": file_obj.original_name,
            "extension": ext,
            "action": action,
            "edit_url": edit_url,
        })

    if (ext == ".excalidraw" or "excalidraw" in raw_path.lower()) and has_module_access(user, "module_excalidraw"):
        stem = os.path.splitext(filename)[0]
        drawing = ExcalidrawDrawing.query.filter(
            db.func.lower(ExcalidrawDrawing.name) == stem.lower()
        ).first()
        if drawing:
            from app.utils.user_content_access import can_access_visibility
            is_allowed = can_access_visibility(
                user,
                drawing.visibility,
                owner_id=drawing.created_by,
                team_id=drawing.team_id,
            )
            if is_allowed:
                return jsonify({
                    "success": True,
                    "found": True,
                    "resource": "excalidraw",
                    "drawing_id": drawing.id,
                    "filename": drawing.name,
                    "extension": ".excalidraw",
                    "action": "edit_excalidraw",
                    "edit_url": url_for("excalidraw.edit", drawing_id=drawing.id),
                })

    return jsonify({
        "success": True,
        "found": False,
        "filename": filename,
        "extension": ext,
        "action": "none",
        "edit_url": url_for("files.index"),
    })


@files_bp.route("/api/windows/webdav-credentials", methods=["GET", "POST"])
def get_or_create_webdav_credentials():
    user = _get_active_user()
    if not user:
        return jsonify({"success": False, "error": "Authentifizierung erforderlich"}), 401

    if getattr(user, "is_guest", False):
        return jsonify({"success": False, "error": "Gast-Accounts dürfen kein Netzlaufwerk verbinden"}), 403

    if not is_webdav_enabled():
        return jsonify({"success": False, "error": "WebDAV ist serverseitig deaktiviert"}), 403

    if not has_module_access(user, "module_files"):
        return jsonify({"success": False, "error": "Keine Berechtigung für das Dateien-Modul"}), 403

    app_label = "Windows Client"

    existing = AppPassword.query.filter_by(
        user_id=user.id,
        name=app_label,
    ).first()

    if request.method == "GET":
        if existing:
            return jsonify({
                "success": True,
                "username": existing.username or existing.ensure_username(user),
                "has_password": True,
                "created_at": existing.created_at.isoformat() if existing.created_at else None,
            })
        return jsonify({
            "success": True,
            "username": getattr(user, "username", None) or getattr(user, "email", None),
            "has_password": False,
            "created_at": None,
        })

    plain_pw = AppPassword.generate_raw()

    if existing:
        existing.password_hash = _ph.hash(plain_pw)
        existing.hint = plain_pw[:4]
        username = existing.ensure_username(user)
        db.session.commit()
        return jsonify({
            "success": True,
            "username": username,
            "password": plain_pw,
            "name": existing.name,
            "created_at": existing.created_at.isoformat() if existing.created_at else None,
        })

    count = AppPassword.query.filter_by(user_id=user.id).count()
    if count >= MAX_PER_USER:
        oldest = AppPassword.query.filter_by(user_id=user.id).order_by(AppPassword.id.asc()).first()
        if oldest:
            db.session.delete(oldest)
            db.session.flush()

    row, plain_pw = AppPassword.create_for_user(user, name=app_label)
    return jsonify({
        "success": True,
        "username": row.username,
        "password": plain_pw,
        "name": row.name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    })
