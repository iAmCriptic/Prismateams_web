"""Shared file I/O, date parsing, and ID-resolution helpers for backup modules."""

from __future__ import annotations

import base64
import os
import secrets
from datetime import date, datetime, time
from typing import Dict, Iterable, Optional

from flask import current_app
from werkzeug.utils import secure_filename


def project_root() -> str:
    return os.path.dirname(current_app.root_path)


def upload_root() -> str:
    cfg = current_app.config.get("UPLOAD_FOLDER", "uploads")
    if os.path.isabs(cfg):
        return cfg
    return os.path.join(project_root(), cfg)


def resolve_existing_file(path_candidates: Iterable[Optional[str]]) -> Optional[str]:
    """Return the first existing file path from candidates."""
    for candidate in path_candidates:
        if not candidate or not isinstance(candidate, str):
            continue
        cleaned = candidate.strip()
        if not cleaned or cleaned.startswith(("http://", "https://")):
            continue
        if os.path.isfile(cleaned):
            return cleaned
        rel_project = os.path.join(project_root(), cleaned.lstrip("/\\"))
        if os.path.isfile(rel_project):
            return rel_project
        rel_upload = os.path.join(upload_root(), cleaned.lstrip("/\\"))
        if os.path.isfile(rel_upload):
            return rel_upload
        if cleaned.startswith("/uploads/"):
            rel_stripped = os.path.join(upload_root(), cleaned.replace("/uploads/", "", 1).lstrip("/\\"))
            if os.path.isfile(rel_stripped):
                return rel_stripped
    return None


def read_file_base64(path_candidates: Iterable[Optional[str]]) -> Optional[str]:
    """Read the first existing candidate file and return its base64 string."""
    found = resolve_existing_file(path_candidates)
    if not found:
        return None
    try:
        with open(found, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as exc:
        current_app.logger.error(f"Backup: Fehler beim Lesen von {found}: {exc}")
        return None


def write_base64_file(
    b64_content: Optional[str],
    subdir: str,
    original_name: Optional[str] = None,
    prefix: Optional[str] = None,
) -> Optional[str]:
    """Decode base64 content into ``<upload_root>/<subdir>/`` and return the saved path."""
    if not b64_content:
        return None
    try:
        raw = base64.b64decode(b64_content)
        target_dir = os.path.join(upload_root(), subdir) if subdir else upload_root()
        os.makedirs(target_dir, exist_ok=True)
        safe_name = secure_filename(os.path.basename(original_name or "file.bin")) or "file.bin"
        stamp = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        filename = f"{prefix}_{stamp}_{safe_name}" if prefix else f"{stamp}_{safe_name}"
        full_path = os.path.join(target_dir, filename)
        with open(full_path, "wb") as f:
            f.write(raw)
        return full_path
    except Exception as exc:
        current_app.logger.error(f"Backup: Fehler beim Schreiben in {subdir}: {exc}")
        return None


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except Exception:
        return None


def parse_time(value: Optional[str]) -> Optional[time]:
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except Exception:
        return None


def resolve_user_id(
    email: Optional[str],
    user_map: Dict[str, int],
    fallback_user_id: Optional[int] = None,
) -> Optional[int]:
    if email and email in user_map:
        return user_map[email]
    return fallback_user_id


def resolve_team_id(
    team_name: Optional[str],
    team_map: Optional[Dict[str, int]] = None,
    fallback_team_id: Optional[int] = None,
) -> Optional[int]:
    if team_name:
        if team_map and team_name in team_map:
            return team_map[team_name]
        from app.models.team import Team

        team = Team.query.filter_by(name=team_name).first()
        if team:
            if team_map is not None:
                team_map[team_name] = team.id
            return team.id
    if fallback_team_id is not None:
        from app.models.team import Team

        if Team.query.get(fallback_team_id):
            return fallback_team_id
    return None
