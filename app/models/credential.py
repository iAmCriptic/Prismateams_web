from datetime import datetime
from app import db
from cryptography.fernet import Fernet
import os


class CredentialFolder(db.Model):
    __tablename__ = 'credential_folders'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    color = db.Column(db.String(16), nullable=False, default='#0d6efd')
    position = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    credentials = db.relationship('Credential', back_populates='folder')

    def __repr__(self):
        return f'<CredentialFolder {self.name}>'


class Credential(db.Model):
    __tablename__ = 'credentials'
    
    id = db.Column(db.Integer, primary_key=True)
    website_url = db.Column(db.String(500), nullable=False)
    website_name = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(255), nullable=False)
    password_encrypted = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    favicon_url = db.Column(db.String(500), nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('credential_folders.id'), nullable=True)
    is_favorite = db.Column(db.Boolean, nullable=False, default=False)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    folder = db.relationship('CredentialFolder', back_populates='credentials')
    
    def set_password(self, password, key):
        """Encrypt and store the password."""
        f = Fernet(key)
        self.password_encrypted = f.encrypt(password.encode()).decode()
    
    def get_password(self, key):
        """Decrypt and return the password."""
        f = Fernet(key)
        return f.decrypt(self.password_encrypted.encode()).decode()
    
    def __repr__(self):
        return f'<Credential {self.website_name}>'



