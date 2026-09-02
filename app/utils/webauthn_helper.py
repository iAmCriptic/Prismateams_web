"""WebAuthn / Passkey helpers."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from flask import current_app, request, session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.options_to_json import options_to_json
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

CHALLENGE_TTL_SECONDS = 300
SESSION_CHALLENGE_KEY = 'webauthn_challenge'
SESSION_CHALLENGE_TS_KEY = 'webauthn_challenge_ts'
SESSION_FLOW_KEY = 'webauthn_flow'


class WebAuthnError(Exception):
    """WebAuthn flow error with optional HTTP status."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _get_portal_name() -> str:
    try:
        from app.models.settings import SystemSettings
        row = SystemSettings.query.filter_by(key='portal_name').first()
        if row and row.value and str(row.value).strip():
            return str(row.value).strip()
    except Exception:
        pass
    try:
        return current_app.config.get('APP_NAME', 'Prismateams')
    except Exception:
        return 'Prismateams'


def _request_host() -> str:
    return (request.host or '').split(':')[0].lower()


def get_rp_config() -> dict[str, str]:
    """Relying party ID, name and expected origin for WebAuthn."""
    env_rp_id = (os.environ.get('WEBAUTHN_RP_ID') or '').strip()
    host = _request_host()

    # Browser akzeptieren keine IP als rpId — lokal nur „localhost“.
    if host == '127.0.0.1':
        host = 'localhost'

    rp_id = env_rp_id or host or 'localhost'

    scheme = request.headers.get('X-Forwarded-Proto', request.scheme or 'http')
    origin = f'{scheme}://{request.host}'

    return {
        'rp_id': rp_id,
        'rp_name': _get_portal_name()[:64],
        'origin': origin,
    }


def passkeys_require_localhost() -> bool:
    """True wenn Passkeys nur über localhost erreichbar sind (127.0.0.1 blockiert)."""
    return _request_host() == '127.0.0.1'


def localhost_passkey_url() -> str | None:
    """URL mit localhost statt 127.0.0.1 für lokale Passkey-Tests."""
    if not passkeys_require_localhost():
        return None
    port = request.host.split(':', 1)[1] if ':' in (request.host or '') else ''
    host = f'localhost:{port}' if port else 'localhost'
    scheme = request.headers.get('X-Forwarded-Proto', request.scheme or 'http')
    path = request.full_path if request.query_string else request.path
    if path.endswith('?') and not request.query_string:
        path = path[:-1]
    return f'{scheme}://{host}{path}'


def user_handle_bytes(user_id: int) -> bytes:
    return str(user_id).encode('utf-8')


def store_challenge(challenge: bytes, flow: str) -> None:
    session[SESSION_CHALLENGE_KEY] = bytes_to_base64url(challenge)
    session[SESSION_CHALLENGE_TS_KEY] = time.time()
    session[SESSION_FLOW_KEY] = flow


def pop_challenge(expected_flow: str) -> bytes:
    stored = session.pop(SESSION_CHALLENGE_KEY, None)
    ts = session.pop(SESSION_CHALLENGE_TS_KEY, None)
    flow = session.pop(SESSION_FLOW_KEY, None)

    if not stored or ts is None or flow != expected_flow:
        raise WebAuthnError('Challenge abgelaufen oder ungültig.', 400)

    if time.time() - float(ts) > CHALLENGE_TTL_SECONDS:
        raise WebAuthnError('Challenge abgelaufen.', 400)

    return base64url_to_bytes(stored)


def passkeys_supported_for_request() -> bool:
    """Passkeys require secure context (HTTPS) or localhost — nicht 127.0.0.1."""
    host = _request_host()
    if host == '127.0.0.1':
        return False
    if host in {'localhost', '[::1]'}:
        return True
    return request.is_secure or request.headers.get('X-Forwarded-Proto', '').lower() == 'https'


