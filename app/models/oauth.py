"""
OAuth2 models for external application authentication.
"""
from datetime import datetime, timedelta
import secrets
import hashlib
from app import db


class OAuth2Client(db.Model):
    """OAuth2 client application."""
    __tablename__ = 'oauth2_client'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Client credentials
    client_id = db.Column(db.String(48), unique=True, nullable=False, index=True)
    client_secret_hash = db.Column(db.String(128), nullable=True)  # Hashed secret, NULL for public clients
    
    # Client metadata
    client_name = db.Column(db.String(100), nullable=False)
    client_description = db.Column(db.Text, nullable=True)
    client_uri = db.Column(db.String(500), nullable=True)  # Homepage URL
    logo_uri = db.Column(db.String(500), nullable=True)
    
    # OAuth2 configuration
    redirect_uris = db.Column(db.JSON, nullable=False, default=list)  # List of allowed redirect URIs
    allowed_scopes = db.Column(db.JSON, nullable=False, default=list)  # List of allowed scopes
    allowed_grant_types = db.Column(db.JSON, nullable=False, default=list)  # authorization_code, client_credentials, refresh_token
    allowed_response_types = db.Column(db.JSON, nullable=False, default=list)  # code, token
    
    # Client type
    is_confidential = db.Column(db.Boolean, default=True)  # False for public clients (mobile/SPA)
    require_pkce = db.Column(db.Boolean, default=False)  # Require PKCE for authorization code flow
    
    # Token settings
    access_token_lifetime = db.Column(db.Integer, default=3600)  # seconds (1 hour)
    refresh_token_lifetime = db.Column(db.Integer, default=2592000)  # seconds (30 days)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Metadata
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    creator = db.relationship('User', backref=db.backref('oauth_clients', lazy='dynamic'))
    authorization_codes = db.relationship('OAuth2AuthorizationCode', backref='client', lazy='dynamic', cascade='all, delete-orphan')
    tokens = db.relationship('OAuth2Token', backref='client', lazy='dynamic', cascade='all, delete-orphan')
    
    # Available OAuth2 scopes
    SCOPES = {
        'openid': 'Grundlegende Identitätsinformationen',
        'profile': 'Profilinformationen (Name, Bild)',
        'email': 'E-Mail-Adresse',
        
        'read:users': 'Benutzerinformationen lesen',
        'write:users': 'Benutzerinformationen bearbeiten',
        
        'read:chats': 'Chat-Nachrichten lesen',
        'write:chats': 'Chat-Nachrichten senden',
        
        'read:files': 'Dateien lesen',
        'write:files': 'Dateien hochladen und bearbeiten',
        
        'read:calendar': 'Kalendertermine lesen',
        'write:calendar': 'Kalendertermine erstellen und bearbeiten',
        
        'read:inventory': 'Inventar lesen',
        'write:inventory': 'Inventar bearbeiten',
        
        'read:email': 'E-Mails lesen',
        'write:email': 'E-Mails senden',
        
        'read:wiki': 'Wiki-Seiten lesen',
        'write:wiki': 'Wiki-Seiten bearbeiten',
        
        'webhooks': 'Webhooks verwalten',
        'admin': 'Administrative Funktionen',
    }
    
    @staticmethod
    def generate_client_id():
        """Generate a unique client ID."""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def generate_client_secret():
        """Generate a secure client secret."""
        return secrets.token_urlsafe(48)
    
    @staticmethod
    def hash_client_secret(secret):
        """Hash a client secret for storage."""
        return hashlib.sha256(secret.encode()).hexdigest()
    
    def set_client_secret(self, secret):
        """Set and hash the client secret."""
        self.client_secret_hash = self.hash_client_secret(secret)
    
    def verify_client_secret(self, secret):
        """Verify a client secret."""
        if not self.client_secret_hash:
            return True  # Public client
        return self.client_secret_hash == self.hash_client_secret(secret)
    
    def check_redirect_uri(self, redirect_uri):
        """Check if redirect URI is allowed."""
        return redirect_uri in (self.redirect_uris or [])
    
    def check_grant_type(self, grant_type):
        """Check if grant type is allowed."""
        return grant_type in (self.allowed_grant_types or [])
    
    def check_response_type(self, response_type):
        """Check if response type is allowed."""
        return response_type in (self.allowed_response_types or [])
    
    def check_scope(self, scope):
        """Check if scope is allowed."""
        if not scope:
            return True
        requested_scopes = scope.split() if isinstance(scope, str) else scope
        allowed = self.allowed_scopes or []
        return all(s in allowed for s in requested_scopes)
    
    def to_dict(self, include_secret=False):
        """Convert client to dictionary."""
        data = {
            'id': self.id,
            'client_id': self.client_id,
            'client_name': self.client_name,
            'client_description': self.client_description,
            'client_uri': self.client_uri,
            'logo_uri': self.logo_uri,
            'redirect_uris': self.redirect_uris,
            'allowed_scopes': self.allowed_scopes,
            'allowed_grant_types': self.allowed_grant_types,
            'allowed_response_types': self.allowed_response_types,
            'is_confidential': self.is_confidential,
            'require_pkce': self.require_pkce,
            'access_token_lifetime': self.access_token_lifetime,
            'refresh_token_lifetime': self.refresh_token_lifetime,
            'is_active': self.is_active,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        return data


class OAuth2AuthorizationCode(db.Model):
    """OAuth2 authorization code for authorization code flow."""
    __tablename__ = 'oauth2_authorization_code'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Code
    code = db.Column(db.String(120), unique=True, nullable=False, index=True)
    
    # References
    client_id = db.Column(db.Integer, db.ForeignKey('oauth2_client.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Authorization details
    redirect_uri = db.Column(db.String(500), nullable=False)
    scope = db.Column(db.String(500), nullable=True)
    state = db.Column(db.String(200), nullable=True)
    nonce = db.Column(db.String(200), nullable=True)  # OpenID Connect
    
    # PKCE
    code_challenge = db.Column(db.String(128), nullable=True)
    code_challenge_method = db.Column(db.String(10), nullable=True)  # S256 or plain
    
    # Timing
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    
    # Status
    is_used = db.Column(db.Boolean, default=False)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('oauth_authorization_codes', lazy='dynamic'))
    
    @staticmethod
    def generate_code():
        """Generate a secure authorization code."""
        return secrets.token_urlsafe(64)
    
    def is_expired(self):
        """Check if code is expired."""
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self):
        """Check if code is valid (not used and not expired)."""
        return not self.is_used and not self.is_expired()
    
    def verify_pkce(self, code_verifier):
        """Verify PKCE code verifier."""
        if not self.code_challenge:
            return True  # PKCE not required
        
        if self.code_challenge_method == 'S256':
            # SHA256 hash of verifier
            challenge = hashlib.sha256(code_verifier.encode()).digest()
            import base64
            expected = base64.urlsafe_b64encode(challenge).rstrip(b'=').decode()
            return expected == self.code_challenge
        elif self.code_challenge_method == 'plain':
            return code_verifier == self.code_challenge
        
        return False


class OAuth2Token(db.Model):
    """OAuth2 access and refresh tokens."""
    __tablename__ = 'oauth2_token'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # References
    client_id = db.Column(db.Integer, db.ForeignKey('oauth2_client.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # NULL for client credentials
    
    # Token type
    token_type = db.Column(db.String(20), default='Bearer')
    
    # Tokens
    access_token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    refresh_token = db.Column(db.String(255), unique=True, nullable=True, index=True)
    
    # Authorization details
    scope = db.Column(db.String(500), nullable=True)
    
    # Timing
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    access_token_expires_at = db.Column(db.DateTime, nullable=False)
    refresh_token_expires_at = db.Column(db.DateTime, nullable=True)
    
    # Status
    revoked = db.Column(db.Boolean, default=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
    
    # Metadata
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('oauth_tokens', lazy='dynamic'))
    
    @staticmethod
    def generate_access_token():
        """Generate a secure access token."""
        return secrets.token_urlsafe(64)
    
    @staticmethod
    def generate_refresh_token():
        """Generate a secure refresh token."""
        return secrets.token_urlsafe(64)
    
    def is_access_token_expired(self):
        """Check if access token is expired."""
        return datetime.utcnow() > self.access_token_expires_at
    
    def is_refresh_token_expired(self):
        """Check if refresh token is expired."""
        if not self.refresh_token_expires_at:
            return True
        return datetime.utcnow() > self.refresh_token_expires_at
    
    def is_valid(self):
        """Check if token is valid."""
        return not self.revoked and not self.is_access_token_expired()
    
    def can_refresh(self):
        """Check if token can be refreshed."""
        return not self.revoked and self.refresh_token and not self.is_refresh_token_expired()
    
    def revoke(self):
        """Revoke this token."""
        self.revoked = True
        self.revoked_at = datetime.utcnow()
    
    def get_scopes(self):
        """Get list of scopes."""
        return self.scope.split() if self.scope else []
    
    def has_scope(self, scope):
        """Check if token has a specific scope."""
        return scope in self.get_scopes()
    
    def to_dict(self):
        """Convert token to dictionary (for token response)."""
        data = {
            'access_token': self.access_token,
            'token_type': self.token_type,
            'expires_in': int((self.access_token_expires_at - datetime.utcnow()).total_seconds()),
            'scope': self.scope,
        }
        if self.refresh_token:
            data['refresh_token'] = self.refresh_token
        return data
    
    @classmethod
    def get_by_access_token(cls, access_token):
        """Get token by access token."""
        return cls.query.filter_by(access_token=access_token, revoked=False).first()
    
    @classmethod
    def get_by_refresh_token(cls, refresh_token):
        """Get token by refresh token."""
        return cls.query.filter_by(refresh_token=refresh_token, revoked=False).first()
    
    @classmethod
    def create_token(cls, client, user=None, scope=None):
        """Create a new access token."""
        access_token_lifetime = client.access_token_lifetime or 3600
        refresh_token_lifetime = client.refresh_token_lifetime or 2592000
        
        token = cls(
            client_id=client.id,
            user_id=user.id if user else None,
            access_token=cls.generate_access_token(),
            refresh_token=cls.generate_refresh_token() if 'refresh_token' in (client.allowed_grant_types or []) else None,
            scope=scope,
            access_token_expires_at=datetime.utcnow() + timedelta(seconds=access_token_lifetime),
            refresh_token_expires_at=datetime.utcnow() + timedelta(seconds=refresh_token_lifetime) if refresh_token_lifetime else None,
        )
        return token
