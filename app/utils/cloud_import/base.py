"""Shared types and credential helpers for cloud import providers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Protocol

from app.utils.multi_mailboxes import decrypt_password, encrypt_password


@dataclass
class RemoteEntry:
    id: str
    name: str
    is_dir: bool
    size: int = 0
    path: str = ''  # provider-specific path or breadcrumb


class CloudProvider(Protocol):
    def test_connection(self) -> None:
        ...

    def list_children(self, path_or_id: str = '') -> list[RemoteEntry]:
        ...

    def iter_selected_files(
        self, selected: list[dict[str, Any]]
    ) -> Iterable[tuple[str, int, Any]]:
        """Yield (relative_path, size, stream_or_bytes) for selected items."""
        ...


def encrypt_credentials(payload: dict) -> str:
    return encrypt_password(json.dumps(payload, ensure_ascii=False)) or ''


def decrypt_credentials(enc: Optional[str]) -> dict:
    raw = decrypt_password(enc) if enc else None
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
