from flask import Blueprint, jsonify, render_template, request, session

from app import db
from app.models.assessment import AssessmentAppSetting, AssessmentUser
from app.utils.assessment_auth import assessment_role_required, is_assessment_user

admin_settings_bp = Blueprint("admin_settings", __name__)


EDITABLE_KEYS = {
    "welcome_title",
    "welcome_subtitle",
    "ranking_active_mode",
    "ranking_sort_mode",
}


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
    return render_template(
        "assessment/admin_settings.html",
        show_assessment_appearance=session.get("user_scope") == "assessment",
    )


@admin_settings_bp.route("/api/admin_settings", methods=["GET", "POST"])
@assessment_role_required(["Administrator"])
def api_get_admin_settings():
    if request.method == "GET":
        settings = AssessmentAppSetting.query.all()
        payload = {s.setting_key: s.setting_value for s in settings}
        if current_user.is_authenticated:
            payload["dark_mode"] = current_user.dark_mode
            payload["oled_mode"] = getattr(current_user, "oled_mode", False)
        return jsonify({"success": True, "settings": payload})

    data = request.get_json(silent=True) or {}
    saved = {}
    for key, value in data.items():
        if key not in EDITABLE_KEYS:
            continue
        _store_setting(key, str(value) if value is not None else "")
        saved[key] = value
    db.session.commit()
    return jsonify({"success": True, "message": "Einstellungen gespeichert.", "saved": saved})


@admin_settings_bp.route("/api/admin_settings/appearance", methods=["POST"])
@assessment_role_required(["Administrator"])
def api_save_appearance():
    data = request.get_json(silent=True) or {}
    dark_mode = bool(data.get("dark_mode"))
    oled_mode = bool(data.get("oled_mode")) if dark_mode else False

    if is_assessment_user():
        user = AssessmentUser.query.get(current_user.id)
        if not user:
            return jsonify({"success": False, "message": "Benutzer nicht gefunden."}), 404
        user.theme_mode = "oled" if oled_mode else ("dark" if dark_mode else "light")
    else:
        current_user.dark_mode = dark_mode
        if hasattr(current_user, "oled_mode"):
            current_user.oled_mode = oled_mode
    db.session.commit()
    return jsonify({"success": True, "message": "Darstellung gespeichert. Seite neu laden, um alle Änderungen zu sehen."})
