from datetime import datetime, timedelta
from app import db
import secrets


class ApiToken(db.Model):
    """API-Token für Mobile API Authentifizierung."""
    __tablename__ = 'api_tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=True)  # Optional: Name für den Token (z.B. "Mobile App")
    expires_at = db.Column(db.DateTime, nullable=True)  # None = kein Ablauf
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id])
    
    def __repr__(self):
        return f'<ApiToken {self.token[:10]}... for User {self.user_id}>'
    
    @staticmethod
    def generate_token():
        """Generiert einen neuen sicheren Token."""
        return secrets.token_urlsafe(32)
    
    def is_expired(self):
        """Prüft ob der Token abgelaufen ist."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def mark_as_used(self):
        """Markiert den Token als verwendet."""
        self.last_used_at = datetime.utcnow()
        db.session.commit()
    
    @staticmethod
    def create_token(user_id, name=None, expires_in_days=None):
        """Erstellt einen neuen API-Token."""
        token = ApiToken(
            user_id=user_id,
            token=ApiToken.generate_token(),
            name=name,
            expires_at=datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None
        )
        db.session.add(token)
        db.session.commit()
        return token

