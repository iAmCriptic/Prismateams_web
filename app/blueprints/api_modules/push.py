from datetime import datetime
import base64
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import jsonify, request, session
from flask_login import current_user, login_required

from app import db
from app.models.notification import PushSubscription
from app.utils.i18n import translate
from app.utils.notifications import register_push_subscription, send_push_notification


def _normalize_vapid_public_key(public_key: str) -> str:
    """Normalisiere einen VAPID Public Key (PEM, DER-SPKI oder Raw) auf unpadded Base64url (65-Byte UncompressedPoint)."""
    key_str = public_key.strip().strip('"').strip("'")
    if "BEGIN PUBLIC KEY" in key_str:
        pem_text = key_str.replace("\\n", "\n")
        pub_obj = serialization.load_pem_public_key(pem_text.encode("utf-8"))
        raw = pub_obj.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    b64_std = "".join(key_str.split()).replace("-", "+").replace("_", "/")
    missing = len(b64_std) % 4
    if missing:
        b64_std += "=" * (4 - missing)
    decoded = base64.b64decode(b64_std)

    if len(decoded) == 65 and decoded[0] == 0x04:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decoded)
        return base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")

    pub_obj = serialization.load_der_public_key(decoded)
    raw = pub_obj.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


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

            key_out = _normalize_vapid_public_key(public_key)
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

            cleanup_failed_subscriptions()
            subscriptions = PushSubscription.query.filter_by(user_id=current_user.id, is_active=True).all()
            if not subscriptions:
                return jsonify({
                    "success": False,
                    "message": "Keine aktiven Push-Subscriptions gefunden. Bitte registrieren Sie sich zuerst für Push-Benachrichtigungen.",
                    "action_required": "subscribe",
                }), 400

            portal_name = current_app.config.get("APP_NAME", "Prismateams")
            try:
                from app.models.settings import SystemSettings

                portal_name_setting = SystemSettings.query.filter_by(key="portal_name").first()
                if portal_name_setting and portal_name_setting.value and portal_name_setting.value.strip():
                    portal_name = portal_name_setting.value.strip()
            except Exception:
                pass

            success = send_push_notification(
                user_id=current_user.id,
                title=translate("notifications.push.test_title", language=current_user.language),
                body=translate(
                    "notifications.push.test_body",
                    language=current_user.language,
                    portal_name=portal_name,
                ),
                url="/dashboard/",
                data={"type": "test", "timestamp": datetime.utcnow().isoformat()},
                dedup_key=f"test:{datetime.utcnow().timestamp()}",
            )
            if success:
                session["last_push_test_time"] = current_time
                return jsonify({"success": True, "message": f"Test-Benachrichtigung erfolgreich gesendet an {len(subscriptions)} Gerät(e)"})
            return jsonify({"success": False, "message": "Test-Benachrichtigung konnte nicht gesendet werden. Bitte prüfen Sie Ihre Push-Subscriptions."}), 400
        except Exception as e:
            return jsonify({"error": str(e), "message": translate("api.errors.test_notification_error")}), 500

