"""
OAuth2 API namespace for client management.
"""
from flask import request
from flask_restx import Namespace, Resource, fields
from flask_login import login_required, current_user

from app import db
from app.models.oauth import OAuth2Client, OAuth2Token

api = Namespace('oauth', description='OAuth2-Client-Verwaltung')


def admin_required(f):
    """Decorator to require admin privileges."""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            api.abort(401, 'Nicht authentifiziert')
        if not current_user.is_admin:
            api.abort(403, 'Admin-Berechtigung erforderlich')
        return f(*args, **kwargs)
    
    return decorated_function


# Models
client_model = api.model('OAuth2Client', {
    'id': fields.Integer(description='Client-ID'),
    'client_id': fields.String(description='OAuth2 Client-ID'),
    'client_name': fields.String(description='Client-Name'),
    'client_description': fields.String(description='Beschreibung'),
    'client_uri': fields.String(description='Homepage-URL'),
    'redirect_uris': fields.List(fields.String, description='Erlaubte Redirect-URIs'),
    'allowed_scopes': fields.List(fields.String, description='Erlaubte Scopes'),
    'allowed_grant_types': fields.List(fields.String, description='Erlaubte Grant-Types'),
    'is_confidential': fields.Boolean(description='Vertraulicher Client'),
    'require_pkce': fields.Boolean(description='PKCE erforderlich'),
    'access_token_lifetime': fields.Integer(description='Token-Gültigkeit (Sekunden)'),
    'is_active': fields.Boolean(description='Aktiv'),
    'created_at': fields.DateTime(description='Erstellt am')
})

client_create_model = api.model('OAuth2ClientCreate', {
    'client_name': fields.String(required=True, description='Client-Name'),
    'client_description': fields.String(description='Beschreibung'),
    'client_uri': fields.String(description='Homepage-URL'),
    'redirect_uris': fields.List(fields.String, required=True, description='Redirect-URIs'),
    'allowed_scopes': fields.List(fields.String, required=True, description='Scopes'),
    'allowed_grant_types': fields.List(fields.String, description='Grant-Types'),
    'is_confidential': fields.Boolean(default=True, description='Vertraulicher Client'),
    'require_pkce': fields.Boolean(default=False, description='PKCE erforderlich')
})


@api.route('/clients')
class ClientList(Resource):
    @api.doc('list_clients', security='Bearer')
    @api.marshal_list_with(client_model)
    @login_required
    @admin_required
    def get(self):
        """
        Alle OAuth2-Clients auflisten.
        
        Gibt alle registrierten OAuth2-Clients zurück.
        Nur für Administratoren.
        """
        clients = OAuth2Client.query.order_by(OAuth2Client.created_at.desc()).all()
        return [c.to_dict() for c in clients]
    
    @api.doc('create_client', security='Bearer')
    @api.expect(client_create_model)
    @api.response(201, 'Client erstellt')
    @api.response(400, 'Ungültige Anfrage')
    @login_required
    @admin_required
    def post(self):
        """
        Neuen OAuth2-Client erstellen.
        
        Erstellt einen neuen OAuth2-Client für externe Anwendungen.
        Das Client-Secret wird nur einmal angezeigt!
        """
        data = request.get_json()
        
        if not data:
            api.abort(400, 'Keine Daten übermittelt')
        
        client_name = data.get('client_name', '').strip()
        
        if not client_name:
            api.abort(400, 'Client-Name ist erforderlich')
        
        redirect_uris = data.get('redirect_uris', [])
        if not redirect_uris:
            api.abort(400, 'Mindestens eine Redirect-URI ist erforderlich')
        
        allowed_scopes = data.get('allowed_scopes', [])
        invalid_scopes = [s for s in allowed_scopes if s not in OAuth2Client.SCOPES]
        if invalid_scopes:
            api.abort(400, f'Ungültige Scopes: {", ".join(invalid_scopes)}')
        
        client_id = OAuth2Client.generate_client_id()
        client_secret = None
        is_confidential = data.get('is_confidential', True)
        
        if is_confidential:
            client_secret = OAuth2Client.generate_client_secret()
        
        allowed_grant_types = data.get('allowed_grant_types', ['authorization_code', 'refresh_token'])
        
        client = OAuth2Client(
            client_id=client_id,
            client_name=client_name,
            client_description=data.get('client_description'),
            client_uri=data.get('client_uri'),
            redirect_uris=redirect_uris,
            allowed_scopes=allowed_scopes,
            allowed_grant_types=allowed_grant_types,
            allowed_response_types=['code'],
            is_confidential=is_confidential,
            require_pkce=data.get('require_pkce', not is_confidential),
            is_active=True,
            created_by=current_user.id
        )
        
        if client_secret:
            client.set_client_secret(client_secret)
        
        db.session.add(client)
        db.session.commit()
        
        result = client.to_dict()
        result['client_id'] = client_id
        if client_secret:
            result['client_secret'] = client_secret
        
        return {
            'success': True,
            'client': result,
            'message': 'OAuth2-Client erstellt. Das Client-Secret wird nur einmal angezeigt!'
        }, 201


@api.route('/clients/<int:client_id>')
@api.param('client_id', 'Client-ID (interne ID)')
class ClientResource(Resource):
    @api.doc('get_client', security='Bearer')
    @api.marshal_with(client_model)
    @api.response(404, 'Client nicht gefunden')
    @login_required
    @admin_required
    def get(self, client_id):
        """
        OAuth2-Client abrufen.
        """
        client = db.session.get(OAuth2Client, client_id)
        if not client:
            api.abort(404, 'Client nicht gefunden')
        return client.to_dict()
    
    @api.doc('delete_client', security='Bearer')
    @api.response(204, 'Gelöscht')
    @api.response(404, 'Client nicht gefunden')
    @login_required
    @admin_required
    def delete(self, client_id):
        """
        OAuth2-Client löschen.
        
        Löscht den Client und alle zugehörigen Tokens.
        """
        client = db.session.get(OAuth2Client, client_id)
        if not client:
            api.abort(404, 'Client nicht gefunden')
        
        db.session.delete(client)
        db.session.commit()
        
        return '', 204


@api.route('/scopes')
class ScopeList(Resource):
    @api.doc('list_scopes', security='Bearer')
    @login_required
    @admin_required
    def get(self):
        """
        Verfügbare OAuth2-Scopes auflisten.
        
        Gibt alle verfügbaren Scopes mit Beschreibungen zurück.
        """
        return {'scopes': OAuth2Client.SCOPES}
