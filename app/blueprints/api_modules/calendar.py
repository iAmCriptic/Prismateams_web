from datetime import datetime, timedelta

from flask import jsonify
from flask_login import current_user, login_required

from app.models.calendar import CalendarEvent, EventParticipant


def register_calendar_routes(api_bp, require_api_auth):
    @api_bp.route("/events", methods=["GET"])
    @login_required
    def get_events():
        events = CalendarEvent.query.order_by(CalendarEvent.start_time).all()
        result = []
        for event in events:
            participation = EventParticipant.query.filter_by(
                event_id=event.id,
                user_id=current_user.id,
            ).first()
            result.append({
                "id": event.id,
                "title": event.title,
                "description": event.description,
                "start_time": event.start_time.isoformat(),
                "end_time": event.end_time.isoformat(),
                "location": event.location,
                "event_color": event.event_color,
                "created_by": event.creator.full_name,
                "participation_status": participation.status if participation else "pending",
            })
        return jsonify(result)

    @api_bp.route("/events/<int:event_id>", methods=["GET"])
    @login_required
    def get_event(event_id):
        event = CalendarEvent.query.get_or_404(event_id)
        participants = EventParticipant.query.filter_by(event_id=event_id).all()
        return jsonify({
            "id": event.id,
            "title": event.title,
            "description": event.description,
            "start_time": event.start_time.isoformat(),
            "end_time": event.end_time.isoformat(),
            "location": event.location,
            "event_color": event.event_color,
            "created_by": event.creator.full_name,
            "participants": [{
                "user_id": p.user_id,
                "user_name": p.user.full_name,
                "status": p.status,
            } for p in participants],
        })

    @api_bp.route("/calendar/upcoming-count", methods=["GET"])
    @require_api_auth
    def get_upcoming_events_count():
        try:
            now = datetime.utcnow()
            week_from_now = now + timedelta(days=7)
            upcoming_count = CalendarEvent.query.filter(
                CalendarEvent.start_time > now,
                CalendarEvent.start_time <= week_from_now,
            ).count()
            return jsonify({"count": upcoming_count})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

