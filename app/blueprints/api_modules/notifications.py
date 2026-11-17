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
    'calendar_invite': 'bi-calendar-plus',
    'file': 'bi-folder',
    'booking': 'bi-calendar2-check',
    'room_booking': 'bi-door-open',
    'inventory': 'bi-box-seam',
    'kanban': 'bi-kanban',
    'comment': 'bi-chat-left-text',
    'comment_mention': 'bi-at',
    'survey': 'bi-ui-checks-grid',
    'test': 'bi-bell',
    'generic': 'bi-bell',
}


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
                # sent_at ist UTC (datetime.utcnow); ohne Z wertet JS die Zeit als lokal → Offset-Bug
                "sent_at": (n.sent_at.isoformat() + "Z") if n.sent_at else None,
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

def get_notification_settings():
    try:
        from app.utils.notifications import get_or_create_notification_settings

        settings = get_or_create_notification_settings(current_user.id)
        return jsonify({
            "is_paused": settings.is_paused(),
            "notifications_paused_until": settings.notifications_paused_until.isoformat() if settings.notifications_paused_until else None,
            "chat_notifications_enabled": settings.chat_notifications_enabled,
            "file_notifications_enabled": settings.file_notifications_enabled,
            "file_new_notifications": settings.file_new_notifications,
            "file_modified_notifications": settings.file_modified_notifications,
            "email_notifications_enabled": settings.email_notifications_enabled,
            "booking_notifications_enabled": getattr(settings, "booking_notifications_enabled", True),
            "booking_message_notifications_enabled": getattr(settings, "booking_message_notifications_enabled", True),
            "calendar_notifications_enabled": settings.calendar_notifications_enabled,
            "calendar_all_events": settings.calendar_all_events,
            "calendar_participating_only": settings.calendar_participating_only,
            "calendar_not_participating": settings.calendar_not_participating,
            "calendar_no_response": settings.calendar_no_response,
            "reminder_times": settings.get_reminder_times(),
            # Portal channels
            "chat_portal_enabled": getattr(settings, "chat_portal_enabled", True),
            "kanban_portal_enabled": getattr(settings, "kanban_portal_enabled", True),
            "email_portal_enabled": getattr(settings, "email_portal_enabled", True),
            "comment_portal_enabled": getattr(settings, "comment_portal_enabled", True),
            "inventory_portal_enabled": getattr(settings, "inventory_portal_enabled", True),
            "booking_portal_enabled": getattr(settings, "booking_portal_enabled", True),
            "room_booking_portal_enabled": getattr(settings, "room_booking_portal_enabled", True),
            "survey_portal_enabled": getattr(settings, "survey_portal_enabled", True),
            "calendar_portal_enabled": getattr(settings, "calendar_portal_enabled", True),
            "file_portal_enabled": getattr(settings, "file_portal_enabled", True),
            # Push channels
            "chat_push_enabled": getattr(settings, "chat_push_enabled", True),
            "kanban_push_enabled": getattr(settings, "kanban_push_enabled", True),
            "email_push_enabled": getattr(settings, "email_push_enabled", True),
            "comment_push_enabled": getattr(settings, "comment_push_enabled", True),
            "inventory_push_enabled": getattr(settings, "inventory_push_enabled", True),
            "booking_push_enabled": getattr(settings, "booking_push_enabled", True),
            "room_booking_push_enabled": getattr(settings, "room_booking_push_enabled", True),
            "survey_push_enabled": getattr(settings, "survey_push_enabled", True),
            "calendar_push_enabled": getattr(settings, "calendar_push_enabled", True),
            "file_push_enabled": getattr(settings, "file_push_enabled", True),
            # Sub-options
            "comment_mention_notifications": getattr(settings, "comment_mention_notifications", True),
            "comment_reply_notifications": getattr(settings, "comment_reply_notifications", True),
            "survey_new_notifications": getattr(settings, "survey_new_notifications", True),
            "survey_response_notifications": getattr(settings, "survey_response_notifications", True),
            "room_booking_new_notifications": getattr(settings, "room_booking_new_notifications", True),
            "room_booking_status_notifications": getattr(settings, "room_booking_status_notifications", True),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def update_notification_settings():
    try:
        from app.utils.notifications import (
            get_or_create_notification_settings,
            sync_user_notification_flags,
        )

        data = request.get_json() or {}
        settings = get_or_create_notification_settings(current_user.id)
        
        # Portal channels
        for field in [
            "chat_portal_enabled", "kanban_portal_enabled", "email_portal_enabled",
            "comment_portal_enabled", "inventory_portal_enabled", "booking_portal_enabled",
            "room_booking_portal_enabled", "survey_portal_enabled", "calendar_portal_enabled",
            "file_portal_enabled",
            "chat_push_enabled", "kanban_push_enabled", "email_push_enabled",
            "comment_push_enabled", "inventory_push_enabled", "booking_push_enabled",
            "room_booking_push_enabled", "survey_push_enabled", "calendar_push_enabled",
            "file_push_enabled",
            "comment_mention_notifications", "comment_reply_notifications",
            "survey_new_notifications", "survey_response_notifications",
            "room_booking_new_notifications", "room_booking_status_notifications",
        ]:
            if field in data:
                setattr(settings, field, bool(data[field]))

        if "chat_notifications_enabled" in data:
            settings.chat_notifications_enabled = bool(data["chat_notifications_enabled"])
        if "file_notifications_enabled" in data:
            settings.file_notifications_enabled = bool(data["file_notifications_enabled"])
        if "file_new_notifications" in data:
            settings.file_new_notifications = bool(data["file_new_notifications"])
        if "file_modified_notifications" in data:
            settings.file_modified_notifications = bool(data["file_modified_notifications"])
        if "email_notifications_enabled" in data:
            settings.email_notifications_enabled = bool(data["email_notifications_enabled"])
        if "booking_notifications_enabled" in data:
            settings.booking_notifications_enabled = bool(data["booking_notifications_enabled"])
        if "booking_message_notifications_enabled" in data:
            settings.booking_message_notifications_enabled = bool(data["booking_message_notifications_enabled"])
        if "calendar_notifications_enabled" in data:
            settings.calendar_notifications_enabled = bool(data["calendar_notifications_enabled"])
        if "calendar_all_events" in data:
            settings.calendar_all_events = bool(data["calendar_all_events"])
        if "calendar_participating_only" in data:
            settings.calendar_participating_only = bool(data["calendar_participating_only"])
        if "calendar_not_participating" in data:
            settings.calendar_not_participating = bool(data["calendar_not_participating"])
        if "calendar_no_response" in data:
            settings.calendar_no_response = bool(data["calendar_no_response"])
        if "reminder_times" in data:
            settings.set_reminder_times(data.get("reminder_times", []))
            
        sync_user_notification_flags(current_user, settings)
        db.session.commit()
        return jsonify({"message": "Benachrichtigungseinstellungen aktualisiert"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        from app.utils.notifications import emit_notification_badge
        emit_notification_badge(current_user.id, unread_count)
        return jsonify({
            "success": True,
            "message": "Benachrichtigung als gelesen markiert",
            "unread_count": unread_count,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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
        from app.utils.notifications import emit_notification_badge
        emit_notification_badge(current_user.id, 0)
        return jsonify({
            "success": True,
            "updated": int(updated or 0),
            "unread_count": 0,
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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
        from app.utils.notifications import emit_notification_badge
        emit_notification_badge(current_user.id, unread_count)
        return jsonify({"success": True, "unread_count": unread_count}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

def delete_all_notifications():
    try:
        deleted = NotificationLog.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        from app.utils.notifications import emit_notification_badge
        emit_notification_badge(current_user.id, 0)
        return jsonify({
            "success": True,
            "deleted": int(deleted or 0),
            "unread_count": 0,
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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

def register_notification_routes(api_bp, require_api_auth):
    """Bind module-level views onto the API blueprint."""
    def _bind(rule, view, methods, auth):
        api_bp.add_url_rule(rule, view.__name__, auth(view), methods=methods)

    _bind('/notifications/pending', get_pending_notifications, ['GET'], require_api_auth)
    _bind('/notifications/settings', get_notification_settings, ['GET'], login_required)
    _bind('/notifications/settings', update_notification_settings, ['POST'], login_required)
    _bind('/notifications/chat/<int:chat_id>', update_chat_notification_settings, ['POST'], login_required)
    _bind('/notifications/mark-read/<int:notification_id>', mark_notification_read, ['POST'], require_api_auth)
    _bind('/notifications/mark-all-read', mark_all_notifications_read, ['POST'], require_api_auth)
    _bind('/notifications/<int:notification_id>', delete_notification, ['DELETE'], require_api_auth)
    _bind('/notifications/delete-all', delete_all_notifications, ['POST'], require_api_auth)
    _bind('/notifications/reset-push', reset_push_notifications, ['POST'], require_api_auth)
