"""
OAuth2 Authorization Server endpoints.

Implements:
- Authorization endpoint (/oauth/authorize)
- Token endpoint (/oauth/token)
- Revocation endpoint (/oauth/revoke)
- Introspection endpoint (/oauth/introspect)
- UserInfo endpoint (/oauth/userinfo)
- Server metadata endpoint (/.well-known/oauth-authorization-server)
"""
import secrets
from urllib.parse import urlencode, urlparse, parse_qs

from flask import Blueprint, request, jsonify, redirect, render_template, url_for, flash, current_app
from flask_login import login_required, current_user

from app import db
from app.models.oauth import OAuth2Client, OAuth2AuthorizationCode, OAuth2Token
from app.models.user import User
from app.utils.oauth_server import (
    OAuth2Server, OAuth2Error, InvalidRequestError, InvalidClientError,
    InvalidGrantError, AccessDeniedError, require_oauth, get_oauth2_server
)


oauth_bp = Blueprint('oauth', __name__)


# ==================== Authorization Endpoint ====================

@oauth_bp.route('/oauth/authorize', methods=['GET', 'POST'])
@login_required
def authorize():
    """
    OAuth2 Authorization Endpoint.
    
    GET: Display authorization form
    POST: Process authorization decision
    """
    server = get_oauth2_server()
    
    # Get request parameters
    client_id = request.args.get('client_id') or request.form.get('client_id')
    redirect_uri = request.args.get('redirect_uri') or request.form.get('redirect_uri')
    response_type = request.args.get('response_type') or request.form.get('response_type')
    scope = request.args.get('scope') or request.form.get('scope')
    state = request.args.get('state') or request.form.get('state')
    code_challenge = request.args.get('code_challenge') or request.form.get('code_challenge')
    code_challenge_method = request.args.get('code_challenge_method') or request.form.get('code_challenge_method', 'S256')
    nonce = request.args.get('nonce') or request.form.get('nonce')
    
    try:
        client, validated_scope, validated_redirect_uri = server.validate_authorization_request(
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method
        )
    except OAuth2Error as e:
        # If we can't validate the redirect_uri, show error page
        if not redirect_uri:
            return render_template('oauth/error.html', error=e.error, description=e.description)
        
        # Otherwise redirect with error
        error_params = {
            'error': e.error,
            'error_description': e.description
        }
        if state:
            error_params['state'] = state
        
        separator = '&' if '?' in redirect_uri else '?'
        return redirect(f"{redirect_uri}{separator}{urlencode(error_params)}")
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'deny':
            # User denied authorization
            error_params = {
                'error': 'access_denied',
                'error_description': 'User denied the request'
            }
            if state:
                error_params['state'] = state
            
            separator = '&' if '?' in validated_redirect_uri else '?'
            return redirect(f"{validated_redirect_uri}{separator}{urlencode(error_params)}")
        
        if action == 'authorize':
            # User authorized the request
            auth_code = server.create_authorization_code(
                client=client,
                user=current_user,
                redirect_uri=validated_redirect_uri,
                scope=validated_scope,
                state=state,
                nonce=nonce,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method
            )
            
            # Redirect with authorization code
            params = {'code': auth_code.code}
            if state:
                params['state'] = state
            
            separator = '&' if '?' in validated_redirect_uri else '?'
            return redirect(f"{validated_redirect_uri}{separator}{urlencode(params)}")
    
    # GET request - show authorization form
    requested_scopes = []
    if validated_scope:
        for scope_name in validated_scope.split():
            scope_description = OAuth2Client.SCOPES.get(scope_name, scope_name)
            requested_scopes.append({
                'name': scope_name,
                'description': scope_description
            })
    
    return render_template('oauth/authorize.html',
        client=client,
        scopes=requested_scopes,
        redirect_uri=validated_redirect_uri,
        scope=validated_scope,
        state=state,
        response_type=response_type,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        nonce=nonce
    )


# ==================== Token Endpoint ====================

