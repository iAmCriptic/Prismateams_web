"""Socket.IO, Redis, limiter, and sessions."""


import logging

from app import limiter, socketio
from app.factory._util import resolve_socketio_cors_origins as _resolve_socketio_cors_origins


def _probe_redis(redis_url, *, timeout=2):
    """Ping Redis. Returns (ok: bool, error: str|None)."""
    try:
        import redis
    except ImportError:
        return False, 'redis package missing'
    try:
        client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )
        if client.ping():
            return True, None
        return False, 'ping failed'
    except Exception as exc:
        return False, str(exc)


def _resolve_redis(app, config_name, logger):
    """
    Resolve Redis for SocketIO / Limiter / Sessions.

    Modes:
    - REDIS_ENABLED=True: require Redis (status connected|unavailable)
    - REDIS_AUTO_DETECT=True and REDIS_ENABLED=False: optional probe
    - else: intentional single-worker (no probe, no scary warnings in Dev)
    """
    want_enabled = bool(app.config.get('REDIS_ENABLED', False))
    auto_detect = bool(app.config.get('REDIS_AUTO_DETECT', False))
    redis_url = app.config.get('REDIS_URL', 'redis://localhost:6379/0')
    production_like = config_name in ('production', 'staging')

    status = 'disabled'
    detail = None
    enabled = False

    if want_enabled:
        ok, err = _probe_redis(redis_url, timeout=2)
        if ok:
            enabled = True
            status = 'connected'
            logger.info('Redis aktiviert: %s', redis_url)
        else:
            status = 'unavailable'
            detail = err
            logger.error(
                'REDIS_ENABLED=True, aber Redis nicht erreichbar (%s): %s',
                redis_url,
                err,
            )
            if production_like:
                logger.error(
                    'Multi-Worker / SocketIO-Queue / shared Rate-Limit brauchen ein laufendes Redis.'
                )
    elif auto_detect:
        ok, err = _probe_redis(redis_url, timeout=1)
        if ok:
            enabled = True
            status = 'connected'
            logger.info('Redis per AUTO_DETECT aktiviert: %s', redis_url)
        else:
            status = 'disabled'
            detail = err
            logger.info(
                'Redis AUTO_DETECT: nicht erreichbar (%s) — Single-Worker ohne Message Queue',
                err,
            )
    else:
        status = 'disabled'
        if production_like:
            logger.warning(
                'Redis absichtlich aus (REDIS_ENABLED=False). '
                'Multi-Worker-Setups brauchen REDIS_ENABLED=True und ein laufendes Redis.'
            )
        else:
            logger.info(
                'Redis aus (REDIS_ENABLED=False) — Single-Worker-Modus. '
                'Für Multi-Worker: Redis starten und REDIS_ENABLED=True setzen.'
            )

    app.config['REDIS_ENABLED'] = enabled
    app.config['REDIS_RUNTIME_STATUS'] = status
    app.config['REDIS_RUNTIME_DETAIL'] = detail
    app.config['REDIS_RUNTIME_URL'] = redis_url
    return enabled, redis_url, status


