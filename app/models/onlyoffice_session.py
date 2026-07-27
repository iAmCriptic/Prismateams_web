from datetime import datetime

from app import db


class OnlyOfficeSession(db.Model):
    """Tracks users currently editing a file in OnlyOffice (presence)."""

    __tablename__ = 'onlyoffice_sessions'

    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    guest_key = db.Column(db.String(128), nullable=True)
    display_name = db.Column(db.String(255), nullable=False)
    avatar_filename = db.Column(db.String(255), nullable=True)
    session_key = db.Column(db.String(128), nullable=False, unique=True)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<OnlyOfficeSession file={self.file_id} user={self.user_id or self.guest_key}>'
