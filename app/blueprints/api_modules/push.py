from datetime import datetime
import base64
import re
import time

from flask import jsonify, request, session
from flask_login import current_user, login_required

from app import db
from app.models.notification import PushSubscription
from app.utils.i18n import translate
from app.utils.notifications import register_push_subscription, send_push_notification


def register_push_routes(api_bp, require_api_auth):
    @api_bp.route("/push/subscribe", methods=["POST"])
    @login_required
    def subscribe_push():
        try:
            data = request.get_json()
            if "subscription" in data:
                subscription_data = data.get("subscription")
            else:
                subscription_data = data
            if not subscription_data:
                return jsonify({"error": translate("api.errors.subscription_data_missing")}), 400

            success = register_push_subscription(current_user.id, subscription_data)
            if success:
                return jsonify({"message": "Push-Subscription erfolgreich registriert", "success": True})
            return jsonify({"error": translate("api.errors.registration_error"), "success": False}), 500
        except Exception as e:
            return jsonify({"error": str(e), "success": False}), 500

    @api_bp.route("/push/unsubscribe", methods=["POST"])
    @login_required
    def unsubscribe_push():
        try:
            subscriptions = PushSubscription.query.filter_by(user_id=current_user.id, is_active=True).all()
            for subscription in subscriptions:
                subscription.is_active = False
            db.session.commit()
            return jsonify({"message": "Push-Subscription erfolgreich deaktiviert"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @api_bp.route("/push/status", methods=["GET"])
    @login_required
    def push_status():
        try:
            active_subscriptions = PushSubscription.query.filter_by(user_id=current_user.id, is_active=True).count()
            return jsonify({
                "has_subscription": active_subscriptions > 0,
                "subscription_count": active_subscriptions,
                "notifications_enabled": current_user.notifications_enabled,
                "chat_notifications": current_user.chat_notifications,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @api_bp.route("/push/vapid-key", methods=["GET"])
    @login_required
    def get_vapid_public_key():
        try:
            from flask import current_app

            public_key = current_app.config.get("VAPID_PUBLIC_KEY")
            if not public_key:
                return jsonify({"error": "VAPID Keys nicht konfiguriert", "message": "Bitte konfigurieren Sie VAPID Keys in der .env Datei"}), 500

            key_out = public_key.strip()
            if "BEGIN PUBLIC KEY" in key_out:
                pem_b64_any = re.sub(r"-----BEGIN PUBLIC KEY-----|-----END PUBLIC KEY-----|\\n|\n|\r|\s", "", key_out)
                pem_b64_std = pem_b64_any.replace("-", "+").replace("_", "/")
                missing = len(pem_b64_std) % 4
                if missing:
                    pem_b64_std += "=" * (4 - missing)
                der = base64.b64decode(pem_b64_std)
                idx = der.find(b"\x04")
                raw = None
                if idx != -1 and idx + 65 <= len(der):
                    candidate = der[idx : idx + 65]
                    if len(candidate) == 65:
                        raw = candidate
                if raw is None:
                    raise ValueError("Konnte EC Public Key (65 Bytes) nicht aus PEM extrahieren")
                key_out = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
            return jsonify({"public_key": key_out})
        except Exception as e:
            return jsonify({"error": str(e), "message": translate("api.errors.vapid_keys_load_error")}), 500

    @api_bp.route("/push/test", methods=["POST"])
    @login_required
    def test_push_notification():
        try:
            from flask import current_app
            from app.utils.notifications import cleanup_failed_subscriptions

            vapid_priv = current_app.config.get("VAPID_PRIVATE_KEY")
            vapid_pub = current_app.config.get("VAPID_PUBLIC_KEY")
            if not vapid_priv or not vapid_pub:
                return jsonify({
                    "success": False,
                    "message": "VAPID Keys sind nicht konfiguriert. Bitte `VAPID_PUBLIC_KEY` und `VAPID_PRIVATE_KEY` in .env setzen oder `vapid_keys.json` bereitstellen.",
                    "action_required": "configure_vapid",
                }), 400

            current_time = time.time()
            last_test_time = session.get("last_push_test_time", 0)
            cooldown_duration = 120
            if current_time - last_test_time < cooldown_duration:
                remaining_time = int(cooldown_duration - (current_time - last_test_time))
                return jsonify({
                    "success": False,
                    "message": f"Bitte warten Sie {remaining_time} Sekunden vor dem nächsten Test.",
                    "cooldown": True,
                    "remaining_seconds": remaining_time,
                    "total_cooldown": cooldown_duration,
                }), 429
            session["last_push_test_time"] = current_time

            cleanup_failed_subscriptions()
            subscriptions = PushSubscription.query.filter_by(user_id=current_user.id, is_active=True).all()
            if not subscriptions:
                return jsonify({
                    "success": False,
                    "message": "Keine aktiven Push-Subscriptions gefunden. Bitte registrieren Sie sich zuerst für Push-Benachrichtigungen.",
                    "action_required": "subscribe",
                }), 400

            success = send_push_notification(
                user_id=current_user.id,
                title="Test-Benachrichtigung",
                body="Dies ist eine Test-Push-Benachrichtigung vom Team Portal.",
                url="/dashboard/",
                data={"type": "test", "timestamp": datetime.utcnow().isoformat()},
            )
            if success:
                return jsonify({"success": True, "message": f"Test-Benachrichtigung erfolgreich gesendet an {len(subscriptions)} Gerät(e)"})
            return jsonify({"success": False, "message": "Test-Benachrichtigung konnte nicht gesendet werden. Bitte prüfen Sie Ihre Push-Subscriptions."}), 400
        except Exception as e:
            return jsonify({"error": str(e), "message": translate("api.errors.test_notification_error")}), 500

