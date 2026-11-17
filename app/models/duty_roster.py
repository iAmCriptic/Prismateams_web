"""Dienstplan (duty roster) models: monthly team plans, shifts, person config, time entries."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta

from app import db

ENTRY_TYPE_SHIFT = 'shift'
ENTRY_TYPE_VACATION = 'vacation'
ENTRY_TYPE_NOTE = 'note'
ENTRY_TYPE_SICK = 'sick'

ROSTER_ENTRY_TYPES = frozenset({
    ENTRY_TYPE_SHIFT,
    ENTRY_TYPE_VACATION,
    ENTRY_TYPE_NOTE,
    ENTRY_TYPE_SICK,
})

TIME_ENTRY_WORK = 'work'
TIME_ENTRY_SICK = 'sick'
TIME_ENTRY_VACATION = 'vacation'
TIME_ENTRY_OTHER = 'other'

TIME_ENTRY_TYPES = frozenset({
    TIME_ENTRY_WORK,
    TIME_ENTRY_SICK,
    TIME_ENTRY_VACATION,
    TIME_ENTRY_OTHER,
})

WEEKDAY_NAMES_DE = (
    'Montag',
    'Dienstag',
    'Mittwoch',
    'Donnerstag',
    'Freitag',
    'Samstag',
    'Sonntag',
)

MONTH_NAMES_DE = (
    'Januar',
    'Februar',
    'März',
    'April',
    'Mai',
    'Juni',
    'Juli',
    'August',
    'September',
    'Oktober',
    'November',
    'Dezember',
)


class DutyRoster(db.Model):
    """Monats-Dienstplan eines Teams."""

    __tablename__ = 'duty_rosters'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=True)
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = db.relationship('Team', backref=db.backref('duty_rosters', cascade='all, delete-orphan'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    days = db.relationship(
        'DutyRosterDay',
        back_populates='roster',
        cascade='all, delete-orphan',
        order_by='DutyRosterDay.date',
    )
    columns = db.relationship(
        'DutyRosterColumn',
        back_populates='roster',
        cascade='all, delete-orphan',
        order_by='DutyRosterColumn.sort_order',
    )

    __table_args__ = (
        db.UniqueConstraint('team_id', 'year', 'month', name='unique_duty_roster_team_month'),
    )

    @property
    def display_title(self):
        """Immer „Monat - Jahr“, z.B. Oktober - 2026."""
        if 1 <= int(self.month) <= 12:
            name = MONTH_NAMES_DE[int(self.month) - 1]
        else:
            name = f'{int(self.month):02d}'
        return f'{name} - {self.year}'

    @property
    def month_start(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def month_end(self) -> date:
        last = monthrange(self.year, self.month)[1]
        return date(self.year, self.month, last)

    def __repr__(self):
        return f'<DutyRoster team={self.team_id} {self.year}-{self.month:02d}>'


class DutyRosterDay(db.Model):
    """Ein Tag (Zeile) im Monatsplan."""

    __tablename__ = 'duty_roster_days'

    id = db.Column(db.Integer, primary_key=True)
    roster_id = db.Column(db.Integer, db.ForeignKey('duty_rosters.id', ondelete='CASCADE'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    weekday = db.Column(db.String(20), nullable=True)
    whats_happening = db.Column(db.String(500), nullable=True)
    row_color = db.Column(db.String(20), nullable=True)

    roster = db.relationship('DutyRoster', back_populates='days')
    entries = db.relationship(
        'DutyRosterEntry',
        back_populates='day',
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.UniqueConstraint('roster_id', 'date', name='unique_duty_roster_day'),
    )

    @property
    def iso_week(self) -> int:
        return self.date.isocalendar()[1]

    @property
    def weekday_label(self) -> str:
        if self.weekday:
            return self.weekday
        return WEEKDAY_NAMES_DE[self.date.weekday()]

    def __repr__(self):
        return f'<DutyRosterDay {self.date}>'


class DutyRosterColumn(db.Model):
    """Personenspalte: Team-User oder externe Person (Team-Stamm)."""

    __tablename__ = 'duty_roster_columns'

    id = db.Column(db.Integer, primary_key=True)
    roster_id = db.Column(db.Integer, db.ForeignKey('duty_rosters.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    external_person_id = db.Column(
        db.Integer, db.ForeignKey('duty_external_persons.id', ondelete='SET NULL'), nullable=True, index=True
    )
    external_name = db.Column(db.String(120), nullable=True)  # Legacy / Anzeige-Fallback
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    show_in_plan = db.Column(db.Boolean, default=True, nullable=False)

    roster = db.relationship('DutyRoster', back_populates='columns')
    user = db.relationship('User', foreign_keys=[user_id])
    external_person = db.relationship('DutyExternalPerson', foreign_keys=[external_person_id])
    entries = db.relationship(
        'DutyRosterEntry',
        back_populates='column',
        cascade='all, delete-orphan',
    )

    @property
    def is_external(self) -> bool:
        return self.user_id is None

    @property
    def display_name(self) -> str:
        if self.user_id and self.user:
            return self.user.first_name or self.user.full_name
        if self.external_person_id and self.external_person:
            return self.external_person.name
        return (self.external_name or '').strip() or '—'

    def __repr__(self):
        return f'<DutyRosterColumn {self.display_name}>'


class DutyRosterEntry(db.Model):
    """Zelle: Schicht / Urlaub / Notiz für eine Person an einem Tag."""

    __tablename__ = 'duty_roster_entries'

    id = db.Column(db.Integer, primary_key=True)
    day_id = db.Column(db.Integer, db.ForeignKey('duty_roster_days.id', ondelete='CASCADE'), nullable=False, index=True)
    column_id = db.Column(
        db.Integer, db.ForeignKey('duty_roster_columns.id', ondelete='CASCADE'), nullable=False, index=True
    )
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    ends_next_day = db.Column(db.Boolean, default=False, nullable=False)
    entry_type = db.Column(db.String(20), nullable=False, default=ENTRY_TYPE_SHIFT)
    label = db.Column(db.String(200), nullable=True)

    day = db.relationship('DutyRosterDay', back_populates='entries')
    column = db.relationship('DutyRosterColumn', back_populates='entries')

    __table_args__ = (
        db.UniqueConstraint('day_id', 'column_id', name='unique_duty_roster_entry_cell'),
    )

    def duration_hours(self) -> float:
        if self.entry_type != ENTRY_TYPE_SHIFT or not self.start_time or not self.end_time:
            return 0.0
        start_dt = datetime.combine(date.today(), self.start_time)
        end_dt = datetime.combine(date.today(), self.end_time)
        if self.ends_next_day or self.end_time <= self.start_time:
            end_dt += timedelta(days=1)
        return max(0.0, (end_dt - start_dt).total_seconds() / 3600.0)

    def display_text(self) -> str:
        if self.label:
            return self.label
        if self.entry_type == ENTRY_TYPE_VACATION:
            return 'URLAUB'
        if self.entry_type == ENTRY_TYPE_SICK:
            return 'KRANK'
        if self.start_time and self.end_time:
            start_label = f'{self.start_time.hour}:{self.start_time.strftime("%M")}'
            if self.ends_next_day and self.end_time.hour == 0 and self.end_time.minute == 0:
                end_label = '24:00'
            else:
                end_label = f'{self.end_time.hour}:{self.end_time.strftime("%M")}'
            return f'{start_label} - {end_label}'
        return ''

    def __repr__(self):
        return f'<DutyRosterEntry day={self.day_id} col={self.column_id}>'


def _validity_active_on(valid_from, valid_until, d: date) -> bool:
    if valid_from is not None and d < valid_from:
        return False
    if valid_until is not None and d > valid_until:
        return False
    return True


def _validity_overlaps(valid_from, valid_until, start: date, end: date) -> bool:
    """True wenn die Person an mindestens einem Tag in [start, end] aktiv ist."""
    if start > end:
        return False
    from_d = valid_from or start
    until_d = valid_until or end
    return from_d <= end and until_d >= start


class DutyPersonConfig(db.Model):
    """Stammdaten pro Team-Mitglied: Soll, Urlaub, Plan-Verfügbarkeit, Zeitraum."""

    __tablename__ = 'duty_person_configs'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    weekly_hours_soll = db.Column(db.Float, nullable=True)
    vacation_days_total = db.Column(db.Float, nullable=True)
    vacation_days_used = db.Column(db.Float, default=0.0, nullable=False)
    available_for_roster = db.Column(db.Boolean, default=True, nullable=False)
    valid_from = db.Column(db.Date, nullable=True)  # None = ab sofort / unbefristet Anfang
    valid_until = db.Column(db.Date, nullable=True)  # None = unbefristet
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = db.relationship('Team', backref=db.backref('duty_person_configs', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('duty_person_configs', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('team_id', 'user_id', name='unique_duty_person_config'),
    )

    @property
    def vacation_days_remaining(self) -> float | None:
        if self.vacation_days_total is None:
            return None
        used = self.vacation_days_used or 0.0
        return max(0.0, float(self.vacation_days_total) - float(used))

    def is_active_on(self, d: date) -> bool:
        if not self.available_for_roster:
            return False
        return _validity_active_on(self.valid_from, self.valid_until, d)

    def overlaps_range(self, start: date, end: date) -> bool:
        if not self.available_for_roster:
            return False
        return _validity_overlaps(self.valid_from, self.valid_until, start, end)

    def __repr__(self):
        return f'<DutyPersonConfig team={self.team_id} user={self.user_id}>'


class DutyExternalPerson(db.Model):
    """Externe / Zeitarbeiter auf Team-Ebene mit optionalem Start-/Enddatum."""

    __tablename__ = 'duty_external_persons'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    valid_from = db.Column(db.Date, nullable=True)
    valid_until = db.Column(db.Date, nullable=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = db.relationship('Team', backref=db.backref('duty_external_persons', cascade='all, delete-orphan'))

    def is_active_on(self, d: date) -> bool:
        if not self.is_active:
            return False
        return _validity_active_on(self.valid_from, self.valid_until, d)

    def overlaps_range(self, start: date, end: date) -> bool:
        if not self.is_active:
            return False
        return _validity_overlaps(self.valid_from, self.valid_until, start, end)

    def __repr__(self):
        return f'<DutyExternalPerson {self.name}>'


class DutyRosterPlanner(db.Model):
    """Zusätzliche Planungsberechtigte (neben Teamleiter)."""

    __tablename__ = 'duty_roster_planners'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    team = db.relationship('Team', backref=db.backref('duty_roster_planners', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('duty_roster_planner_grants', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('team_id', 'user_id', name='unique_duty_roster_planner'),
    )

    def __repr__(self):
        return f'<DutyRosterPlanner team={self.team_id} user={self.user_id}>'


class DutyTimeEntry(db.Model):
    """Private Ist-Zeiterfassung."""

    __tablename__ = 'duty_time_entries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    ends_next_day = db.Column(db.Boolean, default=False, nullable=False)
    entry_type = db.Column(db.String(20), nullable=False, default=TIME_ENTRY_WORK)
    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('duty_time_entries', cascade='all, delete-orphan'))
    team = db.relationship('Team')

    def duration_hours(self) -> float:
        if self.entry_type != TIME_ENTRY_WORK or not self.start_time or not self.end_time:
            return 0.0
        start_dt = datetime.combine(date.today(), self.start_time)
        end_dt = datetime.combine(date.today(), self.end_time)
        if self.ends_next_day or self.end_time <= self.start_time:
            end_dt += timedelta(days=1)
        return max(0.0, (end_dt - start_dt).total_seconds() / 3600.0)

    def display_text(self) -> str:
        if self.entry_type == TIME_ENTRY_SICK:
            return 'KRANK'
        if self.entry_type == TIME_ENTRY_VACATION:
            return 'URLAUB'
        if self.start_time and self.end_time:
            return f'{self.start_time.strftime("%H:%M")}–{self.end_time.strftime("%H:%M")}'
        return self.note or ''

    def __repr__(self):
        return f'<DutyTimeEntry user={self.user_id} {self.date}>'
