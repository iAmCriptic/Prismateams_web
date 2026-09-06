"""
Server-seitige Sessions (P18): Cookie trägt nur die Session-ID.

- Redis, wenn REDIS_ENABLED / Redis erreichbar
- sonst Dateisystem unter instance/flask_sessions
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any, Optional

from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict

logger = logging.getLogger(__name__)

SESSION_KEY_PREFIX = 'pt:sess:'
DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # 30 Tage


class ServerSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None, new=False):
        def on_update(self_dict):
            self_dict.modified = True

        CallbackDict.__init__(self, initial, on_update)
        self.sid = sid
        self.new = new
        self.modified = False
        self.accessed = False
        self._sid_to_delete = None


def _new_session_sid() -> str:
    return secrets.token_urlsafe(32)


def regenerate_server_session_id(sess=None) -> bool:
    """
    Rotate the cookie session id (session-fixation protection).

    Deletes the previous server-side store on the next save_session.
    No-op for non-ServerSession backends (e.g. tests with signed cookies).
    """
    from flask import session as flask_session

    target = sess if sess is not None else flask_session
    if not isinstance(target, ServerSession):
        return False

    old_sid = getattr(target, 'sid', None)
    new_sid = _new_session_sid()
    while new_sid == old_sid:
        new_sid = _new_session_sid()

    target.sid = new_sid
    if old_sid:
        target._sid_to_delete = old_sid
    target.new = True
    target.modified = True
    return True


class RedisSessionInterface(SessionInterface):
    def __init__(self, redis_client, key_prefix=SESSION_KEY_PREFIX, ttl=DEFAULT_TTL_SECONDS):
        self.redis = redis_client
        self.key_prefix = key_prefix
        self.ttl = int(ttl)

    def _key(self, sid: str) -> str:
        return f'{self.key_prefix}{sid}'

    def open_session(self, app, request):
        sid = request.cookies.get(self.get_cookie_name(app))
        if not sid:
            return ServerSession(sid=_new_session_sid(), new=True)
        try:
            raw = self.redis.get(self._key(sid))
            if raw:
                data = json.loads(raw)
                return ServerSession(initial=data, sid=sid, new=False)
        except Exception as exc:
            logger.warning('Redis session read failed: %s', exc)
        return ServerSession(sid=_new_session_sid(), new=True)

    def save_session(self, app, session, response):
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)

        old_sid = getattr(session, '_sid_to_delete', None)
        if old_sid:
            try:
                self.redis.delete(self._key(old_sid))
            except Exception:
                pass
            try:
                session._sid_to_delete = None
            except Exception:
                pass

        if not session:
            if session.modified:
                try:
                    self.redis.delete(self._key(session.sid))
                except Exception:
                    pass
                response.delete_cookie(
                    self.get_cookie_name(app),
                    domain=domain,
                    path=path,
                )
            return

        if not (session.modified or session.new or self.should_set_cookie(app, session)):
            return

        httponly = self.get_cookie_httponly(app)
        secure = self.get_cookie_secure(app)
        samesite = self.get_cookie_samesite(app)
        expires = self.get_expiration_time(app, session)
        ttl = self.ttl
        if expires is not None:
            try:
                ttl = max(60, int(expires.timestamp() - time.time()))
            except Exception:
                pass
        try:
            self.redis.setex(
                self._key(session.sid),
                ttl,
                json.dumps(dict(session), default=str),
            )
        except Exception as exc:
            logger.warning('Redis session write failed: %s', exc)
            return

        response.set_cookie(
            self.get_cookie_name(app),
            session.sid,
            expires=expires,
            httponly=httponly,
            domain=domain,
            path=path,
            secure=secure,
            samesite=samesite,
        )


class FilesystemSessionInterface(SessionInterface):
    def __init__(self, directory: str, ttl=DEFAULT_TTL_SECONDS):
        self.directory = directory
        self.ttl = int(ttl)
        os.makedirs(directory, exist_ok=True)

    def _path(self, sid: str) -> str:
        safe = ''.join(c for c in sid if c.isalnum() or c in '-_')
        return os.path.join(self.directory, f'{safe}.sess')

    def open_session(self, app, request):
        sid = request.cookies.get(self.get_cookie_name(app))
        if not sid:
            return ServerSession(sid=_new_session_sid(), new=True)
        path = self._path(sid)
        try:
            if os.path.isfile(path):
                age = time.time() - os.path.getmtime(path)
                if age <= self.ttl:
                    with open(path, 'r', encoding='utf-8') as fh:
                        data = json.load(fh)
                    return ServerSession(initial=data, sid=sid, new=False)
                try:
                    os.remove(path)
                except OSError:
                    pass
        except Exception as exc:
            logger.warning('Filesystem session read failed: %s', exc)
        return ServerSession(sid=_new_session_sid(), new=True)

    def save_session(self, app, session, response):
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)

        old_sid = getattr(session, '_sid_to_delete', None)
        if old_sid:
            try:
                os.remove(self._path(old_sid))
            except OSError:
                pass
            try:
                session._sid_to_delete = None
            except Exception:
                pass

        if not session:
            if session.modified:
                try:
                    os.remove(self._path(session.sid))
                except OSError:
                    pass
                response.delete_cookie(
                    self.get_cookie_name(app),
                    domain=domain,
                    path=path,
                )
            return

        if not (session.modified or session.new or self.should_set_cookie(app, session)):
            return

        try:
            with open(self._path(session.sid), 'w', encoding='utf-8') as fh:
                json.dump(dict(session), fh, default=str)
        except Exception as exc:
            logger.warning('Filesystem session write failed: %s', exc)
            return

        response.set_cookie(
            self.get_cookie_name(app),
            session.sid,
            expires=self.get_expiration_time(app, session),
            httponly=self.get_cookie_httponly(app),
            domain=domain,
            path=path,
            secure=self.get_cookie_secure(app),
            samesite=self.get_cookie_samesite(app),
        )


def configure_server_sessions(app) -> str:
    """
    Aktiviert server-seitige Sessions. Returns backend label.
    """
    ttl = int(app.config.get('PERMANENT_SESSION_LIFETIME').total_seconds()) if app.config.get('PERMANENT_SESSION_LIFETIME') else DEFAULT_TTL_SECONDS
    redis_enabled = bool(app.config.get('REDIS_ENABLED'))
    redis_url = app.config.get('REDIS_URL', 'redis://localhost:6379/0')

    if not redis_enabled:
        try:
            import redis
            client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
            if client.ping():
                redis_enabled = True
        except Exception:
            redis_enabled = False

    if redis_enabled:
        try:
            import redis
            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            app.session_interface = RedisSessionInterface(client, ttl=ttl)
            logger.info('Server-Sessions: Redis (%s)', redis_url)
            return 'redis'
        except Exception as exc:
            logger.warning('Redis-Sessions nicht verfügbar (%s) — Filesystem-Fallback', exc)

    sess_dir = os.path.join(app.instance_path, 'flask_sessions')
    app.session_interface = FilesystemSessionInterface(sess_dir, ttl=ttl)
    logger.info('Server-Sessions: Filesystem (%s)', sess_dir)
    return 'filesystem'


def prune_bulky_session_keys(session_obj, *, max_share_passwords: int = 20, max_auth_flags: int = 40) -> None:
    """Begrenzt bekannte Session-Keys, die Cookies/Server-Payloads aufblähen."""
    try:
        pw_map = session_obj.get('kanban_share_passwords')
        if isinstance(pw_map, dict) and len(pw_map) > max_share_passwords:
            # Behalte die zuletzt eingefügten Keys (insertion order in Py3.7+)
            keys = list(pw_map.keys())[-max_share_passwords:]
            session_obj['kanban_share_passwords'] = {k: pw_map[k] for k in keys}
            session_obj.modified = True

        auth_keys = [k for k in list(session_obj.keys()) if isinstance(k, str) and (
            k.startswith('share_auth_') or k.startswith('dropbox_auth_') or k.startswith('share_bot_')
        )]
        if len(auth_keys) > max_auth_flags:
            for key in auth_keys[:-max_auth_flags]:
                session_obj.pop(key, None)
            session_obj.modified = True

        cart = session_obj.get('borrow_cart')
        if isinstance(cart, list) and len(cart) > 100:
            session_obj['borrow_cart'] = cart[-100:]
            session_obj.modified = True
    except Exception:
        pass
