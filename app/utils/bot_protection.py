"""Portal bot protection for registration and login forms."""

from __future__ import annotations

import secrets
import string
from typing import Any, Literal

import requests

from app import db
from app.models.settings import SystemSettings

BotContext = Literal['register', 'login']
VALID_PROVIDERS = frozenset({'none', 'honeypot', 'recaptcha', 'turnstile'})
VALID_RECAPTCHA_VERSIONS = frozenset({'v2', 'v3'})

SETTING_KEYS = {
    'provider': 'portal_bot_protection',
    'register_enabled': 'portal_bot_protection_register',
    'login_enabled': 'portal_bot_protection_login',
    'recaptcha_version': 'portal_recaptcha_version',
    'recaptcha_site_key': 'portal_recaptcha_site_key',
    'recaptcha_secret_key': 'portal_recaptcha_secret_key',
    'turnstile_site_key': 'portal_turnstile_site_key',
    'turnstile_secret_key': 'portal_turnstile_secret_key',
    'honeypot_field': 'portal_honeypot_field',
}

DEFAULT_SETTINGS = {
    SETTING_KEYS['provider']: ('none', 'Bot-Schutz-Methode für Registrierung/Login'),
    SETTING_KEYS['register_enabled']: ('true', 'Bot-Schutz bei Registrierung'),
    SETTING_KEYS['login_enabled']: ('false', 'Bot-Schutz bei Login'),
    SETTING_KEYS['recaptcha_version']: ('v2', 'reCAPTCHA-Version (v2 oder v3)'),
    SETTING_KEYS['recaptcha_site_key']: ('', 'reCAPTCHA Site Key'),
    SETTING_KEYS['recaptcha_secret_key']: ('', 'reCAPTCHA Secret Key'),
    SETTING_KEYS['turnstile_site_key']: ('', 'Cloudflare Turnstile Site Key'),
    SETTING_KEYS['turnstile_secret_key']: ('', 'Cloudflare Turnstile Secret Key'),
    SETTING_KEYS['honeypot_field']: ('', 'Honeypot-Feldname'),
}


def _get_setting_value(key: str, default: str = '') -> str:
    setting = SystemSettings.query.filter_by(key=key).first()
    if setting and setting.value is not None:
        return setting.value.strip()
    return default


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def upsert_setting(key: str, value: str, description: str | None = None) -> SystemSettings:
    setting = SystemSettings.query.filter_by(key=key).first()
    if setting:
        setting.value = value
        if description and not setting.description:
            setting.description = description
    else:
        desc = description or DEFAULT_SETTINGS.get(key, ('', ''))[1]
        setting = SystemSettings(key=key, value=value, description=desc)
        db.session.add(setting)
    return setting


def ensure_default_settings() -> None:
    """Seed missing bot-protection settings."""
    for key, (value, description) in DEFAULT_SETTINGS.items():
        if not SystemSettings.query.filter_by(key=key).first():
            db.session.add(SystemSettings(key=key, value=value, description=description))


def generate_honeypot_field_name() -> str:
    alphabet = string.ascii_lowercase + string.digits
    suffix = ''.join(secrets.choice(alphabet) for _ in range(8))
    return f'field_{suffix}'


def get_config() -> dict[str, Any]:
    provider = _get_setting_value(SETTING_KEYS['provider'], 'none')
    if provider not in VALID_PROVIDERS:
        provider = 'none'

    recaptcha_version = _get_setting_value(SETTING_KEYS['recaptcha_version'], 'v2')
    if recaptcha_version not in VALID_RECAPTCHA_VERSIONS:
        recaptcha_version = 'v2'

    honeypot_field = _get_setting_value(SETTING_KEYS['honeypot_field'], '')
    if provider == 'honeypot' and not honeypot_field:
        honeypot_field = generate_honeypot_field_name()
        upsert_setting(SETTING_KEYS['honeypot_field'], honeypot_field)
        db.session.commit()

    return {
        'provider': provider,
        'register_enabled': _as_bool(
            _get_setting_value(SETTING_KEYS['register_enabled'], 'true'),
            default=True,
        ),
        'login_enabled': _as_bool(
            _get_setting_value(SETTING_KEYS['login_enabled'], 'false'),
            default=False,
        ),
        'recaptcha_version': recaptcha_version,
        'recaptcha_site_key': _get_setting_value(SETTING_KEYS['recaptcha_site_key'], ''),
        'recaptcha_secret_key': _get_setting_value(SETTING_KEYS['recaptcha_secret_key'], ''),
        'turnstile_site_key': _get_setting_value(SETTING_KEYS['turnstile_site_key'], ''),
        'turnstile_secret_key': _get_setting_value(SETTING_KEYS['turnstile_secret_key'], ''),
        'honeypot_field': honeypot_field,
    }


