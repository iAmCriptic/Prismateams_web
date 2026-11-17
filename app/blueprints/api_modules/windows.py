"""API routes for Windows Native App integration.

Provides:
- /api/windows/webdav-credentials: Auto-provisioning and retrieval of WebDAV credentials.
- /api/windows/resolve-path: Translates local Explorer file paths to Prismateams editor URLs.
"""

from __future__ import annotations

import logging
import os
from flask import g, jsonify, request, url_for
from flask_login import current_user

from app import db
from app.models.app_password import AppPassword, MAX_PER_USER
from app.models.file import File
from app.models.excalidraw import ExcalidrawDrawing
from app.utils.access_control import has_module_access
from app.utils.onlyoffice import is_onlyoffice_file_type
from app.utils.webdav.flags import is_webdav_enabled
from app.utils.webdav import ops
from app.utils.private_files import (
    ensure_personal_root,
    ensure_team_root,
    can_view_file,
    user_file_teams,
)
from argon2 import PasswordHasher

logger = logging.getLogger(__name__)
_ph = PasswordHasher()


def _get_active_user():
    """Retrieve authenticated user from Flask-Login session or API Bearer token."""
    if current_user and getattr(current_user, "is_authenticated", False):
        return current_user
    user = getattr(g, "_login_user", None)
    if user and getattr(user, "is_active", False):
        return user
    return None


def resolve_webdav_path_to_file(path_str: str, user):
    """
    Given a path like '/Private/folder/file.docx' or 'P:\\Teams\\MyTeam\\file.xlsx'
    returns the matching File model or None.
    """
    clean = (path_str or "").strip().replace("\\", "/").strip("/")
    if len(clean) >= 2 and clean[1] == ":":
        clean = clean[2:].strip("/")
    if not clean:
        return None

    parts = [p for p in clean.split("/") if p and p not in (".", "..")]
    if not parts:
        return None

    top = parts[0].lower()
    rest = parts[1:]

    view = "public"
    team_id = None
    parent_folder = None

    if top in ("private", "ablage", "persönlich", "persoenlich"):
        view = "ablage"
        parent_folder = ensure_personal_root(user.id)
    elif top in ("teams", "team"):
        view = "team"
        if not rest:
            return None
        team_segment = rest[0]
        rest = rest[1:]
        for team in user_file_teams(user):
            if ops.names_match(team.name, team_segment):
                team_id = team.id
                break
        if not team_id:
            return None
        parent_folder = ensure_team_root(team_id, user.id)
    elif top in ("public", "öffentlich", "oeffentlich"):
        view = "public"
        parent_folder = None
    else:
        rest = parts
        view = "public"
        parent_folder = None

    if not rest:
        return None

    current_folder = parent_folder
    for i, segment in enumerate(rest):
        is_last = i == len(rest) - 1
        parent_id = current_folder.id if current_folder is not None else None
        space_filter = "public" if view == "public" and parent_id is None else None

        if not is_last:
            folder = ops.find_child_folder(
                parent_id,
                segment,
                space_filter=space_filter,
                team_id=team_id if view == "team" else None,
            )
            if not folder:
                return None
            current_folder = folder
        else:
            file_obj = ops.find_child_file(
                parent_id,
                segment,
                space_filter=space_filter,
                team_id=team_id if view == "team" else None,
            )
            if file_obj and can_view_file(file_obj, user):
                return file_obj

    return None


def register_windows_routes(api_bp, require_api_auth):
    @api_bp.route("/windows/webdav-credentials", methods=["GET", "POST"])
    @require_api_auth
    def api_windows_webdav_credentials():
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

        if existing and request.method == "GET":
            return jsonify({
                "success": True,
                "username": existing.username or existing.ensure_username(user),
                "has_password": True,
                "created_at": existing.created_at.isoformat() if existing.created_at else None,
            }), 200

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
            }), 200

        # Create new app password, respecting quota
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
        }), 200

    @api_bp.route("/windows/resolve-path", methods=["GET"])
    @require_api_auth
    def api_windows_resolve_path():
        user = _get_active_user()
        if not user:
            return jsonify({"success": False, "error": "Authentifizierung erforderlich"}), 401

        raw_path = request.args.get("path", "").strip()
        if not raw_path:
            return jsonify({"success": False, "error": "Pfad fehlt"}), 400

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
            }), 200

        if ext == ".excalidraw" or "excalidraw" in raw_path.lower():
            stem = os.path.splitext(filename)[0]
            drawing = ExcalidrawDrawing.query.filter(
                db.func.lower(ExcalidrawDrawing.name) == stem.lower()
            ).first()
            if drawing:
                return jsonify({
                    "success": True,
                    "found": True,
                    "resource": "excalidraw",
                    "drawing_id": drawing.id,
                    "filename": drawing.name,
                    "extension": ".excalidraw",
                    "action": "edit_excalidraw",
                    "edit_url": url_for("excalidraw.edit", drawing_id=drawing.id),
                }), 200

        return jsonify({
            "success": True,
            "found": False,
            "filename": filename,
            "extension": ext,
            "action": "none",
            "edit_url": url_for("files.index"),
        }), 200
