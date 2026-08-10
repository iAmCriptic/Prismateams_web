"""Google-Login, Account-Verknüpfung und Registrierungs-Prefill."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import requests
from flask import current_app, session, url_for
from werkzeug.utils import secure_filename

from app import db
from app.utils.integrations import get_google_credentials, google_oauth_configured, google_oauth_redirect_uri

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v2/userinfo'

GOOGLE_REGISTER_SESSION_KEY = 'google_register'

# Login/Link/Register: Identität + Gmail XOAUTH2 für optionales Auto-Postfach
GOOGLE_LOGIN_SCOPES = (
    'openid email profile '
    'https://mail.google.com/ '
    'https://www.googleapis.com/auth/userinfo.email'
)


def google_login_ready() -> bool:
    return google_oauth_configured()


def build_google_login_url(*, purpose: str = 'login', popup: bool = False) -> str:
    """purpose: 'login' | 'link' | 'register'."""
    if purpose not in ('login', 'link', 'register'):
        raise ValueError(purpose)
    creds = get_google_credentials()
    if not creds['client_id']:
        raise RuntimeError('Google Client ID fehlt unter Verknüpfungen')

    state = os.urandom(16).hex()
    session['google_login_state'] = state
    session['google_login_purpose'] = purpose
    session['google_login_popup'] = bool(popup)

    redirect_uri = google_oauth_redirect_uri()
    params = {
        'client_id': creds['client_id'],
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'scope': GOOGLE_LOGIN_SCOPES,
        'state': state,
        'access_type': 'offline',
        'prompt': 'consent' if purpose == 'link' else 'select_account',
        'include_granted_scopes': 'true',
    }
    return f'{GOOGLE_AUTH_URL}?{urlencode(params)}'


def _split_display_name(name: str) -> tuple[str, str]:
    parts = [p for p in (name or '').strip().split() if p]
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], ' '.join(parts[1:])


def exchange_google_login_code(code: str, state: str) -> dict:
    if state != session.get('google_login_state'):
        raise RuntimeError('Ungültiger OAuth-State')
    purpose = session.get('google_login_purpose') or 'login'
    creds = get_google_credentials()
    redirect_uri = google_oauth_redirect_uri()
    resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            'code': code,
            'client_id': creds['client_id'],
            'client_secret': creds['client_secret'],
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    access = data.get('access_token')
    if not access:
        raise RuntimeError('Kein Access-Token von Google')

    ui = requests.get(
        GOOGLE_USERINFO_URL,
        headers={'Authorization': f'Bearer {access}'},
        timeout=10,
    )
    ui.raise_for_status()
    profile = ui.json()
    sub = (profile.get('id') or profile.get('sub') or '').strip()
    email = (profile.get('email') or '').strip().lower()
    if not sub:
        raise RuntimeError('Google-Benutzer-ID fehlt')
    if not email:
        raise RuntimeError('Google-E-Mail fehlt')

    given = (profile.get('given_name') or '').strip()
    family = (profile.get('family_name') or '').strip()
    if not given and not family:
        given, family = _split_display_name(profile.get('name') or '')

    expires_in = int(data.get('expires_in') or 3600)
    result = {
        'purpose': purpose,
        'provider': 'google',
        'sub': sub,
        'email': email,
        'name': (profile.get('name') or '').strip(),
        'first_name': given,
        'last_name': family,
        'picture': (profile.get('picture') or '').strip(),
        'access_token': access,
        'refresh_token': data.get('refresh_token'),
        'expires_at': (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat(),
    }
    session.pop('google_login_state', None)
    session.pop('google_login_purpose', None)
    return result


def store_google_register_prefill(oauth_result: dict) -> dict:
    """Speichert Google-Profildaten für die Registrierungsseite (ohne Tokens)."""
    payload = {
        'sub': oauth_result.get('sub') or '',
        'email': (oauth_result.get('email') or '').strip().lower(),
        'first_name': (oauth_result.get('first_name') or '').strip(),
        'last_name': (oauth_result.get('last_name') or '').strip(),
        'picture': (oauth_result.get('picture') or '').strip(),
        'stored_at': datetime.utcnow().isoformat(),
    }
    if not payload['sub'] or not payload['email']:
        raise RuntimeError('Google-Profil unvollständig')
    session[GOOGLE_REGISTER_SESSION_KEY] = payload
    return payload


def get_google_register_prefill() -> Optional[dict]:
    data = session.get(GOOGLE_REGISTER_SESSION_KEY)
    if not isinstance(data, dict):
        return None
    if not data.get('sub') or not data.get('email'):
        clear_google_register_prefill()
        return None
    # Prefill max. 30 Minuten gültig
    try:
        stored_at = datetime.fromisoformat(data.get('stored_at') or '')
        if datetime.utcnow() - stored_at > timedelta(minutes=30):
            clear_google_register_prefill()
            return None
    except Exception:
        clear_google_register_prefill()
        return None
    return data


def clear_google_register_prefill() -> None:
    session.pop(GOOGLE_REGISTER_SESSION_KEY, None)


def save_google_profile_picture(user, picture_url: str) -> Optional[str]:
    """Lädt das Google-Profilbild herunter und speichert es lokal."""
    if not user or not getattr(user, 'id', None) or not picture_url:
        return None
    try:
        resp = requests.get(picture_url, timeout=12)
        resp.raise_for_status()
        content_type = (resp.headers.get('Content-Type') or '').lower()
        if 'png' in content_type:
            ext = 'png'
        elif 'gif' in content_type:
            ext = 'gif'
        elif 'webp' in content_type:
            ext = 'webp'
        else:
            ext = 'jpg'

        project_root = os.path.dirname(current_app.root_path)
        upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'profile_pics')
        os.makedirs(upload_dir, exist_ok=True)

        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(f'{user.id}_{timestamp}_google.{ext}')
        filepath = os.path.join(upload_dir, filename)
        with open(filepath, 'wb') as fh:
            fh.write(resp.content)

        if user.profile_picture:
            try:
                old_path = os.path.join(upload_dir, user.profile_picture)
                if os.path.exists(old_path):
                    os.remove(old_path)
            except OSError:
                pass

        user.profile_picture = filename
        return filename
    except Exception as exc:
        logger.warning('Google-Profilbild konnte nicht gespeichert werden (user=%s): %s', getattr(user, 'id', None), exc)
        return None


def ensure_gmail_mailbox_for_user(user, token_result: dict):
    """Legt bei aktivem Multi-Postfach ein privates „Gmail“-Postfach an / aktualisiert Tokens."""
    try:
        from app.utils.multi_mailboxes import (
            is_email_multi_enabled,
            can_add_private_mailbox,
            apply_provider_preset,
        )
        from app.utils.mailbox_oauth import apply_oauth_tokens_to_mailbox
        from app.models.email import Mailbox
    except Exception as exc:
        logger.warning('Gmail-Mailbox Auto-Setup Import fehlgeschlagen: %s', exc)
        return None

    if not is_email_multi_enabled():
        return None
    if not user or not getattr(user, 'id', None):
        return None

    existing = (
        Mailbox.query.filter_by(
            owner_id=user.id,
            mailbox_type='private',
            provider='google',
            is_active=True,
        )
        .order_by(Mailbox.id.asc())
        .first()
    )
    if existing is None:
        named = Mailbox.query.filter_by(
            owner_id=user.id,
            mailbox_type='private',
            display_name='Gmail',
            is_active=True,
        ).first()
        existing = named

    if existing is not None:
        apply_oauth_tokens_to_mailbox(existing, token_result)
        if not existing.display_name:
            existing.display_name = 'Gmail'
            existing.name = 'Gmail'
        return existing

    if not can_add_private_mailbox(user):
        logger.info('Gmail-Postfach nicht angelegt: Limit erreicht (user=%s)', user.id)
        return None

    mb = Mailbox(
        name='Gmail',
        display_name='Gmail',
        mailbox_type='private',
        owner_id=user.id,
        is_active=True,
        color='#ea4335',
    )
    apply_provider_preset(mb, 'google')
    apply_oauth_tokens_to_mailbox(mb, token_result)
    db.session.add(mb)
    return mb
