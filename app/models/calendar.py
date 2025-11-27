from datetime import datetime
from app import db


class CalendarEvent(db.Model):
    __tablename__ = 'calendar_events'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(255), nullable=True)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Wiederkehrende Termine
    recurrence_type = db.Column(db.String(20), default='none', nullable=False)  # 'none', 'daily', 'weekly', 'monthly', 'yearly'
    recurrence_end_date = db.Column(db.DateTime, nullable=True)
    recurrence_interval = db.Column(db.Integer, default=1, nullable=False)  # z.B. alle 2 Wochen
    recurrence_days = db.Column(db.String(50), nullable=True)  # Wochentage für wöchentliche Wiederholung (z.B. "1,3,5" für Mo,Mi,Fr)
    parent_event_id = db.Column(db.Integer, db.ForeignKey('calendar_events.id'), nullable=True)
    is_recurring_instance = db.Column(db.Boolean, default=False, nullable=False)
    recurrence_sequence = db.Column(db.Integer, nullable=True)  # Sequenznummer für Instanzen
    
    # Öffentliche iCal-Feeds
    public_ical_token = db.Column(db.String(64), unique=True, nullable=True)
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    
    # Buchungsmodul-Integration
    booking_request_id = db.Column(db.Integer, db.ForeignKey('booking_requests.id'), nullable=True)
    
    # Relationships
    creator = db.relationship('User', back_populates='created_events')
    participants = db.relationship('EventParticipant', back_populates='event', cascade='all, delete-orphan')
    parent_event = db.relationship('CalendarEvent', remote_side=[id], backref='recurring_instances')
    
    def __repr__(self):
        return f'<CalendarEvent {self.title}>'
    
    @property
    def is_master_event(self):
        """Prüft ob dies ein Master-Event für wiederkehrende Termine ist."""
        return self.recurrence_type != 'none' and not self.is_recurring_instance


class EventParticipant(db.Model):
    __tablename__ = 'event_participants'
    
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('calendar_events.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending, accepted, declined, removed
    responded_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    event = db.relationship('CalendarEvent', back_populates='participants')
    user = db.relationship('User', back_populates='event_participations')
    
    __table_args__ = (
        db.UniqueConstraint('event_id', 'user_id', name='unique_event_participant'),
    )
    
    def __repr__(self):
        return f'<EventParticipant event={self.event_id} user={self.user_id} status={self.status}>'


class PublicCalendarFeed(db.Model):
    __tablename__ = 'public_calendar_feeds'
    
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(200), nullable=True)
    include_all_events = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_synced = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    creator = db.relationship('User')
    
    def __repr__(self):
        return f'<PublicCalendarFeed {self.name or self.token}>'



