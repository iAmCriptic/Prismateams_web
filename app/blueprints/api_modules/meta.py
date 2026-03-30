from flask import jsonify, url_for
from flask_login import current_user, login_required

from app.models.role import UserModuleRole
from app.utils.access_control import has_module_access
from app.utils.common import is_module_enabled


def register_meta_routes(api_bp, require_api_auth):
    @api_bp.route("/endpoints", methods=["GET"])
    @login_required
    def list_api_endpoints():
        from flask import current_app

        endpoints = []
        for rule in current_app.url_map.iter_rules():
            if not rule.rule.startswith("/api/"):
                continue
            methods = sorted([m for m in rule.methods if m not in ("HEAD", "OPTIONS")])
            endpoints.append({"path": rule.rule, "methods": methods, "endpoint": rule.endpoint})
        endpoints.sort(key=lambda e: e["path"])
        return jsonify({"count": len(endpoints), "endpoints": endpoints}), 200

    @api_bp.route("/users/me", methods=["GET"])
    @require_api_auth
    def get_current_user():
        return jsonify({
            "success": True,
            "user": {
                "id": current_user.id,
                "email": current_user.email,
                "full_name": current_user.full_name,
                "first_name": current_user.first_name,
                "last_name": current_user.last_name,
                "phone": current_user.phone,
                "is_admin": current_user.is_admin,
                "is_super_admin": getattr(current_user, "is_super_admin", False),
                "is_guest": current_user.is_guest,
                "profile_picture": url_for("settings.profile_picture", filename=current_user.profile_picture) if current_user.profile_picture else None,
                "accent_color": current_user.accent_color,
                "accent_gradient": current_user.accent_gradient,
                "dark_mode": current_user.dark_mode,
                "oled_mode": getattr(current_user, "oled_mode", False),
                "language": getattr(current_user, "language", "de"),
                "preferred_layout": getattr(current_user, "preferred_layout", "auto"),
                "totp_enabled": current_user.totp_enabled,
                "notifications_enabled": current_user.notifications_enabled,
                "chat_notifications": current_user.chat_notifications,
                "email_notifications": current_user.email_notifications,
            },
        }), 200

    @api_bp.route("/modules/active", methods=["GET"])
    @require_api_auth
    def get_active_modules():
        all_modules = [
            "module_chat",
            "module_files",
            "module_calendar",
            "module_email",
            "module_contacts",
            "module_credentials",
            "module_manuals",
            "module_inventory",
            "module_wiki",
            "module_booking",
            "module_music",
        ]

        global_active, user_accessible, module_details = [], [], []
        for module_key in all_modules:
            globally_enabled = is_module_enabled(module_key)
            has_access = bool(globally_enabled and has_module_access(current_user, module_key))
            if globally_enabled:
                global_active.append(module_key)
            if has_access:
                user_accessible.append(module_key)
            role = UserModuleRole.query.filter_by(user_id=current_user.id, module_key=module_key).first()
            module_details.append({
                "key": module_key,
                "globally_enabled": globally_enabled,
                "user_has_access": has_access,
                "user_role_explicit": role is not None,
                "user_role_has_access": role.has_access if role else None,
            })

        return jsonify({
            "success": True,
            "global_active_modules": global_active,
            "user_accessible_modules": user_accessible,
            "modules": module_details,
        }), 200

    @api_bp.route("/appearance/me", methods=["GET"])
    @require_api_auth
    def get_my_appearance():
        return jsonify({
            "success": True,
            "appearance": {
                "accent_color": current_user.accent_color,
                "accent_gradient": current_user.accent_gradient,
                "dark_mode": current_user.dark_mode,
                "oled_mode": getattr(current_user, "oled_mode", False),
                "language": getattr(current_user, "language", "de"),
                "preferred_layout": getattr(current_user, "preferred_layout", "auto"),
            },
        }), 200

