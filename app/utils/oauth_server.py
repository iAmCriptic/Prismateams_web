"""
OAuth2 Server implementation for Prismateams.

Supports:
- Authorization Code flow with PKCE
- Client Credentials flow
- Refresh Token flow
- Token introspection
- Token revocation
"""
import hashlib
import base64
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from functools import wraps

from flask import request, jsonify, current_app
from flask_login import current_user

from app import db
from app.models.oauth import OAuth2Client, OAuth2AuthorizationCode, OAuth2Token
from app.models.user import User


class OAuth2Error(Exception):
    """Base OAuth2 error."""
    error: str = 'server_error'
    description: str = 'An error occurred'
    status_code: int = 400
    
    def __init__(self, description: str = None):
        if description:
            self.description = description
        super().__init__(self.description)
    
    def to_response(self):
        """Convert error to JSON response."""
        return jsonify({
            'error': self.error,
            'error_description': self.description
        }), self.status_code


class InvalidRequestError(OAuth2Error):
    error = 'invalid_request'
    description = 'The request is missing a required parameter or is otherwise malformed'


class InvalidClientError(OAuth2Error):
    error = 'invalid_client'
    description = 'Client authentication failed'
    status_code = 401


class InvalidGrantError(OAuth2Error):
    error = 'invalid_grant'
    description = 'The provided authorization grant is invalid, expired, or revoked'


class UnauthorizedClientError(OAuth2Error):
    error = 'unauthorized_client'
    description = 'The client is not authorized to request an authorization code'


class UnsupportedGrantTypeError(OAuth2Error):
    error = 'unsupported_grant_type'
    description = 'The authorization grant type is not supported'


class InvalidScopeError(OAuth2Error):
    error = 'invalid_scope'
    description = 'The requested scope is invalid, unknown, or malformed'


class AccessDeniedError(OAuth2Error):
    error = 'access_denied'
    description = 'The resource owner denied the request'
    status_code = 403


