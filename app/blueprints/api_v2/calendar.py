"""
Calendar API namespace.
"""
from flask import request
from flask_restx import Namespace, Resource, fields
from flask_login import login_required, current_user
from datetime import datetime, timedelta

from app.models.calendar import CalendarEvent, EventParticipant

api = Namespace('calendar', description='Kalender')

# Models
event_model = api.model('CalendarEvent', {
    'id': fields.Integer(description='Event-ID'),
    'title': fields.String(description='Titel'),
    'description': fields.String(description='Beschreibung'),
    'start_time': fields.DateTime(description='Startzeit'),
    'end_time': fields.DateTime(description='Endzeit'),
    'location': fields.String(description='Ort'),
    'created_by': fields.String(description='Erstellt von'),
    'participation_status': fields.String(description='Teilnahmestatus'),
    'is_recurring': fields.Boolean(description='Wiederkehrend')
})

event_detail_model = api.inherit('CalendarEventDetail', event_model, {
    'participants': fields.List(fields.Raw, description='Teilnehmer')
})


@api.route('/')
class EventList(Resource):
    @api.doc('list_events', security='Bearer')
    @api.marshal_list_with(event_model)
    @api.param('start', 'Startdatum (YYYY-MM-DD)')
    @api.param('end', 'Enddatum (YYYY-MM-DD)')
    @login_required
    def get(self):
        """
        Termine auflisten.
        
        Gibt alle Termine im angegebenen Zeitraum zurück.
        Standardmäßig werden Termine der nächsten 30 Tage zurückgegeben.
        """
        start_str = request.args.get('start')
        end_str = request.args.get('end')
        
        if start_str:
            try:
                start_date = datetime.strptime(start_str, '%Y-%m-%d')
            except ValueError:
                api.abort(400, 'Ungültiges Startdatum')
        else:
            start_date = datetime.utcnow()
        
        if end_str:
            try:
                end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            except ValueError:
                api.abort(400, 'Ungültiges Enddatum')
        else:
            end_date = start_date + timedelta(days=30)
        
        events = CalendarEvent.query.filter(
            CalendarEvent.start_time >= start_date,
            CalendarEvent.start_time < end_date,
            CalendarEvent.is_recurring_instance == False
        ).order_by(CalendarEvent.start_time).all()
        
        result = []
        for event in events:
            participation = EventParticipant.query.filter_by(
                event_id=event.id,
                user_id=current_user.id
            ).first()
            
            result.append({
                'id': event.id,
                'title': event.title,
                'description': event.description,
                'start_time': event.start_time,
                'end_time': event.end_time,
                'location': event.location,
                'created_by': event.creator.full_name if event.creator else 'Unbekannt',
                'participation_status': participation.status if participation else 'no_response',
                'is_recurring': event.recurrence_type != 'none'
            })
        
        return result


@api.route('/<int:event_id>')
@api.param('event_id', 'Event-ID')
class EventResource(Resource):
    @api.doc('get_event', security='Bearer')
    @api.marshal_with(event_detail_model)
    @api.response(404, 'Termin nicht gefunden')
    @login_required
    def get(self, event_id):
        """
        Termin-Details abrufen.
        
        Gibt detaillierte Informationen zu einem Termin zurück,
        einschließlich aller Teilnehmer.
        """
        event = CalendarEvent.query.get_or_404(event_id)
        
        participation = EventParticipant.query.filter_by(
            event_id=event.id,
            user_id=current_user.id
        ).first()
        
        participants = EventParticipant.query.filter_by(event_id=event.id).all()
        
        return {
            'id': event.id,
            'title': event.title,
            'description': event.description,
            'start_time': event.start_time,
            'end_time': event.end_time,
            'location': event.location,
            'created_by': event.creator.full_name if event.creator else 'Unbekannt',
            'participation_status': participation.status if participation else 'no_response',
            'is_recurring': event.recurrence_type != 'none',
            'participants': [{
                'user_id': p.user_id,
                'user_name': p.user.full_name if p.user else 'Unbekannt',
                'status': p.status
            } for p in participants]
        }


@api.route('/upcoming')
class UpcomingEvents(Resource):
    @api.doc('upcoming_events', security='Bearer')
    @api.marshal_list_with(event_model)
    @api.param('days', 'Anzahl Tage', type=int, default=7)
    @login_required
    def get(self):
        """
        Anstehende Termine abrufen.
        
        Gibt die nächsten Termine für den aktuellen Benutzer zurück.
        """
        days = min(request.args.get('days', 7, type=int), 30)
        
        now = datetime.utcnow()
        end_date = now + timedelta(days=days)
        
        # Get events where user is participant
        participations = EventParticipant.query.filter_by(
            user_id=current_user.id
        ).all()
        
        event_ids = [p.event_id for p in participations]
        
        events = CalendarEvent.query.filter(
            CalendarEvent.id.in_(event_ids),
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time < end_date
        ).order_by(CalendarEvent.start_time).limit(10).all()
        
        result = []
        for event in events:
            participation = next((p for p in participations if p.event_id == event.id), None)
            
            result.append({
                'id': event.id,
                'title': event.title,
                'description': event.description,
                'start_time': event.start_time,
                'end_time': event.end_time,
                'location': event.location,
                'created_by': event.creator.full_name if event.creator else 'Unbekannt',
                'participation_status': participation.status if participation else 'no_response',
                'is_recurring': event.recurrence_type != 'none'
            })
        
        return result
