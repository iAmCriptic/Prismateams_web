"""Helpers for HyCanvas integration: presets, SSO/avatar sync, REST client & snapshots."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import threading
import time
import uuid
from typing import Any

import jwt
import requests
from flask import current_app, g, has_app_context, has_request_context, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from requests.adapters import HTTPAdapter
from sqlalchemy import create_engine, text
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

AVATAR_TOKEN_SALT = 'canvas-avatar-token'
AVATAR_TOKEN_MAX_AGE = 365 * 86400
HYCANVAS_FULL_SYNC_TTL_SECONDS = 300
_HYCANVAS_SYNC_LOCK = threading.Lock()
_HYCANVAS_HTTP_ADAPTER = HTTPAdapter(pool_connections=10, pool_maxsize=20)
_HYCANVAS_SHARED_SESSION: requests.Session | None = None


def _get_shared_http_session() -> requests.Session:
    global _HYCANVAS_SHARED_SESSION
    if _HYCANVAS_SHARED_SESSION is None:
        sess = requests.Session()
        sess.mount('http://', _HYCANVAS_HTTP_ADAPTER)
        sess.mount('https://', _HYCANVAS_HTTP_ADAPTER)
        _HYCANVAS_SHARED_SESSION = sess
    return _HYCANVAS_SHARED_SESSION


def _new_pooled_session() -> requests.Session:
    sess = requests.Session()
    sess.mount('http://', _HYCANVAS_HTTP_ADAPTER)
    sess.mount('https://', _HYCANVAS_HTTP_ADAPTER)
    return sess

CANVAS_PRESET_CATEGORIES = [
    {
        'key': 'workspace',
        'label_key': 'canvas.create.cat.workspace',
        'items': [
            {'key': 'whiteboard', 'type': 'whiteboard', 'width': 1920, 'height': 1080, 'icon': 'bi-grid-1x2', 'label_key': 'canvas.preset.whiteboard'},
            {'key': 'sheet', 'type': 'sheet', 'width': 1280, 'height': 800, 'icon': 'bi-table', 'label_key': 'canvas.preset.sheet'},
        ],
    },
    {
        'key': 'presentation',
        'label_key': 'canvas.create.cat.presentation',
        'items': [
            {'key': 'presentation', 'type': 'presentation', 'width': 1920, 'height': 1080, 'icon': 'bi-easel', 'label_key': 'canvas.preset.presentation'},
            {'key': 'video', 'type': 'video', 'width': 1920, 'height': 1080, 'icon': 'bi-film', 'label_key': 'canvas.preset.video'},
        ],
    },
    {
        'key': 'documents',
        'label_key': 'canvas.create.cat.documents',
        'items': [
            {'key': 'a4_doc', 'type': 'doc', 'width': 1240, 'height': 1754, 'icon': 'bi-book', 'label_key': 'canvas.preset.a4_doc'},
            {'key': 'document', 'type': 'doc', 'width': 816, 'height': 1056, 'icon': 'bi-file-earmark-text', 'label_key': 'canvas.preset.document'},
            {'key': 'poster', 'type': 'graphic', 'width': 1080, 'height': 1350, 'icon': 'bi-file-earmark-richtext', 'label_key': 'canvas.preset.poster'},
            {'key': 'flyer', 'type': 'graphic', 'width': 816, 'height': 1056, 'icon': 'bi-file-earmark', 'label_key': 'canvas.preset.flyer'},
            {'key': 'business_card', 'type': 'graphic', 'width': 1050, 'height': 600, 'icon': 'bi-person-vcard', 'label_key': 'canvas.preset.business_card'},
        ],
    },
    {
        'key': 'web',
        'label_key': 'canvas.create.cat.web',
        'items': [
            {'key': 'banner', 'type': 'graphic', 'width': 1500, 'height': 500, 'icon': 'bi-aspect-ratio', 'label_key': 'canvas.preset.banner'},
            {'key': 'desktop_bg', 'type': 'graphic', 'width': 1920, 'height': 1080, 'icon': 'bi-display', 'label_key': 'canvas.preset.desktop_bg'},
            {'key': 'logo', 'type': 'graphic', 'width': 500, 'height': 500, 'icon': 'bi-image', 'label_key': 'canvas.preset.logo'},
        ],
    },
    {
        'key': 'social',
        'label_key': 'canvas.create.cat.social',
        'items': [
            {'key': 'ig_post', 'type': 'graphic', 'width': 1080, 'height': 1080, 'icon': 'bi-instagram', 'label_key': 'canvas.preset.ig_post'},
            {'key': 'ig_portrait', 'type': 'graphic', 'width': 1080, 'height': 1350, 'icon': 'bi-instagram', 'label_key': 'canvas.preset.ig_portrait'},
            {'key': 'ig_story', 'type': 'graphic', 'width': 1080, 'height': 1920, 'icon': 'bi-phone', 'label_key': 'canvas.preset.ig_story'},
            {'key': 'fb_post', 'type': 'graphic', 'width': 1200, 'height': 630, 'icon': 'bi-facebook', 'label_key': 'canvas.preset.fb_post'},
            {'key': 'li_post', 'type': 'graphic', 'width': 1200, 'height': 627, 'icon': 'bi-linkedin', 'label_key': 'canvas.preset.li_post'},
            {'key': 'yt_thumb', 'type': 'graphic', 'width': 1280, 'height': 720, 'icon': 'bi-youtube', 'label_key': 'canvas.preset.yt_thumb'},
        ],
    },
    {
        'key': 'custom',
        'label_key': 'canvas.create.cat.custom',
        'items': [
            {'key': 'custom', 'type': 'graphic', 'width': 1920, 'height': 1080, 'icon': 'bi-plus-square-dotted', 'label_key': 'canvas.preset.custom'},
        ],
    },
]

CANVAS_PRESET_MAP = {
    item['key']: item
    for cat in CANVAS_PRESET_CATEGORIES
    for item in cat['items']
}


def is_canvas_enabled() -> bool:
    return bool(current_app.config.get('HYCANVAS_ENABLED', True))


def get_hycanvas_browser_url() -> str:
    return (current_app.config.get('HYCANVAS_URL') or '/hycanvas').strip().rstrip('/')


def get_hycanvas_api_url() -> str:
    return (current_app.config.get('HYCANVAS_API_URL') or 'http://hycanvas:8005').strip().rstrip('/')


def get_hycanvas_status() -> tuple[bool, str | None]:
    """Return (is_active, version) for HyCanvas on the About/System page."""
    if not is_canvas_enabled():
        return False, None
    api_url = get_hycanvas_api_url()
    if not api_url:
        return False, None

    sess = _get_shared_http_session()
    reachable = False
    for path in ('/api/v1/health', '/health', '/api/v1/version', '/'):
        if path == '/' and reachable:
            break
        try:
            resp = sess.get(f'{api_url}{path}', timeout=1.0)
            if resp.status_code < 500:
                reachable = True
            if resp.ok and resp.content:
                try:
                    data = resp.json()
                except ValueError:
                    data = None
                if isinstance(data, dict):
                    nested = data.get('data') if isinstance(data.get('data'), dict) else {}
                    ver = data.get('version') or nested.get('version')
                    if ver:
                        return True, str(ver).strip()
        except Exception:
            logger.debug('HyCanvas status check failed for %s%s', api_url, path, exc_info=True)
    return reachable, None


def get_hycanvas_db_url() -> str | None:
    url = (
        current_app.config.get('HYCANVAS_DATABASE_URL')
        or os.environ.get('HYCANVAS_DATABASE_URL')
        or ''
    ).strip()
    if not url:
        return None
    if url.startswith('postgresql://'):
        url = 'postgresql+pg8000://' + url[len('postgresql://'):]
    elif url.startswith('postgres://'):
        url = 'postgresql+pg8000://' + url[len('postgres://'):]
    return url


def _get_hycanvas_db_engine():
    db_url = get_hycanvas_db_url()
    if not db_url:
        return None
    engines = current_app.extensions.setdefault('hycanvas_db_engines', {})
    engine = engines.get(db_url)
    if engine is None:
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=3,
            pool_recycle=1800,
        )
        engines[db_url] = engine
    return engine


def _provision_hycanvas_user(user) -> None:
    """Create a HyCanvas user account via signup endpoint if it does not exist yet."""
    api_url = get_hycanvas_api_url()
    if not api_url or not user:
        return
    email, name, password = _hycanvas_user_credentials(user)
    sess = _get_shared_http_session()
    for endpoint in ('/api/v1/auth/signup', '/api/v1/auth/register'):
        try:
            reg = sess.post(
                f'{api_url}{endpoint}',
                json={'email': email, 'password': password, 'name': name},
                headers={'Accept': 'application/json'},
                timeout=4,
            )
            if reg.ok or reg.status_code in (400, 409):
                break
        except Exception:
            continue


def _get_hycanvas_avatar_col(conn) -> str | None:
    cache = current_app.extensions.setdefault('hycanvas_avatar_col_cache', {})
    if 'col' in cache:
        return cache['col']
    cols_rows = conn.execute(
        text(
            'SELECT column_name FROM information_schema.columns '
            "WHERE table_name = 'users' AND table_schema = current_schema()"
        )
    ).fetchall()
    user_cols = {r.column_name for r in cols_rows}
    avatar_col = next(
        (c for c in ('avatar_url', 'avatarUrl', 'avatar', 'image') if c in user_cols),
        None,
    )
    cache['col'] = avatar_col
    return avatar_col


def _sync_single_hycanvas_user(engine, user, email: str, hc_theme: str) -> None:
    """Fast-path: update only the current user's theme, verification and avatar."""
    with engine.begin() as conn:
        conn.execute(
            text(
                'UPDATE users '
                'SET theme = :theme, email_verified = true, updated_at = NOW() '
                'WHERE lower(email) = :email '
                'AND (theme IS DISTINCT FROM :theme OR email_verified = false)'
            ),
            {'email': email, 'theme': hc_theme},
        )
        if has_request_context():
            avatar_col = _get_hycanvas_avatar_col(conn)
            if avatar_col:
                col_ident = f'"{avatar_col}"' if avatar_col != avatar_col.lower() else avatar_col
                u_avatar = get_user_avatar_external_url(user)
                conn.execute(
                    text(
                        f'UPDATE users '
                        f'SET {col_ident} = :avatar_url, updated_at = NOW() '
                        f'WHERE lower(email) = :email AND {col_ident} IS DISTINCT FROM :avatar_url'
                    ),
                    {'email': email, 'avatar_url': u_avatar},
                )


