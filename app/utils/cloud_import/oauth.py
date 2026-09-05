"""Google OAuth for Drive import (readonly)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from flask import session
from flask_login import current_user

from app import db
from app.models.cloud_import import CloudImportConnection
from app.utils.cloud_import.base import decrypt_credentials, encrypt_credentials
from app.utils.cloud_import.google_drive import DRIVE_SCOPE
from app.utils.integrations import get_google_credentials, google_oauth_configured, google_oauth_redirect_uri


SESSION_STATE_KEY = 'cloud_import_google_oauth_state'


def get_google_drive_oauth_url() -> str:
    if not google_oauth_configured():
        raise ValueError('google_not_configured')
    creds = get_google_credentials()
    state = os.urandom(16).hex()
    session[SESSION_STATE_KEY] = state
    params = {
        'client_id': creds['client_id'],
        'response_type': 'code',
        'redirect_uri': google_oauth_redirect_uri(),
        'scope': DRIVE_SCOPE,
        'state': state,
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'true',
    }
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)


def handle_google_drive_callback(code: str, state: str) -> CloudImportConnection:
    if state != session.get(SESSION_STATE_KEY):
        raise ValueError('invalid_state')
    session.pop(SESSION_STATE_KEY, None)

    if not google_oauth_configured():
        raise ValueError('google_not_configured')

    creds = get_google_credentials()
    resp = requests.post(
        'https://oauth2.googleapis.com/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': google_oauth_redirect_uri(),
            'client_id': creds['client_id'],
            'client_secret': creds['client_secret'],
        },
        timeout=30,
    )
    resp.raise_for_status()
    token_data = resp.json()

    expires_at = datetime.utcnow() + timedelta(seconds=int(token_data.get('expires_in', 3600)))
    payload = {
        'access_token': token_data['access_token'],
        'refresh_token': token_data.get('refresh_token'),
        'expires_at': expires_at.isoformat(),
        'scope': token_data.get('scope') or DRIVE_SCOPE,
    }

    # Preserve refresh_token if Google omits it on re-consent
    existing = CloudImportConnection.query.filter_by(
        user_id=current_user.id,
        provider='google_drive',
    ).order_by(CloudImportConnection.created_at.desc()).first()
    if existing and not payload.get('refresh_token'):
        old = decrypt_credentials(existing.credentials_enc)
        if old.get('refresh_token'):
            payload['refresh_token'] = old['refresh_token']

    display = 'Google Drive'
    # Try to get email for display
    try:
        about = requests.get(
            'https://www.googleapis.com/drive/v3/about',
            params={'fields': 'user'},
            headers={'Authorization': f'Bearer {payload["access_token"]}'},
            timeout=15,
        )
        if about.status_code == 200:
            email = (about.json().get('user') or {}).get('emailAddress')
            if email:
                display = f'Google Drive ({email})'
    except Exception:
        pass

    if existing:
        if payload.get('refresh_token') or decrypt_credentials(existing.credentials_enc).get('refresh_token'):
            if not payload.get('refresh_token'):
                payload['refresh_token'] = decrypt_credentials(existing.credentials_enc).get('refresh_token')
        existing.credentials_enc = encrypt_credentials(payload)
        existing.display_name = display
        existing.updated_at = datetime.utcnow()
        db.session.commit()
        return existing

    conn = CloudImportConnection(
        user_id=current_user.id,
        provider='google_drive',
        display_name=display,
        credentials_enc=encrypt_credentials(payload),
    )
    db.session.add(conn)
    db.session.commit()
    return conn
