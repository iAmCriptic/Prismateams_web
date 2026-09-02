from datetime import datetime

from app import db


class UserPasskey(db.Model):
    __tablename__ = 'user_passkeys'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    credential_id = db.Column(db.String(512), nullable=False, unique=True, index=True)
    public_key = db.Column(db.Text, nullable=False)
    sign_count = db.Column(db.Integer, default=0, nullable=False)
    transports = db.Column(db.String(255), nullable=True)
    aaguid = db.Column(db.String(64), nullable=True)
    backed_up = db.Column(db.Boolean, default=False, nullable=False)
    device_label = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('passkeys', lazy='dynamic', cascade='all, delete-orphan'))

    def touch_used(self):
        self.last_used_at = datetime.utcnow()
