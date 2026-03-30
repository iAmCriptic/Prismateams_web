from datetime import datetime

from flask import jsonify
from flask_login import current_user

from app.models.calendar import CalendarEvent
from app.models.chat import ChatMember, ChatMessage
from app.models.email import EmailMessage
from app.models.file import File


def register_dashboard_routes(api_bp, require_api_auth):
    @api_bp.route("/dashboard/stats", methods=["GET"])
    @require_api_auth
    def get_dashboard_stats():
        upcoming_events = CalendarEvent.query.filter(CalendarEvent.start_time >= datetime.utcnow()).count()

        user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
        unread_count = 0
        for membership in user_chats:
            count = ChatMessage.query.filter(
                ChatMessage.chat_id == membership.chat_id,
                ChatMessage.created_at > membership.last_read_at,
                ChatMessage.sender_id != current_user.id,
            ).count()
            unread_count += count

        unread_emails = EmailMessage.query.filter_by(is_read=False, is_sent=False).count()
        total_files = File.query.filter_by(is_current=True).count()

        return jsonify({
            "upcoming_events": upcoming_events,
            "unread_messages": unread_count,
            "unread_emails": unread_emails,
            "total_files": total_files,
        })

    @api_bp.route("/email/unread-count", methods=["GET"])
    @require_api_auth
    def get_unread_email_count():
        try:
            unread_count = EmailMessage.query.filter_by(is_read=False).count()
            return jsonify({"count": unread_count})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

