from datetime import datetime
from app import db


class UserSession(db.Model):
    """Speichert aktive Benutzer-Sessions für Session-Management."""
    __tablename__ = 'user_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    session_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4 oder IPv6
    user_agent = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    
    # Relationship
    user = db.relationship('User', backref='sessions')
    
    def __repr__(self):
        return f'<UserSession {self.session_id[:10]}... for User {self.user_id}>'
    
    def update_activity(self):
        """Aktualisiert die letzte Aktivität."""
        self.last_activity = datetime.utcnow()
        db.session.commit()
    
    def revoke(self):
        """Meldet die Session ab."""
        self.is_active = False
        db.session.commit()