def _options_dict(options) -> dict[str, Any]:
    """options_to_json (webauthn 3.x) liefert einen JSON-String — für API als Dict."""
    payload = options_to_json(options)
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def build_registration_options(user) -> dict[str, Any]:
    if getattr(user, 'is_guest', False):
        raise WebAuthnError('Passkeys sind für Gast-Accounts nicht verfügbar.', 403)

    cfg = get_rp_config()
    options = generate_registration_options(
        rp_id=cfg['rp_id'],
        rp_name=cfg['rp_name'],
        user_id=user_handle_bytes(user.id),
        user_name=user.email,
        user_display_name=user.full_name or user.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    store_challenge(options.challenge, 'register')
    return _options_dict(options)


def verify_registration(user, credential: dict, device_label: str | None = None):
    if getattr(user, 'is_guest', False):
        raise WebAuthnError('Passkeys sind für Gast-Accounts nicht verfügbar.', 403)

    cfg = get_rp_config()
    challenge = pop_challenge('register')

    verification = verify_registration_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=cfg['rp_id'],
        expected_origin=cfg['origin'],
        require_user_verification=False,
    )

    transports = None
    try:
        transport_list = credential.get('response', {}).get('transports') or credential.get('transports')
        if transport_list:
            transports = ','.join(transport_list)
    except Exception:
        pass

    return {
        'credential_id': bytes_to_base64url(verification.credential_id),
        'public_key': bytes_to_base64url(verification.credential_public_key),
        'sign_count': verification.sign_count,
        'aaguid': str(verification.aaguid) if verification.aaguid else None,
        'backed_up': bool(verification.credential_backed_up),
        'transports': transports,
        'device_label': (device_label or '').strip() or None,
    }


def _credential_descriptors(passkeys) -> list[PublicKeyCredentialDescriptor]:
    descriptors = []
    for pk in passkeys:
        transports = None
        if pk.transports:
            transports = [t.strip() for t in pk.transports.split(',') if t.strip()]
        descriptors.append(
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(pk.credential_id),
                transports=transports,
            )
        )
    return descriptors


def build_login_options() -> dict[str, Any]:
    """Discoverable credentials (passwordless login)."""
    cfg = get_rp_config()
    options = generate_authentication_options(
        rp_id=cfg['rp_id'],
        user_verification=UserVerificationRequirement.PREFERRED,
        allow_credentials=[],
    )
    store_challenge(options.challenge, 'login')
    return _options_dict(options)


def build_2fa_options(passkeys) -> dict[str, Any]:
    if not passkeys:
        raise WebAuthnError('Kein Passkey registriert.', 400)

    cfg = get_rp_config()
    options = generate_authentication_options(
        rp_id=cfg['rp_id'],
        user_verification=UserVerificationRequirement.PREFERRED,
        allow_credentials=_credential_descriptors(passkeys),
    )
    store_challenge(options.challenge, '2fa')
    return _options_dict(options)


def verify_login(credential: dict):
    from app.models.passkey import UserPasskey

    cfg = get_rp_config()
    challenge = pop_challenge('login')

    cred_id = credential.get('id') or credential.get('rawId')
    if not cred_id:
        raise WebAuthnError('Ungültige Passkey-Antwort.', 400)

    if isinstance(cred_id, str):
        cred_id_b64 = cred_id
    else:
        cred_id_b64 = bytes_to_base64url(cred_id)

    passkey = UserPasskey.query.filter_by(credential_id=cred_id_b64).first()
    if not passkey:
        raise WebAuthnError('Passkey nicht gefunden.', 401)

    verification = verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=cfg['rp_id'],
        expected_origin=cfg['origin'],
        credential_public_key=base64url_to_bytes(passkey.public_key),
        credential_current_sign_count=passkey.sign_count,
        require_user_verification=False,
    )

    return passkey, verification


def verify_2fa(passkeys, credential: dict):
    cfg = get_rp_config()
    challenge = pop_challenge('2fa')

    cred_id = credential.get('id') or credential.get('rawId')
    if not cred_id:
        raise WebAuthnError('Ungültige Passkey-Antwort.', 400)

    if isinstance(cred_id, str):
        cred_id_b64 = cred_id
    else:
        cred_id_b64 = bytes_to_base64url(cred_id)

    passkey = next((pk for pk in passkeys if pk.credential_id == cred_id_b64), None)
    if not passkey:
        raise WebAuthnError('Passkey nicht gefunden.', 401)

    verification = verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=cfg['rp_id'],
        expected_origin=cfg['origin'],
        credential_public_key=base64url_to_bytes(passkey.public_key),
        credential_current_sign_count=passkey.sign_count,
        require_user_verification=False,
    )

    return passkey, verification


def apply_verification_result(passkey, verification) -> None:
    passkey.sign_count = verification.new_sign_count
    passkey.touch_used()
