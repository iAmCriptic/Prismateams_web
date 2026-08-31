"""Speicherung und Prüfung von Profilbild-Uploads."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

ALLOWED_PROFILE_PICTURE_EXTENSIONS = frozenset({'png', 'jpg', 'jpeg', 'gif'})
MAX_PROFILE_PICTURE_BYTES = 5 * 1024 * 1024


def _extension(filename: str) -> str:
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def get_uploaded_profile_picture(files) -> Optional[FileStorage]:
    """Liefert die hochgeladene Datei oder None, wenn nichts gewählt wurde."""
    file = files.get('profile_picture') if files else None
    if file and getattr(file, 'filename', None):
        return file
    return None


def validate_profile_picture_file(file: Optional[FileStorage]) -> Optional[str]:
    """Prüft Typ und Größe. Gibt 'type', 'size' oder None (gültig / leer) zurück."""
    if not file or not file.filename:
        return None
    if _extension(file.filename) not in ALLOWED_PROFILE_PICTURE_EXTENSIONS:
        return 'type'
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_PROFILE_PICTURE_BYTES:
        return 'size'
    return None


def save_uploaded_profile_picture(user, file: FileStorage) -> Optional[str]:
    """Speichert das Upload lokal und setzt user.profile_picture. User braucht eine ID."""
    if not user or not getattr(user, 'id', None) or not file or not file.filename:
        return None
    if validate_profile_picture_file(file):
        return None

    filename = secure_filename(file.filename)
    if not filename:
        return None

    try:
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f'{user.id}_{timestamp}_{filename}'

        project_root = os.path.dirname(current_app.root_path)
        upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'profile_pics')
        os.makedirs(upload_dir, exist_ok=True)

        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)

        if user.profile_picture:
            try:
                old_path = os.path.join(upload_dir, user.profile_picture)
                if os.path.exists(old_path):
                    os.remove(old_path)
            except OSError:
                pass

        user.profile_picture = filename
        return filename
    except Exception:
        current_app.logger.exception(
            'Profilbild konnte nicht gespeichert werden (user=%s)',
            getattr(user, 'id', None),
        )
        return None