def sync_hycanvas_user_and_workspaces(user, *, force: bool = False) -> None:
    """Mark user email verified in HyCanvas and sync Teamportal Teams/Admins to HyCanvas workspaces."""
    if not user:
        return
    try:
        engine = _get_hycanvas_db_engine()
    except Exception as exc:
        logger.warning('HyCanvas DB engine init failed: %s', exc)
        return
    if engine is None:
        return

    email = (getattr(user, 'email', None) or f'user-{user.id}@portal.local').strip().lower()
    hc_theme = 'dark' if (getattr(user, 'dark_mode', False) or getattr(user, 'oled_mode', False)) else 'light'

    ttl = int(current_app.config.get('HYCANVAS_SYNC_TTL_SECONDS', HYCANVAS_FULL_SYNC_TTL_SECONDS) or 0)
    now = time.monotonic()
    last_sync = float(current_app.extensions.get('hycanvas_last_full_sync', 0.0))

    if not force and ttl > 0 and (now - last_sync) < ttl:
        try:
            _sync_single_hycanvas_user(engine, user, email, hc_theme)
        except Exception as exc:
            logger.warning('HyCanvas single-user sync failed: %s', exc)
        return

    if not _HYCANVAS_SYNC_LOCK.acquire(blocking=False):
        # Another request is already running the full workspace sync; only update current user.
        try:
            _sync_single_hycanvas_user(engine, user, email, hc_theme)
        except Exception as exc:
            logger.warning('HyCanvas single-user sync failed: %s', exc)
        return

    try:
        from app.models.team import Team, TeamMember
        from app.models.user import User

        teams = Team.query.options(
            joinedload(Team.members).joinedload(TeamMember.user),
            joinedload(Team.leader),
        ).all()
        all_active_users = User.query.filter_by(is_active=True).all()
        active_users_by_email = {
            u.email.strip().lower(): u
            for u in all_active_users
            if getattr(u, 'email', None)
        }
        portal_admins = [u for u in all_active_users if getattr(u, 'is_admin', False)]
        admin_emails = {
            u.email.strip().lower()
            for u in portal_admins
            if getattr(u, 'email', None)
        }

        relevant_users_by_email: dict[str, Any] = {email: user}
        for adm in portal_admins:
            if getattr(adm, 'email', None):
                relevant_users_by_email[adm.email.strip().lower()] = adm
        for team in teams:
            if team.leader and getattr(team.leader, 'is_active', True) and getattr(team.leader, 'email', None):
                relevant_users_by_email[team.leader.email.strip().lower()] = team.leader
            for tm in team.members or []:
                u = tm.user
                if u and getattr(u, 'is_active', True) and getattr(u, 'email', None):
                    relevant_users_by_email[u.email.strip().lower()] = u

        with engine.connect() as check_conn:
            existing_rows = check_conn.execute(
                text('SELECT lower(email) AS email FROM users')
            ).fetchall()
            existing_emails = {r.email for r in existing_rows}
            inv_rows = check_conn.execute(
                text(
                    'SELECT DISTINCT lower(email) AS email '
                    'FROM invitations '
                    'WHERE accepted_at IS NULL AND expires_at > NOW()'
                )
            ).fetchall()
            for inv_r in inv_rows:
                if inv_r.email in active_users_by_email:
                    relevant_users_by_email[inv_r.email] = active_users_by_email[inv_r.email]

        for u_email, u_obj in relevant_users_by_email.items():
            if u_email not in existing_emails:
                _provision_hycanvas_user(u_obj)

        with engine.begin() as conn:
            conn.execute(
                text(
                    'UPDATE users '
                    'SET theme = :theme, updated_at = NOW() '
                    'WHERE lower(email) = :email AND theme IS DISTINCT FROM :theme'
                ),
                {'email': email, 'theme': hc_theme},
            )
            conn.execute(
                text(
                    'UPDATE users '
                    'SET email_verified = true, updated_at = NOW() '
                    'WHERE email_verified = false AND lower(email) = ANY(:emails)'
                ),
                {'emails': list(relevant_users_by_email.keys())},
            )

            if has_request_context() and relevant_users_by_email:
                avatar_col = _get_hycanvas_avatar_col(conn)
                if avatar_col:
                    col_ident = f'"{avatar_col}"' if avatar_col != avatar_col.lower() else avatar_col
                    avatar_updates = [
                        {'email': u_email, 'avatar_url': get_user_avatar_external_url(u_obj)}
                        for u_email, u_obj in relevant_users_by_email.items()
                    ]
                    if avatar_updates:
                        conn.execute(
                            text(
                                f'UPDATE users '
                                f'SET {col_ident} = :avatar_url, updated_at = NOW() '
                                f'WHERE lower(email) = :email AND {col_ident} IS DISTINCT FROM :avatar_url'
                            ),
                            avatar_updates,
                        )

            rows = conn.execute(text('SELECT id::text AS id, lower(email) AS email FROM users')).fetchall()
            hc_users = {row.email: row.id for row in rows}
            if not hc_users:
                return

            first_admin_hc_id = next(
                (hc_users[e] for e in admin_emails if e in hc_users),
                None,
            )

            for team in teams:
                leader_email = (
                    (team.leader.email or '').strip().lower()
                    if team.leader and getattr(team.leader, 'is_active', True) and getattr(team.leader, 'email', None)
                    else ''
                )
                member_hc_ids = []
                for tm in team.members or []:
                    u = tm.user
                    if u and getattr(u, 'is_active', True) and getattr(u, 'email', None):
                        uid_val = hc_users.get(u.email.strip().lower())
                        if uid_val:
                            member_hc_ids.append(uid_val)

                owner_hc_id = (
                    hc_users.get(leader_email)
                    or (member_hc_ids[0] if member_hc_ids else None)
                    or first_admin_hc_id
                    or hc_users.get(email)
                )
                if not owner_hc_id:
                    continue

                slug = f'team-{team.id}'
                ws_row = conn.execute(
                    text(
                        'INSERT INTO workspaces (id, kind, name, slug, owner_id, created_at, updated_at) '
                        'VALUES (CAST(:id AS uuid), CAST(:kind AS "WorkspaceKind"), :name, :slug, CAST(:owner_id AS uuid), NOW(), NOW()) '
                        'ON CONFLICT (slug) DO UPDATE '
                        'SET name = EXCLUDED.name, owner_id = EXCLUDED.owner_id, updated_at = NOW() '
                        'RETURNING id::text AS id'
                    ),
                    {
                        'id': str(uuid.uuid4()),
                        'kind': 'TEAM',
                        'name': (team.name or f'Team {team.id}')[:100],
                        'slug': slug,
                        'owner_id': owner_hc_id,
                    },
                ).fetchone()
                if not ws_row:
                    continue
                ws_id = ws_row.id

                desired_roles: dict[str, str] = {}
                for tm in team.members or []:
                    u = tm.user
                    if not u or not getattr(u, 'is_active', True) or not getattr(u, 'email', None):
                        continue
                    hc_uid = hc_users.get(u.email.strip().lower())
                    if not hc_uid:
                        continue
                    if hc_uid == owner_hc_id:
                        desired_roles[hc_uid] = 'OWNER'
                    elif getattr(u, 'is_admin', False) or u.id == team.leader_id:
                        desired_roles[hc_uid] = 'ADMIN'
                    else:
                        desired_roles[hc_uid] = 'MEMBER'

                if leader_email and leader_email in hc_users:
                    l_uid = hc_users[leader_email]
                    desired_roles[l_uid] = 'OWNER' if l_uid == owner_hc_id else 'ADMIN'

                if desired_roles:
                    member_rows = [
                        {
                            'id': str(uuid.uuid4()),
                            'ws_id': ws_id,
                            'uid': hc_uid,
                            'role': role,
                            'status': 'ACTIVE',
                        }
                        for hc_uid, role in desired_roles.items()
                    ]
                    conn.execute(
                        text(
                            'INSERT INTO workspace_members (id, workspace_id, user_id, role, status, joined_at, created_at, updated_at) '
                            'VALUES (CAST(:id AS uuid), CAST(:ws_id AS uuid), CAST(:uid AS uuid), '
                            'CAST(:role AS "Role"), CAST(:status AS "MembershipStatus"), NOW(), NOW(), NOW()) '
                            'ON CONFLICT (workspace_id, user_id) DO UPDATE '
                            'SET role = EXCLUDED.role, status = EXCLUDED.status, updated_at = NOW()'
                        ),
                        member_rows,
                    )

                existing_members = conn.execute(
                    text(
                        'SELECT wm.user_id::text AS uid '
                        'FROM workspace_members wm '
                        'WHERE wm.workspace_id = CAST(:ws_id AS uuid)'
                    ),
                    {'ws_id': ws_id},
                ).fetchall()
                stale_uids = [m.uid for m in existing_members if m.uid not in desired_roles]
                if stale_uids:
                    conn.execute(
                        text(
                            'DELETE FROM workspace_members '
                            'WHERE workspace_id = CAST(:ws_id AS uuid) '
                            'AND user_id = ANY(CAST(:uids AS uuid[]))'
                        ),
                        {'ws_id': ws_id, 'uids': stale_uids},
                    )

            pending_invs = conn.execute(
                text(
                    'SELECT id::text AS inv_id, workspace_id::text AS ws_id, '
                    'lower(email) AS email, role::text AS role, invited_by_id::text AS invited_by_id '
                    'FROM invitations '
                    'WHERE accepted_at IS NULL AND expires_at > NOW()'
                )
            ).fetchall()
            for inv in pending_invs:
                if inv.email not in active_users_by_email:
                    continue
                hc_uid = hc_users.get(inv.email)
                if not hc_uid:
                    continue
                conn.execute(
                    text(
                        'INSERT INTO workspace_members (id, workspace_id, user_id, role, status, invited_by_id, joined_at, created_at, updated_at) '
                        'VALUES (CAST(:id AS uuid), CAST(:ws_id AS uuid), CAST(:uid AS uuid), '
                        'CAST(:role AS "Role"), CAST(:status AS "MembershipStatus"), CAST(:invited_by_id AS uuid), NOW(), NOW(), NOW()) '
                        'ON CONFLICT (workspace_id, user_id) DO UPDATE '
                        'SET status = EXCLUDED.status, updated_at = NOW()'
                    ),
                    {
                        'id': str(uuid.uuid4()),
                        'ws_id': inv.ws_id,
                        'uid': hc_uid,
                        'role': inv.role,
                        'status': 'ACTIVE',
                        'invited_by_id': inv.invited_by_id,
                    },
                )
                conn.execute(
                    text(
                        'UPDATE invitations SET accepted_at = NOW() '
                        'WHERE id = CAST(:inv_id AS uuid)'
                    ),
                    {'inv_id': inv.inv_id},
                )
        current_app.extensions['hycanvas_last_full_sync'] = time.monotonic()
    except Exception as exc:
        logger.warning('HyCanvas workspace/user sync failed: %s', exc)
    finally:
        _HYCANVAS_SYNC_LOCK.release()


