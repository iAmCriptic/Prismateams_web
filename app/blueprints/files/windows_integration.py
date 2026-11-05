"""Windows native integration API routes for Prismateams.

Enables path resolution from local WebDAV / SMB shares (e.g. P:\\...) to internal
file IDs and live editing URLs (Euro-Office & Excalidraw), and automatic WebDAV token provisioning.
"""

from __future__ import annotations

import logging
import os
from flask import jsonify, request, current_app, url_for
from flask_login import current_user, login_required

from app import db
from app.blueprints.files._bp import files_bp
from app.models.app_password import AppPassword
from app.models.file import File
from app.models.excalidraw import ExcalidrawDrawing
from app.utils.access_control import check_module_access
from app.utils.onlyoffice import is_onlyoffice_file_type
from app.utils.webdav import ops
from app.utils.private_files import (
    ensure_personal_root,
    ensure_team_root,
    can_view_file,
    user_file_teams,
)

logger = logging.getLogger(__name__)


def _resolve_webdav_path_to_file(path_str: str, user):
    """
    Given a relative path like '/Private/folder/file.docx' or '/Teams/MyTeam/file.xlsx'
    returns the matching File model or None.
    """
    clean = (path_str or "").strip().replace("\\", "/").strip("/")
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

    if top in ("private", "ablage", "persönlich"):
        view = "ablage"
        parent_folder = ensure_personal_root(user.id)
    elif top in ("teams", "team"):
        view = "team"
        if not rest:
            return None
        team_segment = rest[0]
        rest = rest[1:]
        # Find team matching segment
        for team in user_file_teams(user):
            if ops.names_match(team.name, team_segment):
                team_id = team.id
                break
        if not team_id:
            return None
        parent_folder = ensure_team_root(team_id, user.id)
    elif top in ("public", "öffentlich"):
        view = "public"
        parent_folder = None
    else:
        # Fallback: maybe relative directly from public
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


@files_bp.route("/api/windows/resolve-path", methods=["GET"])
@login_required
@check_module_access("module_files")
def resolve_windows_file_path():
    """
    Resolves a WebDAV relative file path to its editing URL or viewer in Prismateams.
    Query param: path (e.g. /Private/Documents/Note.docx or P:\\Private\\Documents\\Note.docx)
    """
    raw_path = request.args.get("path", "").strip()
    if not raw_path:
        return jsonify({"success": False, "error": "Missing path parameter"}), 400

    # Strip local drive letter if provided (e.g. P:\ or P:/)
    if len(raw_path) >= 2 and raw_path[1] == ":":
        raw_path = raw_path[2:]

    # 1. Try to resolve within Files module
    file_obj = _resolve_webdav_path_to_file(raw_path, current_user)

    filename = os.path.basename(raw_path.replace("\\", "/"))
    ext = os.path.splitext(filename)[1].lower()

    if file_obj:
        is_onlyoffice = is_onlyoffice_file_type(ext)
        onlyoffice_enabled = current_app.config.get("ONLYOFFICE_ENABLED", False)

        edit_url = ""
        action = "view"
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

    # 2. Check if it's an Excalidraw drawing name
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
            })

    # Fallback: file not found on server
    return jsonify({
        "success": True,
        "found": False,
        "filename": filename,
        "extension": ext,
        "action": "none",
        "edit_url": url_for("files.index"),
    })


@files_bp.route("/api/windows/webdav-credentials", methods=["GET", "POST"])
@login_required
@check_module_access("module_files")
def get_or_create_webdav_credentials():
    """
    Provides or auto-provisions dedicated App-Password credentials for the Windows
    Explorer WebDAV drive mount.
    """
    app_label = "Windows Explorer App Mount"

    # Find existing app password for this label
    existing = AppPassword.query.filter_by(
        user_id=current_user.id,
        label=app_label,
        revoked_at=None,
    ).first()

    if existing and request.method == "GET":
        return jsonify({
            "success": True,
            "username": existing.username,
            "has_password": True,
            "created_at": existing.created_at.isoformat() if existing.created_at else None,
        })

    # Generate or recreate app password
    plain_pw = AppPassword.generate_raw_password()
    username = AppPassword.generate_username_for_user(current_user)

    if existing:
        existing.username = username
        existing.set_password(plain_pw)
        existing.touch()
        app_entry = existing
    else:
        app_entry = AppPassword(
            user_id=current_user.id,
            label=app_label,
            username=username,
        )
        app_entry.set_password(plain_pw)
        db.session.add(app_entry)

    db.session.commit()

    return jsonify({
        "success": True,
        "username": app_entry.username,
        "password": plain_pw,
        "label": app_label,
        "created_at": app_entry.created_at.isoformat() if app_entry.created_at else None,
    })
