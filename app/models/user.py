from datetime import datetime
from flask_login import UserMixin
from argon2 import PasswordHasher
from app import db
import json

ph = PasswordHasher()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    
    # User status and role
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_super_admin = db.Column(db.Boolean, default=False, nullable=False)  # Hauptadministrator - kann Admin-Rechte nicht entzogen bekommen
    
    # Email confirmation
    confirmation_code = db.Column(db.String(6), nullable=True)
    confirmation_code_expires = db.Column(db.DateTime, nullable=True)
    is_email_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    
    # Password reset
    password_reset_code = db.Column(db.String(6), nullable=True)
    password_reset_code_expires = db.Column(db.DateTime, nullable=True)
    
    # Profile settings
    profile_picture = db.Column(db.String(255), nullable=True)
    accent_color = db.Column(db.String(7), default='#0d6efd')  # Bootstrap primary blue
    accent_gradient = db.Column(db.String(255), nullable=True)  # CSS gradient string
    dark_mode = db.Column(db.Boolean, default=False)
    oled_mode = db.Column(db.Boolean, default=False)  # OLED Dark Mode mit echtem Schwarz
    language = db.Column(db.String(10), default='de', nullable=False)
    preferred_layout = db.Column(db.String(20), default='auto', nullable=False)  # 'auto', 'mobile', 'desktop'
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    last_seen = db.Column(db.DateTime, nullable=True)  # Last activity timestamp for online status
    
    # Localization
    language = db.Column(db.String(10), default='de', nullable=False)
    
    # Push Notifications
    push_subscription = db.Column(db.Text, nullable=True)  # JSON string of push subscription
    notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    chat_notifications = db.Column(db.Boolean, default=True, nullable=False)
    email_notifications = db.Column(db.Boolean, default=True, nullable=False)
    
    can_borrow = db.Column(db.Boolean, default=True, nullable=False)
    
    # Guest Account Fields
    is_guest = db.Column(db.Boolean, default=False, nullable=False)  # Kennzeichnet Gast-Accounts
    guest_expires_at = db.Column(db.DateTime, nullable=True)  # Ablaufzeit für Gast-Accounts
    guest_username = db.Column(db.String(100), nullable=True)  # Benutzername für Gast-Accounts (z.B. "max.mustermann" für "max.mustermann@gast.system.local")
    
    # Module Access Control
    has_full_access = db.Column(db.Boolean, default=False, nullable=False)  # Vollzugriff auf alle Module
    
    # Password change requirement
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)  # Muss Passwort beim ersten Login ändern
    
    # Two-Factor Authentication (2FA)
    totp_secret = db.Column(db.String(255), nullable=True)  # Verschlüsseltes TOTP-Secret
    totp_enabled = db.Column(db.Boolean, default=False, nullable=False)
    
    # Password Policy
    password_changed_at = db.Column(db.DateTime, nullable=True)  # Wann wurde das Passwort zuletzt geändert
    
    # Rate Limiting für Login-Versuche
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    failed_login_until = db.Column(db.DateTime, nullable=True)  # Sperrung bis zu diesem Zeitpunkt
    
    # Dashboard Configuration
    dashboard_config = db.Column(db.Text, nullable=True)
    
    show_update_notifications = db.Column(db.Boolean, default=True, nullable=False)
    
    chat_memberships = db.relationship('ChatMember', back_populates='user', cascade='all, delete-orphan')
    sent_messages = db.relationship('ChatMessage', back_populates='sender', cascade='all, delete-orphan')
    uploaded_files = db.relationship('File', back_populates='uploader', cascade='all, delete-orphan')
    created_events = db.relationship('CalendarEvent', back_populates='creator', cascade='all, delete-orphan')
    event_participations = db.relationship('EventParticipant', back_populates='user', cascade='all, delete-orphan')
    email_permissions = db.relationship('EmailPermission', back_populates='user', uselist=False, cascade='all, delete-orphan')
    
    def set_password(self, password):
        """Hash and set the user's password."""
        self.password_hash = ph.hash(password)
    
    def check_password(self, password):
        """Verify the user's password."""
        try:
            ph.verify(self.password_hash, password)
            # Rehash if needed (Argon2 does this automatically)
            if ph.check_needs_rehash(self.password_hash):
                self.password_hash = ph.hash(password)
                db.session.commit()
            return True
        except:
            return False
    
    @property
    def full_name(self):
        """Return user's full name."""
        return f"{self.first_name} {self.last_name}"
    
    @property
    def accent_style(self):
        """Return the user's accent color or gradient for CSS."""
        if self.accent_gradient:
            return self.accent_gradient
        # For solid colors, create a gradient with the same start and end color
        # This ensures background-clip: text works properly
        return f"linear-gradient(45deg, {self.accent_color}, {self.accent_color})"
    
    def ensure_email_permissions(self):
        """Stellt sicher, dass der Benutzer E-Mail-Berechtigungen hat."""
        from app.models.email import EmailPermission
        
        existing_perm = EmailPermission.query.filter_by(user_id=self.id).first()
        if existing_perm:
            return existing_perm
        
        email_perm = EmailPermission(
            user_id=self.id,
            can_read=True,
            can_send=True
        )
        db.session.add(email_perm)
        db.session.commit()
        return email_perm
    
    def get_dashboard_config(self):
        """Gibt die Dashboard-Konfiguration zurück."""
        if self.dashboard_config:
            try:
                return json.loads(self.dashboard_config)
            except:
                pass
        # Standard-Konfiguration - nur die wichtigsten Widgets aktiv
        return {
            "enabled_widgets": ["termine", "nachrichten", "emails"],
            "quick_access_links": ["files", "credentials", "manuals"]
        }
    
    def set_dashboard_config(self, config):
        """Setzt die Dashboard-Konfiguration."""
        self.dashboard_config = json.dumps(config)
        db.session.commit()
    
    def is_online(self, threshold_minutes=5):
        """Prüft ob der Benutzer online ist (aktiv in den letzten X Minuten)."""
        if not self.last_seen:
            return False
        
        from datetime import timedelta
        threshold = datetime.utcnow() - timedelta(minutes=threshold_minutes)
        return self.last_seen >= threshold
    
    def update_last_seen(self):
        """Aktualisiert den last_seen Timestamp."""
        self.last_seen = datetime.utcnow()
        db.session.commit()
    
    def __repr__(self):
        return f'<User {self.email}>'



