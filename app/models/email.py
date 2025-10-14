from datetime import datetime
from app import db


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
    
    def __repr__(self):
        return f'<EmailMessage {self.subject}>'


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