def sign_canvas_avatar_token(user_id: int) -> str:
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps({'uid': int(user_id)}, salt=AVATAR_TOKEN_SALT)


def load_canvas_avatar_user_id(token: str) -> int | None:
    if not token:
        return None
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = s.loads(token, salt=AVATAR_TOKEN_SALT, max_age=AVATAR_TOKEN_MAX_AGE)
        return int(data['uid'])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


def get_user_avatar_external_url(user) -> str | None:
    if not user or not getattr(user, 'profile_picture', None):
        return None
    return url_for('canvas.avatar', token=sign_canvas_avatar_token(user.id), _external=True)


def build_hycanvas_sso_jwt(user) -> str | None:
    """Build a short-lived JWT signed with HYCANVAS_JWT_SECRET for seamless SSO."""
    secret = (current_app.config.get('HYCANVAS_JWT_SECRET') or '').strip()
    if not secret:
        return None
    now = int(time.time())
    payload = {
        'sub': str(user.id),
        'email': getattr(user, 'email', None) or f'user-{user.id}@portal.local',
        'name': getattr(user, 'full_name', None) or getattr(user, 'username', None) or f'User {user.id}',
        'avatar_url': get_user_avatar_external_url(user),
        'iat': now,
        'exp': now + 3600 * 8,
    }
    return jwt.encode(payload, secret, algorithm='HS256')


