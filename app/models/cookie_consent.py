"""Cookie-/Consent-Nachweise (Art. 7 Nachweisbarkeit)."""

from datetime import datetime

from app import db


class CookieConsentLog(db.Model):
    """Append-only Nachweis von Einwilligung und Widerruf (Kategorien)."""

    __tablename__ = 'cookie_consent_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    anon_id = db.Column(db.String(64), nullable=False, index=True)
    consent_version = db.Column(db.Integer, nullable=False, default=1)
    necessary = db.Column(db.Boolean, nullable=False, default=True)
    functional = db.Column(db.Boolean, nullable=False, default=False)
    analytics = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship('User', backref=db.backref('cookie_consent_logs', lazy='dynamic'))

    def __repr__(self):
        return (
            f'<CookieConsentLog id={self.id} anon={self.anon_id[:8]}… '
            f'f={self.functional} a={self.analytics}>'
        )
