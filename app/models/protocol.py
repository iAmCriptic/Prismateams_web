"""Meeting protocol (Protokollführung) models."""

from __future__ import annotations

from datetime import datetime

from app import db

PROTOCOL_STATUS_DRAFT = 'draft'
PROTOCOL_STATUS_FINALIZED = 'finalized'
PROTOCOL_STATUSES = (PROTOCOL_STATUS_DRAFT, PROTOCOL_STATUS_FINALIZED)


class Protocol(db.Model):
    __tablename__ = 'protocols'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False, default='Neues Protokoll')
    meeting_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=True)
    participants_text = db.Column(db.Text, nullable=True)
    excused_text = db.Column(db.Text, nullable=True)
    absent_text = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=PROTOCOL_STATUS_DRAFT, index=True)
    visibility = db.Column(db.String(20), nullable=False, default='public')
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finalized_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('User', backref='created_protocols')
    team = db.relationship('Team', backref='protocols')
    agenda_items = db.relationship(
        'ProtocolAgendaItem',
        back_populates='protocol',
        cascade='all, delete-orphan',
        order_by='ProtocolAgendaItem.position',
    )

    @property
    def is_draft(self) -> bool:
        return self.status == PROTOCOL_STATUS_DRAFT

    @property
    def is_finalized(self) -> bool:
        return self.status == PROTOCOL_STATUS_FINALIZED

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'title': self.title,
            'meeting_date': self.meeting_date.isoformat() if self.meeting_date else None,
            'start_time': self.start_time.strftime('%H:%M') if self.start_time else None,
            'end_time': self.end_time.strftime('%H:%M') if self.end_time else None,
            'participants_text': self.participants_text or '',
            'excused_text': self.excused_text or '',
            'absent_text': self.absent_text or '',
            'status': self.status,
            'visibility': self.visibility,
            'team_id': self.team_id,
            'agenda_items': [item.to_dict() for item in self.agenda_items],
        }


class ProtocolAgendaItem(db.Model):
    __tablename__ = 'protocol_agenda_items'

    id = db.Column(db.Integer, primary_key=True)
    protocol_id = db.Column(
        db.Integer,
        db.ForeignKey('protocols.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    position = db.Column(db.Integer, nullable=False, default=0)
    title = db.Column(db.String(500), nullable=False, default='')
    content_html = db.Column(db.Text, nullable=True)

    protocol = db.relationship('Protocol', back_populates='agenda_items')

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'protocol_id': self.protocol_id,
            'position': self.position,
            'title': self.title,
            'content_html': self.content_html or '',
        }
