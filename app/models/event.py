from datetime import datetime
from app import db


class Event(db.Model):
    __tablename__ = 'events'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    default_location = db.Column(db.String(255), nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    folder = db.relationship('Folder')
    owner = db.relationship('User', foreign_keys=[owner_id])
    creator = db.relationship('User', foreign_keys=[created_by])
    appointments = db.relationship('EventAppointment', back_populates='event', cascade='all, delete-orphan', order_by='EventAppointment.start_time')
    assignments = db.relationship('EventAssignment', back_populates='event', cascade='all, delete-orphan')
    contacts = db.relationship('EventContact', back_populates='event', cascade='all, delete-orphan')
    timeline_items = db.relationship('EventTimelineItem', back_populates='event', cascade='all, delete-orphan', order_by='EventTimelineItem.position')

    def __repr__(self):
        return f'<Event {self.name}>'


class EventAppointment(db.Model):
    __tablename__ = 'event_appointments'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False, index=True)
    label = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time = db.Column(db.DateTime, nullable=False, index=True)
    location = db.Column(db.String(255), nullable=True)
    calendar_event_id = db.Column(db.Integer, db.ForeignKey('calendar_events.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    event = db.relationship('Event', back_populates='appointments')
    calendar_event = db.relationship('CalendarEvent')
    inventory_needs = db.relationship('EventInventoryNeed', back_populates='appointment', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<EventAppointment event={self.event_id} label={self.label}>'


class EventAssignment(db.Model):
    __tablename__ = 'event_assignments'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    display_name = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship('Event', back_populates='assignments')
    user = db.relationship('User')

    __table_args__ = (
        db.UniqueConstraint('event_id', 'user_id', name='uq_event_assignment_user'),
    )

    def __repr__(self):
        return f'<EventAssignment event={self.event_id} user={self.user_id} name={self.display_name}>'


class EventInventoryNeed(db.Model):
    __tablename__ = 'event_inventory_needs'

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('event_appointments.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    appointment = db.relationship('EventAppointment', back_populates='inventory_needs')
    product = db.relationship('Product')

    __table_args__ = (
        db.UniqueConstraint('appointment_id', 'product_id', name='uq_event_need_product'),
    )

    def __repr__(self):
        return f'<EventInventoryNeed appointment={self.appointment_id} product={self.product_id} qty={self.quantity}>'


class EventContact(db.Model):
    __tablename__ = 'event_contacts'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship('Event', back_populates='contacts')

    def __repr__(self):
        return f'<EventContact event={self.event_id} name={self.name}>'


class EventTimelineItem(db.Model):
    __tablename__ = 'event_timeline_items'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('event_appointments.id'), nullable=True, index=True)
    position = db.Column(db.Integer, default=0, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship('Event', back_populates='timeline_items')
    appointment = db.relationship('EventAppointment')

    def __repr__(self):
        return f'<EventTimelineItem event={self.event_id} pos={self.position} title={self.title}>'