class OAuth2Server:
    """OAuth2 Authorization Server."""
    
    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize with Flask app."""
        self.app = app
        app.extensions['oauth2_server'] = self
    
    def authenticate_client(self) -> OAuth2Client:
        """
        Authenticate the OAuth2 client from request.
        
        Supports:
        - HTTP Basic Authentication
        - client_id/client_secret in request body
        """
        # Try HTTP Basic Auth first
        auth = request.authorization
        if auth:
            client_id = auth.username
            client_secret = auth.password
        else:
            # Try request body
            data = request.form if request.form else request.get_json() or {}
            client_id = data.get('client_id')
            client_secret = data.get('client_secret')
        
        if not client_id:
            raise InvalidClientError('Missing client_id')
        
        client = OAuth2Client.query.filter_by(client_id=client_id).first()
        
        if not client or not client.is_active:
            raise InvalidClientError('Invalid client')
        
        # For confidential clients, verify secret
        if client.is_confidential:
            if not client_secret:
                raise InvalidClientError('Missing client_secret')
            if not client.verify_client_secret(client_secret):
                raise InvalidClientError('Invalid client_secret')
        
        return client
    
    def validate_authorization_request(
        self,
        client_id: str,
        redirect_uri: str,
        response_type: str,
        scope: str = None,
        state: str = None,
        code_challenge: str = None,
        code_challenge_method: str = None
    ) -> Tuple[OAuth2Client, str, str]:
        """
        Validate an authorization request.
        
        Returns:
            Tuple of (client, validated_scope, redirect_uri)
        """
        if not client_id:
            raise InvalidRequestError('Missing client_id')
        
        if not redirect_uri:
            raise InvalidRequestError('Missing redirect_uri')
        
        if response_type != 'code':
            raise InvalidRequestError('Only response_type=code is supported')
        
        client = OAuth2Client.query.filter_by(client_id=client_id).first()
        
        if not client or not client.is_active:
            raise InvalidClientError('Invalid client')
        
        if not client.check_redirect_uri(redirect_uri):
            raise InvalidRequestError('Invalid redirect_uri')
        
        if not client.check_response_type(response_type):
            raise UnauthorizedClientError('Response type not allowed')
        
        # Validate scope
        if scope and not client.check_scope(scope):
            raise InvalidScopeError('Requested scope not allowed')
        
        # PKCE validation for public clients
        if not client.is_confidential or client.require_pkce:
            if not code_challenge:
                raise InvalidRequestError('PKCE code_challenge required')
            if code_challenge_method not in (None, 'plain', 'S256'):
                raise InvalidRequestError('Invalid code_challenge_method')
        
        return client, scope or '', redirect_uri
    
    def create_authorization_code(
        self,
        client: OAuth2Client,
        user: User,
        redirect_uri: str,
        scope: str = None,
        state: str = None,
        nonce: str = None,
        code_challenge: str = None,
        code_challenge_method: str = 'S256'
    ) -> OAuth2AuthorizationCode:
        """Create an authorization code."""
        code = OAuth2AuthorizationCode(
            code=OAuth2AuthorizationCode.generate_code(),
            client_id=client.id,
            user_id=user.id,
            redirect_uri=redirect_uri,
            scope=scope,
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            expires_at=datetime.utcnow() + timedelta(minutes=10)  # 10 minute expiry
        )
        
        db.session.add(code)
        db.session.commit()
        
        return code
    
    def validate_token_request(self, grant_type: str) -> OAuth2Client:
        """Validate a token request and return the client."""
        if grant_type not in ('authorization_code', 'refresh_token', 'client_credentials'):
            raise UnsupportedGrantTypeError()
        
        client = self.authenticate_client()
        
        if not client.check_grant_type(grant_type):
            raise UnauthorizedClientError(f'Grant type {grant_type} not allowed for this client')
        
        return client
    
    def exchange_authorization_code(
        self,
        client: OAuth2Client,
        code: str,
        redirect_uri: str,
        code_verifier: str = None
    ) -> OAuth2Token:
        """Exchange an authorization code for tokens."""
        auth_code = OAuth2AuthorizationCode.query.filter_by(
            code=code,
            client_id=client.id
        ).first()
        
        if not auth_code:
            raise InvalidGrantError('Invalid authorization code')
        
        if not auth_code.is_valid():
            # Delete the invalid code
            db.session.delete(auth_code)
            db.session.commit()
            raise InvalidGrantError('Authorization code expired or already used')
        
        if auth_code.redirect_uri != redirect_uri:
            raise InvalidGrantError('Redirect URI mismatch')
        
        # Verify PKCE if code_challenge was set
        if auth_code.code_challenge:
            if not code_verifier:
                raise InvalidGrantError('PKCE code_verifier required')
            if not auth_code.verify_pkce(code_verifier):
                raise InvalidGrantError('Invalid code_verifier')
        
        # Mark code as used
        auth_code.is_used = True
        
        # Create token
        user = User.query.get(auth_code.user_id)
        token = OAuth2Token.create_token(client, user, auth_code.scope)
        
        db.session.add(token)
        db.session.commit()
        
        return token
    
    def refresh_access_token(
        self,
        client: OAuth2Client,
        refresh_token: str,
        scope: str = None
    ) -> OAuth2Token:
        """Refresh an access token."""
        token = OAuth2Token.get_by_refresh_token(refresh_token)
        
        if not token:
            raise InvalidGrantError('Invalid refresh token')
        
        if token.client_id != client.id:
            raise InvalidGrantError('Token does not belong to this client')
        
        if not token.can_refresh():
            raise InvalidGrantError('Refresh token expired or revoked')
        
        # Validate scope (can only reduce scope, not expand)
        new_scope = scope
        if scope:
            original_scopes = set(token.get_scopes())
            requested_scopes = set(scope.split())
            if not requested_scopes.issubset(original_scopes):
                raise InvalidScopeError('Cannot expand scope during refresh')
        else:
            new_scope = token.scope
        
        # Revoke old token
        token.revoke()
        
        # Create new token
        user = User.query.get(token.user_id) if token.user_id else None
        new_token = OAuth2Token.create_token(client, user, new_scope)
        
        db.session.add(new_token)
        db.session.commit()
        
        return new_token
    
    def create_client_credentials_token(
        self,
        client: OAuth2Client,
        scope: str = None
    ) -> OAuth2Token:
        """Create a token using client credentials grant."""
        if not client.is_confidential:
            raise UnauthorizedClientError('Client credentials grant requires confidential client')
        
        # Validate scope
        if scope and not client.check_scope(scope):
            raise InvalidScopeError('Requested scope not allowed')
        
        # Create token without user
        token = OAuth2Token.create_token(client, user=None, scope=scope)
        
        db.session.add(token)
        db.session.commit()
        
        return token
    
    def revoke_token(self, token_string: str, token_type_hint: str = None) -> bool:
        """Revoke a token."""
        token = None
        
        if token_type_hint == 'access_token' or not token_type_hint:
            token = OAuth2Token.get_by_access_token(token_string)
        
        if not token and (token_type_hint == 'refresh_token' or not token_type_hint):
            token = OAuth2Token.get_by_refresh_token(token_string)
        
        if token:
            token.revoke()
            db.session.commit()
            return True
        
        return False
    
    def introspect_token(self, token_string: str, token_type_hint: str = None) -> dict:
        """Introspect a token (RFC 7662)."""
        token = None
        
        if token_type_hint == 'access_token' or not token_type_hint:
            token = OAuth2Token.get_by_access_token(token_string)
        
        if not token and (token_type_hint == 'refresh_token' or not token_type_hint):
            token = OAuth2Token.get_by_refresh_token(token_string)
        
        if not token or token.revoked:
            return {'active': False}
        
        # Check if access token is expired
        if token_string == token.access_token and token.is_access_token_expired():
            return {'active': False}
        
        result = {
            'active': True,
            'client_id': token.client.client_id,
            'token_type': token.token_type,
            'scope': token.scope,
            'exp': int(token.access_token_expires_at.timestamp()),
            'iat': int(token.issued_at.timestamp()) if token.issued_at else None,
        }
        
        if token.user_id:
            user = User.query.get(token.user_id)
            if user:
                result['sub'] = str(user.id)
                result['username'] = user.email
        
        return result
    
    def get_userinfo(self, token: OAuth2Token) -> dict:
        """Get user info for OpenID Connect."""
        if not token.user_id:
            raise AccessDeniedError('No user associated with this token')
        
        user = User.query.get(token.user_id)
        if not user:
            raise AccessDeniedError('User not found')
        
        scopes = token.get_scopes()
        
        # Base info (always included)
        info = {
            'sub': str(user.id)
        }
        
        # Profile scope
        if 'profile' in scopes or 'openid' in scopes:
            info['name'] = user.full_name
            info['given_name'] = user.first_name
            info['family_name'] = user.last_name
            if user.profile_picture_filename:
                info['picture'] = f'/settings/profile-picture/{user.profile_picture_filename}'
        
        # Email scope
        if 'email' in scopes:
            info['email'] = user.email
            info['email_verified'] = user.email_confirmed
        
        return info


def get_oauth2_server() -> OAuth2Server:
    """Get the OAuth2 server instance."""
    return current_app.extensions.get('oauth2_server', OAuth2Server())


def require_oauth(scopes: str = None):
    """
    Decorator to require OAuth2 authentication for an endpoint.
    
    Args:
        scopes: Space-separated list of required scopes
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get token from Authorization header
            auth_header = request.headers.get('Authorization', '')
            
            if not auth_header.startswith('Bearer '):
                return jsonify({
                    'error': 'invalid_request',
                    'error_description': 'Missing or invalid Authorization header'
                }), 401
            
            token_string = auth_header[7:]  # Remove 'Bearer ' prefix
            
            token = OAuth2Token.get_by_access_token(token_string)
            
            if not token:
                return jsonify({
                    'error': 'invalid_token',
                    'error_description': 'Invalid access token'
                }), 401
            
            if not token.is_valid():
                return jsonify({
                    'error': 'invalid_token',
                    'error_description': 'Token expired or revoked'
                }), 401
            
            # Check scopes
            if scopes:
                required_scopes = set(scopes.split())
                token_scopes = set(token.get_scopes())
                
                if not required_scopes.issubset(token_scopes):
                    return jsonify({
                        'error': 'insufficient_scope',
                        'error_description': f'Required scopes: {scopes}'
                    }), 403
            
            # Add token and user to request context
            request.oauth_token = token
            if token.user_id:
                request.oauth_user = User.query.get(token.user_id)
            else:
                request.oauth_user = None
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def get_current_oauth_user() -> Optional[User]:
    """Get the current user from OAuth token."""
    return getattr(request, 'oauth_user', None)


def get_current_oauth_token() -> Optional[OAuth2Token]:
    """Get the current OAuth token."""
    return getattr(request, 'oauth_token', None)
