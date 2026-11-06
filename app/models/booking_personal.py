from datetime import datetime
import json
import secrets
from app import db


class BookingPersonalEvent(db.Model):
    __tablename__ = 'booking_personal_events'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    
    # Verknüpftes Postfach aus dem E-Mail-Modul
    mailbox_id = db.Column(db.Integer, db.ForeignKey('mailboxes.id'), nullable=True)

    # Öffentlicher Bewerbungs-Token (für die offene Künstler-/Personal-Anmeldung)
    apply_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    apply_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Standard-E-Mail-Vorlagen je Event
    accept_template_subject = db.Column(
        db.String(255),
        default='Zusage für {{ event_name }} - {{ act_name }}',
        nullable=False
    )
    accept_template_body = db.Column(
        db.Text,
        default=(
            'Hallo {{ contact_name }},\n\n'
            'wir freuen uns sehr, euch für {{ event_name }} zu bestätigen!\n\n'
            'Eure vereinbarte Gage beträgt {{ gage }}.\n'
            'Alle Details, Absprachen und Hospitality-Informationen findet ihr '
            'in eurer persönlichen Übersicht:\n'
            '{{ overview_link }}\n\n'
            'Bei Rückfragen könnt ihr einfach auf diese E-Mail antworten.\n\n'
            'Liebe Grüße,\nEuer Booking-Team'
        ),
        nullable=False
    )

    reject_template_subject = db.Column(
        db.String(255),
        default='Rückmeldung zu deiner Bewerbung / Anfrage für {{ event_name }}',
        nullable=False
    )
    reject_template_body = db.Column(
        db.Text,
        default=(
            'Hallo {{ contact_name }},\n\n'
            'vielen Dank für euer Interesse und die Bewerbung für {{ event_name }}.\n\n'
            'Leider können wir euch dieses Jahr aufgrund der begrenzten Slots nicht im Line-Up berücksichtigen.\n\n'
            'Wir wünschen euch weiterhin alles Gute und viel Erfolg mit eurem Projekt!\n\n'
            'Liebe Grüße,\nEuer Booking-Team'
        ),
        nullable=False
    )

    invite_template_subject = db.Column(
        db.String(255),
        default='Künstler-Fragebogen für {{ event_name }} - {{ act_name }}',
        nullable=False
    )
    invite_template_body = db.Column(
        db.Text,
        default=(
            'Hallo {{ contact_name }},\n\n'
            'wir bereiten derzeit alles für {{ event_name }} vor und benötigen noch einige Angaben von euch '
            '(Techrider, Promo-Bilder, Hospitality etc.).\n\n'
            'Bitte füllt unser kurzes Online-Formular unter folgendem Link aus:\n'
            '{{ form_link }}\n\n'
            'Vielen Dank für eure Unterstützung!\n\n'
            'Liebe Grüße,\nEuer Booking-Team'
        ),
        nullable=False
    )

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    fields = db.relationship(
        'BookingPersonalField',
        back_populates='event',
        cascade='all, delete-orphan',
        order_by='BookingPersonalField.field_order'
    )
    entries = db.relationship(
        'BookingPersonalEntry',
        back_populates='event',
        cascade='all, delete-orphan',
        order_by='BookingPersonalEntry.order_index, BookingPersonalEntry.id'
    )
    mailbox = db.relationship('Mailbox', foreign_keys=[mailbox_id])
    creator = db.relationship('User', foreign_keys=[created_by])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.apply_token:
            self.apply_token = secrets.token_urlsafe(32)

    def get_apply_token(self):
        if not self.apply_token:
            self.apply_token = secrets.token_urlsafe(32)
            try:
                db.session.commit()
            except Exception:
                pass
        return self.apply_token

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description or '',
            'is_active': self.is_active,
            'mailbox_id': self.mailbox_id,
            'accept_template_subject': self.accept_template_subject or '',
            'accept_template_body': self.accept_template_body or '',
            'reject_template_subject': self.reject_template_subject or '',
            'reject_template_body': self.reject_template_body or '',
            'invite_template_subject': self.invite_template_subject or '',
            'invite_template_body': self.invite_template_body or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'entries_count': len(self.entries) if self.entries else 0,
        }


