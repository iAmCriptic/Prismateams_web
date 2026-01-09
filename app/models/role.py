from datetime import datetime
from app import db


class UserModuleRole(db.Model):
    """Modell für benutzerspezifische Modul-Zugriffsrechte."""
    __tablename__ = 'user_module_roles'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    module_key = db.Column(db.String(50), nullable=False, index=True)  # z.B. 'module_chat', 'module_files'
    has_access = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='module_roles')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'module_key', name='unique_user_module_role'),
    )
    
    def __repr__(self):
        return f'<UserModuleRole user={self.user_id} module={self.module_key} access={self.has_access}>'



