@oauth_bp.route('/oauth/token', methods=['POST'])
def token():
    """
    OAuth2 Token Endpoint.
    
    Supports:
    - authorization_code grant
    - refresh_token grant
    - client_credentials grant
    """
    server = get_oauth2_server()
    
    grant_type = request.form.get('grant_type')
    
    try:
        client = server.validate_token_request(grant_type)
        
        if grant_type == 'authorization_code':
            code = request.form.get('code')
            redirect_uri = request.form.get('redirect_uri')
            code_verifier = request.form.get('code_verifier')
            
            if not code:
                raise InvalidRequestError('Missing authorization code')
            if not redirect_uri:
                raise InvalidRequestError('Missing redirect_uri')
            
            token = server.exchange_authorization_code(
                client=client,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier
            )
            
        elif grant_type == 'refresh_token':
            refresh_token = request.form.get('refresh_token')
            scope = request.form.get('scope')
            
            if not refresh_token:
                raise InvalidRequestError('Missing refresh_token')
            
            token = server.refresh_access_token(
                client=client,
                refresh_token=refresh_token,
                scope=scope
            )
            
        elif grant_type == 'client_credentials':
            scope = request.form.get('scope')
            
            token = server.create_client_credentials_token(
                client=client,
                scope=scope
            )
        
        return jsonify(token.to_dict())
        
    except OAuth2Error as e:
        return e.to_response()


# ==================== Revocation Endpoint ====================

@oauth_bp.route('/oauth/revoke', methods=['POST'])
def revoke():
    """
    OAuth2 Token Revocation Endpoint (RFC 7009).
    """
    server = get_oauth2_server()
    
    try:
        client = server.authenticate_client()
    except OAuth2Error as e:
        return e.to_response()
    
    token = request.form.get('token')
    token_type_hint = request.form.get('token_type_hint')
    
    if not token:
        return jsonify({
            'error': 'invalid_request',
            'error_description': 'Missing token parameter'
        }), 400
    
    server.revoke_token(token, token_type_hint)
    
    # Always return 200 OK (RFC 7009)
    return '', 200


# ==================== Introspection Endpoint ====================

@oauth_bp.route('/oauth/introspect', methods=['POST'])
def introspect():
    """
    OAuth2 Token Introspection Endpoint (RFC 7662).
    """
    server = get_oauth2_server()
    
    try:
        client = server.authenticate_client()
    except OAuth2Error as e:
        return e.to_response()
    
    token = request.form.get('token')
    token_type_hint = request.form.get('token_type_hint')
    
    if not token:
        return jsonify({'active': False})
    
    result = server.introspect_token(token, token_type_hint)
    
    return jsonify(result)


# ==================== UserInfo Endpoint ====================

@oauth_bp.route('/oauth/userinfo', methods=['GET', 'POST'])
@require_oauth('openid')
def userinfo():
    """
    OpenID Connect UserInfo Endpoint.
    """
    server = get_oauth2_server()
    token = request.oauth_token
    
    try:
        info = server.get_userinfo(token)
        return jsonify(info)
    except OAuth2Error as e:
        return e.to_response()


# ==================== Server Metadata ====================

@oauth_bp.route('/.well-known/oauth-authorization-server')
def server_metadata():
    """
    OAuth2 Authorization Server Metadata (RFC 8414).
    """
    base_url = request.url_root.rstrip('/')
    
    return jsonify({
        'issuer': base_url,
        'authorization_endpoint': f'{base_url}/oauth/authorize',
        'token_endpoint': f'{base_url}/oauth/token',
        'revocation_endpoint': f'{base_url}/oauth/revoke',
        'introspection_endpoint': f'{base_url}/oauth/introspect',
        'userinfo_endpoint': f'{base_url}/oauth/userinfo',
        
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code', 'refresh_token', 'client_credentials'],
        'token_endpoint_auth_methods_supported': ['client_secret_basic', 'client_secret_post'],
        
        'scopes_supported': list(OAuth2Client.SCOPES.keys()),
        
        'code_challenge_methods_supported': ['S256', 'plain'],
        
        'service_documentation': f'{base_url}/docs/API_AUTH.md',
    })


@oauth_bp.route('/.well-known/openid-configuration')
def openid_configuration():
    """
    OpenID Connect Discovery (for compatibility).
    """
    base_url = request.url_root.rstrip('/')
    
    return jsonify({
        'issuer': base_url,
        'authorization_endpoint': f'{base_url}/oauth/authorize',
        'token_endpoint': f'{base_url}/oauth/token',
        'userinfo_endpoint': f'{base_url}/oauth/userinfo',
        'revocation_endpoint': f'{base_url}/oauth/revoke',
        'introspection_endpoint': f'{base_url}/oauth/introspect',
        
        'response_types_supported': ['code'],
        'subject_types_supported': ['public'],
        'id_token_signing_alg_values_supported': ['RS256'],
        
        'scopes_supported': ['openid', 'profile', 'email'] + [
            s for s in OAuth2Client.SCOPES.keys() 
            if s not in ('openid', 'profile', 'email')
        ],
        
        'token_endpoint_auth_methods_supported': ['client_secret_basic', 'client_secret_post'],
        'claims_supported': ['sub', 'name', 'given_name', 'family_name', 'email', 'email_verified', 'picture'],
        
        'code_challenge_methods_supported': ['S256', 'plain'],
    })


