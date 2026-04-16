from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import AssessmentRole, AssessmentUser
from app.utils.assessment_auth import assessment_role_required

users_bp = Blueprint("users", __name__)


@users_bp.route("/manage_users")
@assessment_role_required(["Administrator"])
def manage_users_page():
    return render_template("assessment/manage_users.html")


@users_bp.route("/api/roles")
@assessment_role_required(["Administrator"])
def api_roles():
    roles = AssessmentRole.query.order_by(AssessmentRole.name.asc()).all()
    return jsonify({"success": True, "roles": [{"id": r.id, "name": r.name} for r in roles]})


@users_bp.route("/api/users", methods=["GET", "POST", "PUT", "DELETE"])
@assessment_role_required(["Administrator"])
def api_users():
    if request.method == "GET":
        users = AssessmentUser.query.order_by(AssessmentUser.username.asc()).all()
        return jsonify(
            {
                "success": True,
                "users": [
                    {
                        "id": u.id,
                        "username": u.username,
                        "display_name": u.display_name,
                        "is_admin": u.is_admin,
                        "role_names": u.role_names,
                        "role_ids": [r.id for r in u.roles],
                    }
                    for u in users
                ],
            }
        )

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        username = (data.get("username") or "").strip().lower()
        password = (data.get("password") or "").strip()
        display_name = (data.get("display_name") or "").strip()
        role_ids = data.get("role_ids") or []

        if not username or not password or not display_name or not isinstance(role_ids, list) or not role_ids:
            return jsonify({"success": False, "message": "Bitte Benutzername, Passwort, Anzeigename und mindestens eine Rolle angeben."}), 400
        if AssessmentUser.query.filter_by(username=username).first():
            return jsonify({"success": False, "message": "Benutzername existiert bereits."}), 409

        user = AssessmentUser(
            username=username,
            display_name=display_name,
            is_admin=False,
            must_change_password=False,
            is_active=True,
        )
        user.set_password(password)
        roles = AssessmentRole.query.filter(AssessmentRole.id.in_(role_ids)).all()
        user.roles = roles
        user.is_admin = any(role.name == "Administrator" for role in roles)
        db.session.add(user)
        db.session.commit()
        return jsonify({"success": True, "message": "Benutzer erfolgreich erstellt."})

    if request.method == "PUT":
        user_id = data.get("id")
        user = AssessmentUser.query.get(user_id)
        if not user:
            return jsonify({"success": False, "message": "Benutzer nicht gefunden."}), 404

        user.display_name = (data.get("display_name") or user.display_name).strip()
        new_password = (data.get("password") or "").strip()
        if new_password:
            user.set_password(new_password)

        role_ids = data.get("role_ids")
        if isinstance(role_ids, list):
            roles = AssessmentRole.query.filter(AssessmentRole.id.in_(role_ids)).all()
            user.roles = roles
            user.is_admin = any(role.name == "Administrator" for role in roles)

        db.session.commit()
        return jsonify({"success": True, "message": "Benutzer aktualisiert."})

    user_id = data.get("id")
    user = AssessmentUser.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "Benutzer nicht gefunden."}), 404
    db.session.delete(user)
    db.session.commit()
    return jsonify({"success": True, "message": "Benutzer gelöscht."})
