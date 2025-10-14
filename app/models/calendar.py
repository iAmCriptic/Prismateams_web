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
    
    # Relationships
    creator = db.relationship('User', back_populates='created_events')
    participants = db.relationship('EventParticipant', back_populates='event', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<CalendarEvent {self.title}>'


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



