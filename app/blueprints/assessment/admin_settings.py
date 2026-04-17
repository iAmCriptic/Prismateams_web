import os
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from app import db
from app.models.assessment import AssessmentAppSetting
from app.utils.assessment_auth import assessment_role_required

admin_settings_bp = Blueprint("admin_settings", __name__)


EDITABLE_KEYS = {
    "welcome_title",
    "welcome_subtitle",
    "module_label",
    "ranking_active_mode",
    "ranking_sort_mode",
}


def _upload_dir():
    base = current_app.config["UPLOAD_FOLDER"]
    if not os.path.isabs(base):
        base = os.path.abspath(base)
    target = os.path.join(base, "assessment", "branding")
    os.makedirs(target, exist_ok=True)
    return target


def _allowed(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in {"png", "jpg", "jpeg", "gif", "svg", "webp"}


def _store_setting(key, value):
    entry = AssessmentAppSetting.query.filter_by(setting_key=key).first()
    if not entry:
        entry = AssessmentAppSetting(setting_key=key, setting_value=value or "")
        db.session.add(entry)
    else:
        entry.setting_value = value or ""
    return entry


@admin_settings_bp.route("/admin_settings")
@assessment_role_required(["Administrator"])
def admin_settings_page():
    return render_template("assessment/admin_settings.html")


@admin_settings_bp.route("/api/admin_settings", methods=["GET", "POST"])
@assessment_role_required(["Administrator"])
def api_get_admin_settings():
    if request.method == "GET":
        settings = AssessmentAppSetting.query.all()
        return jsonify({"success": True, "settings": {s.setting_key: s.setting_value for s in settings}})

    data = request.get_json(silent=True) or {}
    saved = {}
    for key, value in data.items():
        if key not in EDITABLE_KEYS:
            continue
        _store_setting(key, str(value) if value is not None else "")
        saved[key] = value
    db.session.commit()
    return jsonify({"success": True, "message": "Einstellungen gespeichert.", "saved": saved})


@admin_settings_bp.route("/api/upload_logo", methods=["POST"])
@assessment_role_required(["Administrator"])
def api_upload_logo():
    file = request.files.get("logo")
    if not file or not file.filename:
        return jsonify({"success": False, "message": "Keine Datei empfangen."}), 400
    if not _allowed(file.filename):
        return jsonify({"success": False, "message": "Dateityp nicht erlaubt (PNG, JPG, SVG, WEBP, GIF)."}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower()
    filename = f"logo_{uuid4().hex}.{ext}"
    secure_name = secure_filename(filename)
    file.save(os.path.join(_upload_dir(), secure_name))

    rel_url = url_for("assessment.admin_settings.serve_branding_file", filename=secure_name)
    _store_setting("logo_url", rel_url)
    db.session.commit()

    return jsonify({"success": True, "message": "Logo hochgeladen.", "logo_url": rel_url})


@admin_settings_bp.route("/api/delete_logo", methods=["POST"])
@assessment_role_required(["Administrator"])
def api_delete_logo():
    entry = AssessmentAppSetting.query.filter_by(setting_key="logo_url").first()
    if entry and entry.setting_value:
        filename = os.path.basename(entry.setting_value)
        path = os.path.join(_upload_dir(), filename)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        entry.setting_value = ""
        db.session.commit()
    return jsonify({"success": True, "message": "Logo entfernt."})


@admin_settings_bp.route("/uploads/branding/<path:filename>")
def serve_branding_file(filename):
    return send_from_directory(_upload_dir(), filename)
