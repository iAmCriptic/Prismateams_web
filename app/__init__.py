from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from config import config
import os

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()


def create_app(config_name='default'):
    """Create and configure the Flask application."""
    import os
    basedir = os.path.abspath(os.path.dirname(__file__))
    app = Flask(__name__, static_folder=os.path.join(basedir, 'static'))
    
    # Load configuration
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    
    # Configure login manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Bitte melden Sie sich an, um auf diese Seite zuzugreifen.'
    login_manager.login_message_category = 'info'
    
    # User loader for Flask-Login
    from app.models.user import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Create upload directories if they don't exist
    upload_dirs = [
        app.config['UPLOAD_FOLDER'],
        os.path.join(app.config['UPLOAD_FOLDER'], 'files'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'chat'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'manuals'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics'),
    ]
    for directory in upload_dirs:
        os.makedirs(directory, exist_ok=True)
    
    # Make app config available in all templates
    @app.context_processor
    def inject_app_config():
        app_name = app.config.get('APP_NAME', 'Team Portal')
        app_logo = app.config.get('APP_LOGO')
        
        # Fix logo path - remove 'static/' prefix if present since Flask adds it automatically
        if app_logo and app_logo.startswith('static/'):
            app_logo = app_logo[7:]  # Remove 'static/' prefix
        
        # Debug output
        print(f"DEBUG: app_name = {app_name}")
        print(f"DEBUG: app_logo = {app_logo}")
        
        return {
            'app_name': app_name,
            'app_logo': app_logo
        }
    
    
    # Register blueprints
    from app.blueprints.auth import auth_bp
    from app.blueprints.dashboard import dashboard_bp
    from app.blueprints.chat import chat_bp
    from app.blueprints.files import files_bp
    from app.blueprints.calendar import calendar_bp
    from app.blueprints.email import email_bp
    from app.blueprints.credentials import credentials_bp
    from app.blueprints.manuals import manuals_bp
    from app.blueprints.canvas import canvas_bp
    from app.blueprints.settings import settings_bp
    from app.blueprints.api import api_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(chat_bp, url_prefix='/chat')
    app.register_blueprint(files_bp, url_prefix='/files')
    app.register_blueprint(calendar_bp, url_prefix='/calendar')
    app.register_blueprint(email_bp, url_prefix='/email')
    app.register_blueprint(credentials_bp, url_prefix='/credentials')
    app.register_blueprint(manuals_bp, url_prefix='/manuals')
    app.register_blueprint(canvas_bp, url_prefix='/canvas')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # Create database tables
    with app.app_context():
        db.create_all()
        
        # Initialize system settings
        from app.models.settings import SystemSettings
        from app.models.chat import Chat
        from app.models.user import User
        
        # Create default system settings if they don't exist
        if not SystemSettings.query.filter_by(key='email_footer_text').first():
            footer = SystemSettings(
                key='email_footer_text',
                value='Mit freundlichen Grüßen\nIhr Team',
                description='Standard-Footer für E-Mails'
            )
            db.session.add(footer)
        
        if not SystemSettings.query.filter_by(key='email_footer_image').first():
            footer_img = SystemSettings(
                key='email_footer_image',
                value='',
                description='Footer-Bild URL für E-Mails'
            )
            db.session.add(footer_img)
        
        # Create main chat if it doesn't exist
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if not main_chat:
            main_chat = Chat(
                name='Team Chat',
                is_main_chat=True,
                is_direct_message=False
            )
            db.session.add(main_chat)
        
        db.session.commit()
    
    return app