def init_realtime(app, config_name):
    """Redis, rate limiter, Socket.IO, server sessions."""
    logger = logging.getLogger(__name__)

    redis_enabled, redis_url, _redis_status = _resolve_redis(app, config_name, logger)

    # Flask-Limiter für Rate Limiting initialisieren
    # Flask-Limiter 4+: storage_uri nur ueber app.config['RATELIMIT_STORAGE_URI']
    # (init_app(app) akzeptiert keinen storage_uri-Kwarg mehr).
    rate_limit_uri = app.config.get('RATELIMIT_STORAGE_URI') or (redis_url if redis_enabled else None)
    allow_memory = bool(app.config.get('RATELIMIT_ALLOW_MEMORY'))
    production_like = config_name in ('production', 'staging')

    if rate_limit_uri:
        app.config['RATELIMIT_STORAGE_URI'] = rate_limit_uri
        try:
            limiter.init_app(app)
            logger.info('Flask-Limiter Storage: %s', rate_limit_uri)
        except Exception as e:
            if production_like and not allow_memory:
                logger.error(
                    'Flask-Limiter Redis-Storage fehlgeschlagen in %s: %s',
                    config_name,
                    e,
                )
                raise RuntimeError(
                    'Flask-Limiter benötigt in Production/Staging ein erreichbares Redis '
                    '(REDIS_ENABLED=True / RATELIMIT_STORAGE_URI). '
                    'Notfall: RATELIMIT_ALLOW_MEMORY=true'
                ) from e
            logger.warning('Fehler beim Konfigurieren von Flask-Limiter mit Redis: %s', e)
            logger.warning('Verwende Memory-Storage als Fallback (nicht für Production empfohlen)')
            app.config['RATELIMIT_STORAGE_URI'] = 'memory://'
            limiter.init_app(app)
    else:
        if production_like and not allow_memory:
            logger.error(
                'Flask-Limiter: kein Redis/RATELIMIT_STORAGE_URI in %s — Fail-closed',
                config_name,
            )
            raise RuntimeError(
                'Flask-Limiter benötigt in Production/Staging Redis '
                '(REDIS_ENABLED=True und REDIS_URL, oder RATELIMIT_STORAGE_URI). '
                'Notfall: RATELIMIT_ALLOW_MEMORY=true'
            )
        if production_like:
            logger.warning('Flask-Limiter Memory-Storage in Production (RATELIMIT_ALLOW_MEMORY=true)')
        else:
            logger.info('Flask-Limiter: Memory-Storage (Dev). Für Multi-Worker: REDIS_ENABLED=True')
        app.config['RATELIMIT_STORAGE_URI'] = 'memory://'
        limiter.init_app(app)

    socketio_cors = _resolve_socketio_cors_origins(app)
    if socketio_cors == '*':
        logger.warning("Socket.IO CORS: '*' (SOCKETIO_CORS_ORIGINS=*) — nur bewusst einsetzen")
    elif socketio_cors is None:
        logger.info('Socket.IO CORS: same-origin (Host/X-Forwarded-*)')
    else:
        logger.info('Socket.IO CORS Origins: %s', ', '.join(socketio_cors))

    socketio_base = {
        'cors_allowed_origins': socketio_cors,
        'logger': False,
        'engineio_logger': False,
        'ping_timeout': 60,
        'ping_interval': 25,
        'cookie': False,
        'allow_upgrades': True,
        'transports': ['websocket', 'polling'],
        'max_http_buffer_size': 1e6,
        'manage_session': False,
    }

    if redis_enabled:
        try:
            init_kwargs = dict(socketio_base)
            init_kwargs.update({
                'message_queue': redis_url,
                'async_mode': 'threading',
            })
            socketio.init_app(app, **init_kwargs)
            logger.info(
                'SocketIO mit Redis Message Queue konfiguriert: %s (async_mode=threading)',
                redis_url,
            )
        except Exception as e:
            logger.error('Redis-Fehler, verwende SocketIO ohne Message Queue: %s', e, exc_info=True)
            app.config['REDIS_ENABLED'] = False
            app.config['REDIS_RUNTIME_STATUS'] = 'unavailable'
            app.config['REDIS_RUNTIME_DETAIL'] = str(e)
            socketio.init_app(app, **socketio_base)
    else:
        socketio.init_app(app, **socketio_base)

    # P18: Server-seitige Sessions (Cookie = nur Session-ID)
    try:
        from app.utils.server_session import configure_server_sessions
        backend = configure_server_sessions(app)
        app.config['SESSION_BACKEND'] = backend
    except Exception as sess_exc:
        logging.getLogger(__name__).warning('Server-Sessions Setup fehlgeschlagen: %s', sess_exc)

    # Default-Namespace: nur eingeloggte Nutzer; Dashboard-Room an Session binden.
    # Öffentliche Live-Updates (Musik-Wishlist) laufen über SSE (/sse/events/music).
    # Namespace /public für explizit anonyme Realtime-Clients (keine geschützten Rooms).
    from flask_login import current_user
    from flask_socketio import join_room, leave_room

    @socketio.on('connect')
    def handle_connect(auth=None):
        """Default-Namespace: Login erforderlich; Room dashboard_user_<id>."""
        try:
            if not getattr(current_user, 'is_authenticated', False):
                logger.debug('Socket.IO connect abgelehnt: nicht authentifiziert')
                return False
            if not getattr(current_user, 'is_active', True):
                return False
            uid = getattr(current_user, 'id', None)
            if not uid:
                return False
            join_room(f'dashboard_user_{uid}')
            return True
        except Exception as e:
            logger.warning('Socket.IO connect Fehler (abgelehnt): %s', e)
            return False

    @socketio.on('disconnect')
    def handle_disconnect():
        try:
            uid = (
                getattr(current_user, 'id', None)
                if getattr(current_user, 'is_authenticated', False)
                else None
            )
            if uid:
                leave_room(f'dashboard_user_{uid}')
        except Exception:
            pass
        logger.debug('Socket.IO: Client getrennt')

    @socketio.on('connect', namespace='/public')
    def handle_public_connect(auth=None):
        """Öffentlicher Namespace — kein Portal-Login, keine geschützten Rooms."""
        return True

    @socketio.on('disconnect', namespace='/public')
    def handle_public_disconnect():
        logger.debug('Socket.IO /public: Client getrennt')
