from datetime import datetime
from app import db
import re


class Contact(db.Model):
    __tablename__ = 'contacts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Relationships
    creator = db.relationship('User', foreign_keys=[created_by])
    
    def __repr__(self):
        return f'<Contact {self.name} ({self.email})>'
    
    @staticmethod
    def is_valid_email(email):
        """Validiert E-Mail-Adresse."""
        if not email:
            return False
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    def to_dict(self):
        """Konvertiert Kontakt zu Dictionary für JSON-Responses."""
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone or '',
            'notes': self.notes or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
