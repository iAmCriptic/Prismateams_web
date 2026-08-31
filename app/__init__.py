from flask import Flask, render_template, request, jsonify, session, url_for as flask_url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import config
import json
import logging
import os
from app.utils.i18n import register_i18n, translate
from urllib.parse import urlparse

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
limiter = Limiter(key_func=get_remote_address)

# SocketIO mit optionaler Redis Message Queue für Multi-Worker-Setups
def create_socketio():
    """Erstellt SocketIO-Instanz mit optionaler Redis Message Queue."""
    # Initial ohne Config (wird später in create_app konfiguriert)
    return SocketIO(cors_allowed_origins="*")

socketio = create_socketio()


def _is_insecure_secret_key(value):
    secret = (value or "").strip()
    return (not secret) or secret == 'dev-secret-key-change-in-production'


def _is_same_origin(target_url, expected_host):
    if not target_url:
        return False
    try:
        parsed = urlparse(target_url)
        return (parsed.netloc or '').lower() == (expected_host or '').lower()
    except Exception:
        return False


def _env_flag(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def configure_app_logging(app, config_name='default'):
    """Central logging for Gunicorn/systemd (stderr → journalctl)."""
    default_level = logging.INFO if config_name == 'production' else logging.DEBUG
    level_name = os.getenv('LOG_LEVEL', '').strip().upper()
    if level_name:
        level = getattr(logging, level_name, default_level)
    else:
        level = default_level

    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        force=True,
    )
    app.logger.setLevel(level)
    werkzeug_level = logging.WARNING if config_name == 'production' else logging.INFO
    logging.getLogger('werkzeug').setLevel(werkzeug_level)


def _log_startup(message, level=None):
    """Structured startup log (migrations, schema patches)."""
    logger = logging.getLogger('app.startup')
    text = str(message)
    if level is None:
        if text.startswith('[FEHLER]'):
            level = 'error'
        elif text.startswith('[WARNUNG]') or text.startswith('WARNING:'):
            level = 'warning'
        else:
            level = 'info'
    getattr(logger, level, logger.info)(text)


def _current_release_marker(app):
    release = str(app.config.get('ABOUT_RELEASE_VERSION') or '').strip()
    build = str(app.config.get('ABOUT_BUILD_NUMBER') or '').strip()
    if release and build:
        return f"{release}:{build}"
    return release or build or 'unknown'


def _should_run_migrations_after_update(app):
    """
    Auto-Migration nur nach Update:
    Läuft, wenn der gespeicherte Release-Marker vom aktuellen Marker abweicht.
    """
    try:
        from app.models.settings import SystemSettings
        marker = _current_release_marker(app)
        setting = SystemSettings.query.filter_by(key='last_auto_migrated_release').first()
        if not setting:
            return True, marker
        return (str(setting.value or '').strip() != marker), marker
    except Exception:
        # Fallback: lieber migrieren als ein notwendiges Update zu verpassen.
        return True, _current_release_marker(app)


