from datetime import datetime
from app import db


class NotificationSettings(db.Model):
    __tablename__ = 'notification_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    chat_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    
    file_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    file_new_notifications = db.Column(db.Boolean, default=True, nullable=False)
    file_modified_notifications = db.Column(db.Boolean, default=True, nullable=False)
    
    email_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    
    calendar_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    calendar_all_events = db.Column(db.Boolean, default=False, nullable=False)
    calendar_participating_only = db.Column(db.Boolean, default=True, nullable=False)
    calendar_not_participating = db.Column(db.Boolean, default=False, nullable=False)
    calendar_no_response = db.Column(db.Boolean, default=False, nullable=False)
    
    reminder_times = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = db.relationship('User', backref='notification_settings')
    
    def __repr__(self):
        return f'<NotificationSettings user={self.user_id}>'
    
    def get_reminder_times(self):
        """Gibt die Erinnerungszeiten als Liste zurück."""
        if self.reminder_times:
            import json
            return json.loads(self.reminder_times)
        return []
    
    def set_reminder_times(self, times):
        """Setzt die Erinnerungszeiten."""
        import json
        self.reminder_times = json.dumps(times)


class ChatNotificationSettings(db.Model):
    __tablename__ = 'chat_notification_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'), nullable=False)
    notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = db.relationship('User', backref='chat_notification_settings')
    chat = db.relationship('Chat', backref='notification_settings')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'chat_id', name='unique_user_chat_notification'),
    )
    
    def __repr__(self):
        return f'<ChatNotificationSettings user={self.user_id} chat={self.chat_id}>'


class PushSubscription(db.Model):
    __tablename__ = 'push_subscriptions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    endpoint = db.Column(db.Text, nullable=False)
    p256dh_key = db.Column(db.Text, nullable=False)
    auth_key = db.Column(db.Text, nullable=False)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    user = db.relationship('User', backref='push_subscriptions')
    
    def __repr__(self):
        return f'<PushSubscription {self.id} for user {self.user_id}>'
    
    def to_dict(self):
        """Convert subscription to dictionary for web push."""
        return {
            'endpoint': self.endpoint,
            'keys': {
                'p256dh': self.p256dh_key,
                'auth': self.auth_key
            }
        }


class NotificationLog(db.Model):
    __tablename__ = 'notification_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(255), nullable=True)
    url = db.Column(db.String(255), nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    success = db.Column(db.Boolean, default=True, nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', backref='notification_logs')
    
    def __repr__(self):
        return f'<NotificationLog {self.id} for user {self.user_id}>'
    
    def mark_as_read(self):
        """Markiere Benachrichtigung als gelesen."""
        self.is_read = True
        self.read_at = datetime.utcnow()
        db.session.commit()
