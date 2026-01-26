"""
Webhook models for external system integrations.
"""
from datetime import datetime
from app import db


class Webhook(db.Model):
    """Webhook configuration for external systems."""
    __tablename__ = 'webhook'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    secret = db.Column(db.String(64), nullable=True)  # HMAC-SHA256 signature key
    events = db.Column(db.JSON, nullable=False, default=list)  # List of subscribed events
    headers = db.Column(db.JSON, nullable=True, default=dict)  # Custom headers
    is_active = db.Column(db.Boolean, default=True)
    
    # Rate limiting
    max_retries = db.Column(db.Integer, default=5)
    retry_delay = db.Column(db.Integer, default=60)  # seconds
    timeout = db.Column(db.Integer, default=10)  # seconds
    
    # Metadata
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_triggered_at = db.Column(db.DateTime, nullable=True)
    
    # Statistics
    total_deliveries = db.Column(db.Integer, default=0)
    successful_deliveries = db.Column(db.Integer, default=0)
    failed_deliveries = db.Column(db.Integer, default=0)
    
    # Relationships
    creator = db.relationship('User', backref=db.backref('webhooks', lazy='dynamic'))
    deliveries = db.relationship('WebhookDelivery', backref='webhook', lazy='dynamic', cascade='all, delete-orphan')
    
    # Available webhook events
    EVENTS = {
        # Chat events
        'chat.message.created': 'Neue Chat-Nachricht',
        'chat.created': 'Chat erstellt',
        'chat.member.added': 'Chat-Mitglied hinzugefügt',
        'chat.member.removed': 'Chat-Mitglied entfernt',
        
        # Calendar events
        'calendar.event.created': 'Termin erstellt',
        'calendar.event.updated': 'Termin aktualisiert',
        'calendar.event.deleted': 'Termin gelöscht',
        'calendar.event.reminder': 'Terminerinnerung',
        
        # File events
        'file.uploaded': 'Datei hochgeladen',
        'file.updated': 'Datei aktualisiert',
        'file.deleted': 'Datei gelöscht',
        'file.version.created': 'Dateiversion erstellt',
        
        # Email events
        'email.received': 'E-Mail empfangen',
        'email.sent': 'E-Mail gesendet',
        
        # Inventory events
        'inventory.product.created': 'Produkt erstellt',
        'inventory.product.updated': 'Produkt aktualisiert',
        'inventory.product.deleted': 'Produkt gelöscht',
        'inventory.borrow.created': 'Ausleihe erstellt',
        'inventory.return.completed': 'Rückgabe abgeschlossen',
        
        # User events
        'user.created': 'Benutzer erstellt',
        'user.updated': 'Benutzer aktualisiert',
        'user.deleted': 'Benutzer gelöscht',
        'user.login': 'Benutzer angemeldet',
        'user.logout': 'Benutzer abgemeldet',
        
        # Wiki events
        'wiki.page.created': 'Wiki-Seite erstellt',
        'wiki.page.updated': 'Wiki-Seite aktualisiert',
        'wiki.page.deleted': 'Wiki-Seite gelöscht',
        
        # Booking events
        'booking.request.created': 'Buchungsanfrage erstellt',
        'booking.request.approved': 'Buchungsanfrage genehmigt',
        'booking.request.rejected': 'Buchungsanfrage abgelehnt',
    }
    
    def to_dict(self):
        """Convert webhook to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'events': self.events,
            'headers': self.headers or {},
            'is_active': self.is_active,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'timeout': self.timeout,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_triggered_at': self.last_triggered_at.isoformat() if self.last_triggered_at else None,
            'total_deliveries': self.total_deliveries,
            'successful_deliveries': self.successful_deliveries,
            'failed_deliveries': self.failed_deliveries,
        }
    
    def is_subscribed_to(self, event_type):
        """Check if webhook is subscribed to an event type."""
        if not self.is_active:
            return False
        return event_type in (self.events or [])
    
    @classmethod
    def get_active_for_event(cls, event_type):
        """Get all active webhooks subscribed to an event type."""
        return cls.query.filter(
            cls.is_active == True,
            cls.events.contains([event_type])
        ).all()


class WebhookDelivery(db.Model):
    """Webhook delivery log for tracking and debugging."""
    __tablename__ = 'webhook_delivery'
    
    id = db.Column(db.Integer, primary_key=True)
    webhook_id = db.Column(db.Integer, db.ForeignKey('webhook.id'), nullable=False)
    
    # Event details
    event_type = db.Column(db.String(50), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    
    # Request details
    request_headers = db.Column(db.JSON, nullable=True)
    
    # Response details
    response_code = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.Text, nullable=True)
    response_headers = db.Column(db.JSON, nullable=True)
    
    # Timing
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    delivered_at = db.Column(db.DateTime, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)  # Request duration in milliseconds
    
    # Retry tracking
    retry_count = db.Column(db.Integer, default=0)
    next_retry_at = db.Column(db.DateTime, nullable=True)
    
    # Status
    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_RETRYING = 'retrying'
    
    status = db.Column(db.String(20), default=STATUS_PENDING)
    error_message = db.Column(db.Text, nullable=True)
    
    def to_dict(self):
        """Convert delivery to dictionary."""
        return {
            'id': self.id,
            'webhook_id': self.webhook_id,
            'event_type': self.event_type,
            'payload': self.payload,
            'response_code': self.response_code,
            'status': self.status,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None,
            'duration_ms': self.duration_ms,
        }
    
    def mark_success(self, response_code, response_body=None, response_headers=None, duration_ms=None):
        """Mark delivery as successful."""
        self.status = self.STATUS_SUCCESS
        self.response_code = response_code
        self.response_body = response_body[:10000] if response_body else None  # Limit response body
        self.response_headers = response_headers
        self.delivered_at = datetime.utcnow()
        self.duration_ms = duration_ms
        self.error_message = None
        
        # Update webhook statistics
        if self.webhook:
            self.webhook.successful_deliveries += 1
            self.webhook.last_triggered_at = datetime.utcnow()
    
    def mark_failed(self, error_message, response_code=None, response_body=None):
        """Mark delivery as failed."""
        self.status = self.STATUS_FAILED
        self.error_message = error_message
        self.response_code = response_code
        self.response_body = response_body[:10000] if response_body else None
        self.delivered_at = datetime.utcnow()
        
        # Update webhook statistics
        if self.webhook:
            self.webhook.failed_deliveries += 1
    
    def schedule_retry(self, next_retry_at):
        """Schedule a retry for this delivery."""
        self.status = self.STATUS_RETRYING
        self.retry_count += 1
        self.next_retry_at = next_retry_at
