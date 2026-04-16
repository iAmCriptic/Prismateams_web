from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory, session
from flask_login import current_user

from app import db
from app.models.assessment import (
    AssessmentEvaluation,
    AssessmentEvaluationScore,
    AssessmentRoomInspection,
    AssessmentUser,
    AssessmentVisitorEvaluation,
    AssessmentVisitorEvaluationScore,
    AssessmentWarning,
)
from app.utils.assessment_auth import assessment_role_required, is_assessment_user

from .helpers import current_actor

general_bp = Blueprint("general", __name__)


@general_bp.route("/home")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def home():
    actor = current_actor()
    is_admin = "Administrator" in (actor["roles"] or [])
    return render_template("assessment/home.html", is_admin=is_admin)


@general_bp.route("/api/session_data")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def api_session_data():
    actor = current_actor()
    return jsonify(
        {
            "success": True,
            "logged_in": current_user.is_authenticated,
            "user_type": actor["user_type"],
            "user_id": actor["user_id"],
            "user_roles": actor["roles"],
            "display_name": getattr(current_user, "display_name", getattr(current_user, "full_name", "")),
        }
    )


@general_bp.route("/manage_list", methods=["GET"])
@assessment_role_required(["Administrator"])
def manage_list_page():
    return render_template("assessment/manage_list.html")


@general_bp.route("/api/reset_data", methods=["POST"])
@assessment_role_required(["Administrator"])
def api_reset_data():
    action = (request.get_json(silent=True) or {}).get("action")
    if not action:
        return jsonify({"success": False, "message": "Aktion nicht angegeben."}), 400

    if action == "reset_ranking":
        AssessmentEvaluationScore.query.delete()
        AssessmentEvaluation.query.delete()
        AssessmentVisitorEvaluationScore.query.delete()
        AssessmentVisitorEvaluation.query.delete()
    elif action == "reset_room_inspections":
        AssessmentRoomInspection.query.delete()
    elif action == "reset_warnings":
        AssessmentWarning.query.delete()
    else:
        return jsonify({"success": False, "message": "Ungültige Aktion."}), 400

    db.session.commit()
    return jsonify({"success": True, "message": "Daten erfolgreich zurückgesetzt."})


@general_bp.route("/api/theme", methods=["POST"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def api_theme():
    mode = ((request.get_json(silent=True) or {}).get("mode") or "").lower()
    if mode not in ("light", "dark", "oled"):
        return jsonify({"success": False, "message": "Ungültiger Modus."}), 400
    if is_assessment_user():
        user = AssessmentUser.query.get(current_user.id)
        if user:
            user.theme_mode = mode
            db.session.commit()
        session["user_scope_theme_mode"] = mode
    else:
        try:
            current_user.dark_mode = mode in ("dark", "oled")
            if hasattr(current_user, "oled_mode"):
                current_user.oled_mode = mode == "oled"
            db.session.commit()
        except Exception:
            db.session.rollback()
    return jsonify({"success": True, "mode": mode})


@general_bp.route("/static_files/<path:filename>")
def static_files(filename):
    return send_from_directory(current_app.static_folder, filename)


@general_bp.route("/service-worker.js")
def serve_service_worker():
    return send_from_directory(current_app.root_path, "service-worker.js", mimetype="application/javascript")
