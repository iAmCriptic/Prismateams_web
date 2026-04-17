from flask import Blueprint, jsonify, request, g
from app.models.api_token import ApiToken

api_bp = Blueprint('api', __name__)


def require_api_auth(f):
    """
    Decorator für API-Endpunkte, die entweder Session- oder Token-Authentifizierung akzeptieren.
    Setzt current_user für Token-basierte Authentifizierung.
    """
    from functools import wraps
    from flask_login import current_user
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Prüfe zuerst ob Session-basierte Authentifizierung vorhanden ist
        if current_user.is_authenticated:
            return f(*args, **kwargs)
        
        # Prüfe Token-basierte Authentifizierung
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.replace('Bearer ', '').strip()
            api_token = ApiToken.query.filter_by(token=token).first()
            
            if api_token and not api_token.is_expired():
                user = api_token.user
                if user and user.is_active:
                    # Flask-Login-kompatibel (ohne private _request_ctx_stack API):
                    # current_user liest aus g._login_user im aktuellen Request-Kontext.
                    g._login_user = user
                    api_token.mark_as_used()
                    return f(*args, **kwargs)
        
        return jsonify({
            'success': False,
            'error': 'Authentifizierung erforderlich'
        }), 401
    
    return decorated_function


from app import limiter
from app.blueprints.api_modules.auth import register_auth_routes
from app.blueprints.api_modules.meta import register_meta_routes
from app.blueprints.api_modules.users import register_user_routes
from app.blueprints.api_modules.chat import register_chat_routes
from app.blueprints.api_modules.calendar import register_calendar_routes
from app.blueprints.api_modules.files import register_files_routes
from app.blueprints.api_modules.dashboard import register_dashboard_routes
from app.blueprints.api_modules.notifications import register_notification_routes
from app.blueprints.api_modules.push import register_push_routes

register_auth_routes(api_bp, require_api_auth, limiter)
register_meta_routes(api_bp, require_api_auth)
register_user_routes(api_bp, require_api_auth)
register_chat_routes(api_bp, require_api_auth)
register_calendar_routes(api_bp, require_api_auth)
register_files_routes(api_bp, require_api_auth)
register_dashboard_routes(api_bp, require_api_auth)
register_notification_routes(api_bp, require_api_auth)
register_push_routes(api_bp, require_api_auth)
