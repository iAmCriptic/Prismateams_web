"""Upload routes: thin orchestrator over path helpers and batch handlers."""

from flask import flash, jsonify, request, url_for
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.models.file import File, Folder
from app.utils.access_control import check_module_access
from app.utils.file_storage_limits import resolve_limits_for_user
from app.utils.private_files import (
    can_edit_folder,
    is_private_folders_enabled,
    is_team_folders_enabled,
    normalize_view,
)

from app.blueprints.files._bp import files_bp
from app.blueprints.files.helpers import (  # noqa: F401
    _files_context_url,
    _request_team_id,
    _resolve_create_parent,
    _safe_referrer_or,
)
from app.blueprints.files.upload_handlers import (
    finish_upload,
    handle_folder_upload,
    handle_multi_file_upload,
    handle_single_file_upload,
)


@files_bp.route("/upload", methods=["POST"])
@login_required
@check_module_access("module_files")
def upload_file():
    """Upload a file or folder."""
    if hasattr(current_user, "is_guest") and current_user.is_guest:
        folder_id = request.form.get("folder_id")
        folder_id = int(folder_id) if folder_id else None

        if folder_id:
            from app.utils.access_control import GUEST_WRITE_MODES, guest_has_folder_access

            target_folder = Folder.query.get(folder_id)
            if not target_folder or not guest_has_folder_access(
                current_user, target_folder, modes=GUEST_WRITE_MODES
            ):
                flash(
                    "Keine Upload-Berechtigung für diesen Ordner "
                    "(nur Bearbeiten- oder Dropbox-Freigaben).",
                    "danger",
                )
                return finish_upload(_safe_referrer_or(url_for("files.index")))
        else:
            flash(
                "Gast-Accounts können nur in freigegebenen Ordnern Dateien hochladen.",
                "danger",
            )
            return finish_upload(_safe_referrer_or(url_for("files.index")))

    folder_id = request.form.get("folder_id")
    folder_id = int(folder_id) if folder_id else None
    conflict_strategy = request.form.get("conflict_strategy", "").strip().lower()
    files_view = normalize_view(request.form.get("view") or request.args.get("view"))
    team_id = _request_team_id()
    folder_id, upload_parent = _resolve_create_parent(files_view, folder_id, team_id)
    if files_view == "team" and is_team_folders_enabled() and not upload_parent:
        flash("Keine Berechtigung für diese Team-Ablage.", "danger")
        return finish_upload(_safe_referrer_or(url_for("files.index")))

    private_enabled = is_private_folders_enabled()
    team_enabled = is_team_folders_enabled()
    if (
        (private_enabled or team_enabled)
        and upload_parent
        and not current_user.is_admin
        and not can_edit_folder(upload_parent, current_user)
    ):
        flash("Keine Berechtigung für diesen Ordner.", "danger")
        return finish_upload(_safe_referrer_or(url_for("files.index")))

    limits = resolve_limits_for_user(current_user.id)
    max_size = limits["max_file_size"]

    if "folder_upload" in request.files:
        result = handle_folder_upload(
            folder_id, conflict_strategy, files_view, team_id, max_size
        )
        if result is not None:
            return result

    if "file" not in request.files:
        flash("Keine Datei ausgewählt.", "danger")
        return finish_upload(_safe_referrer_or(url_for("files.index")))

    uploaded_files = [f for f in request.files.getlist("file") if f and f.filename]
    if not uploaded_files:
        flash("Keine Datei ausgewählt.", "danger")
        return finish_upload(_safe_referrer_or(url_for("files.index")))

    if len(uploaded_files) > 1:
        return handle_multi_file_upload(
            uploaded_files, folder_id, conflict_strategy, max_size
        )

    return handle_single_file_upload(
        uploaded_files[0], folder_id, conflict_strategy, max_size
    )


@files_bp.route("/upload-conflicts", methods=["POST"])
@login_required
@check_module_access("module_files")
def upload_conflicts():
    """Return file names that already exist in target folder."""
    payload = request.get_json(silent=True) or {}
    raw_folder_id = payload.get("folder_id")
    raw_names = payload.get("filenames") or []

    try:
        folder_id = int(raw_folder_id) if raw_folder_id not in (None, "", "null") else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Ungültiger Ordner."}), 400

    if folder_id is not None:
        target = Folder.query.get(folder_id)
        if not target:
            return jsonify({"success": False, "error": "Ordner nicht gefunden."}), 404
        if (
            (is_private_folders_enabled() or is_team_folders_enabled())
            and not current_user.is_admin
            and not can_edit_folder(target, current_user)
        ):
            return jsonify({"success": False, "error": "Keine Berechtigung."}), 403

    candidate_names = []
    for raw_name in raw_names:
        clean_name = secure_filename(str(raw_name or ""))
        if clean_name:
            candidate_names.append(clean_name)

    if not candidate_names:
        return jsonify({"success": True, "conflicts": []})

    query = File.query.filter(File.is_current.is_(True), File.name.in_(candidate_names))
    if folder_id is None:
        query = query.filter(File.folder_id.is_(None))
    else:
        query = query.filter(File.folder_id == folder_id)

    conflicts = sorted({file.name for file in query.all()})
    return jsonify({"success": True, "conflicts": conflicts})
