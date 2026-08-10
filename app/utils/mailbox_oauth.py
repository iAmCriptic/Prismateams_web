"""OAuth für Multi-Postfächer (Google Gmail + Microsoft Outlook) inkl. XOAUTH2."""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Tuple
from urllib.parse import urlencode

import requests
from flask import session, url_for

from app import db
from app.utils.integrations import (
    get_google_credentials,
    get_microsoft_credentials,
    google_oauth_configured,
    google_oauth_redirect_uri,
    microsoft_oauth_configured,
)
from app.utils.multi_mailboxes import decrypt_password, encrypt_password, get_provider_preset

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v2/userinfo'
# Voller Mail-Scope für IMAP/SMTP XOAUTH2
GOOGLE_SCOPES = 'https://mail.google.com/ https://www.googleapis.com/auth/userinfo.email'

MS_SCOPES = ' '.join([
    'offline_access',
    'openid',
    'email',
    'https://outlook.office.com/IMAP.AccessAsUser.All',
    'https://outlook.office.com/SMTP.Send',
])


def provider_oauth_ready(provider: str) -> bool:
    if provider == 'google':
        return google_oauth_configured()
    if provider == 'microsoft':
        return microsoft_oauth_configured()
    return False


def build_oauth_authorize_url(provider: str, *, popup: bool = True) -> str:
    state = os.urandom(16).hex()
    session['mailbox_oauth_state'] = state
    session['mailbox_oauth_provider'] = provider
    session['mailbox_oauth_popup'] = bool(popup)

    if provider == 'google':
        creds = get_google_credentials()
        if not creds['client_id']:
            raise RuntimeError('Google Client ID fehlt unter Verknüpfungen')
        redirect_uri = google_oauth_redirect_uri()
        params = {
            'client_id': creds['client_id'],
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'scope': GOOGLE_SCOPES,
            'state': state,
            'access_type': 'offline',
            'prompt': 'consent',
            'include_granted_scopes': 'true',
        }
        return f'{GOOGLE_AUTH_URL}?{urlencode(params)}'

    if provider == 'microsoft':
        creds = get_microsoft_credentials()
        if not creds['client_id']:
            raise RuntimeError('Microsoft Client ID fehlt unter Verknüpfungen')
        tenant = creds.get('tenant') or 'common'
        redirect_uri = url_for('settings.mailbox_oauth_callback', provider=provider, _external=True)
        params = {
            'client_id': creds['client_id'],
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'scope': MS_SCOPES,
            'state': state,
            'response_mode': 'query',
            'prompt': 'select_account',
        }
        return f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}'

    raise ValueError(f'Unbekannter OAuth-Provider: {provider}')


def _exchange_google_code(code: str, *, redirect_uri: Optional[str] = None) -> dict:
    creds = get_google_credentials()
    redirect_uri = redirect_uri or google_oauth_redirect_uri()
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
    email = ''
    try:
        ui = requests.get(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f"Bearer {data['access_token']}"},
            timeout=10,
        )
        if ui.ok:
            email = (ui.json().get('email') or '').strip()
    except Exception:
        pass
    data['email'] = email
    return data


def _exchange_microsoft_code(code: str) -> dict:
    creds = get_microsoft_credentials()
    tenant = creds.get('tenant') or 'common'
    redirect_uri = url_for('settings.mailbox_oauth_callback', provider='microsoft', _external=True)
    resp = requests.post(
        f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
        data={
            'client_id': creds['client_id'],
            'client_secret': creds['client_secret'],
            'code': code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
            'scope': MS_SCOPES,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    email = ''
    # id_token payload ohne Verifikation (nur Anzeige der Konto-Adresse)
    try:
        id_token = data.get('id_token') or ''
        parts = id_token.split('.')
        if len(parts) >= 2:
            pad = '=' * (-len(parts[1]) % 4)
            import json
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad).decode('utf-8'))
            email = (payload.get('email') or payload.get('preferred_username') or '').strip()
    except Exception:
        pass
    data['email'] = email
    return data


