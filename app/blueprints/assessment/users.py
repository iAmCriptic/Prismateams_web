from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import AssessmentList, AssessmentRole, AssessmentUser
from app.utils.assessment_auth import assessment_role_required
from app.utils.password_policy import validate_password

users_bp = Blueprint("users", __name__)


def _apply_list_ids(user, list_ids):
    if not isinstance(list_ids, list):
        return
    if not list_ids:
        user.evaluation_lists = []
        return
    lists = AssessmentList.query.filter(AssessmentList.id.in_(list_ids)).all()
    user.evaluation_lists = lists


def _user_payload(user):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "role_names": user.role_names,
        "role_ids": [r.id for r in user.roles],
        "list_ids": [lst.id for lst in (user.evaluation_lists or [])],
        "list_names": [lst.name for lst in (user.evaluation_lists or [])],
    }


@users_bp.route("/manage_users")
@assessment_role_required(["Administrator"])
def manage_users_page():
    lists = AssessmentList.query.order_by(AssessmentList.sort_order.asc(), AssessmentList.name.asc()).all()
    return render_template("assessment/manage_users.html", evaluation_lists=lists)


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
        return jsonify({"success": True, "users": [_user_payload(u) for u in users]})

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        username = (data.get("username") or "").strip().lower()
        password = (data.get("password") or "").strip()
        display_name = (data.get("display_name") or "").strip()
        role_ids = data.get("role_ids") or []
        list_ids = data.get("list_ids") if "list_ids" in data else []

        if not username or not password or not display_name or not isinstance(role_ids, list) or not role_ids:
            return jsonify({
                "success": False,
                "message": "Bitte Benutzername, Passwort, Anzeigename und mindestens eine Rolle angeben.",
            }), 400
        is_valid, error_msg = validate_password(password)
        if not is_valid:
            return jsonify({"success": False, "message": error_msg or "Passwort entspricht nicht der Policy."}), 400
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
        _apply_list_ids(user, list_ids)
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
            is_valid, error_msg = validate_password(new_password)
            if not is_valid:
                return jsonify({"success": False, "message": error_msg or "Passwort entspricht nicht der Policy."}), 400
            user.set_password(new_password)

        role_ids = data.get("role_ids")
        if isinstance(role_ids, list):
            roles = AssessmentRole.query.filter(AssessmentRole.id.in_(role_ids)).all()
            user.roles = roles
            user.is_admin = any(role.name == "Administrator" for role in roles)

        if "list_ids" in data:
            _apply_list_ids(user, data.get("list_ids") or [])

        db.session.commit()
        return jsonify({"success": True, "message": "Benutzer aktualisiert."})

    user_id = data.get("id")
    user = AssessmentUser.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "Benutzer nicht gefunden."}), 404
    db.session.delete(user)
    db.session.commit()
    return jsonify({"success": True, "message": "Benutzer gelöscht."})
