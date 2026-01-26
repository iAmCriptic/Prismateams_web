"""
Authentication API namespace.
"""
from flask import request
from flask_restx import Namespace, Resource, fields
from flask_login import login_required, current_user, login_user

from app import db, limiter
from app.models.user import User
from app.models.api_token import ApiToken
from app.utils.totp import verify_totp, decrypt_secret
from app.utils.session_manager import create_session

api = Namespace('auth', description='Authentifizierung')

# Models for Swagger documentation
login_model = api.model('Login', {
    'email': fields.String(required=True, description='E-Mail-Adresse', example='user@example.com'),
    'password': fields.String(required=True, description='Passwort'),
    'totp_code': fields.String(description='2FA-Code (falls aktiviert)', example='123456'),
    'remember': fields.Boolean(description='Angemeldet bleiben', default=False),
    'return_token': fields.Boolean(description='API-Token statt Session zurückgeben', default=False)
})

user_model = api.model('User', {
    'id': fields.Integer(description='Benutzer-ID'),
    'email': fields.String(description='E-Mail-Adresse'),
    'full_name': fields.String(description='Vollständiger Name'),
    'first_name': fields.String(description='Vorname'),
    'last_name': fields.String(description='Nachname'),
    'is_admin': fields.Boolean(description='Admin-Status'),
    'is_guest': fields.Boolean(description='Gast-Account'),
    'profile_picture': fields.String(description='Profilbild-URL'),
    'totp_enabled': fields.Boolean(description='2FA aktiviert')
})

login_response = api.model('LoginResponse', {
    'success': fields.Boolean(description='Erfolgreich'),
    'user': fields.Nested(user_model, description='Benutzerinformationen'),
    'token': fields.String(description='API-Token (wenn return_token=true)'),
    'token_expires_at': fields.String(description='Token-Ablaufzeit')
})

login_2fa_response = api.model('Login2FAResponse', {
    'success': fields.Boolean(description='Erfolgreich', default=False),
    'requires_2fa': fields.Boolean(description='2FA erforderlich', default=True),
    'message': fields.String(description='Nachricht')
})

error_response = api.model('ErrorResponse', {
    'success': fields.Boolean(description='Erfolgreich', default=False),
    'error': fields.String(description='Fehlermeldung')
})


@api.route('/login')
class Login(Resource):
    @api.doc('login')
    @api.expect(login_model)
    @api.response(200, 'Erfolgreich', login_response)
    @api.response(200, '2FA erforderlich', login_2fa_response)
    @api.response(400, 'Ungültige Anfrage', error_response)
    @api.response(401, 'Ungültige Zugangsdaten', error_response)
    @api.response(423, 'Account gesperrt', error_response)
    @limiter.limit("5 per 15 minutes")
    def post(self):
        """
        Benutzer-Login mit optionaler 2FA-Unterstützung.
        
        Wenn 2FA aktiviert ist und kein Code übermittelt wurde, wird
        `requires_2fa: true` zurückgegeben. Der Login muss dann mit
        dem 2FA-Code wiederholt werden.
        """
        try:
            data = request.get_json()
            if not data:
                return {'success': False, 'error': 'Keine Daten übermittelt'}, 400
            
            email = data.get('email', '').strip().lower()
            password = data.get('password', '')
            totp_code = data.get('totp_code')
            remember = data.get('remember', False)
            return_token = data.get('return_token', False)
            
            if not email or not password:
                return {'success': False, 'error': 'E-Mail und Passwort erforderlich'}, 400
            
            user = User.query.filter_by(email=email).first()
            
            if not user or not user.check_password(password):
                return {'success': False, 'error': 'Ungültige Zugangsdaten'}, 401
            
            if not user.is_active:
                return {'success': False, 'error': 'Account deaktiviert'}, 401
            
            # Check 2FA
            if user.totp_enabled and user.totp_secret:
                if not totp_code:
                    return {
                        'success': False,
                        'requires_2fa': True,
                        'message': '2FA-Code erforderlich',
                        'error': 'Bitte geben Sie den 2FA-Code ein'
                    }, 200
                
                # Verify TOTP
                try:
                    decrypted_secret = decrypt_secret(user.totp_secret)
                    if not verify_totp(decrypted_secret, totp_code):
                        return {'success': False, 'error': 'Ungültiger 2FA-Code'}, 401
                except Exception:
                    return {'success': False, 'error': '2FA-Verifizierung fehlgeschlagen'}, 500
            
            # Create session or token
            if return_token:
                token = ApiToken.create_token(user)
                db.session.add(token)
                db.session.commit()
                
                return {
                    'success': True,
                    'user': self._user_to_dict(user),
                    'token': token.token,
                    'token_expires_at': token.expires_at.isoformat() if token.expires_at else None
                }
            else:
                login_user(user, remember=remember)
                create_session(user.id)
                
                return {
                    'success': True,
                    'user': self._user_to_dict(user)
                }
                
        except Exception as e:
            return {'success': False, 'error': str(e)}, 500
    
    def _user_to_dict(self, user):
        return {
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'is_admin': user.is_admin,
            'is_guest': getattr(user, 'is_guest', False),
            'profile_picture': f'/settings/profile-picture/{user.profile_picture_filename}' if user.profile_picture_filename else None,
            'totp_enabled': user.totp_enabled
        }


@api.route('/logout')
class Logout(Resource):
    @api.doc('logout', security='Bearer')
    @api.response(200, 'Erfolgreich')
    @login_required
    def post(self):
        """
        Benutzer abmelden.
        
        Beendet die aktuelle Session oder invalidiert den Token.
        """
        from flask_login import logout_user
        logout_user()
        return {'success': True, 'message': 'Erfolgreich abgemeldet'}


@api.route('/me')
class CurrentUser(Resource):
    @api.doc('current_user', security='Bearer')
    @api.response(200, 'Erfolgreich', user_model)
    @api.response(401, 'Nicht authentifiziert', error_response)
    @login_required
    def get(self):
        """
        Aktuellen Benutzer abrufen.
        
        Gibt die Informationen des authentifizierten Benutzers zurück.
        """
        user = current_user
        return {
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'is_admin': user.is_admin,
            'is_guest': getattr(user, 'is_guest', False),
            'profile_picture': f'/settings/profile-picture/{user.profile_picture_filename}' if user.profile_picture_filename else None,
            'accent_color': user.accent_color,
            'dark_mode': user.dark_mode,
            'totp_enabled': user.totp_enabled
        }