def handle_oauth_callback(provider: str, code: str, state: str, *, redirect_uri: Optional[str] = None) -> dict:
    """Tauscht Code gegen Tokens; speichert Ergebnis in Session für den Wizard."""
    if state != session.get('mailbox_oauth_state'):
        raise RuntimeError('Ungültiger OAuth-State')
    if provider != session.get('mailbox_oauth_provider'):
        raise RuntimeError('OAuth-Provider stimmt nicht überein')

    if provider == 'google':
        token_data = _exchange_google_code(code, redirect_uri=redirect_uri)
    elif provider == 'microsoft':
        token_data = _exchange_microsoft_code(code)
    else:
        raise ValueError(provider)

    expires_in = int(token_data.get('expires_in') or 3600)
    result = {
        'provider': provider,
        'access_token': token_data.get('access_token'),
        'refresh_token': token_data.get('refresh_token'),
        'expires_at': (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat(),
        'email': token_data.get('email') or '',
    }
    if not result['access_token']:
        raise RuntimeError('Kein Access-Token erhalten')
    session['mailbox_oauth_result'] = result
    session.pop('mailbox_oauth_state', None)
    return result


def mailbox_oauth_popup_error_html(message: str) -> Tuple[str, int]:
    import json
    return (
        '<!doctype html><html><body><script>'
        'window.opener&&window.opener.postMessage({type:"mailbox_oauth_error",error:'
        + json.dumps(message)
        + '},"*");window.close();</script>'
        f'<p>{message}</p></body></html>'
    ), 400


def mailbox_oauth_popup_success_html(result: dict) -> str:
    import json
    payload = {
        'type': 'mailbox_oauth_done',
        'provider': result.get('provider'),
        'email': result.get('email') or '',
    }
    return (
        '<!doctype html><html><body><script>'
        'window.opener&&window.opener.postMessage('
        + json.dumps(payload)
        + ',"*");window.close();</script>'
        '<p>OK</p></body></html>'
    )


def pop_oauth_result() -> Optional[dict]:
    return session.pop('mailbox_oauth_result', None)


def peek_oauth_result() -> Optional[dict]:
    return session.get('mailbox_oauth_result')


def apply_oauth_tokens_to_mailbox(mailbox, token_result: dict) -> None:
    """Schreibt OAuth-Tokens + Preset-Hosts auf das Mailbox-Modell."""
    provider = token_result.get('provider') or mailbox.provider or 'google'
    preset = get_provider_preset(provider)
    mailbox.provider = provider
    mailbox.auth_type = 'oauth'
    mailbox.smtp_server = preset.get('smtp_server')
    mailbox.smtp_port = int(preset.get('smtp_port') or 587)
    mailbox.smtp_use_tls = bool(preset.get('smtp_use_tls', True))
    mailbox.smtp_use_ssl = bool(preset.get('smtp_use_ssl', False))
    mailbox.imap_server = preset.get('imap_server')
    mailbox.imap_port = int(preset.get('imap_port') or 993)
    mailbox.imap_use_ssl = bool(preset.get('imap_use_ssl', True))

    email = (token_result.get('email') or '').strip()
    mailbox.oauth_email = email or mailbox.oauth_email
    if email:
        mailbox.smtp_username = email
        mailbox.imap_username = email

    access = token_result.get('access_token')
    refresh = token_result.get('refresh_token')
    if access:
        mailbox.oauth_access_token_enc = encrypt_password(access)
    if refresh:
        mailbox.oauth_refresh_token_enc = encrypt_password(refresh)
    expires_raw = token_result.get('expires_at')
    if expires_raw:
        try:
            mailbox.oauth_expires_at = datetime.fromisoformat(expires_raw)
        except Exception:
            mailbox.oauth_expires_at = datetime.utcnow() + timedelta(hours=1)
    else:
        mailbox.oauth_expires_at = datetime.utcnow() + timedelta(hours=1)


def _refresh_google(refresh_token: str) -> dict:
    creds = get_google_credentials()
    resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            'client_id': creds['client_id'],
            'client_secret': creds['client_secret'],
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _refresh_microsoft(refresh_token: str) -> dict:
    creds = get_microsoft_credentials()
    tenant = creds.get('tenant') or 'common'
    resp = requests.post(
        f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
        data={
            'client_id': creds['client_id'],
            'client_secret': creds['client_secret'],
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
            'scope': MS_SCOPES,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def get_valid_access_token(mailbox) -> str:
    """Liefert einen gültigen Access-Token (refresh bei Bedarf)."""
    access = decrypt_password(getattr(mailbox, 'oauth_access_token_enc', None))
    refresh = decrypt_password(getattr(mailbox, 'oauth_refresh_token_enc', None))
    expires_at = getattr(mailbox, 'oauth_expires_at', None)
    now = datetime.utcnow()
    if access and expires_at and expires_at > now + timedelta(minutes=2):
        return access
    if not refresh:
        if access:
            return access
        raise RuntimeError('OAuth-Token fehlt – bitte Postfach erneut verbinden')

    provider = getattr(mailbox, 'provider', None) or 'google'
    try:
        if provider == 'microsoft':
            data = _refresh_microsoft(refresh)
        else:
            data = _refresh_google(refresh)
    except Exception as exc:
        logger.warning('OAuth refresh failed for mailbox %s: %s', getattr(mailbox, 'id', None), exc)
        if access:
            return access
        raise

    new_access = data.get('access_token')
    if not new_access:
        raise RuntimeError('OAuth-Refresh ohne Access-Token')
    mailbox.oauth_access_token_enc = encrypt_password(new_access)
    if data.get('refresh_token'):
        mailbox.oauth_refresh_token_enc = encrypt_password(data['refresh_token'])
    mailbox.oauth_expires_at = now + timedelta(seconds=int(data.get('expires_in') or 3600))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return new_access


def xoauth2_string(user: str, access_token: str) -> bytes:
    return f'user={user}\x01auth=Bearer {access_token}\x01\x01'.encode('utf-8')


def xoauth2_b64(user: str, access_token: str) -> str:
    return base64.b64encode(xoauth2_string(user, access_token)).decode('ascii')


def imap_authenticate_xoauth2(conn, user: str, access_token: str) -> None:
    auth = xoauth2_string(user, access_token)

    def _auth_callback(_challenge):
        return auth

    typ, data = conn.authenticate('XOAUTH2', _auth_callback)
    if typ != 'OK':
        raise RuntimeError(f'IMAP XOAUTH2 fehlgeschlagen: {data}')


def smtp_authenticate_xoauth2(smtp, user: str, access_token: str) -> None:
    # smtplib.SMTP.auth erwartet Callable, das den Auth-String liefert
    def _auth_object(_challenge=None):
        return xoauth2_string(user, access_token).decode('utf-8')

    try:
        smtp.auth('XOAUTH2', _auth_object, initial_response_ok=True)
    except TypeError:
        # Ältere Python-Versionen ohne initial_response_ok
        code, resp = smtp.docmd('AUTH', 'XOAUTH2 ' + xoauth2_b64(user, access_token))
        if code != 235:
            raise RuntimeError(f'SMTP XOAUTH2 fehlgeschlagen: {code} {resp}')
