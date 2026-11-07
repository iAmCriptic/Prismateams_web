from datetime import datetime
from app import db


class Event(db.Model):
    __tablename__ = 'events'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    default_location = db.Column(db.String(255), nullable=True)
    is_multiday = db.Column(db.Boolean, default=False, nullable=False)
    start_date = db.Column(db.Date, nullable=True, index=True)
    end_date = db.Column(db.Date, nullable=True, index=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True, index=True)
    kanban_board_id = db.Column(db.Integer, db.ForeignKey('kanban_boards.id', ondelete='SET NULL'), nullable=True, index=True)
    kanban_card_id = db.Column(db.Integer, db.ForeignKey('kanban_cards.id', ondelete='SET NULL'), nullable=True, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    folder = db.relationship('Folder')
    kanban_board = db.relationship('KanbanBoard', foreign_keys=[kanban_board_id])
    kanban_card = db.relationship('KanbanCard', foreign_keys=[kanban_card_id])
    owner = db.relationship('User', foreign_keys=[owner_id])
    creator = db.relationship('User', foreign_keys=[created_by])
    days = db.relationship('EventDay', back_populates='event', cascade='all, delete-orphan', order_by='EventDay.day_number, EventDay.date')
    appointments = db.relationship('EventAppointment', back_populates='event', cascade='all, delete-orphan', order_by='EventAppointment.start_time')
    assignments = db.relationship('EventAssignment', back_populates='event', cascade='all, delete-orphan')
    contacts = db.relationship('EventContact', back_populates='event', cascade='all, delete-orphan')
    timeline_items = db.relationship('EventTimelineItem', back_populates='event', cascade='all, delete-orphan', order_by='EventTimelineItem.position')
    todo_lists = db.relationship('EventTodoList', back_populates='event', cascade='all, delete-orphan', order_by='EventTodoList.id')
    booking_personal_links = db.relationship('EventBookingPersonalLink', back_populates='event', cascade='all, delete-orphan')
    custom_values = db.relationship('EventCustomFieldValue', back_populates='event', cascade='all, delete-orphan')
    links = db.relationship('EventLink', back_populates='event', cascade='all, delete-orphan')

    @property
    def custom_values_dict(self):
        return {cv.field_id: cv.value for cv in self.custom_values}

    def __repr__(self):
        return f'<Event {self.name}>'


class EventDay(db.Model):
    __tablename__ = 'event_days'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    day_number = db.Column(db.Integer, nullable=False, default=1)
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    location = db.Column(db.String(255), nullable=True)
    label = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship('Event', back_populates='days')
    appointments = db.relationship('EventAppointment', back_populates='day')
    todo_lists = db.relationship('EventTodoList', back_populates='day', cascade='all, delete-orphan', order_by='EventTodoList.id')

    __table_args__ = (
        db.UniqueConstraint('event_id', 'day_number', name='uq_event_day_number'),
    )

    def __repr__(self):
        return f'<EventDay event={self.event_id} day={self.day_number} date={self.date}>'


class EventAppointment(db.Model):
    __tablename__ = 'event_appointments'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False, index=True)
    day_id = db.Column(db.Integer, db.ForeignKey('event_days.id', ondelete='SET NULL'), nullable=True, index=True)
    label = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time = db.Column(db.DateTime, nullable=False, index=True)
    location = db.Column(db.String(255), nullable=True)
    calendar_event_id = db.Column(db.Integer, db.ForeignKey('calendar_events.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    event = db.relationship('Event', back_populates='appointments')
    day = db.relationship('EventDay', back_populates='appointments')
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


class EventTodoList(db.Model):
    __tablename__ = 'event_todo_lists'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    day_id = db.Column(db.Integer, db.ForeignKey('event_days.id', ondelete='CASCADE'), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship('Event', back_populates='todo_lists')
    day = db.relationship('EventDay', back_populates='todo_lists')
    creator = db.relationship('User', foreign_keys=[created_by])
    items = db.relationship(
        'EventTodoItem',
        back_populates='todo_list',
        cascade='all, delete-orphan',
        order_by='EventTodoItem.position, EventTodoItem.id',
    )

    @property
    def completed_count(self):
        return sum(1 for item in self.items if item.is_completed)

    @property
    def total_count(self):
        return len(self.items)

    @property
    def progress_percent(self):
        if not self.items:
            return 0
        return int((self.completed_count / self.total_count) * 100)

    def __repr__(self):
        return f'<EventTodoList id={self.id} event={self.event_id} title={self.title}>'


class EventTodoItem(db.Model):
    __tablename__ = 'event_todo_items'

    id = db.Column(db.Integer, primary_key=True)
    todo_list_id = db.Column(db.Integer, db.ForeignKey('event_todo_lists.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    is_completed = db.Column(db.Boolean, default=False, nullable=False, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    due_time = db.Column(db.Time, nullable=True)
    position = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    todo_list = db.relationship('EventTodoList', back_populates='items')
    completed_by = db.relationship('User', foreign_keys=[completed_by_id])
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_user_id])

    def __repr__(self):
        return f'<EventTodoItem id={self.id} list={self.todo_list_id} done={self.is_completed}>'


class EventBookingPersonalLink(db.Model):
    __tablename__ = 'event_booking_personal_links'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    booking_personal_event_id = db.Column(db.Integer, db.ForeignKey('booking_personal_events.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship('Event', back_populates='booking_personal_links')
    booking_personal_event = db.relationship('BookingPersonalEvent')

    __table_args__ = (
        db.UniqueConstraint('event_id', 'booking_personal_event_id', name='uq_event_booking_personal_link'),
    )

    def __repr__(self):
        return f'<EventBookingPersonalLink event={self.event_id} booking={self.booking_personal_event_id}>'


class EventCustomField(db.Model):
    __tablename__ = 'event_custom_fields'

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), default='Allgemein', nullable=False)
    field_type = db.Column(db.String(30), nullable=False, default='text')
    options = db.Column(db.Text, nullable=True)  # JSON-encoded array or newline-delimited options for select
    placeholder = db.Column(db.String(255), nullable=True)
    position = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    values = db.relationship('EventCustomFieldValue', back_populates='field', cascade='all, delete-orphan')

    @property
    def options_list(self):
        if not self.options:
            return []
        import json
        try:
            parsed = json.loads(self.options)
            if isinstance(parsed, list):
                return [str(o).strip() for o in parsed if str(o).strip()]
        except Exception:
            pass
        # Fallback newline or comma
        if '\n' in self.options:
            return [line.strip() for line in self.options.splitlines() if line.strip()]
        return [part.strip() for part in self.options.split(',') if part.strip()]

    def get_options_list(self):
        """Method alias for template and helper compatibility."""
        return self.options_list

    def __repr__(self):
        return f'<EventCustomField {self.id}: {self.label} ({self.field_type})>'


class EventCustomFieldValue(db.Model):
    __tablename__ = 'event_custom_field_values'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey('event_custom_fields.id', ondelete='CASCADE'), nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    event = db.relationship('Event', back_populates='custom_values')
    field = db.relationship('EventCustomField', back_populates='values')

    __table_args__ = (
        db.UniqueConstraint('event_id', 'field_id', name='uq_event_custom_field_value'),
    )

    def __repr__(self):
        return f'<EventCustomFieldValue event={self.event_id} field={self.field_id}>'


class EventLink(db.Model):
    __tablename__ = 'event_links'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship('Event', back_populates='links')

    def __repr__(self):
        return f'<EventLink {self.id}: {self.title} -> {self.url}>'
