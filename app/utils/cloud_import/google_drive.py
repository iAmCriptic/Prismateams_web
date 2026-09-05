"""Google Drive API provider (readonly)."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

import requests

from app.utils.cloud_import.base import RemoteEntry
from app.utils.integrations import get_google_credentials

DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
FOLDER_MIME = 'application/vnd.google-apps.folder'
EXPORT_MAP = {
    'application/vnd.google-apps.document': (
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.docx',
    ),
    'application/vnd.google-apps.spreadsheet': (
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xlsx',
    ),
    'application/vnd.google-apps.presentation': (
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.pptx',
    ),
}


class GoogleDriveProvider:
    def __init__(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        on_token_refresh=None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.on_token_refresh = on_token_refresh
        self._session = requests.Session()

    def _ensure_token(self) -> None:
        if self.expires_at and datetime.utcnow() < self.expires_at - timedelta(seconds=60):
            return
        if not self.refresh_token:
            return
        creds = get_google_credentials()
        resp = requests.post(
            'https://oauth2.googleapis.com/token',
            data={
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token,
                'client_id': creds['client_id'],
                'client_secret': creds['client_secret'],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data['access_token']
        self.expires_at = datetime.utcnow() + timedelta(seconds=int(data.get('expires_in', 3600)))
        if self.on_token_refresh:
            self.on_token_refresh(self.access_token, self.expires_at)

    def _headers(self) -> dict:
        self._ensure_token()
        return {'Authorization': f'Bearer {self.access_token}'}

    def test_connection(self) -> None:
        resp = self._session.get(
            'https://www.googleapis.com/drive/v3/about',
            params={'fields': 'user'},
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            raise ConnectionError(f'google_drive_auth_failed:{resp.status_code}')

    def list_children(self, path_or_id: str = '') -> list[RemoteEntry]:
        parent = path_or_id or 'root'
        q = f"'{parent}' in parents and trashed=false"
        entries: list[RemoteEntry] = []
        page_token = None
        while True:
            params = {
                'q': q,
                'fields': 'nextPageToken,files(id,name,mimeType,size)',
                'pageSize': 200,
                'orderBy': 'folder,name',
                'supportsAllDrives': 'true',
                'includeItemsFromAllDrives': 'true',
            }
            if page_token:
                params['pageToken'] = page_token
            resp = self._session.get(
                'https://www.googleapis.com/drive/v3/files',
                params=params,
                headers=self._headers(),
                timeout=60,
            )
            if resp.status_code != 200:
                raise ConnectionError(f'google_drive_list_failed:{resp.status_code}')
            data = resp.json()
            for f in data.get('files') or []:
                is_dir = f.get('mimeType') == FOLDER_MIME
                size = int(f.get('size') or 0)
                entries.append(RemoteEntry(
                    id=f['id'],
                    name=f.get('name') or f['id'],
                    is_dir=is_dir,
                    size=size,
                    path=f['id'],
                ))
            page_token = data.get('nextPageToken')
            if not page_token:
                break
        return entries

    def _list_recursive_files(self, folder_id: str, prefix: str = '') -> list[tuple[str, dict]]:
        result = []
        for entry in self.list_children(folder_id):
            rel = f'{prefix}/{entry.name}'.lstrip('/') if prefix else entry.name
            if entry.is_dir:
                result.extend(self._list_recursive_files(entry.id, rel))
            else:
                result.append((rel, {
                    'id': entry.id,
                    'name': entry.name,
                    'size': entry.size,
                    'mimeType': None,
                }))
        return result

    def _get_meta(self, file_id: str) -> dict:
        resp = self._session.get(
            f'https://www.googleapis.com/drive/v3/files/{file_id}',
            params={'fields': 'id,name,mimeType,size', 'supportsAllDrives': 'true'},
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            raise ConnectionError(f'google_drive_meta_failed:{resp.status_code}')
        return resp.json()

    def download_bytes(self, file_id: str, mime_type: Optional[str] = None) -> tuple[bytes, str]:
        """Return (content, filename_extension_hint)."""
        meta = self._get_meta(file_id) if not mime_type else {'id': file_id, 'mimeType': mime_type, 'name': ''}
        mime = meta.get('mimeType') or ''
        name = meta.get('name') or file_id

        if mime in EXPORT_MAP:
            export_mime, ext = EXPORT_MAP[mime]
            resp = self._session.get(
                f'https://www.googleapis.com/drive/v3/files/{file_id}/export',
                params={'mimeType': export_mime},
                headers=self._headers(),
                timeout=120,
            )
            if resp.status_code != 200:
                raise ConnectionError(f'google_drive_export_failed:{resp.status_code}')
            if not name.lower().endswith(ext):
                name = name + ext
            return resp.content, name

        resp = self._session.get(
            f'https://www.googleapis.com/drive/v3/files/{file_id}',
            params={'alt': 'media', 'supportsAllDrives': 'true'},
            headers=self._headers(),
            timeout=120,
        )
        if resp.status_code != 200:
            raise ConnectionError(f'google_drive_download_failed:{resp.status_code}')
        return resp.content, name

    def collect_selected_entries(self, selected: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
        """Return list of (relative_path, file_id, size)."""
        items: list[tuple[str, str, int]] = []
        for item in selected:
            file_id = item.get('id') or ''
            is_dir = bool(item.get('is_dir'))
            name = item.get('name') or file_id
            if is_dir:
                for rel, meta in self._list_recursive_files(file_id, name):
                    items.append((rel, meta['id'], int(meta.get('size') or 0)))
            else:
                items.append((name, file_id, int(item.get('size') or 0)))
        seen = set()
        out = []
        for rel, file_id, size in items:
            if file_id in seen:
                continue
            seen.add(file_id)
            out.append((rel, file_id, size))
        return out

    def iter_selected_files(
        self, selected: list[dict[str, Any]]
    ) -> Iterable[tuple[str, int, Any]]:
        for rel, file_id, _size in self.collect_selected_entries(selected):
            content, final_name = self.download_bytes(file_id)
            if '/' in rel:
                parent, _ = rel.rsplit('/', 1)
                rel_out = f'{parent}/{final_name}'
            else:
                rel_out = final_name
            yield rel_out, len(content), io.BytesIO(content)


def build_google_drive_provider(creds: dict, on_token_refresh=None) -> GoogleDriveProvider:
    expires_at = None
    raw_exp = creds.get('expires_at')
    if raw_exp:
        try:
            expires_at = datetime.fromisoformat(raw_exp)
        except ValueError:
            expires_at = None
    return GoogleDriveProvider(
        access_token=creds.get('access_token') or '',
        refresh_token=creds.get('refresh_token'),
        expires_at=expires_at,
        on_token_refresh=on_token_refresh,
    )
