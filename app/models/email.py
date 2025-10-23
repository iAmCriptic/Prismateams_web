from datetime import datetime
from app import db
import json
from flask import current_app


class EmailMessage(db.Model):
    __tablename__ = 'email_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(100), nullable=True)  # IMAP UID (not unique, can be same across folders)
    message_id = db.Column(db.String(255), unique=True, nullable=True)
    subject = db.Column(db.String(500), nullable=False)
    sender = db.Column(db.String(255), nullable=False)
    recipients = db.Column(db.Text, nullable=False)  # JSON string
    cc = db.Column(db.Text, nullable=True)
    bcc = db.Column(db.Text, nullable=True)
    body_text = db.Column(db.Text, nullable=True)  # TEXT can handle up to 65,535 characters
    body_html = db.Column(db.Text, nullable=True)  # TEXT can handle large content (up to 1GB in most databases)
    
    # Metadata
    is_read = db.Column(db.Boolean, default=False)
    is_sent = db.Column(db.Boolean, default=False)  # True if sent from portal
    has_attachments = db.Column(db.Boolean, default=False)
    folder = db.Column(db.String(100), default='INBOX', nullable=False)  # IMAP folder
    
    # IMAP synchronization tracking
    imap_uid = db.Column(db.String(100), nullable=True)  # IMAP UID for this specific folder
    last_imap_sync = db.Column(db.DateTime, nullable=True)  # Last time synced from IMAP
    is_deleted_imap = db.Column(db.Boolean, default=False)  # Marked as deleted in IMAP
    
    sent_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    received_at = db.Column(db.DateTime, nullable=True, index=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    attachments = db.relationship('EmailAttachment', back_populates='email', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<EmailMessage {self.subject}>'


class EmailAttachment(db.Model):
    __tablename__ = 'email_attachments'
    
    id = db.Column(db.Integer, primary_key=True)
    email_id = db.Column(db.Integer, db.ForeignKey('email_messages.id'), nullable=False)
    
    filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    size = db.Column(db.Integer, nullable=False)  # Size in bytes
    content = db.Column(db.LargeBinary, nullable=True)  # File content (can be None for file storage)
    file_path = db.Column(db.String(500), nullable=True)  # Path to file on disk
    is_inline = db.Column(db.Boolean, default=False)  # True if inline image
    content_id = db.Column(db.String(255), nullable=True)  # Content-ID for inline images
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    email = db.relationship('EmailMessage', back_populates='attachments')
    
    def __repr__(self):
        return f'<EmailAttachment {self.filename}>'
    
    def get_data_url(self):
        """Get data URL for inline images."""
        if self.is_inline and self.content_type.startswith('image/'):
            import base64
            if self.content:
                return f"data:{self.content_type};base64,{base64.b64encode(self.content).decode()}"
            elif self.file_path:
                try:
                    import os
                    with open(self.file_path, 'rb') as f:
                        content = f.read()
                        return f"data:{self.content_type};base64,{base64.b64encode(content).decode()}"
                except:
                    return None
        return None
    
    def get_content(self):
        """Get attachment content from database or file system."""
        if self.content:
            return self.content
        elif self.file_path:
            try:
                import os
                with open(self.file_path, 'rb') as f:
                    return f.read()
            except:
                return None
        return None


class EmailFolder(db.Model):
    __tablename__ = 'email_folders'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)  # IMAP folder name
    display_name = db.Column(db.String(100), nullable=False)  # Display name in UI
    folder_type = db.Column(db.String(20), default='custom', nullable=False)  # 'standard' or 'custom'
    is_system = db.Column(db.Boolean, default=False, nullable=False)  # True for system folders like INBOX
    parent_folder = db.Column(db.String(100), nullable=True)  # For nested folders
    separator = db.Column(db.String(5), default='/', nullable=False)  # IMAP folder separator
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_synced = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<EmailFolder {self.name}>'
    
    @staticmethod
    def get_folder_display_name(imap_name):
        """Convert IMAP folder name to display name."""
        display_names = {
            'INBOX': 'Posteingang',
            'Sent': 'Gesendet',
            'Sent Messages': 'Gesendet',
            'Drafts': 'Entwürfe',
            'Trash': 'Papierkorb',
            'Deleted Messages': 'Papierkorb',
            'Spam': 'Spam',
            'Junk': 'Spam',
            'Archive': 'Archiv'
        }
        return display_names.get(imap_name, imap_name)


class EmailPermission(db.Model):
    __tablename__ = 'email_permissions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    can_read = db.Column(db.Boolean, default=True, nullable=False)
    can_send = db.Column(db.Boolean, default=True, nullable=False)
    
    # Relationships
    user = db.relationship('User', back_populates='email_permissions')
    
    def __repr__(self):
        return f'<EmailPermission user={self.user_id} read={self.can_read} send={self.can_send}>'



