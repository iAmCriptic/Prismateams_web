"""Core Flask config and base extensions."""


import logging
import os

from flask import jsonify, request, redirect, url_for

from config import config

from app import csrf, db, login_manager, mail
from app.factory._util import configure_app_logging, is_insecure_secret_key as _is_insecure_secret_key
from app.utils.i18n import init_i18n, register_i18n

def configure_core(app, config_name, basedir):
    """Config, logging, CSRF, upload path, reverse-proxy."""
    # Gmail/IMAP-Ordner: Namen mit "/" und "&" (modUTF7) sicher in URLs
    from app.utils.imap_folder_url import ImapFolderConverter
    app.url_map.converters['imap_folder'] = ImapFolderConverter

    app.config.from_object(config[config_name])
    configure_app_logging(app, config_name)
    csrf.init_app(app)

    if config_name in ('production', 'staging') and _is_insecure_secret_key(app.config.get('SECRET_KEY')):
        raise RuntimeError(
            f"{config_name.capitalize()} requires a strong SECRET_KEY via environment variable SECRET_KEY."
        )

    if (
        config_name in ('production', 'staging')
        and app.config.get('ONLYOFFICE_ENABLED')
        and not (app.config.get('ONLYOFFICE_SECRET_KEY') or '').strip()
        and not app.config.get('ONLYOFFICE_ALLOW_UNSIGNED_CALLBACKS')
    ):
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "ONLYOFFICE is enabled without ONLYOFFICE_SECRET_KEY in %s. "
            "Callbacks will be rejected until the secret matches Document Server JWT_SECRET "
            "(or set ONLYOFFICE_ALLOW_UNSIGNED_CALLBACKS=true for JWT_ENABLED=false).",
            config_name,
        )

    # Relative UPLOAD_FOLDER must resolve to project root, not app package
    # (Flask send_file joins relative paths with app.root_path = .../app).
    upload_folder = app.config.get('UPLOAD_FOLDER') or 'uploads'
    if not os.path.isabs(upload_folder):
        project_root = os.path.dirname(basedir)
        upload_folder = os.path.join(project_root, upload_folder)
    app.config['UPLOAD_FOLDER'] = os.path.abspath(upload_folder)
    
    # Reverse-Proxy-Support: X-Forwarded-For als echte IP verwenden
    proxy_count = int(os.getenv('PROXY_COUNT', '1'))
    if proxy_count > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_count, x_proto=proxy_count, x_host=proxy_count, x_prefix=proxy_count)


def init_base_extensions(app):
    """DB, caches, login, mail, i18n, upload directories."""
    db.init_app(app)
    try:
        from app.utils.system_settings_cache import register_settings_cache_invalidation
        register_settings_cache_invalidation()
        from app.utils.module_roles_cache import register_module_roles_cache_invalidation
        register_module_roles_cache_invalidation()
        from app.utils.file_storage_limits import register_usage_cache_invalidation
        register_usage_cache_invalidation()
    except Exception:
        pass
    login_manager.init_app(app)
    mail.init_app(app)
    register_i18n(app)
    
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Bitte melden Sie sich an, um auf diese Seite zuzugreifen.'
    login_manager.login_message_category = 'info'
    
    @login_manager.unauthorized_handler
    def unauthorized():
        # WICHTIG: Socket.IO-Requests nicht blockieren
        if request.path.startswith('/socket.io/'):
            return None  # Erlaube Socket.IO-Requests, Authentifizierung wird im on_connect Handler geprüft
        
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Authentication required'}), 401
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))
    from app.models.user import User
    from app.models.assessment import AssessmentUser
    
    @login_manager.user_loader
    def load_user(user_id):
        if isinstance(user_id, str) and user_id.startswith('ass:'):
            raw_id = user_id.split(':', 1)[1]
            if raw_id.isdigit():
                return AssessmentUser.query.get(int(raw_id))
            return None
        return User.query.get(int(user_id))
    
    from app.utils.i18n import init_i18n
    init_i18n(app)

    upload_dirs = [
        app.config['UPLOAD_FOLDER'],
        os.path.join(app.config['UPLOAD_FOLDER'], 'files'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'chat'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'chat', 'avatars'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'manuals'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'profile_pics'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'inventory', 'product_images'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'inventory', 'product_documents'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'system'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'wiki'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'bookings'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'booking_forms'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'veranstaltungen'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'assessment'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'assessment', 'branding'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'media_downloader'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'file_converter'),
    ]
    for directory in upload_dirs:
        os.makedirs(directory, exist_ok=True)