class BookingPersonalField(db.Model):
    __tablename__ = 'booking_personal_fields'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('booking_personal_events.id', ondelete='CASCADE'), nullable=False, index=True)
    field_key = db.Column(db.String(64), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    label_en = db.Column(db.String(200), nullable=True)
    field_type = db.Column(db.String(32), nullable=False)  # text, textarea, number, currency, counter, badge_select, file_upload, image_upload, formula, form_link, action_accept
    field_order = db.Column(db.Integer, default=0, nullable=False)
    width = db.Column(db.Integer, default=160, nullable=False)
    is_required = db.Column(db.Boolean, default=False, nullable=False)
    is_external = db.Column(db.Boolean, default=False, nullable=False)  # Über externes Künstler-Formular befüllbar
    is_internal = db.Column(db.Boolean, default=True, nullable=False)   # Vom Team pflegbar
    visible_in_overview = db.Column(db.Boolean, default=True, nullable=False)  # In Zusage-Übersicht für Künstler sichtbar
    options_json = db.Column(db.Text, nullable=True)  # JSON-Array für Badge-Select Optionen z. B. [{"value":"Offen","color":"#ffc107"}]
    formula_definition = db.Column(db.String(255), nullable=True)  # z. B. "gage + booking_fee + travel + lodging + other"
    help_text = db.Column(db.String(255), nullable=True)

    event = db.relationship('BookingPersonalEvent', back_populates='fields')

    def get_options(self):
        if self.options_json:
            try:
                return json.loads(self.options_json)
            except Exception:
                return []
        return []

    def set_options(self, options):
        if options is not None:
            self.options_json = json.dumps(options, ensure_ascii=False)
        else:
            self.options_json = None

    def to_dict(self):
        return {
            'id': self.id,
            'event_id': self.event_id,
            'field_key': self.field_key,
            'label': self.label,
            'label_en': self.label_en or self.label,
            'field_type': self.field_type,
            'field_order': self.field_order,
            'width': self.width,
            'is_required': self.is_required,
            'is_external': self.is_external,
            'is_internal': self.is_internal,
            'visible_in_overview': self.visible_in_overview,
            'options': self.get_options(),
            'formula_definition': self.formula_definition or '',
            'help_text': self.help_text or '',
        }


class BookingPersonalEntry(db.Model):
    __tablename__ = 'booking_personal_entries'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('booking_personal_events.id', ondelete='CASCADE'), nullable=False, index=True)
    order_index = db.Column(db.Integer, default=0, nullable=False)

    # Schnellzugriffsfelder (auch im Custom Data gepflegt)
    name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    phone = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), default='Angefragt', nullable=False)

    # Tokens für externe Links
    form_token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    form_submitted_at = db.Column(db.DateTime, nullable=True)
    overview_token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    acceptance_sent_at = db.Column(db.DateTime, nullable=True)
    rejection_sent_at = db.Column(db.DateTime, nullable=True)
    invite_sent_at = db.Column(db.DateTime, nullable=True)

    # Beliebig viele Custom Fields als JSON
    custom_data_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    event = db.relationship('BookingPersonalEvent', back_populates='entries')
    files = db.relationship('BookingPersonalFile', back_populates='entry', cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.form_token:
            self.form_token = secrets.token_urlsafe(32)
        if not self.overview_token:
            self.overview_token = secrets.token_urlsafe(32)

    def get_custom_data(self):
        if self.custom_data_json:
            try:
                return json.loads(self.custom_data_json)
            except Exception:
                return {}
        return {}

    def set_custom_data(self, data):
        if data is not None:
            self.custom_data_json = json.dumps(data, ensure_ascii=False)
        else:
            self.custom_data_json = '{}'

    def get_value(self, field_key, default=None):
        data = self.get_custom_data()
        if field_key in data:
            return data[field_key]
        if hasattr(self, field_key):
            val = getattr(self, field_key)
            if val is not None:
                return val
        return default

    def set_value(self, field_key, value):
        data = self.get_custom_data()
        data[field_key] = value
        self.set_custom_data(data)
        # Synchronisiere Basis-Attribute falls zutreffend
        if field_key in ('name', 'project_name') and value:
            self.name = str(value)
        elif field_key in ('email', 'mail') and value:
            self.email = str(value).strip()
        elif field_key in ('phone', 'telefonnummer') and value:
            self.phone = str(value).strip()
        elif field_key in ('status', 'status_booking') and value:
            self.status = str(value)

    def compute_formula_values(self, fields):
        """Berechnet Formelfelder wie GESAMT."""
        data = self.get_custom_data()
        changed = False
        for f in fields:
            if f.field_type == 'formula' and f.formula_definition:
                expr = f.formula_definition
                # Unterstütze Standard-Formel: gage + booking_fee + travel + lodging + other_expenses + food_allowance_cost
                total = 0.0
                try:
                    # Zerlege nach +
                    terms = [t.strip() for t in expr.split('+')]
                    for t in terms:
                        val = data.get(t)
                        if val is not None:
                            try:
                                total += float(str(val).replace('€', '').replace(',', '.').strip() or 0)
                            except (ValueError, TypeError):
                                pass
                    data[f.field_key] = f"€{total:.2f}"
                    changed = True
                except Exception:
                    pass
        if changed:
            self.set_custom_data(data)

    def to_dict(self):
        return {
            'id': self.id,
            'event_id': self.event_id,
            'order_index': self.order_index,
            'name': self.name or '',
            'email': self.email or '',
            'phone': self.phone or '',
            'status': self.status or 'Angefragt',
            'form_token': self.form_token,
            'form_submitted_at': self.form_submitted_at.isoformat() if self.form_submitted_at else None,
            'overview_token': self.overview_token,
            'acceptance_sent_at': self.acceptance_sent_at.isoformat() if self.acceptance_sent_at else None,
            'rejection_sent_at': self.rejection_sent_at.isoformat() if self.rejection_sent_at else None,
            'invite_sent_at': self.invite_sent_at.isoformat() if self.invite_sent_at else None,
            'custom_data': self.get_custom_data(),
            'files': [f.to_dict() for f in self.files],
        }


class BookingPersonalFile(db.Model):
    __tablename__ = 'booking_personal_files'

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('booking_personal_entries.id', ondelete='CASCADE'), nullable=False, index=True)
    field_key = db.Column(db.String(64), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    is_image = db.Column(db.Boolean, default=False, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    entry = db.relationship('BookingPersonalEntry', back_populates='files')

    def to_dict(self):
        return {
            'id': self.id,
            'entry_id': self.entry_id,
            'field_key': self.field_key,
            'file_path': self.file_path,
            'file_name': self.file_name,
            'mime_type': self.mime_type,
            'is_image': self.is_image,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


class BookingPersonalTemplate(db.Model):
    __tablename__ = 'booking_personal_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.String(500), nullable=True)
    is_system_default = db.Column(db.Boolean, default=False, nullable=False)
    fields_schema_json = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def get_fields(self):
        if self.fields_schema_json:
            try:
                return json.loads(self.fields_schema_json)
            except Exception:
                return []
        return []

    def set_fields(self, fields_list):
        self.fields_schema_json = json.dumps(fields_list, ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'is_system_default': self.is_system_default,
            'fields': self.get_fields(),
            'fields_count': len(self.get_fields()),
        }

