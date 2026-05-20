from flask import jsonify, request
from flask_login import current_user, login_required

from app import db
from app.models.chat import ChatMember
from app.models.notification import NotificationLog, PushSubscription
from app.utils.i18n import translate

NOTIFICATION_TYPE_ICONS = {
    'chat': 'bi-chat-dots',
    'email': 'bi-envelope',
    'calendar': 'bi-calendar-event',
    'file': 'bi-folder',
    'test': 'bi-bell',
    'generic': 'bi-bell',
}


def register_notification_routes(api_bp, require_api_auth):
    @api_bp.route("/notifications/pending", methods=["GET"])
    @require_api_auth
    def get_pending_notifications():
        """Liefert ungelesene Benachrichtigungen für die Glockenliste."""
        try:
            limit = request.args.get("limit", default=20, type=int)
            if limit is None or limit < 1:
                limit = 20
            limit = min(limit, 100)

            notifications = (
                NotificationLog.query.filter_by(user_id=current_user.id, is_read=False)
                .order_by(NotificationLog.sent_at.desc())
                .limit(limit)
                .all()
            )

            items = []
            for n in notifications:
                ntype = n.notification_type or 'generic'
                items.append({
                    "id": n.id,
                    "title": n.title,
                    "body": n.body or "",
                    "icon": n.icon,
                    "url": n.url,
                    "type": ntype,
                    "icon_class": NOTIFICATION_TYPE_ICONS.get(ntype, 'bi-bell'),
                    "source_id": n.source_id,
                    "dedup_key": n.dedup_key,
                    "sent_at": n.sent_at.isoformat() if n.sent_at else None,
                })

            unread_count = NotificationLog.query.filter_by(
                user_id=current_user.id,
                is_read=False,
            ).count()

            return jsonify({
                "success": True,
                "count": len(items),
                "unread_count": unread_count,
                "items": items,
            }), 200
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @api_bp.route("/notifications/settings", methods=["GET"])
    @login_required
    def get_notification_settings():
        try:
            from app.utils.notifications import get_or_create_notification_settings

            settings = get_or_create_notification_settings(current_user.id)
            return jsonify({
                "chat_notifications_enabled": settings.chat_notifications_enabled,
                "file_notifications_enabled": settings.file_notifications_enabled,
                "file_new_notifications": settings.file_new_notifications,
                "file_modified_notifications": settings.file_modified_notifications,
                "email_notifications_enabled": settings.email_notifications_enabled,
                "calendar_notifications_enabled": settings.calendar_notifications_enabled,
                "calendar_all_events": settings.calendar_all_events,
                "calendar_participating_only": settings.calendar_participating_only,
                "calendar_not_participating": settings.calendar_not_participating,
                "calendar_no_response": settings.calendar_no_response,
                "reminder_times": settings.get_reminder_times(),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @api_bp.route("/notifications/settings", methods=["POST"])
    @login_required
    def update_notification_settings():
        try:
            from app.utils.notifications import get_or_create_notification_settings

            data = request.get_json()
            settings = get_or_create_notification_settings(current_user.id)
            settings.chat_notifications_enabled = data.get("chat_notifications_enabled", True)
            settings.file_notifications_enabled = data.get("file_notifications_enabled", True)
            settings.file_new_notifications = data.get("file_new_notifications", True)
            settings.file_modified_notifications = data.get("file_modified_notifications", True)
            settings.email_notifications_enabled = data.get("email_notifications_enabled", True)
            settings.calendar_notifications_enabled = data.get("calendar_notifications_enabled", True)
            settings.calendar_all_events = data.get("calendar_all_events", False)
            settings.calendar_participating_only = data.get("calendar_participating_only", True)
            settings.calendar_not_participating = data.get("calendar_not_participating", False)
            settings.calendar_no_response = data.get("calendar_no_response", False)
            settings.set_reminder_times(data.get("reminder_times", []))
            db.session.commit()
            return jsonify({"message": "Benachrichtigungseinstellungen aktualisiert"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @api_bp.route("/notifications/chat/<int:chat_id>", methods=["POST"])
    @login_required
    def update_chat_notification_settings(chat_id):
        try:
            from app.models.notification import ChatNotificationSettings

            data = request.get_json()
            enabled = data.get("enabled", True)
            membership = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()
            if not membership:
                return jsonify({"error": translate("api.errors.unauthorized")}), 403

            chat_settings = ChatNotificationSettings.query.filter_by(
                user_id=current_user.id,
                chat_id=chat_id,
            ).first()
            if not chat_settings:
                chat_settings = ChatNotificationSettings(
                    user_id=current_user.id,
                    chat_id=chat_id,
                    notifications_enabled=enabled,
                )
                db.session.add(chat_settings)
            else:
                chat_settings.notifications_enabled = enabled
            db.session.commit()
            return jsonify({"message": "Chat-Benachrichtigungseinstellungen aktualisiert"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @api_bp.route("/notifications/mark-read/<int:notification_id>", methods=["POST"])
    @require_api_auth
    def mark_notification_read(notification_id):
        try:
            notification = NotificationLog.query.filter_by(
                id=notification_id, user_id=current_user.id
            ).first()
            if not notification:
                return jsonify({
                    "success": False,
                    "error": translate("api.errors.notification_not_found"),
                }), 404
            notification.is_read = True
            notification.read_at = db.func.now()
            db.session.commit()
            unread_count = NotificationLog.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()
            return jsonify({
                "success": True,
                "message": "Benachrichtigung als gelesen markiert",
                "unread_count": unread_count,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @api_bp.route("/notifications/mark-all-read", methods=["POST"])
    @require_api_auth
    def mark_all_notifications_read():
        try:
            updated = NotificationLog.query.filter_by(
                user_id=current_user.id,
                is_read=False,
            ).update(
                {NotificationLog.is_read: True, NotificationLog.read_at: db.func.now()},
                synchronize_session=False,
            )
            db.session.commit()
            return jsonify({
                "success": True,
                "updated": int(updated or 0),
                "unread_count": 0,
            }), 200
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @api_bp.route("/notifications/<int:notification_id>", methods=["DELETE"])
    @require_api_auth
    def delete_notification(notification_id):
        try:
            notification = NotificationLog.query.filter_by(
                id=notification_id, user_id=current_user.id
            ).first()
            if not notification:
                return jsonify({
                    "success": False,
                    "error": translate("api.errors.notification_not_found"),
                }), 404
            db.session.delete(notification)
            db.session.commit()
            unread_count = NotificationLog.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()
            return jsonify({"success": True, "unread_count": unread_count}), 200
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @api_bp.route("/notifications/delete-all", methods=["POST"])
    @require_api_auth
    def delete_all_notifications():
        try:
            deleted = NotificationLog.query.filter_by(user_id=current_user.id).delete()
            db.session.commit()
            return jsonify({
                "success": True,
                "deleted": int(deleted or 0),
                "unread_count": 0,
            }), 200
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @api_bp.route("/notifications/reset-push", methods=["POST"])
    @require_api_auth
    def reset_push_notifications():
        """Deaktiviert alle Web-Push-Subscriptions des aktuellen Nutzers."""
        try:
            from app.utils.notifications import reset_user_push_subscriptions

            count = reset_user_push_subscriptions(current_user.id)
            return jsonify({
                "success": True,
                "deactivated": count,
                "message": "Push-Abonnements wurden zurückgesetzt",
            }), 200
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
