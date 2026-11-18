"""Nextcloud WebDAV provider."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional
from urllib.parse import quote, unquote, urlparse
from xml.sax.saxutils import escape as xml_escape

import requests

from app.utils.cloud_import.base import RemoteEntry

NS = {
    'd': 'DAV:',
}


class NextcloudLockError(ConnectionError):
    """Raised when Nextcloud rejects an operation due to an active WebDAV lock (HTTP 423)."""

    def __init__(self, message: str, owner: str | None = None):
        super().__init__(message)
        self.owner = owner


class NextcloudProvider:
    def __init__(self, server_url: str, username: str, app_password: str):
        self.server_url = (server_url or '').rstrip('/')
        self.username = (username or '').strip()
        self.app_password = app_password or ''
        if not self.server_url or not self.username or not self.app_password:
            raise ValueError('nextcloud_credentials_incomplete')
        self._session = requests.Session()
        self._session.auth = (self.username, self.app_password)
        self._session.headers.update({'User-Agent': 'PrismaTeams-CloudImport/1.0'})
        self._dav_root = f'{self.server_url}/remote.php/dav/files/{quote(self.username, safe="")}/'

    def _url_for(self, path: str = '') -> str:
        path = (path or '').lstrip('/')
        if not path:
            return self._dav_root
        parts = [quote(p, safe='') for p in path.split('/') if p]
        return self._dav_root + '/'.join(parts)

    def _rel_path_from_href(self, href: str) -> str:
        parsed = urlparse(href)
        href_path = unquote(parsed.path or href)
        marker = f'/remote.php/dav/files/{self.username}/'
        idx = href_path.find(marker)
        if idx >= 0:
            return href_path[idx + len(marker):].strip('/')
        # try encoded username
        marker2 = f'/remote.php/dav/files/{quote(self.username, safe="")}/'
        idx = href_path.find(marker2)
        if idx >= 0:
            return href_path[idx + len(marker2):].strip('/')
        return href_path.strip('/')

    def test_connection(self) -> None:
        resp = self._session.request(
            'PROPFIND',
            self._dav_root,
            headers={'Depth': '0'},
            data='<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>',
            timeout=30,
        )
        if resp.status_code not in (207, 200):
            raise ConnectionError(f'nextcloud_auth_failed:{resp.status_code}')

    def list_children(self, path_or_id: str = '') -> list[RemoteEntry]:
        url = self._url_for(path_or_id)
        resp = self._session.request(
            'PROPFIND',
            url,
            headers={'Depth': '1'},
            data=(
                '<?xml version="1.0"?>'
                '<d:propfind xmlns:d="DAV:">'
                '<d:prop><d:displayname/><d:getcontentlength/><d:getetag/><d:getcontenttype/><d:resourcetype/></d:prop>'
                '</d:propfind>'
            ),
            timeout=60,
        )
        if resp.status_code not in (207, 200):
            raise ConnectionError(f'nextcloud_list_failed:{resp.status_code}')

        if not resp.content:
            return []
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            return []
        current_rel = (path_or_id or '').strip('/')
        entries: list[RemoteEntry] = []
        for resp_el in root.findall('d:response', NS):
            href_el = resp_el.find('d:href', NS)
            if href_el is None or not href_el.text:
                continue
            rel = self._rel_path_from_href(href_el.text)
            if rel == current_rel or (not rel and not current_rel):
                continue
            # only direct children
            if current_rel:
                if not rel.startswith(current_rel + '/'):
                    continue
                rest = rel[len(current_rel) + 1:]
                if '/' in rest:
                    continue
            elif '/' in rel:
                continue

            prop_elements = []
            for ps in resp_el.findall('d:propstat', NS):
                st = ps.find('d:status', NS)
                if st is not None and st.text and '200' not in st.text:
                    continue
                p_el = ps.find('d:prop', NS)
                if p_el is not None:
                    prop_elements.append(p_el)
            if not prop_elements:
                ps_first = resp_el.find('d:propstat', NS)
                p_first = ps_first.find('d:prop', NS) if ps_first is not None else None
                if p_first is not None:
                    prop_elements.append(p_first)

            is_dir = False
            size = 0
            etag = ''
            content_type = ''
            name = rel.rsplit('/', 1)[-1] if rel else ''
            for prop in prop_elements:
                rt = prop.find('d:resourcetype', NS)
                if rt is not None and rt.find('d:collection', NS) is not None:
                    is_dir = True
                length_el = prop.find('d:getcontentlength', NS)
                if length_el is not None and length_el.text:
                    try:
                        size = int(length_el.text)
                    except ValueError:
                        size = 0
                etag_el = prop.find('d:getetag', NS)
                if etag_el is not None and etag_el.text:
                    etag = etag_el.text.strip().strip('"')
                ct_el = prop.find('d:getcontenttype', NS)
                if ct_el is not None and ct_el.text:
                    content_type = ct_el.text.strip()
                dn = prop.find('d:displayname', NS)
                if dn is not None and dn.text:
                    name = dn.text
            entries.append(
                RemoteEntry(
                    id=rel,
                    name=name,
                    is_dir=is_dir,
                    size=size,
                    path=rel,
                    etag=etag,
                    content_type=content_type,
                )
            )
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def _list_recursive_files(self, path: str) -> list[RemoteEntry]:
        """Collect all files under a folder path."""
        result: list[RemoteEntry] = []
        stack = [path.strip('/')]
        while stack:
            current = stack.pop()
            for entry in self.list_children(current):
                if entry.is_dir:
                    stack.append(entry.id)
                else:
                    result.append(entry)
        return result

    def collect_selected_entries(
        self, selected: list[dict[str, Any]]
    ) -> list[RemoteEntry]:
        files: list[RemoteEntry] = []
        for item in selected:
            path = (item.get('id') or item.get('path') or '').strip('/')
            is_dir = bool(item.get('is_dir'))
            if is_dir:
                files.extend(self._list_recursive_files(path))
            else:
                name = item.get('name') or path.rsplit('/', 1)[-1]
                size = int(item.get('size') or 0)
                files.append(RemoteEntry(id=path, name=name, is_dir=False, size=size, path=path))
        seen = set()
        out = []
        for entry in files:
            if entry.id in seen:
                continue
            seen.add(entry.id)
            out.append(entry)
        return out

    def iter_selected_files(
        self, selected: list[dict[str, Any]]
    ) -> Iterable[tuple[str, int, Any]]:
        for entry in self.collect_selected_entries(selected):
            stream = self.download_stream(entry.id)
            yield entry.path or entry.id, entry.size, stream

    def download_stream(self, path: str):
        url = self._url_for(path)
        resp = self._session.get(url, timeout=120)
        if resp.status_code != 200:
            raise ConnectionError(f'nextcloud_download_failed:{resp.status_code}')
        return io.BytesIO(resp.content)

    def download_bytes(self, path: str) -> bytes:
        url = self._url_for(path)
        resp = self._session.get(url, timeout=120)
        if resp.status_code != 200:
            raise ConnectionError(f'nextcloud_download_failed:{resp.status_code}')
        return resp.content

    def _raise_if_locked(self, resp: requests.Response, path: str) -> None:
        if resp.status_code == 423:
            info = None
            try:
                info = self.get_lock_info(path)
            except Exception:
                info = None
            owner = (info or {}).get('owner')
            raise NextcloudLockError('nextcloud_resource_locked', owner=owner)

    def upload_bytes(
        self,
        path: str,
        data: bytes,
        *,
        content_type: str | None = None,
        lock_token: str | None = None,
    ) -> str:
        url = self._url_for(path)
        headers: dict[str, str] = {}
        if content_type:
            headers['Content-Type'] = content_type
        if lock_token:
            headers['If'] = f'(<{lock_token}>)'
        resp = self._session.put(url, data=data, headers=headers, timeout=120)
        self._raise_if_locked(resp, path)
        if resp.status_code not in (200, 201, 204):
            raise ConnectionError(f'nextcloud_upload_failed:{resp.status_code}')
        return (resp.headers.get('ETag') or '').strip().strip('"')

    def create_folder(self, path: str) -> None:
        clean = (path or '').strip('/')
        if not clean:
            return
        parts = [p for p in clean.split('/') if p]
        acc = ''
        for part in parts:
            acc = f'{acc}/{part}' if acc else part
            url = self._url_for(acc)
            resp = self._session.request('MKCOL', url, timeout=30)
            # 405 Method Not Allowed means collection already exists in WebDAV
            if resp.status_code not in (201, 200, 204, 405):
                raise ConnectionError(f'nextcloud_mkcol_failed:{resp.status_code}')

    def move_entry(
        self,
        src_path: str,
        dst_path: str,
        *,
        overwrite: bool = False,
        lock_token: str | None = None,
    ) -> None:
        src_url = self._url_for(src_path)
        dst_url = self._url_for(dst_path)
        headers = {
            'Destination': dst_url,
            'Overwrite': 'T' if overwrite else 'F',
        }
        if lock_token:
            headers['If'] = f'(<{lock_token}>)'
        resp = self._session.request('MOVE', src_url, headers=headers, timeout=60)
        self._raise_if_locked(resp, src_path)
        if resp.status_code not in (201, 204):
            raise ConnectionError(f'nextcloud_move_failed:{resp.status_code}')

    def delete_entry(self, path: str, *, lock_token: str | None = None) -> None:
        url = self._url_for(path)
        headers: dict[str, str] = {}
        if lock_token:
            headers['If'] = f'(<{lock_token}>)'
        resp = self._session.delete(url, headers=headers, timeout=60)
        self._raise_if_locked(resp, path)
        if resp.status_code not in (200, 202, 204, 404):
            raise ConnectionError(f'nextcloud_delete_failed:{resp.status_code}')

    def lock_resource(
        self,
        path: str,
        *,
        owner: str = 'PrismaTeams',
        timeout_seconds: int = 300,
    ) -> tuple[str, datetime]:
        url = self._url_for(path)
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:lockinfo xmlns:d="DAV:">'
            '<d:lockscope><d:exclusive/></d:lockscope>'
            '<d:locktype><d:write/></d:locktype>'
            f'<d:owner><d:href>{xml_escape(owner or "PrismaTeams")}</d:href></d:owner>'
            '</d:lockinfo>'
        )
        headers = {
            'Content-Type': 'application/xml; charset=utf-8',
            'Timeout': f'Second-{max(60, int(timeout_seconds))}',
            'Depth': '0',
        }
        resp = self._session.request('LOCK', url, headers=headers, data=body.encode('utf-8'), timeout=30)
        self._raise_if_locked(resp, path)
        if resp.status_code not in (200, 201):
            raise ConnectionError(f'nextcloud_lock_failed:{resp.status_code}')
        token = (resp.headers.get('Lock-Token') or '').strip().strip('<>')
        if not token and resp.content:
            try:
                root = ET.fromstring(resp.content)
                tok_el = root.find('.//d:locktoken/d:href', NS)
                if tok_el is not None and tok_el.text:
                    token = tok_el.text.strip().strip('<>')
            except ET.ParseError:
                pass
        if not token:
            raise ConnectionError('nextcloud_lock_missing_token')
        expires_at = datetime.utcnow() + timedelta(seconds=max(60, int(timeout_seconds)))
        return token, expires_at

    def refresh_lock(
        self,
        path: str,
        lock_token: str,
        *,
        timeout_seconds: int = 300,
    ) -> datetime:
        url = self._url_for(path)
        headers = {
            'If': f'(<{lock_token}>)',
            'Timeout': f'Second-{max(60, int(timeout_seconds))}',
        }
        resp = self._session.request('LOCK', url, headers=headers, timeout=30)
        self._raise_if_locked(resp, path)
        if resp.status_code not in (200, 201):
            raise ConnectionError(f'nextcloud_lock_refresh_failed:{resp.status_code}')
        return datetime.utcnow() + timedelta(seconds=max(60, int(timeout_seconds)))

    def unlock_resource(self, path: str, lock_token: str) -> None:
        if not lock_token:
            return
        url = self._url_for(path)
        headers = {'Lock-Token': f'<{lock_token}>'}
        resp = self._session.request('UNLOCK', url, headers=headers, timeout=30)
        if resp.status_code not in (200, 204, 404, 409, 412):
            raise ConnectionError(f'nextcloud_unlock_failed:{resp.status_code}')

    def get_lock_info(self, path: str) -> dict[str, Any] | None:
        url = self._url_for(path)
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:">'
            '<d:prop><d:lockdiscovery/></d:prop>'
            '</d:propfind>'
        )
        resp = self._session.request(
            'PROPFIND',
            url,
            headers={'Depth': '0', 'Content-Type': 'application/xml; charset=utf-8'},
            data=body.encode('utf-8'),
            timeout=30,
        )
        if resp.status_code not in (200, 207) or not resp.content:
            return None
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            return None
        active = root.find('.//d:lockdiscovery/d:activelock', NS)
        if active is None:
            return None
        tok_el = active.find('.//d:locktoken/d:href', NS)
        owner_el = active.find('.//d:owner/d:href', NS)
        if owner_el is None:
            owner_el = active.find('.//d:owner', NS)
        owner_text = (owner_el.text or '').strip() if owner_el is not None and owner_el.text else None
        token_text = (tok_el.text or '').strip().strip('<>') if tok_el is not None and tok_el.text else None
        return {'token': token_text, 'owner': owner_text}


def build_nextcloud_provider(creds: dict) -> NextcloudProvider:
    return NextcloudProvider(
        server_url=creds.get('server_url') or '',
        username=creds.get('username') or '',
        app_password=creds.get('app_password') or '',
    )
