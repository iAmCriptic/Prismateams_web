from datetime import datetime
from app import db
import json


class BookingForm(db.Model):
    __tablename__ = 'booking_forms'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Archivierung
    archive_days = db.Column(db.Integer, default=30, nullable=False)  # Wie lange vergangene Events archiviert werden
    
    # Datei-Integration
    enable_mailbox = db.Column(db.Boolean, default=False, nullable=False)  # Briefkasten aktivieren
    enable_shared_folder = db.Column(db.Boolean, default=False, nullable=False)  # Geteilter Ordner aktivieren
    
    # Relationships
    creator = db.relationship('User', backref='created_booking_forms')
    fields = db.relationship('BookingFormField', back_populates='form', cascade='all, delete-orphan', order_by='BookingFormField.field_order')
    images = db.relationship('BookingFormImage', back_populates='form', cascade='all, delete-orphan', order_by='BookingFormImage.display_order')
    requests = db.relationship('BookingRequest', back_populates='form', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<BookingForm {self.title}>'


class BookingFormField(db.Model):
    __tablename__ = 'booking_form_fields'
    
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('booking_forms.id'), nullable=False)
    field_type = db.Column(db.String(20), nullable=False)  # text, textarea, date, select, checkbox, number
    field_name = db.Column(db.String(100), nullable=False)  # Interner Name
    field_label = db.Column(db.String(200), nullable=False)  # Anzeigename
    is_required = db.Column(db.Boolean, default=False, nullable=False)
    field_order = db.Column(db.Integer, default=0, nullable=False)
    field_options = db.Column(db.Text, nullable=True)  # JSON für Dropdown-Optionen
    placeholder = db.Column(db.String(255), nullable=True)
    
    # Relationships
    form = db.relationship('BookingForm', back_populates='fields')
    request_values = db.relationship('BookingRequestField', back_populates='field', cascade='all, delete-orphan')
    
    def get_options(self):
        """Gibt die Optionen als Liste zurück."""
        if self.field_options:
            try:
                return json.loads(self.field_options)
            except:
                return []
        return []
    
    def set_options(self, options):
        """Setzt die Optionen als JSON."""
        if options:
            self.field_options = json.dumps(options)
        else:
            self.field_options = None
    
    def __repr__(self):
        return f'<BookingFormField {self.field_label} ({self.field_type})>'


class BookingFormImage(db.Model):
    __tablename__ = 'booking_form_images'
    
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('booking_forms.id'), nullable=False)
    image_path = db.Column(db.String(500), nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    form = db.relationship('BookingForm', back_populates='images')
    
    def __repr__(self):
        return f'<BookingFormImage {self.image_path}>'


class BookingRequest(db.Model):
    __tablename__ = 'booking_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('booking_forms.id'), nullable=False)
    event_name = db.Column(db.String(200), nullable=False)  # Pflicht
    email = db.Column(db.String(120), nullable=False)  # Pflicht
    token = db.Column(db.String(64), unique=True, nullable=True, index=True)  # Token nach Absendung
    
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending, accepted, rejected, archived
    
    # Event-Daten
    event_date = db.Column(db.Date, nullable=True)  # Gewünschtes Datum
    event_start_time = db.Column(db.Time, nullable=True)
    event_end_time = db.Column(db.Time, nullable=True)
    
    # Integration
    calendar_event_id = db.Column(db.Integer, db.ForeignKey('calendar_events.id'), nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True)
    
    # Ablehnung
    rejection_reason = db.Column(db.Text, nullable=True)
    rejected_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)
    
    # Annahme
    accepted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    form = db.relationship('BookingForm', back_populates='requests')
    # CalendarEvent relationship - nur eine Richtung, um zirkuläre Beziehung zu vermeiden
    calendar_event = db.relationship('CalendarEvent', foreign_keys=[calendar_event_id], primaryjoin='BookingRequest.calendar_event_id == CalendarEvent.id', viewonly=True)
    folder = db.relationship('Folder', backref='booking_requests')
    field_values = db.relationship('BookingRequestField', back_populates='request', cascade='all, delete-orphan')
    files = db.relationship('BookingRequestFile', back_populates='request', cascade='all, delete-orphan')
    accepter = db.relationship('User', foreign_keys=[accepted_by], backref='accepted_bookings')
    rejecter = db.relationship('User', foreign_keys=[rejected_by], backref='rejected_bookings')
    
    def __repr__(self):
        return f'<BookingRequest {self.event_name} ({self.status})>'


class BookingRequestField(db.Model):
    __tablename__ = 'booking_request_fields'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('booking_requests.id'), nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey('booking_form_fields.id'), nullable=False)
    field_value = db.Column(db.Text, nullable=True)  # Text-Wert
    file_path = db.Column(db.String(500), nullable=True)  # Für Datei-Uploads
    
    # Relationships
    request = db.relationship('BookingRequest', back_populates='field_values')
    field = db.relationship('BookingFormField', back_populates='request_values')
    
    def __repr__(self):
        return f'<BookingRequestField request={self.request_id} field={self.field_id}>'


class BookingRequestFile(db.Model):
    __tablename__ = 'booking_request_files'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('booking_requests.id'), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    request = db.relationship('BookingRequest', back_populates='files')
    
    def __repr__(self):
        return f'<BookingRequestFile {self.original_filename}>'

