"""Folder-, multi- and single-file upload handlers (extracted from upload_file)."""

import logging

from flask import (
    flash,
    get_flashed_messages,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask import url_for as flask_url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

from app import db
from app.models.file import File
from app.utils.dashboard_events import emit_dashboard_update
from app.utils.file_storage_limits import check_upload_allowed, format_bytes_de
from app.utils.notifications import send_file_notification
from app.utils.upload_policy import is_allowed_upload_filename

from app.blueprints.files.helpers import (
    _create_new_file_version,
    _files_context_url,
    _generate_unique_filename_in_folder,
    _process_file_upload,
    _safe_referrer_or,
)
from app.blueprints.files.upload_path import (
    apply_conflict_or_create,
    ensure_nested_upload_folder_path,
)


def is_ajax_upload():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def finish_upload(url):
    """Redirect for normal form posts; JSON for XHR uploads (toast UI)."""
    if is_ajax_upload():
        flashes = get_flashed_messages(with_categories=True)
        messages = [{"category": cat, "text": msg} for cat, msg in flashes]
        cats = {m["category"] for m in messages}
        return jsonify(
            {
                "success": "danger" not in cats,
                "messages": messages,
                "redirect_url": url,
            }
        )
    return redirect(url)


def _notify_new_uploads(folder_id, uploaded_count):
    if uploaded_count <= 0:
        return
    try:
        query = File.query.filter_by(uploaded_by=current_user.id)
        if folder_id is not None:
            query = query.filter_by(folder_id=folder_id)
        recent_uploads = query.order_by(File.created_at.desc()).limit(uploaded_count).all()
        for recent_file in recent_uploads:
            try:
                send_file_notification(recent_file.id, "new")
            except Exception as exc:
                logging.error("Fehler beim Senden der Datei-Benachrichtigung: %s", exc)
    except Exception as exc:
        logging.error("Fehler beim Senden von Benachrichtigungen: %s", exc)


def _emit_files_dashboard_update():
    try:
        recent_files = (
            File.query.filter_by(uploaded_by=current_user.id)
            .order_by(File.updated_at.desc())
            .limit(3)
            .all()
        )
        files_data = [
            {
                "id": recent.id,
                "name": recent.name,
                "original_name": recent.original_name,
                "updated_at": recent.updated_at.isoformat(),
                "mime_type": recent.mime_type,
                "url": flask_url_for("files.view_file", file_id=recent.id),
            }
            for recent in recent_files
        ]
        emit_dashboard_update(current_user.id, "files_update", {"files": files_data})
    except Exception as exc:
        logging.error("Fehler beim Senden der Dashboard-Updates für Dateien: %s", exc)


def _flash_batch_result(uploaded_count, skipped_count, skipped_files, max_size, *, detail=True):
    if uploaded_count > 0:
        flash(f"{uploaded_count} Datei(en) wurden hochgeladen.", "success")
    if skipped_count > 0:
        msg = (
            f"{skipped_count} Datei(en) wurden übersprungen (zu groß, Kontingent oder Fehler)."
            if detail
            else f"{skipped_count} Datei(en) wurden übersprungen."
        )
        flash(msg, "warning")
        if skipped_files:
            preview = ", ".join(skipped_files[:5])
            flash(
                f'Übersprungene Dateien: {preview}{"..." if len(skipped_files) > 5 else ""}',
                "info",
            )
    if uploaded_count == 0 and skipped_count > 0:
        flash(
            f"Kein Upload möglich. Dateien ggf. zu groß (max. {format_bytes_de(max_size)}) "
            "oder Speicherkontingent voll.",
            "danger",
        )


def handle_folder_upload(folder_id, conflict_strategy, files_view, team_id, max_size):
    folder_files = request.files.getlist("folder_upload")
    if not folder_files or not folder_files[0].filename:
        return None

    uploaded_count = 0
    skipped_count = 0
    skipped_files = []
    folder_children_cache = {}
    files_by_folder_cache = {}
    pending_bytes = 0

    for file_storage in folder_files:
        if not file_storage.filename:
            continue

        file_storage.seek(0, 2)
        file_size = file_storage.tell()
        file_storage.seek(0)

        ok, _code, _err = check_upload_allowed(
            current_user.id, file_size, pending_bytes=pending_bytes
        )
        if not ok:
            skipped_count += 1
            skipped_files.append(file_storage.filename)
            continue

        file_path_parts = file_storage.filename.replace("\\", "/").split("/")
        file_name = secure_filename(file_path_parts[-1])
        if not file_name or not is_allowed_upload_filename(file_name):
            skipped_count += 1
            skipped_files.append(file_storage.filename)
            continue

        target_folder_id = folder_id
        if len(file_path_parts) > 1:
            target_folder_id = ensure_nested_upload_folder_path(
                folder_id,
                file_path_parts[:-1],
                files_view,
                team_id,
                current_user.id,
                folder_children_cache,
            )

        try:
            status, grew = apply_conflict_or_create(
                file_storage=file_storage,
                file_name=file_name,
                folder_id=target_folder_id,
                conflict_strategy=conflict_strategy,
                user_id=current_user.id,
                files_cache=files_by_folder_cache,
            )
            if status == "uploaded":
                uploaded_count += 1
                if grew:
                    pending_bytes += file_size
            else:
                skipped_count += 1
                skipped_files.append(file_name)
        except Exception as exc:
            logging.error("Fehler beim Hochladen von %s: %s", file_name, exc)
            skipped_count += 1
            skipped_files.append(file_storage.filename)

    db.session.commit()
    _notify_new_uploads(folder_id, uploaded_count)
    _flash_batch_result(uploaded_count, skipped_count, skipped_files, max_size, detail=True)

    if folder_id:
        return finish_upload(_files_context_url(folder_id=folder_id))
    return finish_upload(_files_context_url())


def handle_multi_file_upload(uploaded_files, folder_id, conflict_strategy, max_size):
    uploaded_count = 0
    skipped_count = 0
    skipped_files = []
    pending_bytes = 0
    files_cache = {}

    for uploaded_file in uploaded_files:
        uploaded_file.seek(0, 2)
        file_size = uploaded_file.tell()
        uploaded_file.seek(0)
        ok, _code, _err = check_upload_allowed(
            current_user.id, file_size, pending_bytes=pending_bytes
        )
        if not ok:
            skipped_count += 1
            skipped_files.append(uploaded_file.filename)
            continue

        original_name = secure_filename(uploaded_file.filename)
        if not original_name or not is_allowed_upload_filename(original_name):
            skipped_count += 1
            skipped_files.append(uploaded_file.filename)
            continue

        try:
            status, grew = apply_conflict_or_create(
                file_storage=uploaded_file,
                file_name=original_name,
                folder_id=folder_id,
                conflict_strategy=conflict_strategy,
                user_id=current_user.id,
                files_cache=files_cache,
            )
            if status == "uploaded":
                uploaded_count += 1
                if grew:
                    pending_bytes += file_size
            else:
                skipped_count += 1
                skipped_files.append(original_name)
        except Exception as exc:
            logging.error("Fehler beim Hochladen von %s: %s", original_name, exc)
            skipped_count += 1
            skipped_files.append(uploaded_file.filename)

    db.session.commit()
    _notify_new_uploads(folder_id, uploaded_count)
    _emit_files_dashboard_update()
    _flash_batch_result(uploaded_count, skipped_count, skipped_files, max_size, detail=False)
    return finish_upload(_files_context_url(folder_id=folder_id))


def handle_single_file_upload(file_storage, folder_id, conflict_strategy, max_size):
    file_storage.seek(0, 2)
    file_size = file_storage.tell()
    file_storage.seek(0)

    ok, _code, err_msg = check_upload_allowed(current_user.id, file_size)
    if not ok:
        flash(err_msg or f"Datei ist zu groß (max. {format_bytes_de(max_size)}).", "danger")
        return finish_upload(_safe_referrer_or(url_for("files.index")))

    original_name = secure_filename(file_storage.filename)
    if not original_name:
        flash("Ungültiger Dateiname.", "danger")
        return finish_upload(_safe_referrer_or(url_for("files.index")))
    if not is_allowed_upload_filename(original_name):
        flash("Dieser Dateityp ist nicht erlaubt.", "danger")
        return finish_upload(_safe_referrer_or(url_for("files.index")))

    existing_file = File.query.filter_by(
        name=original_name,
        folder_id=folder_id,
        is_current=True,
    ).first()

    if existing_file:
        if conflict_strategy == "version":
            version_number = _create_new_file_version(
                existing_file, file_storage, current_user.id
            )
            db.session.commit()
            try:
                send_file_notification(existing_file.id, "modified")
            except Exception as exc:
                logging.error("Fehler beim Senden der Datei-Benachrichtigung: %s", exc)
            _emit_files_dashboard_update()
            flash(
                f'Datei "{original_name}" wurde aktualisiert (Version {version_number}).',
                "success",
            )
            return finish_upload(_files_context_url(folder_id=folder_id))

        if conflict_strategy == "separate":
            unique_name = _generate_unique_filename_in_folder(original_name, folder_id)
            _process_file_upload(file_storage, unique_name, folder_id, current_user.id)
            db.session.commit()
            flash(f'Datei "{unique_name}" wurde als separate Datei hochgeladen.', "success")
            return finish_upload(_files_context_url(folder_id=folder_id))

        overwrite = request.form.get("overwrite")
        if overwrite != "yes":
            flash(
                f'Datei "{original_name}" existiert bereits. Bitte Konfliktstrategie wählen.',
                "danger",
            )
            if is_ajax_upload():
                return (
                    jsonify(
                        {
                            "success": False,
                            "messages": [
                                {
                                    "category": "danger",
                                    "text": f'Datei "{original_name}" existiert bereits.',
                                }
                            ],
                            "conflict": True,
                        }
                    ),
                    409,
                )
            flash(
                f'Datei "{original_name}" existiert bereits. Möchten Sie sie überschreiben?',
                "warning",
            )
            return render_template(
                "files/confirm_overwrite.html",
                filename=original_name,
                folder_id=folder_id,
            )

        version_number = _create_new_file_version(
            existing_file, file_storage, current_user.id
        )
        db.session.commit()
        try:
            send_file_notification(existing_file.id, "modified")
        except Exception as exc:
            logging.error("Fehler beim Senden der Datei-Benachrichtigung: %s", exc)
        _emit_files_dashboard_update()
        flash(
            f'Datei "{original_name}" wurde aktualisiert (Version {version_number}).',
            "success",
        )
        return finish_upload(_files_context_url(folder_id=folder_id))

    _process_file_upload(file_storage, original_name, folder_id, current_user.id)
    db.session.commit()

    new_file = (
        File.query.filter_by(
            name=original_name,
            folder_id=folder_id,
            uploaded_by=current_user.id,
        )
        .order_by(File.created_at.desc())
        .first()
    )
    if new_file:
        try:
            send_file_notification(new_file.id, "new")
        except Exception as exc:
            logging.error("Fehler beim Senden der Datei-Benachrichtigung: %s", exc)
        _emit_files_dashboard_update()

    flash(f'Datei "{original_name}" wurde hochgeladen.', "success")
    return finish_upload(_files_context_url(folder_id=folder_id))
