from datetime import datetime
from app import db


class ShortLink(db.Model):
    __tablename__ = 'short_links'

    id = db.Column(db.Integer, primary_key=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    target_url = db.Column(db.String(2048), nullable=False)
    slug = db.Column(db.String(64), nullable=False, unique=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    password_hash = db.Column(db.String(255), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    max_clicks = db.Column(db.Integer, nullable=True)
    click_count = db.Column(db.Integer, default=0, nullable=False)
    last_clicked_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship('User', backref='short_links')

    def is_expired(self):
        return self.expires_at is not None and datetime.utcnow() > self.expires_at

    def is_max_clicks_reached(self):
        return self.max_clicks is not None and self.click_count >= self.max_clicks

    def is_accessible(self):
        return self.is_active and not self.is_expired() and not self.is_max_clicks_reached()

    def __repr__(self):
        return f'<ShortLink {self.slug}>'
