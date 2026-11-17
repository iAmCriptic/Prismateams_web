from datetime import datetime
from app import db


class NotificationSettings(db.Model):
    __tablename__ = 'notification_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Global Snooze / Pause
    notifications_paused_until = db.Column(db.DateTime, nullable=True)

    # Legacy / Master flags for backwards compatibility
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
    booking_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    booking_message_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    inventory_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    kanban_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    kanban_upload_notifications = db.Column(db.Boolean, default=True, nullable=False)
    kanban_change_notifications = db.Column(db.Boolean, default=True, nullable=False)
    kanban_checklist_notifications = db.Column(db.Boolean, default=True, nullable=False)

    # In-App / Portal Channel flags
    chat_portal_enabled = db.Column(db.Boolean, default=True, nullable=False)
    kanban_portal_enabled = db.Column(db.Boolean, default=True, nullable=False)
    email_portal_enabled = db.Column(db.Boolean, default=True, nullable=False)
    comment_portal_enabled = db.Column(db.Boolean, default=True, nullable=False)
    inventory_portal_enabled = db.Column(db.Boolean, default=True, nullable=False)
    booking_portal_enabled = db.Column(db.Boolean, default=True, nullable=False)
    room_booking_portal_enabled = db.Column(db.Boolean, default=True, nullable=False)
    survey_portal_enabled = db.Column(db.Boolean, default=True, nullable=False)
    calendar_portal_enabled = db.Column(db.Boolean, default=True, nullable=False)
    file_portal_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # WebPush Channel flags
    chat_push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    kanban_push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    email_push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    comment_push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    inventory_push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    booking_push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    room_booking_push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    survey_push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    calendar_push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    file_push_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Specific Sub-Toggles
    comment_mention_notifications = db.Column(db.Boolean, default=True, nullable=False)
    comment_reply_notifications = db.Column(db.Boolean, default=True, nullable=False)
    survey_new_notifications = db.Column(db.Boolean, default=True, nullable=False)
    survey_response_notifications = db.Column(db.Boolean, default=True, nullable=False)
    room_booking_new_notifications = db.Column(db.Boolean, default=True, nullable=False)
    room_booking_status_notifications = db.Column(db.Boolean, default=True, nullable=False)

    reminder_times = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = db.relationship('User', backref='notification_settings')
    
    def __repr__(self):
        return f'<NotificationSettings user={self.user_id}>'

    def is_paused(self) -> bool:
        """Prüft, ob Benachrichtigungen aktuell zeitgesteuert pausiert sind."""
        if self.notifications_paused_until:
            return datetime.utcnow() < self.notifications_paused_until
        return False

    def pause(self, minutes: int):
        """Pausiert alle Benachrichtigungen für die angegebene Minutenzahl."""
        if minutes > 0:
            from datetime import timedelta
            self.notifications_paused_until = datetime.utcnow() + timedelta(minutes=minutes)
        else:
            self.notifications_paused_until = None

    def unpause(self):
        """Beendet die Pausierung von Benachrichtigungen."""
        self.notifications_paused_until = None

    def is_portal_enabled(self, module_type: str) -> bool:
        """Prüft, ob In-App-Benachrichtigungen für diesen Modultyp aktiv sind."""
        key = (module_type or '').lower().strip()
        mapping = {
            'chat': 'chat_portal_enabled',
            'kanban': 'kanban_portal_enabled',
            'email': 'email_portal_enabled',
            'comment': 'comment_portal_enabled',
            'comment_mention': 'comment_portal_enabled',
            'inventory': 'inventory_portal_enabled',
            'booking': 'booking_portal_enabled',
            'booking_message': 'booking_portal_enabled',
            'room_booking': 'room_booking_portal_enabled',
            'survey': 'survey_portal_enabled',
            'calendar': 'calendar_portal_enabled',
            'file': 'file_portal_enabled',
        }
        attr = mapping.get(key)
        if attr:
            return bool(getattr(self, attr, True))
        return True

    def is_push_enabled(self, module_type: str) -> bool:
        """Prüft, ob WebPush-Benachrichtigungen für diesen Modultyp aktiv sind."""
        key = (module_type or '').lower().strip()
        mapping = {
            'chat': 'chat_push_enabled',
            'kanban': 'kanban_push_enabled',
            'email': 'email_push_enabled',
            'comment': 'comment_push_enabled',
            'comment_mention': 'comment_push_enabled',
            'inventory': 'inventory_push_enabled',
            'booking': 'booking_push_enabled',
            'booking_message': 'booking_push_enabled',
            'room_booking': 'room_booking_push_enabled',
            'survey': 'survey_push_enabled',
            'calendar': 'calendar_push_enabled',
            'file': 'file_push_enabled',
        }
        attr = mapping.get(key)
        if attr:
            return bool(getattr(self, attr, True))
        return True
    
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
    notification_type = db.Column(db.String(32), nullable=True)
    dedup_key = db.Column(db.String(255), nullable=True, index=True)
    source_id = db.Column(db.Integer, nullable=True)
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


class PushDeliveryLog(db.Model):
    """Pro Push-Subscription und dedup_key maximal ein Web-Push."""
    __tablename__ = 'push_delivery_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey('push_subscriptions.id'), nullable=False)
    dedup_key = db.Column(db.String(255), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref='push_delivery_logs')
    subscription = db.relationship('PushSubscription', backref='delivery_logs')

    __table_args__ = (
        db.UniqueConstraint('subscription_id', 'dedup_key', name='unique_push_delivery_per_subscription'),
    )

    def __repr__(self):
        return f'<PushDeliveryLog sub={self.subscription_id} key={self.dedup_key}>'
