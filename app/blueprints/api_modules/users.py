from flask import jsonify, request, url_for
from flask_login import current_user, login_required

from app.models.user import User
from app.utils.chat_visibility import selectable_chat_user_filters


def register_user_routes(api_bp, require_api_auth):
    @api_bp.route("/users", methods=["GET"])
    @login_required
    def get_users():
        include_guests = request.args.get("include_guests", "0") == "1"
        users = User.query.filter(
            *selectable_chat_user_filters(include_guests=include_guests)
        ).all()
        return jsonify([{
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_admin": user.is_admin,
            "is_guest": user.is_guest,
            "guest_username": user.guest_username,
            "profile_picture": url_for("settings.profile_picture", filename=user.profile_picture) if user.profile_picture else None,
        } for user in users])

    @api_bp.route("/users/<int:user_id>", methods=["GET"])
    @login_required
    def get_user(user_id):
        user = User.query.get_or_404(user_id)
        return jsonify({
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone": user.phone,
            "is_admin": user.is_admin,
            "profile_picture": url_for("settings.profile_picture", filename=user.profile_picture) if user.profile_picture else None,
            "accent_color": user.accent_color,
            "dark_mode": user.dark_mode,
        })

    @api_bp.route("/users/<int:user_id>/status", methods=["GET"])
    @login_required
    def get_user_status(user_id):
        user = User.query.get_or_404(user_id)
        return jsonify({
            "id": user.id,
            "is_online": user.is_online(),
            "last_seen": user.last_seen.isoformat() if user.last_seen else None,
        })

    @api_bp.route("/users/update-last-seen", methods=["POST"])
    @require_api_auth
    def update_last_seen():
        try:
            current_user.update_last_seen()
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