# ==================== Client Management API ====================

def admin_required(f):
    """Decorator to require admin privileges."""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Nicht authentifiziert'}), 401
        if not current_user.is_admin:
            return jsonify({'error': 'Admin-Berechtigung erforderlich'}), 403
        return f(*args, **kwargs)
    
    return decorated_function


@oauth_bp.route('/api/oauth/clients', methods=['GET'])
@login_required
@admin_required
def list_clients():
    """List all OAuth2 clients."""
    clients = OAuth2Client.query.order_by(OAuth2Client.created_at.desc()).all()
    
    return jsonify({
        'clients': [c.to_dict() for c in clients],
        'available_scopes': OAuth2Client.SCOPES
    })


@oauth_bp.route('/api/oauth/clients', methods=['POST'])
@login_required
@admin_required
def create_client():
    """Create a new OAuth2 client."""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Keine Daten übermittelt'}), 400
    
    # Validate required fields
    client_name = data.get('client_name', '').strip()
    
    if not client_name:
        return jsonify({'error': 'Client-Name ist erforderlich'}), 400
    
    # Validate redirect URIs
    redirect_uris = data.get('redirect_uris', [])
    if not isinstance(redirect_uris, list):
        redirect_uris = [redirect_uris] if redirect_uris else []
    
    # Validate scopes
    allowed_scopes = data.get('allowed_scopes', [])
    if not isinstance(allowed_scopes, list):
        allowed_scopes = allowed_scopes.split() if allowed_scopes else []
    
    invalid_scopes = [s for s in allowed_scopes if s not in OAuth2Client.SCOPES]
    if invalid_scopes:
        return jsonify({'error': f'Ungültige Scopes: {", ".join(invalid_scopes)}'}), 400
    
    # Validate grant types
    allowed_grant_types = data.get('allowed_grant_types', ['authorization_code', 'refresh_token'])
    valid_grant_types = ['authorization_code', 'refresh_token', 'client_credentials']
    invalid_grants = [g for g in allowed_grant_types if g not in valid_grant_types]
    if invalid_grants:
        return jsonify({'error': f'Ungültige Grant-Types: {", ".join(invalid_grants)}'}), 400
    
    # Generate credentials
    client_id = OAuth2Client.generate_client_id()
    client_secret = None
    is_confidential = data.get('is_confidential', True)
    
    if is_confidential:
        client_secret = OAuth2Client.generate_client_secret()
    
    # Create client
    client = OAuth2Client(
        client_id=client_id,
        client_name=client_name,
        client_description=data.get('client_description'),
        client_uri=data.get('client_uri'),
        logo_uri=data.get('logo_uri'),
        redirect_uris=redirect_uris,
        allowed_scopes=allowed_scopes,
        allowed_grant_types=allowed_grant_types,
        allowed_response_types=['code'],
        is_confidential=is_confidential,
        require_pkce=data.get('require_pkce', not is_confidential),
        access_token_lifetime=data.get('access_token_lifetime', 3600),
        refresh_token_lifetime=data.get('refresh_token_lifetime', 2592000),
        is_active=data.get('is_active', True),
        created_by=current_user.id
    )
    
    if client_secret:
        client.set_client_secret(client_secret)
    
    db.session.add(client)
    
    try:
        db.session.commit()
        
        response_data = client.to_dict()
        response_data['client_id'] = client_id
        if client_secret:
            response_data['client_secret'] = client_secret  # Only shown once!
        
        return jsonify({
            'success': True,
            'client': response_data,
            'message': 'OAuth2-Client erfolgreich erstellt. Das Client-Secret wird nur einmal angezeigt!'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Fehler beim Erstellen: {str(e)}'}), 500


@oauth_bp.route('/api/oauth/clients/<int:client_id>', methods=['GET'])
@login_required
@admin_required
def get_client(client_id):
    """Get OAuth2 client details."""
    client = db.session.get(OAuth2Client, client_id)
    
    if not client:
        return jsonify({'error': 'Client nicht gefunden'}), 404
    
    return jsonify({
        'client': client.to_dict()
    })


@oauth_bp.route('/api/oauth/clients/<int:client_id>', methods=['PUT'])
@login_required
@admin_required
def update_client(client_id):
    """Update an OAuth2 client."""
    client = db.session.get(OAuth2Client, client_id)
    
    if not client:
        return jsonify({'error': 'Client nicht gefunden'}), 404
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Keine Daten übermittelt'}), 400
    
    # Update allowed fields
    if 'client_name' in data:
        client.client_name = data['client_name'].strip()
    
    if 'client_description' in data:
        client.client_description = data['client_description']
    
    if 'client_uri' in data:
        client.client_uri = data['client_uri']
    
    if 'logo_uri' in data:
        client.logo_uri = data['logo_uri']
    
    if 'redirect_uris' in data:
        redirect_uris = data['redirect_uris']
        if not isinstance(redirect_uris, list):
            redirect_uris = [redirect_uris] if redirect_uris else []
        client.redirect_uris = redirect_uris
    
    if 'allowed_scopes' in data:
        allowed_scopes = data['allowed_scopes']
        if not isinstance(allowed_scopes, list):
            allowed_scopes = allowed_scopes.split() if allowed_scopes else []
        invalid_scopes = [s for s in allowed_scopes if s not in OAuth2Client.SCOPES]
        if invalid_scopes:
            return jsonify({'error': f'Ungültige Scopes: {", ".join(invalid_scopes)}'}), 400
        client.allowed_scopes = allowed_scopes
    
    if 'allowed_grant_types' in data:
        allowed_grant_types = data['allowed_grant_types']
        valid_grant_types = ['authorization_code', 'refresh_token', 'client_credentials']
        invalid_grants = [g for g in allowed_grant_types if g not in valid_grant_types]
        if invalid_grants:
            return jsonify({'error': f'Ungültige Grant-Types: {", ".join(invalid_grants)}'}), 400
        client.allowed_grant_types = allowed_grant_types
    
    if 'require_pkce' in data:
        client.require_pkce = bool(data['require_pkce'])
    
    if 'access_token_lifetime' in data:
        client.access_token_lifetime = max(60, min(86400 * 7, int(data['access_token_lifetime'])))
    
    if 'refresh_token_lifetime' in data:
        client.refresh_token_lifetime = max(0, min(86400 * 365, int(data['refresh_token_lifetime'])))
    
    if 'is_active' in data:
        client.is_active = bool(data['is_active'])
    
    try:
        db.session.commit()
        
        return jsonify({
            'success': True,
            'client': client.to_dict(),
            'message': 'Client erfolgreich aktualisiert'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Fehler beim Aktualisieren: {str(e)}'}), 500


@oauth_bp.route('/api/oauth/clients/<int:client_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_client(client_id):
    """Delete an OAuth2 client."""
    client = db.session.get(OAuth2Client, client_id)
    
    if not client:
        return jsonify({'error': 'Client nicht gefunden'}), 404
    
    try:
        db.session.delete(client)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Client erfolgreich gelöscht'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Fehler beim Löschen: {str(e)}'}), 500


@oauth_bp.route('/api/oauth/clients/<int:client_id>/regenerate-secret', methods=['POST'])
@login_required
@admin_required
def regenerate_client_secret(client_id):
    """Regenerate the client secret."""
    client = db.session.get(OAuth2Client, client_id)
    
    if not client:
        return jsonify({'error': 'Client nicht gefunden'}), 404
    
    if not client.is_confidential:
        return jsonify({'error': 'Public Clients haben kein Secret'}), 400
    
    new_secret = OAuth2Client.generate_client_secret()
    client.set_client_secret(new_secret)
    
    # Revoke all existing tokens for this client
    OAuth2Token.query.filter_by(client_id=client.id).update({'revoked': True})
    
    try:
        db.session.commit()
        
        return jsonify({
            'success': True,
            'client_secret': new_secret,
            'message': 'Client-Secret erfolgreich neu generiert. Alle bestehenden Tokens wurden widerrufen.'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Fehler beim Regenerieren: {str(e)}'}), 500


@oauth_bp.route('/api/oauth/scopes', methods=['GET'])
@login_required
@admin_required
def list_scopes():
    """List all available OAuth2 scopes."""
    return jsonify({
        'scopes': OAuth2Client.SCOPES
    })
