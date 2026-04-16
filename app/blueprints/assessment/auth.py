from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.models.assessment import AssessmentUser
from app.utils.assessment_auth import assessment_role_required, is_assessment_user

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/admin_setup", methods=["GET", "POST"])
@assessment_role_required(["Administrator"])
def admin_setup():
    if not is_assessment_user():
        return redirect(url_for("assessment.general.home"))

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        new_password = (data.get("new_password") or "").strip()
        confirm_password = (data.get("confirm_password") or "").strip()
        display_name = (data.get("display_name") or "").strip() or current_user.display_name

        if not new_password or not confirm_password:
            return jsonify({"success": False, "message": "Bitte Passwort und Bestätigung eingeben."}), 400
        if new_password != confirm_password:
            return jsonify({"success": False, "message": "Passwörter stimmen nicht überein."}), 400
        if len(new_password) < 8:
            return jsonify({"success": False, "message": "Passwort muss mindestens 8 Zeichen lang sein."}), 400

        user = AssessmentUser.query.get(current_user.id)
        user.display_name = display_name
        user.must_change_password = False
        user.set_password(new_password)
        db.session.commit()
        return jsonify({"success": True, "message": "Administratorkonto erfolgreich eingerichtet."})

    return render_template("assessment/admin_setup.html")
