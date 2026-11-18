from datetime import datetime
import json
import re
import secrets
from app import db


def _slugify(value):
    text = re.sub(r'[^a-z0-9]+', '-', (value or '').strip().lower()).strip('-')
    return text or 'event'


class HelperEvent(db.Model):
    """Veranstaltung im Modul Helferverwaltung (analog BookingPersonalEvent)."""
    __tablename__ = 'helper_events'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # Öffentlicher Anmelde-Token (für /helfer/anmeldung/<apply_token>)
    apply_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    apply_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Marken-Berechnungsmodus: 'per_shift' oder 'cumulative_per_person_day'
    voucher_calc_mode = db.Column(db.String(40), default='per_shift', nullable=False)

    # E-Mail-Versand & Vorlage pro Veranstaltung
    mailbox_id = db.Column(db.Integer, db.ForeignKey('mailboxes.id', ondelete='SET NULL'), nullable=True)
    mail_template_subject = db.Column(
        db.String(255),
        default='Dein Schichtplan für {{ event_name }}',
        nullable=False,
    )
    mail_template_body = db.Column(
        db.Text,
        default=(
            'Hallo {{ first_name }},\n\n'
            'vielen Dank für deine Unterstützung bei {{ event_name }}!\n\n'
            'Hier ist deine aktuelle Übersicht:\n'
            'T-Shirt-Größe: {{ tshirt_size }}\n'
            'Gesamtstunden: {{ total_hours }} Std.\n'
            'Essensmarken: {{ food_vouchers }} | Getränkemarken: {{ drinks_vouchers }}\n\n'
            'Deine Schichten:\n'
            '{{ shifts_list }}\n\n'
            'Bei Fragen melde dich gerne beim Orga-Team.\n\n'
            'Liebe Grüße,\nDein Orga-Team'
        ),
        nullable=False,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    mailbox = db.relationship('Mailbox', foreign_keys=[mailbox_id])

    helpers = db.relationship(
        'Helper',
        back_populates='event',
        cascade='all, delete-orphan',
        order_by='Helper.last_name.asc(), Helper.first_name.asc()',
    )
    areas = db.relationship(
        'HelperArea',
        back_populates='event',
        cascade='all, delete-orphan',
        order_by='HelperArea.sort_order.asc(), HelperArea.name.asc()',
    )
    shifts = db.relationship(
        'HelperShift',
        back_populates='event',
        cascade='all, delete-orphan',
        order_by='HelperShift.date.asc(), HelperShift.start_time.asc()',
    )
    field_configs = db.relationship(
        'HelperFieldConfig',
        back_populates='event',
        cascade='all, delete-orphan',
        order_by='HelperFieldConfig.sort_order.asc(), HelperFieldConfig.id.asc()',
    )
    voucher_rules = db.relationship(
        'HelperVoucherRule',
        back_populates='event',
        cascade='all, delete-orphan',
        order_by='HelperVoucherRule.min_hours.asc(), HelperVoucherRule.id.asc()',
    )

    def ensure_apply_token(self):
        if not self.apply_token:
            self.apply_token = secrets.token_urlsafe(24)
        if not self.slug:
            self.slug = _slugify(self.name)
        return self.apply_token

    def __repr__(self):
        return f'<HelperEvent {self.id}: {self.name}>'


class Helper(db.Model):
    """Registrierter Helfer innerhalb einer Veranstaltung."""
    __tablename__ = 'helpers'
    __table_args__ = (
        db.UniqueConstraint('event_id', 'email', name='uq_helpers_event_email'),
    )

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(
        db.Integer,
        db.ForeignKey('helper_events.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(80), nullable=True)
    tshirt_size = db.Column(db.String(32), nullable=True)
    allergies = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(40), default='registered', nullable=False, index=True)
    custom_fields = db.Column(db.JSON, default=dict, nullable=False)

    dsgvo_accepted = db.Column(db.Boolean, default=False, nullable=False)
    dsgvo_accepted_at = db.Column(db.DateTime, nullable=True)

    # Abhakbare Ausgabe-Checkliste pro Helfer
    vouchers_issued = db.Column(db.Boolean, default=False, nullable=False)
    vouchers_issued_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    event = db.relationship('HelperEvent', back_populates='helpers')
    wishes = db.relationship(
        'HelperAreaWish',
        back_populates='helper',
        cascade='all, delete-orphan',
        order_by='HelperAreaWish.priority.asc(), HelperAreaWish.id.asc()',
    )
    shifts = db.relationship(
        'HelperShift',
        back_populates='helper',
        order_by='HelperShift.date.asc(), HelperShift.start_time.asc()',
    )

    @property
    def full_name(self):
        return f'{self.first_name or ""} {self.last_name or ""}'.strip()

    def get_custom_fields(self):
        if isinstance(self.custom_fields, dict):
            return dict(self.custom_fields)
        if isinstance(self.custom_fields, str) and self.custom_fields.strip():
            try:
                parsed = json.loads(self.custom_fields)
                if isinstance(parsed, dict):
                    return parsed
            except (ValueError, TypeError):
                pass
        return {}

    def __repr__(self):
        return f'<Helper {self.id}: {self.full_name}>'


class HelperArea(db.Model):
    """Einsatzbereich innerhalb einer Veranstaltung."""
    __tablename__ = 'helper_areas'
    __table_args__ = (
        db.UniqueConstraint('event_id', 'name', name='uq_helper_areas_event_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(
        db.Integer,
        db.ForeignKey('helper_events.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_public_selectable = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    event = db.relationship('HelperEvent', back_populates='areas')
    wishes = db.relationship(
        'HelperAreaWish',
        back_populates='area',
        cascade='all, delete-orphan',
    )
    shifts = db.relationship(
        'HelperShift',
        back_populates='area',
        cascade='all, delete-orphan',
        order_by='HelperShift.date.asc(), HelperShift.start_time.asc()',
    )
    voucher_rules = db.relationship(
        'HelperVoucherRule',
        back_populates='area',
        cascade='all, delete-orphan',
    )

    def __repr__(self):
        return f'<HelperArea {self.id}: {self.name}>'


class HelperAreaWish(db.Model):
    """Verknüpfung Helfer <-> Wunschbereich inkl. Verfügbarkeiten."""
    __tablename__ = 'helper_area_wishes'
    __table_args__ = (
        db.UniqueConstraint('helper_id', 'area_id', name='uq_helper_area_wishes_pair'),
    )

    id = db.Column(db.Integer, primary_key=True)
    helper_id = db.Column(
        db.Integer,
        db.ForeignKey('helpers.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    area_id = db.Column(
        db.Integer,
        db.ForeignKey('helper_areas.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    priority = db.Column(db.Integer, default=1, nullable=False)
    available_days = db.Column(db.JSON, default=list, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    helper = db.relationship('Helper', back_populates='wishes')
    area = db.relationship('HelperArea', back_populates='wishes')

    def get_available_days(self):
        if isinstance(self.available_days, list):
            return list(self.available_days)
        if isinstance(self.available_days, str) and self.available_days.strip():
            try:
                parsed = json.loads(self.available_days)
                if isinstance(parsed, list):
                    return parsed
            except (ValueError, TypeError):
                return [d.strip() for d in self.available_days.split(',') if d.strip()]
        return []

    def __repr__(self):
        return f'<HelperAreaWish helper={self.helper_id} area={self.area_id}>'


class HelperShift(db.Model):
    """Schicht oder anonymer Sammelposten (group_count > 1) in einem Bereich."""
    __tablename__ = 'helper_shifts'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(
        db.Integer,
        db.ForeignKey('helper_events.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    area_id = db.Column(
        db.Integer,
        db.ForeignKey('helper_areas.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    helper_id = db.Column(
        db.Integer,
        db.ForeignKey('helpers.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    group_count = db.Column(db.Integer, default=1, nullable=False)
    role_label = db.Column(db.String(120), nullable=True)
    day_label = db.Column(db.String(60), nullable=False, default='Freitag')
    date = db.Column(db.Date, nullable=True)
    start_time = db.Column(db.String(20), nullable=True)
    end_time = db.Column(db.String(20), nullable=True)
    hours = db.Column(db.Float, default=0.0, nullable=False)
    is_head = db.Column(db.Boolean, default=False, nullable=False)
    food_override = db.Column(db.Integer, nullable=True)
    drinks_override = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship('HelperEvent', back_populates='shifts')
    area = db.relationship('HelperArea', back_populates='shifts')
    helper = db.relationship('Helper', back_populates='shifts')

    @property
    def is_head_role(self):
        if self.is_head:
            return True
        return 'head' in (self.role_label or '').lower()

    @property
    def is_bulk_post(self):
        return self.helper_id is None and (self.group_count or 1) > 1

    def __repr__(self):
        return f'<HelperShift {self.id}: area={self.area_id} day={self.day_label}>'


class HelperFieldConfig(db.Model):
    """Dynamische Feld-Konfiguration je Veranstaltung."""
    __tablename__ = 'helper_field_configs'
    __table_args__ = (
        db.UniqueConstraint('event_id', 'field_key', name='uq_helper_fields_event_key'),
    )

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(
        db.Integer,
        db.ForeignKey('helper_events.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    field_key = db.Column(db.String(80), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    field_type = db.Column(db.String(32), default='text', nullable=False)
    options = db.Column(db.JSON, default=list, nullable=False)
    is_public = db.Column(db.Boolean, default=True, nullable=False)
    is_required = db.Column(db.Boolean, default=False, nullable=False)
    admin_only = db.Column(db.Boolean, default=False, nullable=False)
    show_in_overview = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_core = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    event = db.relationship('HelperEvent', back_populates='field_configs')

    def get_options(self):
        if isinstance(self.options, list):
            return [str(o).strip() for o in self.options if str(o).strip()]
        if isinstance(self.options, str) and self.options.strip():
            try:
                parsed = json.loads(self.options)
                if isinstance(parsed, list):
                    return [str(o).strip() for o in parsed if str(o).strip()]
            except (ValueError, TypeError):
                return [o.strip() for o in self.options.split(',') if o.strip()]
        return []

    def __repr__(self):
        return f'<HelperFieldConfig {self.field_key} ({self.field_type})>'


class HelperVoucherRule(db.Model):
    """Konfigurierbare Staffelregeln für Essens- und Getränkemarken."""
    __tablename__ = 'helper_voucher_rules'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(
        db.Integer,
        db.ForeignKey('helper_events.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    min_hours = db.Column(db.Float, default=0.0, nullable=False)
    max_hours = db.Column(db.Float, nullable=True)
    food_count = db.Column(db.Integer, default=0, nullable=False)
    drinks_count = db.Column(db.Integer, default=0, nullable=False)
    head_bonus_drinks = db.Column(db.Integer, default=0, nullable=False)
    area_id = db.Column(
        db.Integer,
        db.ForeignKey('helper_areas.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )

    event = db.relationship('HelperEvent', back_populates='voucher_rules')
    area = db.relationship('HelperArea', back_populates='voucher_rules')

    def matches_hours(self, hours):
        h = float(hours or 0.0)
        if h < float(self.min_hours or 0.0):
            return False
        if self.max_hours is not None and h > float(self.max_hours):
            return False
        return True

    def __repr__(self):
        return f'<HelperVoucherRule {self.name}: {self.min_hours}-{self.max_hours}h>'


# Kompatible Aliase gemäß Spezifikation
Area = HelperArea
Shift = HelperShift
FieldConfig = HelperFieldConfig
VoucherRule = HelperVoucherRule
