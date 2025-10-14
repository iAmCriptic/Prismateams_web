from datetime import datetime
from app import db
import json


class EmailMessage(db.Model):
    __tablename__ = 'email_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(100), unique=True, nullable=True)  # IMAP UID
    message_id = db.Column(db.String(255), unique=True, nullable=True)
    subject = db.Column(db.String(500), nullable=False)
    sender = db.Column(db.String(255), nullable=False)
    recipients = db.Column(db.Text, nullable=False)  # JSON string
    cc = db.Column(db.Text, nullable=True)
    bcc = db.Column(db.Text, nullable=True)
    body_text = db.Column(db.Text, nullable=True)
    body_html = db.Column(db.Text, nullable=True)
    
    # Metadata
    is_read = db.Column(db.Boolean, default=False)
    is_sent = db.Column(db.Boolean, default=False)  # True if sent from portal
    has_attachments = db.Column(db.Boolean, default=False)
    
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
    content = db.Column(db.LargeBinary, nullable=False)  # File content
    is_inline = db.Column(db.Boolean, default=False)  # True if inline image
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    email = db.relationship('EmailMessage', back_populates='attachments')
    
    def __repr__(self):
        return f'<EmailAttachment {self.filename}>'
    
    def get_data_url(self):
        """Get data URL for inline images."""
        if self.is_inline and self.content_type.startswith('image/'):
            import base64
            return f"data:{self.content_type};base64,{base64.b64encode(self.content).decode()}"
        return None


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



