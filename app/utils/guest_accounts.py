"""
Helpers für Gast-Accounts und die konfigurierbare Gast-E-Mail-Domain.
"""
from __future__ import annotations

import re
from typing import Optional

DEFAULT_GUEST_EMAIL_DOMAIN = "gast.system.local"
GUEST_EMAIL_DOMAIN_SETTING_KEY = "guest_email_domain"

# Domain ohne @: Kleinbuchstaben, Ziffern, Punkte, Bindestriche; kein führender/trailing Punkt.
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def normalize_guest_email_domain(raw: Optional[str]) -> Optional[str]:
    """Normalisiert und validiert eine Gast-Domain. Bei ungültig: None."""
    if raw is None:
        return None
    domain = raw.strip().lower().lstrip("@")
    if not domain or not _DOMAIN_RE.match(domain):
        return None
    if ".." in domain:
        return None
    return domain


def get_guest_email_domain() -> str:
    """Aktuelle Gast-E-Mail-Domain aus SystemSettings (ohne @)."""
    try:
        from app.models.settings import SystemSettings

        setting = SystemSettings.query.filter_by(key=GUEST_EMAIL_DOMAIN_SETTING_KEY).first()
        if setting and setting.value:
            normalized = normalize_guest_email_domain(setting.value)
            if normalized:
                return normalized
    except Exception:
        pass
    return DEFAULT_GUEST_EMAIL_DOMAIN


def get_guest_email_suffix() -> str:
    """Suffix inkl. @ für UI und Login-Erkennung."""
    return f"@{get_guest_email_domain()}"


def build_guest_email(username: str) -> str:
    """Baut die Login-E-Mail für einen Gast-Benutzernamen."""
    clean = (username or "").strip().lower()
    return f"{clean}@{get_guest_email_domain()}"


def parse_guest_login_email(email: str) -> Optional[str]:
    """
    Extrahiert den Gast-Benutzernamen, wenn die E-Mail zur konfigurierten Domain gehört.
    Sonst None.
    """
    if not email:
        return None
    value = email.strip().lower()
    suffix = get_guest_email_suffix().lower()
    if not value.endswith(suffix):
        return None
    username = value[: -len(suffix)]
    if not username or "@" in username:
        return None
    return username
