from datetime import datetime
from app import db
import re


class Contact(db.Model):
    __tablename__ = 'contacts'
    
    id = db.Column(db.Integer, primary_key=True)
    salutation = db.Column(db.String(50), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    sort_name = db.Column(db.String(255), nullable=False, index=True)
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
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Z|a-z]{2,}$'
        return bool(re.match(pattern, email))
    
    def to_dict(self):
        """Konvertiert Kontakt zu Dictionary für JSON-Responses."""
        return {
            'id': self.id,
            'salutation': self.salutation or '',
            'name': self.name,
            'sort_name': self.sort_name,
            'email': self.email,
            'phone': self.phone or '',
            'notes': self.notes or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ContactFavorite(db.Model):
    """Per-user contact favorites for the Kontakte nav."""
    __tablename__ = 'contact_favorites'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref='contact_favorites')
    contact = db.relationship('Contact', backref='favorited_by')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'contact_id', name='unique_user_contact_favorite'),
    )

    def __repr__(self):
        return f'<ContactFavorite user={self.user_id} contact={self.contact_id}>'
