"""Socket.IO, Redis, limiter, and sessions."""


import logging

from app import limiter, socketio
from app.factory._util import resolve_socketio_cors_origins as _resolve_socketio_cors_origins

def init_realtime(app, config_name):
    """Redis, rate limiter, Socket.IO, server sessions."""
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
    allow_memory = bool(app.config.get('RATELIMIT_ALLOW_MEMORY'))
    production_like = config_name in ('production', 'staging')

    if rate_limit_uri:
        try:
            limiter.init_app(app, storage_uri=rate_limit_uri)
            logger.info(f"Flask-Limiter Storage: {rate_limit_uri}")
        except Exception as e:
            if production_like and not allow_memory:
                logger.error(
                    "Flask-Limiter Redis-Storage fehlgeschlagen in %s: %s",
                    config_name,
                    e,
                )
                raise RuntimeError(
                    'Flask-Limiter benötigt in Production/Staging ein erreichbares Redis '
                    '(REDIS_ENABLED=True / RATELIMIT_STORAGE_URI). '
                    'Notfall: RATELIMIT_ALLOW_MEMORY=true'
                ) from e
            logger.warning(f"Fehler beim Konfigurieren von Flask-Limiter mit Redis: {e}")
            logger.warning("Verwende Memory-Storage als Fallback (nicht für Production empfohlen)")
            limiter.init_app(app)
    else:
        if production_like and not allow_memory:
            logger.error(
                "Flask-Limiter: kein Redis/RATELIMIT_STORAGE_URI in %s — Fail-closed",
                config_name,
            )
            raise RuntimeError(
                'Flask-Limiter benötigt in Production/Staging Redis '
                '(REDIS_ENABLED=True und REDIS_URL, oder RATELIMIT_STORAGE_URI). '
                'Notfall: RATELIMIT_ALLOW_MEMORY=true'
            )
        if production_like:
            logger.warning("⚠️  Flask-Limiter Memory-Storage in Production (RATELIMIT_ALLOW_MEMORY=true)")
        else:
            logger.info("Flask-Limiter: Memory-Storage (Dev). Für Multi-Worker: REDIS_ENABLED=True")
        limiter.init_app(app)

    socketio_cors = _resolve_socketio_cors_origins(app)
    if socketio_cors == '*':
        logger.warning("Socket.IO CORS: '*' (SOCKETIO_CORS_ORIGINS=*) — nur bewusst einsetzen")
    elif socketio_cors is None:
        logger.info("Socket.IO CORS: same-origin (Host/X-Forwarded-*)")
    else:
        logger.info("Socket.IO CORS Origins: %s", ", ".join(socketio_cors))
    
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
                'cors_allowed_origins': socketio_cors,
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
                cors_allowed_origins=socketio_cors,
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
            cors_allowed_origins=socketio_cors,
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

    # P18: Server-seitige Sessions (Cookie = nur Session-ID)
    try:
        from app.utils.server_session import configure_server_sessions
        configure_server_sessions(app)
    except Exception as sess_exc:
        logging.getLogger(__name__).warning('Server-Sessions Setup fehlgeschlagen: %s', sess_exc)
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
