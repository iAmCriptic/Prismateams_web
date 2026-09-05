"""Mount WsgiDAV under /webdav on the Flask WSGI stack."""

from __future__ import annotations

import logging

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wsgi import ClosingIterator

from app.utils.webdav import flags as webdav_flags

logger = logging.getLogger(__name__)


def create_webdav_wsgi_app(flask_app):
    """Build a WSGI app that serves WebDAV with Flask app context."""
    from wsgidav.wsgidav_app import WsgiDAVApp

    from app.utils.webdav.auth import PrismaDomainController
    from app.utils.webdav.provider import PrismaFilesProvider

    config = {
        'provider_mapping': {
            '/': PrismaFilesProvider(),
        },
        'http_authenticator': {
            'domain_controller': PrismaDomainController,
            'accept_basic': True,
            'accept_digest': False,
            'default_to_digest': False,
        },
        'dir_browser': {
            'enable': True,
            'response_trailer': False,
            'davmount': False,
            'ms_support': True,
        },
        'verbose': 1,
        'property_manager': True,
        'lock_storage': True,
        'prisma_flask_app': flask_app,
        'hotfixes': {
            're_encode_path_info': True,
        },
    }

    dav_app = WsgiDAVApp(config)

    def application(environ, start_response):
        # DispatcherMiddleware may leave PATH_INFO empty for exact /webdav
        if not environ.get('PATH_INFO'):
            environ['PATH_INFO'] = '/'

        # Keep app context alive for the whole response iterator.
        # WsgiDAV does DB work while yielding — a plain `with app_context()`
        # would exit before get_resource_inst() runs.
        ctx = flask_app.app_context()
        ctx.push()
        try:
            try:
                enabled = webdav_flags.is_webdav_enabled()
            except Exception:
                logger.exception('WebDAV flag check failed')
                enabled = False

            if not enabled:
                start_response(
                    '404 Not Found',
                    [('Content-Type', 'text/plain; charset=utf-8')],
                )
                ctx.pop()
                return [b'WebDAV is disabled']

            result = dav_app(environ, start_response)
            return ClosingIterator(result, ctx.pop)
        except Exception:
            ctx.pop()
            raise

    return application


def mount_webdav(flask_app):
    """Attach /webdav to the Flask application via DispatcherMiddleware."""
    try:
        dav = create_webdav_wsgi_app(flask_app)
    except Exception as exc:
        logger.exception('Failed to initialize WebDAV: %s', exc)
        return flask_app

    flask_app.wsgi_app = DispatcherMiddleware(
        flask_app.wsgi_app,
        {
            '/webdav': dav,
        },
    )
    logger.info('WebDAV mounted at /webdav')
    return flask_app
