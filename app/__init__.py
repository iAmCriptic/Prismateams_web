from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
limiter = Limiter(key_func=get_remote_address)
csrf = CSRFProtect()


def create_socketio():
    """Erstellt SocketIO-Instanz; CORS wird in create_app gesetzt (Default: same-origin)."""
    return SocketIO(cors_allowed_origins=None)


socketio = create_socketio()


def create_app(config_name='default'):
    """Create and configure the Flask application."""
    import mimetypes
    import os

    basedir = os.path.abspath(os.path.dirname(__file__))
    app = Flask(__name__, static_folder=os.path.join(basedir, 'static'))
    mimetypes.add_type('text/javascript', '.mjs')
    mimetypes.add_type('text/javascript', '.js')
    app.url_map.strict_slashes = False

    from app.factory.core import configure_core, init_base_extensions
    from app.factory.realtime import init_realtime
    from app.factory.hooks import register_request_hooks
    from app.factory.templates import register_template_helpers
    from app.factory.errors import register_error_handlers
    from app.factory.blueprints import register_blueprints
    from app.factory.routes import register_app_routes
    from app.factory.startup import run_app_startup

    configure_core(app, config_name, basedir)
    init_base_extensions(app)
    init_realtime(app, config_name)
    register_request_hooks(app)
    register_template_helpers(app)
    register_error_handlers(app)
    register_blueprints(app)
    register_app_routes(app)
    run_app_startup(app)
    return app