def create_app(config_name='default'):
    """Create and configure the Flask application."""
    import os
    import mimetypes
    basedir = os.path.abspath(os.path.dirname(__file__))
    app = Flask(__name__, static_folder=os.path.join(basedir, 'static'))
    mimetypes.add_type('text/javascript', '.mjs')
    mimetypes.add_type('text/javascript', '.js')
    app.url_map.strict_slashes = False

    # Gmail/IMAP-Ordner: Namen mit "/" und "&" (modUTF7) sicher in URLs
    from app.utils.imap_folder_url import ImapFolderConverter
    app.url_map.converters['imap_folder'] = ImapFolderConverter

    app.config.from_object(config[config_name])
    configure_app_logging(app, config_name)

    if config_name == 'production' and _is_insecure_secret_key(app.config.get('SECRET_KEY')):
        raise RuntimeError(
            "Production requires a strong SECRET_KEY via environment variable SECRET_KEY."
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

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    
    # Konfiguriere SocketIO mit optionaler Redis Message Queue
    redis_enabled = app.config.get('REDIS_ENABLED', False)
    redis_url = app.config.get('REDIS_URL', 'redis://localhost:6379/0')
    
    import logging
    logger = logging.getLogger(__name__)
    
    # Automatische Redis-Aktivierung wenn Redis verfügbar ist
    # (außer wenn explizit REDIS_ENABLED=False gesetzt wurde)
    if not redis_enabled:
        try:
            import redis
            r = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
            if r.ping():
                redis_enabled = True
                logger.info(f"Redis automatisch aktiviert (verfügbar): {redis_url}")
            else:
                logger.warning(f"Redis-Ping fehlgeschlagen: {redis_url}")
        except ImportError:
            logger.warning("Redis-Python-Package nicht verfügbar. Installiere mit: pip install redis")
        except Exception as e:
            logger.warning(f"Redis-Verbindung fehlgeschlagen: {e} - SocketIO läuft ohne Message Queue")
    
    # Logge Redis-Status
    if redis_enabled:
        logger.info(f"Redis aktiviert: {redis_url}")
    else:
        logger.warning(f"Redis NICHT aktiviert - Multi-Worker-Setups funktionieren nicht korrekt!")
        logger.warning(f"Setze REDIS_ENABLED=True in der .env oder stelle sicher, dass Redis läuft")
    
    # Flask-Limiter für Rate Limiting initialisieren
    # Verwende Redis als Storage-Backend wenn verfügbar (für Production)
    rate_limit_uri = app.config.get('RATELIMIT_STORAGE_URI') or (redis_url if redis_enabled else None)
    if rate_limit_uri:
        try:
            limiter.init_app(app, storage_uri=rate_limit_uri)
            logger.info(f"Flask-Limiter Storage: {rate_limit_uri}")
        except Exception as e:
            logger.warning(f"Fehler beim Konfigurieren von Flask-Limiter mit Redis: {e}")
            logger.warning("Verwende Memory-Storage als Fallback (nicht für Production empfohlen)")
            limiter.init_app(app)
    else:
        if config_name == 'production':
            logger.warning("⚠️  WICHTIG: Flask-Limiter verwendet Memory-Storage in Production!")
            logger.warning("⚠️  Für Production Redis setzen: REDIS_ENABLED=True und REDIS_URL=…")
            logger.warning("⚠️  Alternativ RATELIMIT_STORAGE_URI=redis://… in .env")
        else:
            logger.info("Flask-Limiter: Memory-Storage (Dev). Für Multi-Worker: REDIS_ENABLED=True")
        limiter.init_app(app)
    
    if redis_enabled:
        try:
            # Verwende Redis als Message Queue für Multi-Worker-Setups
            # Threading wird verwendet (kein eventlet), da eventlet Monkey Patching benötigt
            # Threading funktioniert zuverlässig mit Redis und Gunicorn
            async_mode = 'threading'
            
            # Socket.IO mit Redis Message Queue initialisieren
            # WICHTIG: WebSocket-First-Strategie für Multi-Worker-Setups
            # - WebSocket hat KEINE Session-Probleme (persistente Verbindung)
            # - Fallback auf Polling nur wenn WebSocket nicht verfügbar
            init_kwargs = {
                'message_queue': redis_url,
                'async_mode': async_mode,
                'cors_allowed_origins': "*",
                'logger': False,
                'engineio_logger': False,
                'ping_timeout': 60,
                'ping_interval': 25,
                'cookie': False,  # KEINE Cookies
                'allow_upgrades': True,  # WebSocket-Upgrades erlauben
                'transports': ['websocket', 'polling'],  # WebSocket bevorzugt, Polling als Fallback
                'max_http_buffer_size': 1e6,
                'manage_session': False
            }
            
            socketio.init_app(app, **init_kwargs)
            # WICHTIG: Logge auf INFO-Level, damit es in systemd-Logs sichtbar ist
            logger.info(f"SocketIO mit Redis Message Queue konfiguriert: {redis_url} (async_mode={async_mode})")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Redis-Fehler, verwende SocketIO ohne Message Queue: {e}", exc_info=True)
            logger.warning("Hinweis: Multi-Worker-Setups funktionieren nur mit Redis!")
            # Fallback: SocketIO ohne Message Queue (nur für Single-Worker)
            socketio.init_app(
                app,
                cors_allowed_origins="*",
                logger=False,
                engineio_logger=False,
                ping_timeout=60,
                ping_interval=25,
                cookie=False,
                allow_upgrades=True,
                transports=['websocket', 'polling'],
                max_http_buffer_size=1e6,
                manage_session=False
            )
    else:
        # Kein Redis konfiguriert - nur für Single-Worker oder Development
        socketio.init_app(
            app,
            cors_allowed_origins="*",
            logger=False,
            engineio_logger=False,
            ping_timeout=60,
            ping_interval=25,
            cookie=False,
            allow_upgrades=True,
            transports=['websocket', 'polling'],
            max_http_buffer_size=1e6,
            manage_session=False
        )
        if config_name == 'production':
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("Redis nicht aktiviert! Multi-Worker-Setups funktionieren nicht korrekt.")
            logger.warning("Setze REDIS_ENABLED=True in der .env für Production mit mehreren Workern.")
    
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
    
    # Socket.IO Authentifizierungs-Handler
    # Erlaubt sowohl authentifizierte als auch nicht-authentifizierte Verbindungen
    # (für öffentliche Routen wie Musikwunschliste)
    @socketio.on('connect')
    def handle_connect(auth):
        """Handle Socket.IO-Verbindungen. Erlaubt sowohl authentifizierte als auch nicht-authentifizierte Clients.
        
        WICHTIG: Diese Funktion muss IMMER True zurückgeben, sonst bekommt der Client 400 Bad Request.
        Mit manage_session=False akzeptiert Socket.IO alle Sessions, auch wenn der Worker sie nicht kennt.
        Dies ist wichtig für Multi-Worker-Setups mit Redis, wo Sessions zwischen Workern geteilt werden.
        """
        try:
        # Verbindung IMMER akzeptieren - keine Prüfung, keine Exception, kein Logging
        # Dies verhindert 400 Bad Request Fehler bei Session-Konflikten zwischen Workern
            # Mit manage_session=False werden Sessions nicht validiert, was für Multi-Worker wichtig ist
            return True
        except Exception as e:
            # Bei Fehlern trotzdem akzeptieren, um 400-Fehler zu vermeiden
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Socket.IO connect handler Fehler (trotzdem akzeptiert): {e}")
        return True
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle Socket.IO-Trennung."""
        import logging
        logger = logging.getLogger(__name__)
        logger.debug("Socket.IO: Client getrennt")
    
    @app.before_request
    def csrf_same_origin_guard():
        """
        CSRF mitigation without breaking existing forms/AJAX:
        enforce same-origin on state-changing requests.
        """
        if request.method in {'GET', 'HEAD', 'OPTIONS', 'TRACE'}:
            return

        # Ignore Socket.IO transport paths.
        if request.path.startswith('/socket.io/'):
            return

        endpoint = request.endpoint or ''

        # Machine callbacks/webhooks and token/public paths are excluded.
        if (
            endpoint.startswith('files.onlyoffice') or
            endpoint.startswith('files.share_onlyoffice') or
            endpoint.startswith('kanban.onlyoffice') or
            request.path.startswith('/onlyoffice') or
            '/onlyoffice-callback' in request.path
        ):
            return

        origin = request.headers.get('Origin', '')
        referer = request.headers.get('Referer', '')
        sec_fetch_site = (request.headers.get('Sec-Fetch-Site') or '').strip().lower()
        host = request.host

        if origin:
            if _is_same_origin(origin, host):
                return
            app.logger.warning("CSRF blocked by Origin mismatch: %s -> %s", origin, host)
            return jsonify({'error': 'CSRF validation failed'}), 403

        if referer:
            if _is_same_origin(referer, host):
                return
            app.logger.warning("CSRF blocked by Referer mismatch: %s -> %s", referer, host)
            return jsonify({'error': 'CSRF validation failed'}), 403

        # Einige Reverse-Proxy/Client-Kombinationen senden kein Origin/Referer.
        # Wenn Browser den Request als same-origin/same-site/none klassifiziert,
        # akzeptieren wir den State-Change trotzdem.
        if sec_fetch_site in {'same-origin', 'same-site', 'none'}:
            return

        app.logger.warning("CSRF blocked: missing Origin/Referer for %s %s", request.method, request.path)
        return jsonify({'error': 'CSRF validation failed'}), 403

    @app.before_request
    def check_email_confirmation():
        """Prüft E-Mail-Bestätigung für alle Routen außer Auth und Setup."""
        from flask import request, redirect, url_for, flash
        from flask_login import current_user

        if session.get('user_scope') == 'assessment':
            if request.path.startswith('/assessment'):
                return
            if request.endpoint in {'auth.login', 'auth.logout', 'manifest', 'static'}:
                return
            return redirect(url_for('assessment.general.home'))
        
        # WICHTIG: Socket.IO-Requests ausschließen (verhindert 401-Fehler)
        # Socket.IO verwendet /socket.io/ als Pfad und hat keinen normalen Endpoint
        if request.path.startswith('/socket.io/'):
            return
        
        # Öffentliche Musikwunschliste-Route ausschließen (keine Authentifizierung erforderlich)
        if request.path.startswith('/music/wishlist'):
            return
        
        if (request.endpoint and 
            (request.endpoint.startswith('auth.') or 
             request.endpoint.startswith('setup.') or
             request.endpoint.startswith('static') or
             request.endpoint.startswith('api.') or
             request.endpoint.startswith('files.onlyoffice') or
             request.endpoint.startswith('files.share_onlyoffice') or
             request.endpoint.startswith('booking.public') or
             request.endpoint.startswith('booking.public_') or
             request.endpoint == 'booking.public_booking' or
             request.endpoint == 'booking.public_form' or
             request.endpoint == 'booking.public_view' or
             request.endpoint == 'manifest' or
             request.endpoint == 'settings.portal_logo' or
             request.endpoint == 'music.public_wishlist' or
             request.endpoint == 'music.public_search' or
             request.endpoint.startswith('surveys.public_') or
             request.endpoint == 'surveys.public_fill' or
             request.endpoint == 'surveys.public_done' or
             request.endpoint == 'surveys.public_header' or
             request.endpoint == 'shortlinks.resolve')):
            return
        
        if not current_user.is_authenticated:
            return
        
        if not current_user.is_email_confirmed:
            if request.endpoint == 'auth.confirm_email':
                return
            flash('Bitte bestätigen Sie Ihre E-Mail-Adresse, um fortzufahren.', 'info')
            return redirect(url_for('auth.confirm_email'))

    @app.before_request
    def ensure_portal_session_tracking():
        """Sorgt dafür, dass authentifizierte Portal-Sessions in user_sessions erfasst sind."""
        from flask import redirect, url_for, flash
        from flask_login import current_user, logout_user

        if not current_user.is_authenticated:
            return

        # Assessment-Logins nutzen einen separaten Scope und kein Portal-Session-Tracking.
        if session.get('user_scope') == 'assessment':
            return

        # Socket.IO-Handshake/Events sind keine klassischen HTTP-Seitenaufrufe.
        if request.path.startswith('/socket.io/'):
            return

        if request.endpoint and request.endpoint.startswith('static'):
            return

        # Setup-Wizard: Session-Tracking erst nach Abschluss erzwingen.
        # Sonst landet man nach Admin-Anlage (login_user ohne session_id) sofort auf /login.
        if request.endpoint and request.endpoint.startswith('setup.'):
            return

        from datetime import datetime, timedelta
        from app.utils.session_manager import get_current_session, revoke_all_sessions
        from app.utils.common import portal_now_naive

        try:
            # Abgelaufene Gast-Accounts sofort deaktivieren und abmelden.
            if getattr(current_user, 'is_guest', False) and current_user.guest_expires_at:
                if portal_now_naive() > current_user.guest_expires_at:
                    if current_user.is_active:
                        current_user.is_active = False
                        revoke_all_sessions(current_user.id, exclude_current=False)
                        db.session.commit()
                    logout_user()
                    session.clear()
                    if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
                        return jsonify({'error': 'Guest access expired'}), 401
                    flash(translate('auth.flash.guest_access_expired_contact_admin'), 'warning')
                    return redirect(url_for('auth.login'))

            if not getattr(current_user, 'is_active', True):
                logout_user()
                session.clear()
                if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
                    return jsonify({'error': 'Account deactivated'}), 401
                return redirect(url_for('auth.login'))

            current_session_id = session.get('session_id')
            if not current_session_id:
                logout_user()
                session.clear()
                if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
                    return jsonify({'error': 'Session invalidated'}), 401
                return redirect(url_for('auth.login'))

            current_session = get_current_session(current_user.id)
            if current_session is None:
                # WICHTIG: Keine automatische Neuanlage widerrufener Sessions.
                logout_user()
                session.clear()
                if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
                    return jsonify({'error': 'Session invalidated'}), 401
                return redirect(url_for('auth.login'))

            # Last-Activity nicht bei jedem Request schreiben, um DB-Last zu reduzieren.
            if not current_session.last_activity or (datetime.utcnow() - current_session.last_activity) >= timedelta(minutes=1):
                current_session.last_activity = datetime.utcnow()
                db.session.commit()

            inactivity_limit = timedelta(days=30)
            last_seen = current_session.last_activity or current_session.created_at
            if last_seen and (datetime.utcnow() - last_seen) >= inactivity_limit:
                from app.utils.session_manager import revoke_session
                revoke_session(current_user.id, current_session_id)
                db.session.commit()
                logout_user()
                session.clear()
                if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
                    return jsonify({'error': 'Session expired due to inactivity'}), 401
                flash(translate('settings.admin.system.flash_inactivity_logout'), 'info')
                return redirect(url_for('auth.login'))
        except Exception as exc:
            app.logger.warning("Session-Tracking konnte nicht aktualisiert werden: %s", exc)
    
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

    def _asset_version():
        build = str(app.config.get('ABOUT_BUILD_NUMBER') or '').strip()
        release = str(app.config.get('ABOUT_RELEASE_VERSION') or '').strip()
        return build or release or 'dev'

    def versioned_url_for(endpoint, **values):
        """Jinja url_for with cache-busting query for static assets."""
        if endpoint == 'static':
            values.setdefault('v', _asset_version())
        return flask_url_for(endpoint, **values)

    @app.context_processor
    def inject_versioned_url_for():
        return {
            'url_for': versioned_url_for,
            'asset_version': _asset_version(),
            'app_version': str(app.config.get('ABOUT_RELEASE_VERSION') or '').strip() or 'unknown',
        }
    
    @app.context_processor
    def inject_app_config():
        from app.utils.common import is_module_enabled
        from app.utils.access_control import has_module_access
        from app.utils.multi_mailboxes import is_email_multi_enabled
        from flask_login import current_user
        app_name = app.config.get('APP_NAME', 'Prismateams')
        app_logo = app.config.get('APP_LOGO')
        color_gradient = None
        portal_logo_filename = None
        
        try:
            from app.models.settings import SystemSettings
            
            portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
            if portal_name_setting and portal_name_setting.value and portal_name_setting.value.strip():
                app_name = portal_name_setting.value
            else:
                org_name_setting = SystemSettings.query.filter_by(key='organization_name').first()
                if org_name_setting and org_name_setting.value and org_name_setting.value.strip():
                    app_name = org_name_setting.value
                else:
                    app_name = app.config.get('APP_NAME', 'Prismateams')
            
            portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
            if portal_logo_setting and portal_logo_setting.value:
                portal_logo_filename = portal_logo_setting.value
                app_logo = None
            
            gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
            if gradient_setting and gradient_setting.value:
                color_gradient = gradient_setting.value
        except:
            pass
        
        if app_logo and app_logo.startswith('static/'):
            app_logo = app_logo[7:]
        
        from app.utils.onlyoffice import is_onlyoffice_enabled
        onlyoffice_available = is_onlyoffice_enabled()

        from app.utils.common import is_module_enabled
        
        def get_chat_display_name(chat):
            """Returns the display name for a chat. For private chats, shows only the other person's name."""
            from flask_login import current_user
            if chat.is_direct_message and not chat.is_main_chat:
                from app.models.chat import ChatMember
                from app.models.user import User
                from app.utils.chat_visibility import visible_chat_user_filters
                members = ChatMember.query.filter_by(chat_id=chat.id).join(User).filter(
                    *visible_chat_user_filters(),
                ).all()
                for member in members:
                    if member.user_id != current_user.id:
                        return member.user.full_name
                return chat.name
            if chat.is_main_chat:
                return translate('chat.common.main_chat_name')
            return chat.name
        
        def get_other_chat_user(chat):
            """Returns the other user in a private chat."""
            from flask_login import current_user
            from app.models.chat import ChatMember
            from app.models.user import User
            from app.utils.chat_visibility import visible_chat_user_filters
            
            if not chat or not chat.is_direct_message or chat.is_main_chat:
                return None
            
            members = ChatMember.query.filter_by(chat_id=chat.id).join(User).filter(
                *visible_chat_user_filters(),
            ).all()
            
            for member in members:
                if member.user_id != current_user.id:
                    return member.user
            return None
        
        def get_back_url():
            """Bestimmt die logische Zurück-URL basierend auf dem aktuellen Endpoint."""
            from flask import request, url_for
            
            if not request.endpoint:
                return url_for('dashboard.index')
            
            endpoint = request.endpoint
            
            specific_mappings = {
                'inventory.product_edit': 'inventory.stock',
                'inventory.product_new': 'inventory.stock',
                'inventory.product_documents': 'inventory.stock',
                'inventory.product_borrow': 'inventory.stock',
                'inventory.product_document_upload': 'inventory.stock',
                'inventory.product_document_delete': 'inventory.stock',
                'inventory.product_document_download': 'inventory.stock',
                'inventory.set_view': 'inventory.sets',
                'inventory.set_edit': 'inventory.sets',
                'inventory.set_borrow': 'inventory.sets',
                'inventory.set_form': 'inventory.sets',
                'inventory.folders': 'inventory.stock',
                'settings.profile': 'settings.index',
                'settings.appearance': 'settings.index',
                'settings.notifications': 'settings.index',
                'settings.about': 'settings.index',
                'settings.admin': 'settings.index',
                'settings.admin_users': 'settings.index',
                'settings.admin_email_permissions': 'settings.index',
                'settings.admin_email_footer': 'settings.index',
                'settings.admin_system': 'settings.index',
                'settings.admin_modules': 'settings.index',
                'settings.admin_backup': 'settings.index',
                'settings.admin_whitelist': 'settings.index',
                'settings.add_whitelist_entry': 'settings.index',
                'settings.toggle_whitelist_entry': 'settings.index',
                'settings.delete_whitelist_entry': 'settings.index',
                'settings.admin_file_settings': 'settings.index',
                'settings.booking_forms': 'settings.index',
                'settings.booking_form_create': 'settings.index',
                'settings.booking_form_edit': 'settings.index',
                'settings.booking_form_delete': 'settings.index',
                'settings.booking_field_add': 'settings.index',
                'settings.booking_field_edit': 'settings.index',
                'settings.booking_field_delete': 'settings.index',
                'settings.booking_field_order': 'settings.index',
                'settings.booking_image_upload': 'settings.index',
                'settings.booking_image_delete': 'settings.index',
                'settings.booking_image': 'settings.index',
                'auth.show_confirmation_codes': 'settings.index',
                'auth.test_email': 'settings.index',
                'calendar.view': 'calendar.index',
                'calendar.edit_event': 'calendar.index',
                'calendar.create': 'calendar.index',
                'events.view_event': 'events.index',
                'events.edit_event': 'events.index',
                'events.create_event': 'events.index',
                'email.view_email': 'email.index',
                'email.compose': 'email.index',
                'email.reply': 'email.index',
                'email.reply_all': 'email.index',
                'email.forward': 'email.index',
                'chat.view_chat': 'chat.index',
                'chat.create': 'chat.index',
                'wiki.view': 'wiki.index',
                'wiki.edit': 'wiki.index',
                'wiki.create': 'wiki.index',
                'credentials.view': 'credentials.index',
                'credentials.edit': 'credentials.index',
                'credentials.create': 'credentials.index',
                'manuals.view': 'manuals.index',
                'manuals.raw': 'manuals.index',
                'manuals.edit': 'manuals.index',
                'manuals.create': 'manuals.index',
                'assessment.lists.manage_list_subjects_page': 'assessment.lists.manage_lists_page',
                'assessment.auth.admin_setup': 'assessment.general.home',
            }
            
            if endpoint in specific_mappings:
                return url_for(specific_mappings[endpoint])
            
            if endpoint == 'files.browse_folder':
                folder_id = request.view_args.get('folder_id') if request.view_args else None
                if folder_id:
                    from app.models.file import Folder
                    folder = Folder.query.get(folder_id)
                    if folder and folder.parent_id:
                        return url_for('files.browse_folder', folder_id=folder.parent_id)
                return url_for('files.index')
            
            if endpoint.startswith('settings.admin_'):
                return url_for('settings.index')
            
            module_mapping = {
                'inventory': 'inventory.dashboard',
                'email': 'email.index',
                'chat': 'chat.index',
                'files': 'files.index',
                'calendar': 'calendar.index',
                'events': 'events.index',
                'contacts': 'contacts.index',
                'credentials': 'credentials.index',
                'manuals': 'manuals.index',
                'wiki': 'wiki.index',
                'excalidraw': 'excalidraw.index',
                'shortlinks': 'shortlinks.index',
                'settings': 'settings.index',
                'assessment': 'assessment.general.home'
            }
            
            for module_prefix, index_endpoint in module_mapping.items():
                if endpoint.startswith(module_prefix + '.'):
                    if endpoint == index_endpoint:
                        return url_for('dashboard.index')
                    return url_for(index_endpoint)
            
            return url_for('dashboard.index')
        
        mobile_nav_slots = None
        mobile_nav_left = None
        mobile_nav_right = None
        desktop_nav_modules = []
        desktop_nav_favorites = []
        current_nav_module = None
        nav_storage_usage = None
        # Assessment-Scope: keine Portal-Mobile-Nav (nur Modul-Sidebar inkl. Logout).
        if current_user.is_authenticated and session.get('user_scope') != 'assessment':
            from flask import request as _req
            from app.utils.navigation import (
                get_current_nav_module,
                get_desktop_nav_modules,
                get_mobile_nav_slots,
                get_nav_favorites,
                resolve_nav_link,
            )
            mobile_nav_slots = get_mobile_nav_slots(current_user)
            mobile_nav_left = resolve_nav_link(mobile_nav_slots['left'], current_user)
            mobile_nav_right = resolve_nav_link(mobile_nav_slots['right'], current_user)
            desktop_nav_modules = get_desktop_nav_modules(current_user)
            desktop_nav_favorites = get_nav_favorites(current_user)
            current_nav_module = get_current_nav_module(_req.endpoint, current_user)
            try:
                from app.utils.file_storage_limits import usage_payload_for_user
                payload = usage_payload_for_user(current_user.id)
                if payload.get('quota_enabled'):
                    nav_storage_usage = payload
            except Exception:
                nav_storage_usage = None

        robots_meta = 'noindex, nofollow'
        try:
            from app.utils.search_indexing import robots_meta_content
            robots_meta = robots_meta_content()
        except Exception:
            pass

        return {
            'app_name': app_name,
            'app_logo': app_logo,
            'color_gradient': color_gradient,
            'portal_logo_filename': portal_logo_filename,
            'onlyoffice_available': onlyoffice_available,
            'is_module_enabled': is_module_enabled,
            'is_email_multi_enabled': is_email_multi_enabled,
            'has_module_access': has_module_access,
            'get_back_url': get_back_url,
            'get_chat_display_name': get_chat_display_name,
            'get_other_chat_user': get_other_chat_user,
            'mobile_nav_slots': mobile_nav_slots,
            'mobile_nav_left': mobile_nav_left,
            'mobile_nav_right': mobile_nav_right,
            'desktop_nav_modules': desktop_nav_modules,
            'desktop_nav_favorites': desktop_nav_favorites,
            'current_nav_module': current_nav_module,
            'nav_storage_usage': nav_storage_usage,
            'robots_meta': robots_meta,
        }
    
    @app.template_filter('decode_email_header')
    def decode_email_header_filter(header):
        """Decode email header fields properly."""
        if not header:
            return ''
        
        try:
            from email.header import decode_header
            decoded_parts = decode_header(str(header))
            decoded_string = ''
            
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        decoded_string += part.decode(encoding)
                    else:
                        decoded_string += part.decode('utf-8', errors='ignore')
                else:
                    decoded_string += str(part)
            
            return decoded_string.strip()
        except Exception:
            return str(header)
    
    @app.template_filter('email_sender_initials')
    def email_sender_initials_filter(sender):
        """Initialen für Avatar: Anzeigenamen ohne Anführungszeichen, Vorname+Nachname wenn möglich."""
        if not sender:
            return '??'

        def _strip_outer_quotes(s: str) -> str:
            t = (s or '').strip()
            while len(t) >= 2 and t[0] in '"\'' and t[-1] == t[0]:
                t = t[1:-1].strip()
            return t

        def _initials_from_local_part(local: str) -> str:
            alnum = ''.join(c for c in (local or '') if c.isalnum())
            if len(alnum) >= 2:
                return alnum[0:2].upper()
            if len(alnum) == 1:
                return (alnum[0] * 2).upper()
            return '??'

        try:
            import re

            decoded = decode_email_header_filter(sender).strip()
            display = ''
            addr = ''

            m = re.match(r'^(?P<dn>.*?)\s*<(?P<em>[^>\s]+@[^>\s]+)>\s*$', decoded, re.DOTALL)
            if m:
                display = (m.group('dn') or '').strip()
                addr = (m.group('em') or '').strip()
            elif re.match(r'^[^\s<]+@[^\s>]+$', decoded):
                addr = decoded.strip()
            else:
                display = decoded

            display = _strip_outer_quotes(display)

            parts = [p for p in re.split(r'\s+', display) if p]
            if len(parts) >= 2:
                return (parts[0][0] + parts[-1][0]).upper()
            if len(parts) == 1:
                w = parts[0]
                if len(w) >= 2:
                    return w[0:2].upper()
                if len(w) == 1:
                    return (w[0] * 2).upper()
            if addr and '@' in addr:
                return _initials_from_local_part(addr.split('@', 1)[0])
            if display and '@' in display:
                return _initials_from_local_part(display.split('@', 1)[0])
            return '??'
        except Exception:
            return '??'
    
    
    from app.utils import format_time, format_datetime
    
    @app.template_filter('localtime')
    def localtime_filter(dt, format_string='%H:%M'):
        """Filter to format datetime in local timezone."""
        return format_time(dt, format_string)
    
    @app.template_filter('localdatetime')
    def localdatetime_filter(dt, format_string='%d.%m.%Y %H:%M'):
        """Filter to format datetime in local timezone."""
        return format_datetime(dt, format_string)
    
    @app.template_filter('smart_datetime')
    def smart_datetime_filter(dt):
        """Smart datetime formatting: Today shows time only, Yesterday shows 'Gestern HH:MM', older shows date."""
        if not dt:
            return ''
        
        from app.utils.common import get_local_time, now_in_portal_timezone
        
        local_dt = get_local_time(dt)
        if isinstance(local_dt, str):
            try:
                local_dt = datetime.fromisoformat(local_dt.replace('Z', '+00:00'))
            except:
                return str(dt)
        
        now = now_in_portal_timezone()
        today = now.date()
        message_date = local_dt.date()
        
        days_diff = (today - message_date).days
        
        if days_diff == 0:
            return local_dt.strftime('%H:%M')
        elif days_diff == 1:
            return f"Gestern {local_dt.strftime('%H:%M')}"
        else:
            return local_dt.strftime('%d.%m.%Y %H:%M')
    
    @app.template_filter('markdown')
    def markdown_filter(text):
        """Filter to render markdown text."""
        try:
            from app.utils.markdown import process_markdown
            return process_markdown(text, wiki_mode=False)
            
        except Exception as e:
            from flask import current_app
            current_app.logger.warning(f"Markdown processing failed: {e}, using plain text fallback")
            return text.replace('\n', '<br>')

    def _error_detail(error):
        """Human-readable detail for error pages (server log / exception text)."""
        if error is None:
            return None
        detail = getattr(error, 'description', None) or str(error)
        detail = (detail or '').strip()
        return detail or None

    @app.errorhandler(400)
    def bad_request(error):
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Bad request', 'message': str(error)}), 400
        return render_template('errors/400.html', error_detail=_error_detail(error)), 400
    
    @app.errorhandler(403)
    def forbidden(error):
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Forbidden', 'message': str(error)}), 403
        return render_template('errors/403.html', error_detail=_error_detail(error)), 403
    
    @app.errorhandler(404)
    def not_found(error):
        app.logger.warning(f"404 Not Found: {request.url}")
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Not found', 'path': request.path}), 404
        return render_template('errors/404.html', error_detail=_error_detail(error)), 404
    
    @app.errorhandler(429)
    def too_many_requests(error):
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Too many requests', 'message': str(error)}), 429
        return render_template('errors/429.html', error_detail=_error_detail(error)), 429
    
    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle 413 Request Entity Too Large errors."""
        app.logger.warning(f"413 Request Entity Too Large: {request.url}")
        wants_json = (
            request.path.startswith('/api/')
            or request.path.startswith('/files/api/')
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in (request.headers.get('Accept') or '')
        )
        msg = 'Die hochgeladene Datei überschreitet das maximale Größenlimit.'
        if wants_json:
            return jsonify({
                'success': False,
                'error': 'File too large',
                'message': msg,
                'messages': [{'category': 'danger', 'text': msg}],
            }), 413
        try:
            from app.utils.file_storage_limits import format_bytes_de, get_max_configured_file_size
            max_label = format_bytes_de(get_max_configured_file_size())
            msg = f'Die hochgeladene Datei überschreitet das maximale Größenlimit (max. {max_label} pro Datei).'
        except Exception:
            pass
        max_size_mb = (app.config.get('MAX_CONTENT_LENGTH') or (100 * 1024 * 1024)) / (1024 * 1024)
        return render_template(
            'errors/413.html',
            max_size_mb=max_size_mb,
            error_detail=_error_detail(error),
        ), 413
    
    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"500 Internal Server Error: {error}", exc_info=True)
        db.session.rollback()
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Internal server error', 'message': str(error)}), 500
        return render_template('errors/500.html', error_detail=_error_detail(error)), 500
    
    @app.errorhandler(Exception)
    def handle_exception(e):
        from werkzeug.exceptions import RequestEntityTooLarge
        if isinstance(e, RequestEntityTooLarge):
            raise
        
        app.logger.error(f"Unhandled exception: {e}", exc_info=True)
        
        db.session.rollback()
        
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Internal server error', 'message': str(e)}), 500
        return render_template('errors/500.html', error_detail=_error_detail(e)), 500
    
    @app.errorhandler(ValueError)
    def handle_value_error(e):
        app.logger.warning(f"Value error: {e}")
        return render_template('errors/generic.html', 
                             error_code='400',
                             error_title='Ungültige Eingabe',
                             error_message=str(e),
                             error_detail=_error_detail(e)), 400
    
    @app.errorhandler(PermissionError)
    def handle_permission_error(e):
        app.logger.warning(f"Permission error: {e}")
        return render_template('errors/403.html', error_detail=_error_detail(e)), 403

    from app.blueprints.setup import setup_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.dashboard import dashboard_bp
    from app.blueprints.chat import chat_bp
    from app.blueprints.files import files_bp
    from app.blueprints.calendar import calendar_bp
    from app.blueprints.email import email_bp, start_email_sync
    from app.blueprints.contacts import contacts_bp
    from app.blueprints.credentials import credentials_bp
    from app.blueprints.manuals import manuals_bp
    from app.blueprints.settings import settings_bp
    from app.blueprints.api import api_bp
    from app.blueprints.errors import errors_bp
    from app.blueprints.inventory import inventory_bp
    from app.blueprints.inventory_vnext import inventory_vnext_bp, inventory_vnext_compat_bp
    from app.blueprints.wiki import wiki_bp
    from app.blueprints.comments import comments_bp
    from app.blueprints.booking import booking_bp
    from app.blueprints.music import music_bp
    from app.blueprints.sse import sse_bp
    from app.blueprints.assessment import assessment_bp
    from app.blueprints.shortlinks import shortlinks_bp
    from app.blueprints.events import events_bp
    from app.blueprints.media_downloader import media_downloader_bp
    from app.blueprints.file_converter import file_converter_bp
    from app.blueprints.kanban import kanban_bp
    from app.blueprints.excalidraw import excalidraw_bp
    from app.blueprints.surveys import surveys_bp
    
    app.register_blueprint(setup_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(chat_bp, url_prefix='/chat')
    app.register_blueprint(files_bp, url_prefix='/files')
    app.register_blueprint(calendar_bp, url_prefix='/calendar')
    app.register_blueprint(email_bp, url_prefix='/email')
    app.register_blueprint(contacts_bp, url_prefix='/contacts')
    app.register_blueprint(credentials_bp, url_prefix='/credentials')
    app.register_blueprint(manuals_bp, url_prefix='/manuals')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_bp, url_prefix='/api')
    if config_name != 'production':
        app.register_blueprint(errors_bp, url_prefix='/test')
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(inventory_vnext_bp, url_prefix='/inventory')
    app.register_blueprint(inventory_vnext_compat_bp)
    app.register_blueprint(wiki_bp)
    app.register_blueprint(comments_bp)
    app.register_blueprint(booking_bp, url_prefix='/booking')
    app.register_blueprint(music_bp)
    app.register_blueprint(sse_bp, url_prefix='/sse')
    app.register_blueprint(assessment_bp)
    app.register_blueprint(shortlinks_bp)
    app.register_blueprint(events_bp, url_prefix='/events')
    app.register_blueprint(media_downloader_bp)
    app.register_blueprint(file_converter_bp)
    app.register_blueprint(kanban_bp, url_prefix='/kanban')
    app.register_blueprint(excalidraw_bp)
    app.register_blueprint(surveys_bp)
    
    @app.route('/manifest.json')
    def manifest():
        import json
        from flask import url_for
        from app.models.settings import SystemSettings
        
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else app.config.get('APP_NAME', 'Prismateams')
        
        # Standard Logo-URL
        logo_url = url_for('static', filename='img/logo.png')
        
        # Portal-Logo prüfen
        portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
        if portal_logo_setting and portal_logo_setting.value:
            logo_url = url_for('settings.portal_logo', filename=portal_logo_setting.value)
        
        manifest_path = os.path.join(app.static_folder, 'manifest.json')
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
            
            manifest_data['name'] = portal_name
            manifest_data['short_name'] = portal_name[:12]  # short_name sollte max 12 Zeichen haben

            # Statusleisten-/PWA-Farbe an Dark/OLED anpassen
            theme_color = '#f0f2f5'
            from flask_login import current_user
            if getattr(current_user, 'is_authenticated', False):
                if getattr(current_user, 'oled_mode', False) and getattr(current_user, 'dark_mode', False):
                    theme_color = '#000000'
                elif getattr(current_user, 'dark_mode', False):
                    theme_color = '#1a1a1a'
            manifest_data['theme_color'] = theme_color
            manifest_data['background_color'] = theme_color
            
            # Logo in allen Icon-Einträgen aktualisieren
            for icon in manifest_data.get('icons', []):
                icon['src'] = logo_url
            
            # Logo auch in Screenshots aktualisieren (falls vorhanden)
            for screenshot in manifest_data.get('screenshots', []):
                screenshot['src'] = logo_url
            
            return jsonify(manifest_data)
        except:
            # Fallback: Statische Datei senden, aber trotzdem Portalnamen verwenden
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest_data = json.load(f)
                manifest_data['name'] = portal_name
                manifest_data['short_name'] = portal_name[:12]
                for icon in manifest_data.get('icons', []):
                    icon['src'] = logo_url
                return jsonify(manifest_data)
            except:
                return app.send_static_file('manifest.json')
    
    @app.route('/api/portal-info')
    def portal_info():
        """API-Endpoint für Portal-Informationen (für Service Worker)."""
        from flask import url_for
        from app.models.settings import SystemSettings
        
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else app.config.get('APP_NAME', 'Prismateams')
        
        # Standard Logo-URL
        logo_url = url_for('static', filename='img/logo.png', _external=False)
        
        # Portal-Logo prüfen
        portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
        if portal_logo_setting and portal_logo_setting.value:
            logo_url = url_for('settings.portal_logo', filename=portal_logo_setting.value, _external=False)
        
        return jsonify({
            'name': portal_name,
            'logo': logo_url
        })
    
    @app.route('/sw.js')
    def service_worker():
        """Serve SW with release-bound cache name and no-cache headers."""
        from flask import Response, make_response

        sw_path = os.path.join(app.static_folder, 'sw.js')
        with open(sw_path, 'r', encoding='utf-8') as f:
            content = f.read()

        release = str(app.config.get('ABOUT_RELEASE_VERSION') or 'v0.0.0').strip().lstrip('vV') or '0.0.0'
        build = str(app.config.get('ABOUT_BUILD_NUMBER') or '').strip()
        cache_name = f"team-portal-v{release}"
        if build:
            cache_name = f"{cache_name}-{build}"

        content = content.replace('__SW_CACHE_NAME__', cache_name)
        content = content.replace('__SW_ASSET_VERSION__', _asset_version())

        response = make_response(Response(content, mimetype='application/javascript'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.route('/robots.txt')
    def robots_txt():
        from flask import Response
        from app.utils.search_indexing import build_robots_txt
        response = Response(build_robots_txt(), mimetype='text/plain; charset=utf-8')
        response.headers['Cache-Control'] = 'public, max-age=300'
        return response

    @app.route('/sitemap.xml')
    def sitemap_xml():
        from flask import Response
        from app.utils.search_indexing import build_sitemap_xml
        response = Response(build_sitemap_xml(), mimetype='application/xml; charset=utf-8')
        response.headers['Cache-Control'] = 'public, max-age=300'
        return response

    @app.after_request
    def apply_search_indexing_headers(response):
        if request.endpoint in ('robots_txt', 'sitemap_xml'):
            return response
        mimetype = response.mimetype or ''
        if 'html' not in mimetype:
            return response
        try:
            from app.utils.search_indexing import robots_meta_content
            response.headers.setdefault('X-Robots-Tag', robots_meta_content())
        except Exception:
            pass
        return response
    
    # Schema-Init: immer (außer Reloader-Parent / explizitem Skip).
    # Background-Jobs: nicht im Reloader-Parent und nicht während Migrationen.
    werkzeug_run_main = os.environ.get('WERKZEUG_RUN_MAIN')
    is_debug = app.config.get('DEBUG', False)
    from app.utils.schema_init import should_run_startup_schema, ensure_all_tables
    run_schema_init = should_run_startup_schema(debug=is_debug)
    run_startup_migrations = _env_flag('PRISMATEAMS_STARTUP_MIGRATIONS', False)
    # Legacy-Name: Background-Jobs nur im „Hauptprozess“ (kein Reloader-Parent)
    is_main_process = (werkzeug_run_main == 'true') or (not is_debug)
    
    with app.app_context():
        if run_schema_init:
            try:
                from app.models.user import User
                from app.models.chat import Chat, ChatMessage, ChatMember, ChatPin
                from app.models.file import File, FileVersion, Folder, FileEditLock
                from app.models.calendar import CalendarEvent, EventParticipant, PublicCalendarFeed, CalendarSyncSource
                from app.models.email import EmailMessage, EmailPermission, EmailAttachment, EmailFolder
                from app.models.credential import Credential, CredentialFolder, CredentialFavorite
                from app.models.manual import Manual
                from app.models.settings import SystemSettings
                from app.models.whitelist import WhitelistEntry
                from app.models.notification import NotificationSettings, ChatNotificationSettings, PushSubscription, NotificationLog
                from app.models.inventory import Product, BorrowTransaction, ProductFolder, ProductSet, ProductSetItem, ProductDocument, SavedFilter, ProductFavorite, Inventory, InventoryItem, ProductLot, StockMovement, ProductStatusHistory, InventoryItemLock, Checkout, CheckoutItem
                from app.models.api_token import ApiToken
                from app.models.wiki import WikiPage, WikiPageVersion, WikiCategory, WikiTag, WikiFavorite
                from app.models.comment import Comment, CommentMention
                from app.models.music import MusicProviderToken, MusicWish, MusicQueue, MusicSettings
                from app.models.media_downloader import MediaDownloadJob
                from app.models.file_converter import ConversionJob
                from app.models.shortlink import ShortLink
                from app.models.kanban import (
                    KanbanBoard, KanbanBoardMember, KanbanList, KanbanCard,
                    KanbanLabel, KanbanCardLabel, KanbanCardAssignee,
                    KanbanChecklist, KanbanChecklistItem, KanbanAttachment,
                    KanbanCardVote, KanbanActivity, KanbanBoardTemplate, KanbanBoardView,
                    KanbanCustomField, KanbanCardFieldValue,
                )
                from app.models.booking import BookingRequest, BookingForm, BookingFormField, BookingFormImage, BookingRequestField, BookingRequestFile, BookingFormRole, BookingFormRoleUser, BookingRequestApproval
                from app.models.event import Event, EventAppointment, EventAssignment, EventInventoryNeed, EventContact, EventTimelineItem
                from app.models.user_session import UserSession
                from app.models.assessment import (
                    AssessmentUser,
                    AssessmentRole,
                    AssessmentUserRole,
                    AssessmentStandType,
                    AssessmentList,
                    AssessmentListSubject,
                    AssessmentRoom,
                    AssessmentStand,
                    AssessmentCriterion,
                    AssessmentEvaluation,
                    AssessmentEvaluationScore,
                    AssessmentVisitorEvaluation,
                    AssessmentVisitorEvaluationScore,
                    AssessmentWarning,
                    AssessmentRoomInspection,
                    AssessmentAppSetting,
                )
                from sqlalchemy import inspect, text

                # Robust: create_all + kritische Tabellen einzeln nachziehen (MySQL-Lock bei Multi-Worker)
                schema_ok, missing_tables = ensure_all_tables(db)
                if not schema_ok:
                    _log_startup(f"[WARNUNG] Schema unvollständig, fehlend: {', '.join(missing_tables)}")

                auto_migrate_after_update, release_marker = _should_run_migrations_after_update(app)
                should_run_startup_migrations = run_startup_migrations or auto_migrate_after_update

                # Migrationen laufen automatisch nach Update (Release-Marker-Wechsel)
                # oder explizit via PRISMATEAMS_STARTUP_MIGRATIONS=true.
                if should_run_startup_migrations and not os.getenv("PRISMATEAMS_RUNNING_MIGRATIONS"):
                    try:
                        from app.utils.auto_migrate import run_pending_migrations
                        run_pending_migrations(db)
                    except Exception as auto_mig_err:
                        _log_startup(f"[WARNUNG] Auto-Migration fehlgeschlagen: {auto_mig_err}")
                    # Nach Migrationen nochmals kritische Tabellen sicherstellen
                    try:
                        ensure_all_tables(db)
                    except Exception as schema_again_err:
                        _log_startup(f"[WARNUNG] Schema-Nachprüfung fehlgeschlagen: {schema_again_err}")
                else:
                    _log_startup("[INFO] Startup-Migrationen übersprungen (kein Update erkannt)")
                
                try:
                    from sqlalchemy import inspect
                    inspector = inspect(db.engine)
                    if 'folders' in inspector.get_table_names():
                        columns = {col['name']: col for col in inspector.get_columns('folders')}
                        if 'color' not in columns:
                            _log_startup("[INFO] Ergänze folders.color ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE folders ADD COLUMN color VARCHAR(16)"))
                            _log_startup("[OK] folders.color hinzugefügt")
                        if 'team_id' not in columns:
                            _log_startup("[INFO] Ergänze folders.team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE folders ADD COLUMN team_id INTEGER NULL"))
                            _log_startup("[OK] folders.team_id hinzugefügt")
                        if 'is_team_root' not in columns:
                            _log_startup("[INFO] Ergänze folders.is_team_root ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE folders ADD COLUMN is_team_root BOOLEAN NOT NULL DEFAULT 0"
                                ))
                            _log_startup("[OK] folders.is_team_root hinzugefügt")

                    if 'files' in inspector.get_table_names():
                        file_cols = {col['name'] for col in inspector.get_columns('files')}
                        if 'team_id' not in file_cols:
                            _log_startup("[INFO] Ergänze files.team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE files ADD COLUMN team_id INTEGER NULL"))
                            _log_startup("[OK] files.team_id hinzugefügt")

                    if 'resource_acl' in inspector.get_table_names():
                        acl_cols = {col['name'] for col in inspector.get_columns('resource_acl')}
                        if 'grantee_team_id' not in acl_cols:
                            _log_startup("[INFO] Ergänze resource_acl.grantee_team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE resource_acl ADD COLUMN grantee_team_id INTEGER NULL"
                                ))
                            _log_startup("[OK] resource_acl.grantee_team_id hinzugefügt")

                    if 'kanban_cards' in inspector.get_table_names():
                        kanban_cols = {col['name'] for col in inspector.get_columns('kanban_cards')}
                        if 'poll_text' not in kanban_cols:
                            _log_startup("[INFO] Ergänze kanban_cards.poll_text ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE kanban_cards ADD COLUMN poll_text TEXT"))
                            _log_startup("[OK] kanban_cards.poll_text hinzugefügt")
                        if 'completed_at' not in kanban_cols:
                            _log_startup("[INFO] Ergänze kanban_cards.completed_at ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE kanban_cards ADD COLUMN completed_at DATETIME NULL"))
                            _log_startup("[OK] kanban_cards.completed_at hinzugefügt")

                    if 'kanban_attachments' in inspector.get_table_names():
                        att_cols = {col['name']: col for col in inspector.get_columns('kanban_attachments')}
                        if 'url' not in att_cols:
                            _log_startup("[INFO] Ergänze kanban_attachments.url ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE kanban_attachments ADD COLUMN url VARCHAR(1000) NULL"))
                            _log_startup("[OK] kanban_attachments.url hinzugefügt")
                        dialect = db.engine.dialect.name
                        if dialect == 'mysql':
                            for col_name in ('filename', 'original_filename', 'storage_path'):
                                col = att_cols.get(col_name)
                                if col and not col.get('nullable', True):
                                    _log_startup(f"[INFO] Lockere kanban_attachments.{col_name} (nullable) ...")
                                    with db.engine.begin() as connection:
                                        connection.execute(text(
                                            f"ALTER TABLE kanban_attachments MODIFY COLUMN {col_name} VARCHAR(500) NULL"
                                            if col_name == 'storage_path'
                                            else f"ALTER TABLE kanban_attachments MODIFY COLUMN {col_name} VARCHAR(255) NULL"
                                        ))
                                    _log_startup(f"[OK] kanban_attachments.{col_name} nullable")
                        elif dialect == 'sqlite':
                            # SQLite: nullable change via recreate is heavy; new rows can use NULL if column allows
                            pass

                    table_names = inspector.get_table_names()
                    if 'credential_folders' not in table_names:
                        _log_startup("[INFO] Erstelle credential_folders ...")
                        CredentialFolder.__table__.create(db.engine, checkfirst=True)
                        _log_startup("[OK] credential_folders erstellt")

                    if 'credentials' in table_names:
                        credential_columns = {col['name'] for col in inspector.get_columns('credentials')}
                        if 'folder_id' not in credential_columns:
                            _log_startup("[INFO] Ergänze credentials.folder_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE credentials ADD COLUMN folder_id INTEGER NULL"))
                            _log_startup("[OK] credentials.folder_id hinzugefügt")

                        if 'is_favorite' not in credential_columns:
                            _log_startup("[INFO] Ergänze credentials.is_favorite ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE credentials ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT 0"))
                            _log_startup("[OK] credentials.is_favorite hinzugefügt")

                    if 'credential_favorites' not in inspector.get_table_names():
                        _log_startup("[INFO] Erstelle credential_favorites ...")
                        CredentialFavorite.__table__.create(db.engine, checkfirst=True)
                        _log_startup("[OK] credential_favorites erstellt")
                        # Legacy-Favoriten auf Ersteller übernehmen
                        try:
                            dialect = db.engine.dialect.name
                            if dialect == "sqlite":
                                sql = """
                                    INSERT OR IGNORE INTO credential_favorites (user_id, credential_id, created_at)
                                    SELECT created_by, id, CURRENT_TIMESTAMP
                                    FROM credentials
                                    WHERE is_favorite = 1
                                """
                            else:
                                sql = """
                                    INSERT IGNORE INTO credential_favorites (user_id, credential_id, created_at)
                                    SELECT created_by, id, CURRENT_TIMESTAMP
                                    FROM credentials
                                    WHERE is_favorite = 1
                                """
                            with db.engine.begin() as connection:
                                connection.execute(text(sql))
                            _log_startup("[OK] Legacy credential favorites migriert")
                        except Exception as fav_err:
                            _log_startup(f"[WARNUNG] Legacy-Favoriten-Migration: {fav_err}")

                    if ('users' in inspector.get_table_names() and
                            'language' not in {col['name'] for col in inspector.get_columns('users')}):
                        _log_startup("[INFO] Ergänze users.language ...")
                        with db.engine.begin() as connection:
                            connection.execute(text(
                                "ALTER TABLE users ADD COLUMN language VARCHAR(10) NOT NULL DEFAULT 'de'"
                            ))
                        _log_startup("[OK] users.language hinzugefügt")
                    
                    # Sicherheitsfeatures-Migration (2FA, Rate Limiting, Session-Management)
                    # Vollständige Migration läuft über Auto-Migration (migrate_to_2_4_3.py).
                    # Hier nur Notfall-Fallback, falls Spalten noch fehlen.
                    if 'users' in inspector.get_table_names():
                        columns = {col['name'] for col in inspector.get_columns('users')}
                        security_columns = {
                            ('totp_secret', 'VARCHAR(255)'),
                            ('totp_enabled', 'BOOLEAN DEFAULT 0'),
                            ('password_changed_at', 'DATETIME'),
                            ('failed_login_attempts', 'INTEGER DEFAULT 0'),
                            ('failed_login_until', 'DATETIME'),
                        }
                        missing = [(n, d) for n, d in security_columns if n not in columns]
                        if missing:
                            _log_startup("[INFO] Ergänze fehlende Security-Spalten an users ...")
                            with db.engine.begin() as connection:
                                for col_name, col_ddl in missing:
                                    connection.execute(text(
                                        f"ALTER TABLE users ADD COLUMN {col_name} {col_ddl}"
                                    ))
                            _log_startup("[OK] Security-Spalten ergänzt")
                        if 'user_sessions' not in inspector.get_table_names():
                            _log_startup("[INFO] user_sessions fehlt – wird von Auto-Migration (2.4.3) angelegt")

                    # Kalender-Events: event_color ergänzen
                    if 'calendar_events' in inspector.get_table_names():
                        calendar_columns = {col['name'] for col in inspector.get_columns('calendar_events')}
                        if 'event_color' not in calendar_columns:
                            _log_startup("[INFO] Ergänze calendar_events.event_color ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE calendar_events "
                                    "ADD COLUMN event_color VARCHAR(7) NOT NULL DEFAULT '#0d6efd'"
                                ))
                            _log_startup("[OK] calendar_events.event_color hinzugefügt")
                        if 'sync_source_id' not in calendar_columns:
                            _log_startup("[INFO] Ergänze calendar_events.sync_source_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE calendar_events ADD COLUMN sync_source_id INTEGER NULL"
                                ))
                            _log_startup("[OK] calendar_events.sync_source_id hinzugefügt")
                        if 'ical_uid' not in calendar_columns:
                            _log_startup("[INFO] Ergänze calendar_events.ical_uid ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE calendar_events ADD COLUMN ical_uid VARCHAR(255) NULL"
                                ))
                            _log_startup("[OK] calendar_events.ical_uid hinzugefügt")

                    # Kalender Sync-Sources Tabelle
                    if 'calendar_sync_sources' not in inspector.get_table_names():
                        _log_startup("[INFO] Erstelle calendar_sync_sources ...")
                        from app.models.calendar import CalendarSyncSource as _CalendarSyncSource
                        _CalendarSyncSource.__table__.create(db.engine, checkfirst=True)
                        _log_startup("[OK] calendar_sync_sources erstellt")

                    # Multi-Kalender: calendars + calendar_id
                    if 'calendars' not in inspector.get_table_names():
                        _log_startup("[INFO] Erstelle calendars ...")
                        from app.models.calendar import Calendar as _Calendar
                        _Calendar.__table__.create(db.engine, checkfirst=True)
                        _log_startup("[OK] calendars erstellt")
                    if 'calendar_events' in inspector.get_table_names():
                        calendar_columns = {col['name'] for col in inspector.get_columns('calendar_events')}
                        if 'calendar_id' not in calendar_columns:
                            _log_startup("[INFO] Ergänze calendar_events.calendar_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE calendar_events ADD COLUMN calendar_id INTEGER NULL"
                                ))
                            _log_startup("[OK] calendar_events.calendar_id hinzugefügt")

                    if 'calendars' in inspector.get_table_names():
                        cal_cols = {col['name'] for col in inspector.get_columns('calendars')}
                        cal_alters = []
                        if 'team_id' not in cal_cols:
                            cal_alters.append("ALTER TABLE calendars ADD COLUMN team_id INTEGER NULL")
                        if 'is_default' not in cal_cols:
                            cal_alters.append("ALTER TABLE calendars ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0")
                        if 'hidden_from_others' not in cal_cols:
                            cal_alters.append("ALTER TABLE calendars ADD COLUMN hidden_from_others BOOLEAN NOT NULL DEFAULT 0")
                        if cal_alters:
                            _log_startup("[INFO] Ergänze calendars Team-/Default-Spalten ...")
                            with db.engine.begin() as connection:
                                for stmt in cal_alters:
                                    connection.execute(text(stmt))
                            _log_startup("[OK] calendars Team-/Default-Spalten ergänzt")

                    if 'chats' in inspector.get_table_names():
                        chat_cols = {col['name'] for col in inspector.get_columns('chats')}
                        if 'team_id' not in chat_cols:
                            _log_startup("[INFO] Ergänze chats.team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE chats ADD COLUMN team_id INTEGER NULL"))
                            _log_startup("[OK] chats.team_id hinzugefügt")
                        chat_indexes = inspector.get_indexes('chats')
                        has_team_unique = any(
                            ix.get('unique') and ix.get('column_names') == ['team_id']
                            for ix in chat_indexes
                        ) or any(
                            u.get('column_names') == ['team_id']
                            for u in inspector.get_unique_constraints('chats')
                        )
                        if not has_team_unique:
                            _log_startup("[INFO] Lege Unique-Index chats.team_id an ...")
                            try:
                                with db.engine.begin() as connection:
                                    connection.execute(text(
                                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_chats_team_id ON chats(team_id)"
                                    ))
                                _log_startup("[OK] Unique-Index chats.team_id angelegt")
                            except Exception as idx_error:
                                _log_startup(f"[WARNUNG] Unique-Index chats.team_id: {idx_error}")

                    # Veranstaltungsmodul: Rückwärtskompatibilität für ältere Datenbanken
                    table_names = set(inspector.get_table_names())
                    if 'events' in table_names:
                        event_columns = {col['name'] for col in inspector.get_columns('events')}
                        with db.engine.begin() as connection:
                            if 'is_archived' not in event_columns:
                                connection.execute(
                                    text("ALTER TABLE events ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0")
                                )
                                _log_startup("[OK] events.is_archived hinzugefügt")
                            if 'archived_at' not in event_columns:
                                connection.execute(
                                    text("ALTER TABLE events ADD COLUMN archived_at DATETIME NULL")
                                )
                                _log_startup("[OK] events.archived_at hinzugefügt")

                    if 'event_timeline_items' in table_names:
                        timeline_columns = {
                            col['name'] for col in inspector.get_columns('event_timeline_items')
                        }
                        if 'appointment_id' not in timeline_columns:
                            with db.engine.begin() as connection:
                                connection.execute(
                                    text(
                                        "ALTER TABLE event_timeline_items "
                                        "ADD COLUMN appointment_id INTEGER NULL"
                                    )
                                )
                            _log_startup("[OK] event_timeline_items.appointment_id hinzugefügt")

                    # Chat-Messages: metadata_json für strukturierte Nachrichtentypen ergänzen
                    if 'chat_messages' in inspector.get_table_names():
                        chat_columns = {col['name'] for col in inspector.get_columns('chat_messages')}
                        if 'metadata_json' not in chat_columns:
                            _log_startup("[INFO] Ergänze chat_messages.metadata_json ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE chat_messages ADD COLUMN metadata_json TEXT"))
                            _log_startup("[OK] chat_messages.metadata_json hinzugefügt")

                    # Kontakte: sort_name für flexible Sortierung ergänzen
                    if 'contacts' in inspector.get_table_names():
                        contact_columns = {col['name'] for col in inspector.get_columns('contacts')}
                        if 'salutation' not in contact_columns:
                            _log_startup("[INFO] Ergänze contacts.salutation ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE contacts ADD COLUMN salutation VARCHAR(50)"))
                            _log_startup("[OK] contacts.salutation hinzugefügt")
                        if 'sort_name' not in contact_columns:
                            _log_startup("[INFO] Ergänze contacts.sort_name ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE contacts ADD COLUMN sort_name VARCHAR(255)"))
                                connection.execute(text(
                                    "UPDATE contacts SET sort_name = name "
                                    "WHERE sort_name IS NULL OR TRIM(sort_name) = ''"
                                ))
                            _log_startup("[OK] contacts.sort_name hinzugefügt und initialisiert")

                    visibility_tables = (
                        ('credentials', 'public'),
                        ('contacts', 'public'),
                        ('wiki_pages', 'public'),
                        ('manuals', 'public'),
                        ('short_links', 'private'),
                    )
                    current_tables = set(inspector.get_table_names())
                    for vis_table, vis_default in visibility_tables:
                        if vis_table not in current_tables:
                            continue
                        vis_cols = {col['name'] for col in inspector.get_columns(vis_table)}
                        if 'visibility' not in vis_cols:
                            _log_startup(f"[INFO] Ergänze {vis_table}.visibility ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    f"ALTER TABLE {vis_table} ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT '{vis_default}'"
                                ))
                            _log_startup(f"[OK] {vis_table}.visibility hinzugefügt")
                        if 'team_id' not in vis_cols:
                            _log_startup(f"[INFO] Ergänze {vis_table}.team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    f"ALTER TABLE {vis_table} ADD COLUMN team_id INTEGER NULL"
                                ))
                            _log_startup(f"[OK] {vis_table}.team_id hinzugefügt")

                    # E-Mail-Manager-Großupdate: Farbpunkt/Keyword-Sync-Spalten ergänzen
                    if 'email_messages' in inspector.get_table_names():
                        email_columns = {col['name'] for col in inspector.get_columns('email_messages')}
                        mail_manager_columns = []
                        if 'color_dot' not in email_columns:
                            mail_manager_columns.append(("color_dot", "VARCHAR(24) NULL"))
                        if 'is_flagged' not in email_columns:
                            mail_manager_columns.append(("is_flagged", "BOOLEAN NOT NULL DEFAULT 0"))
                        if 'imap_color_keyword' not in email_columns:
                            mail_manager_columns.append(("imap_color_keyword", "VARCHAR(64) NULL"))
                        if 'last_flag_sync_at' not in email_columns:
                            mail_manager_columns.append(("last_flag_sync_at", "DATETIME NULL"))
                        if mail_manager_columns:
                            _log_startup("[INFO] Ergänze email_messages Mail-Manager-Spalten ...")
                            try:
                                with db.engine.begin() as connection:
                                    for col_name, col_def in mail_manager_columns:
                                        connection.execute(text(
                                            f"ALTER TABLE email_messages ADD COLUMN {col_name} {col_def}"
                                        ))
                                _log_startup(
                                    "[OK] email_messages Mail-Manager-Spalten hinzugefügt: "
                                    + ", ".join(c[0] for c in mail_manager_columns)
                                )
                            except Exception as mail_col_error:
                                _log_startup(f"[WARNUNG] Mail-Manager-Spalten konnten nicht hinzugefügt werden: {mail_col_error}")
                except Exception as migration_error:
                    _log_startup(f"[WARNUNG] Inline-Schema-Nachrüstung fehlgeschlagen: {migration_error}")
                    _log_startup("[INFO] Bitte prüfen: python migrations/run_all.py")

                try:
                    from sqlalchemy import inspect, text
                    from app.models.assessment import (
                        AssessmentAppSetting,
                        AssessmentRole,
                    )

                    inspector = inspect(db.engine)
                    dialect = db.engine.dialect.name
                    existing_tables = set(inspector.get_table_names())

                    if 'ass_users' in existing_tables:
                        user_columns = {col['name'] for col in inspector.get_columns('ass_users')}
                        if 'theme_mode' not in user_columns:
                            _log_startup("[INFO] Ergänze ass_users.theme_mode ...")
                            stmt = "ALTER TABLE ass_users ADD COLUMN theme_mode VARCHAR(16) NOT NULL DEFAULT 'light'"
                            with db.engine.begin() as connection:
                                connection.execute(text(stmt))
                            _log_startup("[OK] ass_users.theme_mode hinzugefügt")

                    default_roles = ['Administrator', 'Bewerter', 'Betrachter', 'Inspektor', 'Verwarner']
                    for role_name in default_roles:
                        role = AssessmentRole.query.filter_by(name=role_name).first()
                        if not role:
                            role = AssessmentRole(name=role_name)
                            db.session.add(role)
                            db.session.flush()

                    assessment_defaults = {
                        'welcome_title': 'Willkommen im Bewertungstool',
                        'welcome_subtitle': 'Bewerten, Ränge prüfen und Verwaltung – alles an einem Ort.',
                        'ranking_active_mode': 'standard',
                        'ranking_sort_mode': 'total',
                    }
                    for key, value in assessment_defaults.items():
                        if not AssessmentAppSetting.query.filter_by(setting_key=key).first():
                            db.session.add(AssessmentAppSetting(setting_key=key, setting_value=value))
                    db.session.commit()

                    if should_run_startup_migrations:
                        from app.blueprints.assessment.migration import run_assessment_migrations
                        run_assessment_migrations()
                except Exception as assessment_error:
                    db.session.rollback()
                    _log_startup(f"[WARNUNG] Assessment-Modul-Migration übersprungen: {assessment_error}")

                if should_run_startup_migrations:
                    try:
                        from app.models.settings import SystemSettings
                        marker_setting = SystemSettings.query.filter_by(
                            key='last_auto_migrated_release'
                        ).first()
                        if not marker_setting:
                            marker_setting = SystemSettings(
                                key='last_auto_migrated_release',
                                value=release_marker,
                                description='Letzter Release-Marker mit erfolgreicher Startup-Auto-Migration'
                            )
                            db.session.add(marker_setting)
                        else:
                            marker_setting.value = release_marker
                            if not marker_setting.description:
                                marker_setting.description = (
                                    'Letzter Release-Marker mit erfolgreicher Startup-Auto-Migration'
                                )
                        db.session.commit()
                    except Exception as marker_err:
                        db.session.rollback()
                        _log_startup(f"[WARNUNG] Release-Marker für Auto-Migration konnte nicht gespeichert werden: {marker_err}")
                
                from app.models.email import EmailFolder
                
                standard_folders = [
                    {'name': 'INBOX', 'display_name': 'Posteingang', 'folder_type': 'standard', 'is_system': True},
                    {'name': 'Sent', 'display_name': 'Gesendet', 'folder_type': 'standard', 'is_system': True},
                    {'name': 'Drafts', 'display_name': 'Entwürfe', 'folder_type': 'standard', 'is_system': True},
                    {'name': 'Trash', 'display_name': 'Papierkorb', 'folder_type': 'standard', 'is_system': True},
                    {'name': 'Spam', 'display_name': 'Spam', 'folder_type': 'standard', 'is_system': True},
                    {'name': 'Archive', 'display_name': 'Archiv', 'folder_type': 'standard', 'is_system': True}
                ]
                
                for folder_data in standard_folders:
                    existing_folder = EmailFolder.query.filter_by(
                        name=folder_data['name'], mailbox_id=None
                    ).first()
                    if not existing_folder:
                        folder = EmailFolder(**folder_data)
                        db.session.add(folder)
                        _log_startup(f"Created standard folder: {folder_data['display_name']}")
                
                db.session.commit()
                _log_startup("[OK] Standard email folders ensured")
                
                from app.models.settings import SystemSettings
                from app.models.chat import Chat
                from app.models.user import User
                from sqlalchemy import inspect, text
                
                if not SystemSettings.query.filter_by(key='module_assessment').first():
                    db.session.add(SystemSettings(
                        key='module_assessment',
                        value='True',
                        description='Modul module_assessment aktiviert'
                    ))
                
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

                if not SystemSettings.query.filter_by(key='default_language').first():
                    db.session.add(SystemSettings(
                        key='default_language',
                        value='de',
                        description='Standardsprache für die Benutzeroberfläche'
                    ))

                if not SystemSettings.query.filter_by(key='email_language').first():
                    db.session.add(SystemSettings(
                        key='email_language',
                        value='de',
                        description='Standardsprache für System-E-Mails'
                    ))

                if not SystemSettings.query.filter_by(key='available_languages').first():
                    db.session.add(SystemSettings(
                        key='available_languages',
                        value='["de","en","pt","es","ru"]',
                        description='Liste der aktivierten Sprachen'
                    ))

                if not SystemSettings.query.filter_by(key='portal_timezone').first():
                    db.session.add(SystemSettings(
                        key='portal_timezone',
                        value='Europe/Berlin',
                        description='Globale Zeitzone für Datums- und Zeitangaben'
                    ))
                
                language_settings = {
                    'default_language': (
                        'de',
                        'Standardsprache der Benutzeroberfläche für neue Benutzer.'
                    ),
                    'email_language': (
                        'de',
                        'Sprache für automatisch versendete System-E-Mails.'
                    ),
                    'available_languages': (
                        json.dumps(['de', 'en', 'pt', 'es', 'ru']),
                        'Aktivierte Sprachen im Portal (JSON-Liste).'
                    )
                }
                
                for key, (value, description) in language_settings.items():
                    setting = SystemSettings.query.filter_by(key=key).first()
                    if not setting:
                        db.session.add(SystemSettings(key=key, value=value, description=description))
                    else:
                        if not setting.value:
                            setting.value = value
                        if description and not setting.description:
                            setting.description = description

                from app.utils.bot_protection import ensure_default_settings
                ensure_default_settings()
                from app.utils.search_indexing import ensure_default_settings as ensure_indexing_settings
                ensure_indexing_settings()
                
                try:
                    inspector = inspect(db.engine)
                    if 'users' in inspector.get_table_names():
                        columns = {col['name'] for col in inspector.get_columns('users')}
                        if 'language' in columns:
                            with db.engine.begin() as connection:
                                connection.execute(
                                    text("""
                                        UPDATE users
                                        SET language = :default_lang
                                        WHERE language IS NULL OR TRIM(language) = ''
                                    """),
                                    {'default_lang': 'de'}
                                )
                except Exception as e:
                    app.logger.warning("Konnte Benutzersprachen nicht aktualisieren: %s", e)

                main_chat = Chat.query.filter_by(is_main_chat=True).first()
                if not main_chat:
                    main_chat = Chat(
                        name='Team Chat',
                        is_main_chat=True,
                        is_direct_message=False
                    )
                    db.session.add(main_chat)
                    db.session.flush()
                    
                    from app.models.chat import ChatMember
                    # Prüfe ob has_full_access Spalte existiert
                    try:
                        from sqlalchemy import inspect
                        inspector = inspect(db.engine)
                        if 'users' in inspector.get_table_names():
                            columns = {col['name'] for col in inspector.get_columns('users')}
                            if 'has_full_access' in columns:
                                from app.utils.access_control import has_module_access
                                active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                                for user in active_users:
                                    if has_module_access(user, 'module_chat'):
                                        member = ChatMember(
                                            chat_id=main_chat.id,
                                            user_id=user.id
                                        )
                                        db.session.add(member)
                            else:
                                # Spalte existiert noch nicht - füge alle aktiven Benutzer hinzu (Rückwärtskompatibilität)
                                active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                                for user in active_users:
                                    member = ChatMember(
                                        chat_id=main_chat.id,
                                        user_id=user.id
                                    )
                                    db.session.add(member)
                    except Exception as e:
                        _log_startup(f"WARNING: Could not check has_full_access column: {e}")
                        # Fallback: Füge alle aktiven Benutzer hinzu
                        from app.models.chat import ChatMember
                        active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                        for user in active_users:
                            member = ChatMember(
                                chat_id=main_chat.id,
                                user_id=user.id
                            )
                            db.session.add(member)
                else:
                    from app.models.chat import ChatMember
                    try:
                        # Prüfe ob has_full_access Spalte existiert
                        from sqlalchemy import inspect
                        inspector = inspect(db.engine)
                        if 'users' in inspector.get_table_names():
                            columns = {col['name'] for col in inspector.get_columns('users')}
                            if 'has_full_access' in columns:
                                from app.utils.access_control import has_module_access
                                active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                                existing_members = ChatMember.query.filter_by(chat_id=main_chat.id).all()
                                existing_user_ids = [member.user_id for member in existing_members]
                                
                                for user in active_users:
                                    if user.id not in existing_user_ids and has_module_access(user, 'module_chat'):
                                        member = ChatMember(
                                            chat_id=main_chat.id,
                                            user_id=user.id
                                        )
                                        db.session.add(member)
                            else:
                                # Spalte existiert noch nicht - füge alle aktiven Benutzer hinzu (Rückwärtskompatibilität)
                                active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                                existing_members = ChatMember.query.filter_by(chat_id=main_chat.id).all()
                                existing_user_ids = [member.user_id for member in existing_members]
                                
                                for user in active_users:
                                    if user.id not in existing_user_ids:
                                        member = ChatMember(
                                            chat_id=main_chat.id,
                                            user_id=user.id
                                        )
                                        db.session.add(member)
                        else:
                            # Fallback: Füge alle aktiven Benutzer hinzu
                            active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                            existing_members = ChatMember.query.filter_by(chat_id=main_chat.id).all()
                            existing_user_ids = [member.user_id for member in existing_members]
                            
                            for user in active_users:
                                if user.id not in existing_user_ids:
                                    member = ChatMember(
                                        chat_id=main_chat.id,
                                        user_id=user.id
                                    )
                                    db.session.add(member)
                    except Exception as e:
                        _log_startup(f"WARNING: Could not update main chat members: {e}")

                try:
                    from app.models.settings import SystemSettings as _Sys
                    if not _Sys.query.filter_by(key='calendar_personal_enabled').first():
                        multi = _Sys.query.filter_by(key='calendar_multi_enabled').first()
                        val = 'True' if multi and str(multi.value).lower() == 'true' else 'False'
                        db.session.add(_Sys(key='calendar_personal_enabled', value=val, description='Private Kalender aktiv'))
                    if not _Sys.query.filter_by(key='calendar_team_enabled').first():
                        db.session.add(_Sys(key='calendar_team_enabled', value='False', description='Team-Kalender aktiv'))
                except Exception as e:
                    _log_startup(f"WARNING: Kalender-Settings konnten nicht migriert werden: {e}")

                try:
                    inspector = inspect(db.engine)
                    chat_cols = {c['name'] for c in inspector.get_columns('chats')} if 'chats' in inspector.get_table_names() else set()
                    if 'team_id' in chat_cols:
                        from app.utils.team_chat import ensure_all_team_chats
                        ensure_all_team_chats()
                except Exception as e:
                    _log_startup(f"WARNING: Team-Chats konnten nicht angelegt werden: {e}")

                try:
                    inspector = inspect(db.engine)
                    cal_cols = {c['name'] for c in inspector.get_columns('calendars')} if 'calendars' in inspector.get_table_names() else set()
                    if 'is_default' in cal_cols:
                        from app.utils.multi_calendars import backfill_space_calendars
                        from app.models.calendar import Calendar as _Cal
                        first_public = _Cal.query.filter_by(calendar_type='public').order_by(_Cal.id.asc()).first()
                        if first_public and not first_public.is_default:
                            first_public.is_default = True
                        backfill_space_calendars()
                except Exception as e:
                    _log_startup(f"WARNING: Kalender-Backfill fehlgeschlagen: {e}")
                
                db.session.commit()
                
            except Exception as e:
                _log_startup(f"[WARNUNG] Warnung beim Erstellen der Datenbank-Tabellen: {e}")

        try:
            from app.utils.file_storage_limits import sync_flask_max_content_length
            synced = sync_flask_max_content_length(app)
            _log_startup(f"[INFO] MAX_CONTENT_LENGTH aus Datei-Einstellungen: {synced} Bytes")
        except Exception as sync_err:
            _log_startup(f"[WARNUNG] MAX_CONTENT_LENGTH-Sync fehlgeschlagen: {sync_err}")
    
    # Background-Jobs nur im Hauptprozess starten
    if is_main_process and not os.getenv('PRISMATEAMS_SKIP_BACKGROUND_JOBS'):
        start_email_sync(app)
        
        from app.tasks.notification_scheduler import start_notification_scheduler
        start_notification_scheduler(app)

        from app.tasks.calendar_sync_scheduler import start_calendar_sync_scheduler
        start_calendar_sync_scheduler(app)

        from app.tasks.media_downloader_cleanup import start_media_downloader_cleanup
        start_media_downloader_cleanup(app)

        from app.tasks.file_converter_cleanup import start_file_converter_cleanup
        start_file_converter_cleanup(app)
    
    return app



