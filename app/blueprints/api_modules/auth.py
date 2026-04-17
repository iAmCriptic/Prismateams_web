from datetime import datetime, timedelta

from flask import jsonify, request, session as flask_session, url_for
from flask_login import current_user, login_user

from app import db
from app.models.api_token import ApiToken
from app.models.user import User
from app.utils.session_manager import create_session
from app.utils.totp import verify_totp


def _user_payload(user):
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_admin": user.is_admin,
        "is_guest": user.is_guest,
        "profile_picture": url_for("settings.profile_picture", filename=user.profile_picture) if user.profile_picture else None,
        "accent_color": user.accent_color,
        "dark_mode": user.dark_mode,
        "totp_enabled": user.totp_enabled,
    }


def register_auth_routes(api_bp, require_api_auth, limiter):
    @api_bp.route("/auth/login", methods=["POST"])
    @limiter.limit("5 per 15 minutes")
    def api_login():
        try:
            data = request.get_json()
            if not data:
                return jsonify({"success": False, "error": "Keine Daten übermittelt"}), 400

            email = data.get("email", "").strip().lower()
            password = data.get("password", "")
            totp_code = data.get("totp_code", "").strip()
            remember = data.get("remember", False)
            return_token = data.get("return_token", False)

            if not email or not password:
                return jsonify({"success": False, "error": "E-Mail und Passwort sind erforderlich"}), 400

            if email.endswith("@gast.system.local"):
                guest_username = email.replace("@gast.system.local", "")
                user = User.query.filter_by(guest_username=guest_username, is_guest=True).first()
            else:
                user = User.query.filter_by(email=email).first()

            if user and user.failed_login_until and datetime.utcnow() < user.failed_login_until:
                remaining_seconds = int((user.failed_login_until - datetime.utcnow()).total_seconds())
                return jsonify({
                    "success": False,
                    "error": f"Account gesperrt. Bitte warten Sie {remaining_seconds} Sekunden.",
                    "account_locked": True,
                    "remaining_seconds": remaining_seconds,
                }), 423

            if not user or not user.check_password(password):
                if user:
                    user.failed_login_attempts += 1
                    if user.failed_login_attempts >= 5:
                        user.failed_login_until = datetime.utcnow() + timedelta(minutes=15)
                        user.failed_login_attempts = 0
                    db.session.commit()
                return jsonify({"success": False, "error": "Ungültige Zugangsdaten"}), 401

            user.failed_login_attempts = 0
            user.failed_login_until = None

            if user.is_guest and user.guest_expires_at and datetime.utcnow() > user.guest_expires_at:
                db.session.delete(user)
                db.session.commit()
                return jsonify({"success": False, "error": "Gast-Account ist abgelaufen"}), 401

            if not user.is_active:
                return jsonify({"success": False, "error": "Account ist nicht aktiviert"}), 403

            if user.totp_enabled and user.totp_secret:
                if not totp_code:
                    return jsonify({
                        "success": False,
                        "requires_2fa": True,
                        "message": "2FA-Code erforderlich",
                        "error": "Bitte geben Sie den 2FA-Code ein",
                    }), 200
                if not verify_totp(user.totp_secret, totp_code):
                    user.failed_login_attempts += 1
                    if user.failed_login_attempts >= 5:
                        user.failed_login_until = datetime.utcnow() + timedelta(minutes=15)
                        user.failed_login_attempts = 0
                    db.session.commit()
                    return jsonify({"success": False, "requires_2fa": True, "error": "Ungültiger 2FA-Code"}), 401

            if not user.is_guest and not user.is_email_confirmed and not user.is_admin:
                return jsonify({
                    "success": False,
                    "requires_email_confirmation": True,
                    "error": "E-Mail-Bestätigung erforderlich",
                }), 403

            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)

            if not return_token:
                create_session(user.id)

            response_data = {"success": True, "user": _user_payload(user)}
            if return_token:
                token = ApiToken.create_token(user_id=user.id, name="API Login", expires_in_days=30)
                response_data["token"] = token.token
                response_data["token_expires_at"] = token.expires_at.isoformat() if token.expires_at else None

            return jsonify(response_data), 200
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @api_bp.route("/auth/logout", methods=["POST"])
    def api_logout():
        from flask_login import logout_user
        from app.utils.session_manager import revoke_session_by_id

        if current_user.is_authenticated:
            session_id = flask_session.get("session_id")
            if session_id:
                revoke_session_by_id(session_id)
            logout_user()

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "").strip()
            api_token = ApiToken.query.filter_by(token=token).first()
            if api_token:
                db.session.delete(api_token)
                db.session.commit()

        return jsonify({"success": True, "message": "Erfolgreich abgemeldet"}), 200

    @api_bp.route("/auth/verify-token", methods=["POST"])
    def api_verify_token():
        try:
            data = request.get_json()
            if not data:
                return jsonify({"success": False, "error": "Keine Daten übermittelt"}), 400

            token = data.get("token", "").strip()
            if not token:
                return jsonify({"success": False, "error": "Token erforderlich"}), 400

            api_token = ApiToken.query.filter_by(token=token, expires_at=None).first()
            if not api_token:
                api_token = ApiToken.query.filter_by(token=token).first()
                if not api_token or api_token.is_expired():
                    return jsonify({"success": False, "error": "Ungültiger oder abgelaufener Token"}), 401

            user = api_token.user
            if not user or not user.is_active:
                return jsonify({"success": False, "error": "Benutzer ist nicht aktiv"}), 401

            api_token.mark_as_used()
            return jsonify({"success": True, "user": _user_payload(user)}), 200
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

