from datetime import datetime

from app import db
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.event import EventAssignment
from app.models.user import User


class EventService:
    @staticmethod
    def _calendar_title(event_name, appointment_label):
        return f"{event_name} - {appointment_label}"

    @staticmethod
    def sync_calendar_for_appointment(event_obj, appointment, actor_user_id):
        calendar_event = appointment.calendar_event
        if calendar_event is None:
            calendar_event = CalendarEvent(
                created_by=actor_user_id,
                recurrence_type='none',
            )
            db.session.add(calendar_event)
            appointment.calendar_event = calendar_event

        calendar_event.title = EventService._calendar_title(event_obj.name, appointment.label)
        calendar_event.description = appointment.description or event_obj.description
        calendar_event.start_time = appointment.start_time
        calendar_event.end_time = appointment.end_time
        calendar_event.location = appointment.location or event_obj.default_location

        assigned_user_ids = {
            assignment.user_id
            for assignment in event_obj.assignments
            if assignment.user_id is not None
        }
        active_users = User.query.filter_by(is_active=True).all()
        participant_by_user = {
            participant.user_id: participant
            for participant in EventParticipant.query.filter_by(event_id=calendar_event.id).all()
        }

        for user in active_users:
            target_status = 'accepted' if user.id in assigned_user_ids else 'declined'
            participant = participant_by_user.get(user.id)
            if participant is None:
                participant = EventParticipant(
                    event_id=calendar_event.id,
                    user_id=user.id,
                    status=target_status,
                    responded_at=datetime.utcnow(),
                )
                db.session.add(participant)
            else:
                participant.status = target_status
                participant.responded_at = datetime.utcnow()

    @staticmethod
    def sync_calendar_for_event(event_obj, actor_user_id):
        for appointment in event_obj.appointments:
            EventService.sync_calendar_for_appointment(event_obj, appointment, actor_user_id)

    @staticmethod
    def remove_orphan_calendar_entries(event_obj):
        for appointment in event_obj.appointments:
            if appointment.calendar_event:
                db.session.delete(appointment.calendar_event)
