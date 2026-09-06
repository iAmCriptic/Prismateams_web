"""Video meetings (MiroTalk SFU) models."""

from __future__ import annotations

from datetime import datetime

from app import db

MEETING_ACCESS_PUBLIC = 'public'
MEETING_ACCESS_INVITE = 'invite'
MEETING_ACCESS_MODES = (MEETING_ACCESS_PUBLIC, MEETING_ACCESS_INVITE)

MEETING_STATUS_ACTIVE = 'active'
MEETING_STATUS_ENDED = 'ended'
MEETING_STATUSES = (MEETING_STATUS_ACTIVE, MEETING_STATUS_ENDED)


class Meeting(db.Model):
    __tablename__ = 'meetings'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    room_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    access_mode = db.Column(db.String(20), nullable=False, default=MEETING_ACCESS_PUBLIC, index=True)
    status = db.Column(db.String(20), nullable=False, default=MEETING_STATUS_ACTIVE, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='SET NULL'), nullable=True, index=True)
    guest_join_token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    ended_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by], backref='created_meetings')
    ender = db.relationship('User', foreign_keys=[ended_by])
    chat = db.relationship('Chat', backref='meetings')
    invites = db.relationship(
        'MeetingInvite',
        back_populates='meeting',
        cascade='all, delete-orphan',
    )

    @property
    def is_active(self) -> bool:
        return self.status == MEETING_STATUS_ACTIVE

    @property
    def is_public(self) -> bool:
        return self.access_mode == MEETING_ACCESS_PUBLIC


class MeetingInvite(db.Model):
    __tablename__ = 'meeting_invites'

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(
        db.Integer,
        db.ForeignKey('meetings.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    invited_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    meeting = db.relationship('Meeting', back_populates='invites')
    user = db.relationship('User', backref='meeting_invites')

    __table_args__ = (
        db.UniqueConstraint('meeting_id', 'user_id', name='unique_meeting_invite'),
    )