def _hycanvas_headers(user=None) -> dict[str, str]:
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    api_key = (current_app.config.get('HYCANVAS_API_KEY') or '').strip()
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    elif user is not None:
        token = build_hycanvas_sso_jwt(user)
        if token:
            headers['Authorization'] = f'Bearer {token}'
    return headers


def _hycanvas_user_credentials(user) -> tuple[str, str, str]:
    email = getattr(user, 'email', None) or f'user-{user.id}@portal.local'
    name = getattr(user, 'full_name', None) or getattr(user, 'username', None) or f'User {user.id}'
    secret = (current_app.config.get('SECRET_KEY') or 'prismateams-hycanvas').encode('utf-8')
    digest = hmac.new(secret, f'hycanvas:{user.id}:{email}'.encode('utf-8'), hashlib.sha256).hexdigest()
    password = f'{digest[:20]}!Aa1'
    return email, name, password


def authenticate_hycanvas_session(user) -> requests.Session | None:
    """
    Ensure user exists in HyCanvas and return an authenticated requests.Session
    holding HyCanvas's real session cookies (or None if HyCanvas is unreachable).
    Cached on flask.g for the duration of the current request to avoid duplicate logins.
    """
    api_url = get_hycanvas_api_url()
    if not api_url or not user:
        return None

    uid = getattr(user, 'id', None)
    if has_app_context() and uid is not None:
        g_cache = getattr(g, '_hycanvas_auth_sessions', None)
        if g_cache is not None and uid in g_cache:
            return g_cache[uid]

    email, name, password = _hycanvas_user_credentials(user)
    sess = _new_pooled_session()
    sess.headers.update({'Accept': 'application/json'})

    try:
        resp = sess.post(
            f'{api_url}/api/v1/auth/login',
            json={'email': email, 'password': password},
            timeout=5,
        )
        if not resp.ok:
            for endpoint in ('/api/v1/auth/signup', '/api/v1/auth/register', '/api/v1/setup'):
                reg = sess.post(
                    f'{api_url}{endpoint}',
                    json={'email': email, 'password': password, 'name': name},
                    timeout=5,
                )
                if reg.ok:
                    break
            if not sess.cookies:
                sess.post(
                    f'{api_url}/api/v1/auth/login',
                    json={'email': email, 'password': password},
                    timeout=5,
                )

        if sess.cookies:
            sync_hycanvas_user_and_workspaces(user)
            avatar_url = get_user_avatar_external_url(user)
            hc_theme = 'dark' if (getattr(user, 'dark_mode', False) or getattr(user, 'oled_mode', False)) else 'light'
            patch_payload: dict[str, Any] = {'name': name, 'theme': hc_theme}
            if avatar_url:
                patch_payload['avatar_url'] = avatar_url
                patch_payload['avatarUrl'] = avatar_url
            try:
                patch_resp = sess.patch(
                    f'{api_url}/api/v1/me',
                    json=patch_payload,
                    timeout=3,
                )
                if not patch_resp.ok:
                    logger.debug('HyCanvas PATCH /api/v1/me returned %s: %s', patch_resp.status_code, patch_resp.text[:200])
            except Exception as exc:
                logger.debug('HyCanvas PATCH /api/v1/me failed: %s', exc)
            if has_app_context() and uid is not None:
                g.setdefault('_hycanvas_auth_sessions', {})[uid] = sess
            return sess
    except Exception as exc:
        logger.debug('HyCanvas session auth skipped/failed: %s', exc)
    if has_app_context() and uid is not None:
        g.setdefault('_hycanvas_auth_sessions', {})[uid] = None
    return None


