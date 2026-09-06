"""Safe URL unfurl for Markdown link hover cards."""
from __future__ import annotations

import html as html_module
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

from flask import current_app, request
from flask_login import current_user

MAX_BYTES = 524288
FETCH_TIMEOUT = 3.5
USER_AGENT = 'Prismateams-LinkPreview/1.0'


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_public_http_url(newurl):
            raise urllib.error.URLError('redirect blocked')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def is_public_http_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    host = parsed.hostname
    if not host:
        return False
    if host.lower() in ('localhost', 'localhost.localdomain'):
        return False
    try:
        infos = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == 'https' else 80),
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror:
        return False
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
        if ip.version == 6 and ip in ipaddress.ip_network('fc00::/7'):
            return False
    return True


def _meta_content(html, prop):
    prop_re = re.escape(prop)
    patterns = [
        rf'<meta[^>]+(?:property|name)=["\']{prop_re}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{prop_re}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return html_module.unescape(match.group(1)).strip()
    return ''


def _html_title(html):
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ''
    title = re.sub(r'\s+', ' ', match.group(1))
    return html_module.unescape(title).strip()


def _truncate(text, limit):
    text = re.sub(r'\s+', ' ', text or '').strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + '…'


def _internal_file_preview(url):
    parsed = urlparse(url)
    path = parsed.path or url
    match = re.search(r'/files/view/(\d+)', path)
    if not match:
        return None
    file_id = int(match.group(1))
    from app.models.file import File
    from app.utils.private_files import can_view_file

    file = File.query.get(file_id)
    if not file or file.deleted_at:
        return {
            'ok': False,
            'kind': 'internal',
            'url': url,
            'title': '',
            'description': '',
            'error': 'not_found',
        }

    allowed = False
    try:
        if current_user.is_authenticated and (getattr(current_user, 'is_admin', False) or can_view_file(file, current_user)):
            allowed = True
    except Exception:
        allowed = False

    if not allowed:
        return {
            'ok': False,
            'kind': 'internal',
            'url': url,
            'title': '',
            'description': '',
            'error': 'forbidden',
        }

    display = file.original_name or file.name
    ext = ''
    if '.' in display:
        ext = display.rsplit('.', 1)[-1].upper()
    return {
        'ok': True,
        'kind': 'internal',
        'url': url,
        'title': display,
        'description': ext or 'File',
        'icon': 'file',
        'file_id': file.id,
    }


def _fetch_external(url):
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
        },
        method='GET',
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    with opener.open(req, timeout=FETCH_TIMEOUT) as resp:
        final_url = resp.geturl()
        if not is_public_http_url(final_url):
            raise urllib.error.URLError('unsafe final url')
        raw = resp.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raw = raw[:MAX_BYTES]
    html = raw.decode('utf-8', errors='replace')

    title = _meta_content(html, 'og:title') or _html_title(html) or urlparse(url).hostname or url
    description = _meta_content(html, 'og:description') or _meta_content(html, 'description')
    image = _meta_content(html, 'og:image')
    if image:
        image = urljoin(url, image)
        if not is_public_http_url(image):
            image = ''
    return {
        'ok': True,
        'kind': 'external',
        'url': url,
        'title': _truncate(title, 120),
        'description': _truncate(description, 220),
        'image': image,
        'site': urlparse(url).hostname or '',
    }


def build_link_preview(url):
    """Return a JSON-serializable preview payload for a URL."""
    from app.utils.i18n import translate

    raw = (url or '').strip()
    if not raw:
        return {'ok': False, 'error': 'empty', 'title': translate('markdown.editor.preview.invalid')}

    if raw.startswith('/') and not raw.startswith('//'):
        try:
            raw = urljoin(request.host_url, raw)
        except Exception:
            pass

    internal = _internal_file_preview(raw)
    if internal is not None:
        if not internal.get('ok'):
            err = internal.get('error')
            if err == 'forbidden':
                internal['title'] = translate('markdown.editor.preview.forbidden_title')
                internal['description'] = translate('markdown.editor.preview.forbidden_body')
            else:
                internal['title'] = translate('markdown.editor.preview.not_found_title')
                internal['description'] = translate('markdown.editor.preview.not_found_body')
        return internal

    parsed = urlparse(raw)
    if parsed.scheme not in ('http', 'https'):
        return {
            'ok': False,
            'kind': 'local',
            'url': raw,
            'title': parsed.path or raw,
            'description': '',
            'error': 'unsupported',
        }

    site = parsed.hostname or ''
    fallback = {
        'ok': False,
        'kind': 'external',
        'url': raw,
        'title': site or raw,
        'description': translate('markdown.editor.preview.unavailable_body'),
        'site': site,
        'error': 'fetch',
    }

    if not is_public_http_url(raw):
        fallback['title'] = translate('markdown.editor.preview.unavailable_title')
        return fallback

    try:
        return _fetch_external(raw)
    except Exception as exc:
        current_app.logger.debug('Link preview failed for %s: %s', raw, exc)
        fallback['title'] = translate('markdown.editor.preview.unavailable_title')
        return fallback
