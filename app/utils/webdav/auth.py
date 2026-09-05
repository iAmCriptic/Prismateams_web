"""HTTP Basic Auth for WebDAV (login password; 2FA intentionally skipped)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from wsgidav.dc.base_dc import BaseDomainController

from app import db
from app.models.user import User
from app.utils.access_control import has_module_access
from app.utils.common import is_module_enabled
from app.utils.webdav.flags import is_webdav_enabled

logger = logging.getLogger(__name__)


def _normalize_webdav_username(user_name: str) -> str:
    """Strip Windows domain prefixes like MicrosoftAccount\\email@x.de."""
    raw = (user_name or '').strip()
    if not raw:
        return ''
    # DOMAIN\user or MicrosoftAccount\user
    if '\\' in raw:
        raw = raw.rsplit('\\', 1)[-1]
    # Rare: /user form
    if '/' in raw and '@' in raw:
        raw = raw.rsplit('/', 1)[-1]
    return raw.strip().lower()


class PrismaDomainController(BaseDomainController):
    """Authenticate WebDAV users with email + password (no TOTP)."""

    def get_domain_realm(self, path_info, environ):
        return 'Prismateams Files'

    def require_authentication(self, realm, environ):
        return True

    def supports_http_digest_auth(self):
        return False

    def basic_auth_user(self, realm, user_name, password, environ):
        flask_app = self.config.get('prisma_flask_app')
        if flask_app is None:
            return False

        with flask_app.app_context():
            if not is_webdav_enabled():
                logger.warning('WebDAV auth rejected: feature disabled')
                return False
            if not is_module_enabled('module_files'):
                logger.warning('WebDAV auth rejected: module_files disabled')
                return False

            email = _normalize_webdav_username(user_name)
            if not email or not password:
                logger.warning('WebDAV auth rejected: empty user/password (raw=%r)', user_name)
                return False

            user = User.query.filter(db.func.lower(User.email) == email).first()
            if not user:
                logger.warning('WebDAV auth rejected: unknown user %r (raw=%r)', email, user_name)
                return False

            if user.failed_login_until and datetime.utcnow() < user.failed_login_until:
                logger.warning('WebDAV auth rejected: account locked user_id=%s', user.id)
                return False

            if getattr(user, 'is_guest', False):
                logger.warning('WebDAV auth rejected: guest user_id=%s', user.id)
                return False

            if not user.is_active:
                logger.warning('WebDAV auth rejected: inactive user_id=%s', user.id)
                return False

            if not user.check_password(password):
                user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
                if user.failed_login_attempts >= 5:
                    user.failed_login_until = datetime.utcnow() + timedelta(minutes=15)
                    user.failed_login_attempts = 0
                db.session.commit()
                logger.warning('WebDAV auth rejected: bad password user_id=%s', user.id)
                return False

            user.failed_login_attempts = 0
            user.failed_login_until = None
            db.session.commit()

            if not has_module_access(user, 'module_files'):
                logger.warning('WebDAV auth rejected: no module_files access user_id=%s', user.id)
                return False

            environ['wsgidav.auth.user_name'] = user.email
            environ['wsgidav.auth.roles'] = ('admin',) if user.is_admin else ('editor',)
            environ['wsgidav.auth.permissions'] = (
                'browse_dir',
                'delete_resource',
                'edit_resource',
            )
            environ['prisma.user_id'] = user.id
            logger.info('WebDAV auth ok user_id=%s email=%s', user.id, user.email)
            return True