def hycanvas_create_design(
    *,
    title: str,
    design_type: str,
    width: int,
    height: int,
    user=None,
) -> str | None:
    """Create a design in HyCanvas and return its remote design_id (or None if offline)."""
    api_url = get_hycanvas_api_url()
    if not api_url:
        return None
    sess = authenticate_hycanvas_session(user)
    payload: dict[str, Any] = {
        'title': title,
        'type': design_type,
        'width': int(width),
        'height': int(height),
    }
    try:
        client = sess or _get_shared_http_session()
        resp = client.post(
            f'{api_url}/api/v1/designs',
            json=payload,
            headers=_hycanvas_headers(user) if sess is None else None,
            timeout=6,
        )
        if resp.ok:
            data = resp.json() if resp.content else {}
            design_id = data.get('id') or (data.get('data') or {}).get('id')
            if design_id:
                return str(design_id)
    except Exception as exc:
        logger.warning('HyCanvas create design failed: %s', exc)
    return None


def hycanvas_export_hyc(design_id: str, user=None) -> bytes | None:
    if not design_id:
        return None
    api_url = get_hycanvas_api_url()
    sess = authenticate_hycanvas_session(user)
    client = sess or _get_shared_http_session()
    headers = None if sess is not None else _hycanvas_headers(user)
    try:
        resp = client.get(
            f'{api_url}/api/v1/designs/{design_id}/file',
            headers=headers,
            timeout=10,
        )
        if resp.ok and resp.content:
            return resp.content
    except Exception as exc:
        logger.warning('HyCanvas .hyc export failed for %s: %s', design_id, exc)
    return None