def is_configured(config: dict[str, Any] | None = None) -> bool:
    config = config or get_config()
    provider = config['provider']
    if provider == 'none':
        return True
    if provider == 'honeypot':
        return bool(config.get('honeypot_field'))
    if provider == 'recaptcha':
        return bool(config.get('recaptcha_site_key') and config.get('recaptcha_secret_key'))
    if provider == 'turnstile':
        return bool(config.get('turnstile_site_key') and config.get('turnstile_secret_key'))
    return False


def is_enabled_for(context: BotContext, config: dict[str, Any] | None = None) -> bool:
    config = config or get_config()
    if config['provider'] == 'none':
        return False
    if not is_configured(config):
        return False
    if context == 'register':
        return config['register_enabled']
    if context == 'login':
        return config['login_enabled']
    return False


def get_template_context() -> dict[str, Any]:
    config = get_config()
    return {
        'bot_config': config,
        'bot_enabled_register': is_enabled_for('register', config),
        'bot_enabled_login': is_enabled_for('login', config),
    }


def _verify_honeypot(request, config: dict[str, Any]) -> tuple[bool, str | None]:
    field = config.get('honeypot_field') or ''
    if not field:
        return False, 'honeypot_misconfigured'
    if request.form.get(field, '').strip():
        return False, 'honeypot_triggered'
    return True, None


def _verify_recaptcha(request, config: dict[str, Any]) -> tuple[bool, str | None]:
    token = request.form.get('g-recaptcha-response', '').strip()
    if not token:
        return False, 'recaptcha_missing'

    secret = config.get('recaptcha_secret_key', '')
    if not secret:
        return False, 'recaptcha_misconfigured'

    try:
        response = requests.post(
            'https://www.google.com/recaptcha/api/siteverify',
            data={'secret': secret, 'response': token},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException:
        return False, 'recaptcha_unreachable'

    if not result.get('success'):
        return False, 'recaptcha_failed'

    if config.get('recaptcha_version') == 'v3':
        score = result.get('score', 0)
        if score < 0.5:
            return False, 'recaptcha_low_score'

    return True, None


def _verify_turnstile(request, config: dict[str, Any]) -> tuple[bool, str | None]:
    token = request.form.get('cf-turnstile-response', '').strip()
    if not token:
        return False, 'turnstile_missing'

    secret = config.get('turnstile_secret_key', '')
    if not secret:
        return False, 'turnstile_misconfigured'

    try:
        response = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': secret, 'response': token},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException:
        return False, 'turnstile_unreachable'

    if not result.get('success'):
        return False, 'turnstile_failed'

    return True, None


def apply_bot_protection_settings(data: dict[str, Any]) -> None:
    """Persist bot protection configuration (admin UI or setup)."""
    provider = data.get('provider', 'none')
    if provider not in VALID_PROVIDERS:
        provider = 'none'

    recaptcha_version = data.get('recaptcha_version', 'v2')
    if recaptcha_version not in VALID_RECAPTCHA_VERSIONS:
        recaptcha_version = 'v2'

    upsert_setting(SETTING_KEYS['provider'], provider)
    upsert_setting(
        SETTING_KEYS['register_enabled'],
        'true' if data.get('register_enabled', True) else 'false',
    )
    upsert_setting(
        SETTING_KEYS['login_enabled'],
        'true' if data.get('login_enabled', False) else 'false',
    )
    upsert_setting(SETTING_KEYS['recaptcha_version'], recaptcha_version)
    upsert_setting(SETTING_KEYS['recaptcha_site_key'], data.get('recaptcha_site_key', '') or '')
    upsert_setting(SETTING_KEYS['recaptcha_secret_key'], data.get('recaptcha_secret_key', '') or '')
    upsert_setting(SETTING_KEYS['turnstile_site_key'], data.get('turnstile_site_key', '') or '')
    upsert_setting(SETTING_KEYS['turnstile_secret_key'], data.get('turnstile_secret_key', '') or '')

    if provider == 'honeypot':
        honeypot_field = data.get('honeypot_field') or generate_honeypot_field_name()
        upsert_setting(SETTING_KEYS['honeypot_field'], honeypot_field)


def validate_bot_protection(request, context: BotContext) -> tuple[bool, str | None]:
    config = get_config()
    if not is_enabled_for(context, config):
        return True, None

    provider = config['provider']
    if provider == 'honeypot':
        return _verify_honeypot(request, config)
    if provider == 'recaptcha':
        return _verify_recaptcha(request, config)
    if provider == 'turnstile':
        return _verify_turnstile(request, config)

    return True, None
