"""Nextcloud WebDAV provider."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Optional
from urllib.parse import quote, unquote, urlparse

import requests

from app.utils.cloud_import.base import RemoteEntry

NS = {
    'd': 'DAV:',
}


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
                '<d:prop><d:displayname/><d:getcontentlength/><d:resourcetype/></d:prop>'
                '</d:propfind>'
            ),
            timeout=60,
        )
        if resp.status_code not in (207, 200):
            raise ConnectionError(f'nextcloud_list_failed:{resp.status_code}')

        root = ET.fromstring(resp.content)
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

            propstat = resp_el.find('d:propstat', NS)
            prop = propstat.find('d:prop', NS) if propstat is not None else None
            is_dir = False
            size = 0
            name = rel.rsplit('/', 1)[-1] if rel else ''
            if prop is not None:
                rt = prop.find('d:resourcetype', NS)
                if rt is not None and rt.find('d:collection', NS) is not None:
                    is_dir = True
                length_el = prop.find('d:getcontentlength', NS)
                if length_el is not None and length_el.text:
                    try:
                        size = int(length_el.text)
                    except ValueError:
                        size = 0
                dn = prop.find('d:displayname', NS)
                if dn is not None and dn.text:
                    name = dn.text
            entries.append(RemoteEntry(id=rel, name=name, is_dir=is_dir, size=size, path=rel))
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


def build_nextcloud_provider(creds: dict) -> NextcloudProvider:
    return NextcloudProvider(
        server_url=creds.get('server_url') or '',
        username=creds.get('username') or '',
        app_password=creds.get('app_password') or '',
    )
