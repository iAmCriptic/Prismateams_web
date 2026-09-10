from flask import jsonify
from flask_login import current_user

from app.models.calendar import CalendarEvent
from app.models.file import File
from app.utils.common import portal_now_naive
from app.utils.email_counts import count_unread_emails
from app.utils.chat_unread import total_unread_count_for_user


def register_dashboard_routes(api_bp, require_api_auth):
    @api_bp.route("/dashboard/stats", methods=["GET"])
    @require_api_auth
    def get_dashboard_stats():
        upcoming_events = CalendarEvent.query.filter(CalendarEvent.start_time >= portal_now_naive()).count()
        unread_count = total_unread_count_for_user(current_user.id)
        unread_emails = count_unread_emails(user=current_user)
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
            from app.utils.email_counts import count_unread_emails_by_folder

            return jsonify({
                "count": count_unread_emails(user=current_user),
                "by_folder": count_unread_emails_by_folder(
                    user=current_user, all_accessible=True
                ),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