def hycanvas_export_thumbnail(design_id: str, user=None) -> bytes | None:
    if not design_id:
        return None
    api_url = get_hycanvas_api_url()
    sess = authenticate_hycanvas_session(user)
    client = sess or _get_shared_http_session()
    headers = None if sess is not None else _hycanvas_headers(user)
    try:
        resp = client.get(
            f'{api_url}/api/v1/designs/{design_id}/render.png',
            params={'width': 640},
            headers=headers,
            timeout=10,
        )
        if resp.ok and resp.content:
            return resp.content
    except Exception as exc:
        logger.warning('HyCanvas thumbnail export failed for %s: %s', design_id, exc)
    return None


def hycanvas_delete_design(design_id: str, user=None) -> None:
    if not design_id:
        return
    api_url = get_hycanvas_api_url()
    try:
        _get_shared_http_session().delete(
            f'{api_url}/api/v1/designs/{design_id}',
            headers=_hycanvas_headers(user),
            timeout=5,
        )
    except Exception as exc:
        logger.warning('HyCanvas delete design failed for %s: %s', design_id, exc)


def get_hycanvas_embed_url(doc, user=None) -> str:
    base = get_hycanvas_browser_url()
    if doc.hycanvas_design_id:
        return f'{base}/design/{doc.hycanvas_design_id}'
    return f'{base}/'


def _canvas_upload_dir() -> str:
    root = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    path = os.path.join(root, 'canvas')
    os.makedirs(path, exist_ok=True)
    return path


def save_canvas_hyc_file(doc_id: int, name: str, raw_bytes: bytes) -> str:
    slug = secure_filename(re.sub(r'\s+', '_', name or 'canvas')) or 'canvas'
    filename = f'canvas_{doc_id}_{int(time.time())}_{slug[:40]}.hyc'
    full_path = os.path.join(_canvas_upload_dir(), filename)
    with open(full_path, 'wb') as fh:
        fh.write(raw_bytes)
    return full_path


def save_canvas_thumbnail(doc_id: int, raw_bytes: bytes) -> str:
    filename = f'canvas_{doc_id}_thumb.png'
    full_path = os.path.join(_canvas_upload_dir(), filename)
    with open(full_path, 'wb') as fh:
        fh.write(raw_bytes)
    return full_path


def remove_file_quietly(path: str | None) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
