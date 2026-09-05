"""Upload-Allowlist für das Dateien-Modul."""
from __future__ import annotations

from flask import current_app, has_app_context


# Fallback wenn Config fehlt — bewusst ohne HTML/SVG/JS/EXE
DEFAULT_ALLOWED_EXTENSIONS = frozenset({
    'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp',
    'mp4', 'webm', 'ogg', 'mp3', 'wav', 'mov',
    'md', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'odt', 'ods', 'odp', 'csv', 'rtf',
    'zip', 'rar', '7z',
})


def get_allowed_upload_extensions():
    """Erlaubte Dateiendungen aus Config (kleingeschrieben, ohne Punkt)."""
    raw = None
    if has_app_context():
        raw = current_app.config.get('ALLOWED_EXTENSIONS')
    if not raw:
        return set(DEFAULT_ALLOWED_EXTENSIONS)
    if isinstance(raw, str):
        return {part.strip().lower().lstrip('.') for part in raw.split(',') if part.strip()}
    return {str(part).strip().lower().lstrip('.') for part in raw if str(part).strip()}


def upload_extension(filename: str | None) -> str:
    """Dateiendung ohne Punkt, kleingeschrieben — leer wenn keine."""
    name = (filename or '').rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    if '.' not in name:
        return ''
    return name.rsplit('.', 1)[-1].strip().lower()


def is_allowed_upload_filename(filename: str | None) -> bool:
    """True wenn Dateiname eine erlaubte Extension hat."""
    ext = upload_extension(filename)
    if not ext:
        return False
    return ext in get_allowed_upload_extensions()
