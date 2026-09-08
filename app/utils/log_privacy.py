"""Helpers to keep PII out of application logs."""

from __future__ import annotations

import re


_EMAIL_RE = re.compile(
    r'(?i)\b([A-Z0-9._%+\-]+)@([A-Z0-9.\-]+\.[A-Z]{2,})\b'
)


def mask_email(value: str | None) -> str:
    """Mask an email for logs: ``j***@e***.com`` (empty → ``?``)."""
    if value is None:
        return '?'
    text = str(value).strip()
    if not text:
        return '?'
    if '@' not in text:
        return _mask_local(text)
    local, _, domain = text.partition('@')
    if not local or not domain:
        return '***'
    return f'{_mask_local(local)}@{_mask_domain(domain)}'


def mask_emails_in_text(text: str | None) -> str:
    """Replace email-shaped tokens inside free-form log messages."""
    if text is None:
        return ''
    return _EMAIL_RE.sub(lambda m: mask_email(m.group(0)), str(text))


def _mask_local(local: str) -> str:
    local = local.strip()
    if not local:
        return '***'
    if len(local) == 1:
        return '*'
    return f'{local[0]}***'


def _mask_domain(domain: str) -> str:
    domain = domain.strip().lower()
    if not domain:
        return '***'
    parts = domain.rsplit('.', 1)
    if len(parts) == 1:
        return f'{parts[0][0]}***' if parts[0] else '***'
    name, tld = parts
    if not name:
        return f'***.{tld}'
    return f'{name[0]}***.{tld}'
