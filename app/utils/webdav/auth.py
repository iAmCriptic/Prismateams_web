"""HTTP Basic Auth for WebDAV via scoped app passwords (not login password / 2FA).

Clients (Explorer, macOS, DAV-Apps) unterstützen kein TOTP über Basic Auth.
Login: App-Benutzername (vorname+nachname.id, z. B. enricomatzke.12) + App-Passwort.
Fallback: Portal-E-Mail + App-Passwort (ältere Clients / Hinweistexte).
Residualrisiko: Feature-Flag, module_files, Guest-Sperre, Account-Lockout 5/15min.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from wsgidav.dc.base_dc import BaseDomainController

from app.utils.log_privacy import mask_email

from app import db
from app.models.app_password import AppPassword
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


def _resolve_user_and_app_password(login: str, password: str):
    """
    Resolve WebDAV credentials.
    1) App-Username + matching app password
    2) E-Mail + any of the user's app passwords
    Returns (user, app_password) or (None, None).
    """
    # Preferred: dedicated app username (enricomatzke.12)
    user, app_pw = AppPassword.verify_login(login, password)
    if user and app_pw:
        return user, app_pw

    # Fallback: portal email + app password
    if '@' in login:
        user = User.query.filter(db.func.lower(User.email) == login).first()
        if user:
            app_pw = AppPassword.verify_for_user(user.id, password)
            if app_pw:
                return user, app_pw
    return None, None


class PrismaDomainController(BaseDomainController):
    """Authenticate WebDAV with app username/password (no login password / TOTP)."""

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

            login = _normalize_webdav_username(user_name)
            if not login or not password:
                logger.warning('WebDAV auth rejected: empty user/password (raw=%r)', user_name)
                return False

            # Soft lockout: if login looks like email, check that account first
            lock_user = None
            if '@' in login:
                lock_user = User.query.filter(db.func.lower(User.email) == login).first()
            else:
                app_row = AppPassword.find_by_login(login)
                if app_row:
                    lock_user = app_row.user or User.query.get(app_row.user_id)

            if lock_user and lock_user.failed_login_until and datetime.utcnow() < lock_user.failed_login_until:
                logger.warning('WebDAV auth rejected: account locked user_id=%s', lock_user.id)
                return False

            user, app_pw = _resolve_user_and_app_password(login, password)
            if not user or not app_pw:
                if lock_user:
                    lock_user.failed_login_attempts = (lock_user.failed_login_attempts or 0) + 1
                    if lock_user.failed_login_attempts >= 5:
                        lock_user.failed_login_until = datetime.utcnow() + timedelta(minutes=15)
                        lock_user.failed_login_attempts = 0
                    db.session.commit()
                logger.warning(
                    'WebDAV auth rejected: bad credentials login=%r raw=%r',
                    mask_email(login) if '@' in login else login,
                    mask_email(user_name) if '@' in str(user_name or '') else user_name,
                )
                return False

            if getattr(user, 'is_guest', False):
                logger.warning('WebDAV auth rejected: guest user_id=%s', user.id)
                return False

            if not user.is_active:
                logger.warning('WebDAV auth rejected: inactive user_id=%s', user.id)
                return False

            user.failed_login_attempts = 0
            user.failed_login_until = None
            db.session.commit()

            if not has_module_access(user, 'module_files'):
                logger.warning('WebDAV auth rejected: no module_files access user_id=%s', user.id)
                return False

            environ['wsgidav.auth.user_name'] = app_pw.username or user.email
            environ['wsgidav.auth.roles'] = ('admin',) if user.is_admin else ('editor',)
            environ['wsgidav.auth.permissions'] = (
                'browse_dir',
                'delete_resource',
                'edit_resource',
            )
            environ['prisma.user_id'] = user.id
            environ['prisma.app_password_id'] = app_pw.id
            logger.info(
                'WebDAV auth ok user_id=%s email=%s app_password_id=%s username=%s',
                user.id,
                mask_email(user.email),
                app_pw.id,
                app_pw.username,
            )
            return True
