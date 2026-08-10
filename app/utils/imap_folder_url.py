"""URL-sichere IMAP-Ordnernamen (Gmail: /, & in modified UTF-7)."""

from __future__ import annotations

from urllib.parse import quote, unquote

from werkzeug.routing import BaseConverter


class ImapFolderConverter(BaseConverter):
    """Kodiert Ordnernamen so, dass /, & usw. ein einzelnes Path-Segment bleiben."""

    def to_python(self, value: str) -> str:
        return unquote(value or '')

    def to_url(self, value) -> str:
        return quote(str(value or ''), safe='')
