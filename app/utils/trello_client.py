"""Lightweight Trello REST API client for optional board & media import."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import requests
from flask import session

logger = logging.getLogger(__name__)

TRELLO_API_BASE = 'https://api.trello.com/1'
_TRELLO_SESSION_KEY = 'kanban_trello_auth'
_TIMEOUT = 25


class TrelloApiError(RuntimeError):
    """Raised when a Trello API request fails."""

    def __init__(self, code: str, message: str = ''):
        super().__init__(message or code)
        self.code = code


def build_trello_oauth_header(api_key: str, token: str) -> str:
    """Build OAuth 1.0 header accepted by Trello API & attachment download URLs."""
    return f'OAuth oauth_consumer_key="{api_key}", oauth_token="{token}"'


def is_trello_url(url: str) -> bool:
    """Return True if *url* points to Trello or Trello-hosted attachment storage."""
    try:
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        return False
    return (
        host == 'trello.com'
        or host.endswith('.trello.com')
        or host == 'trello-attachments.s3.amazonaws.com'
    )


def _trello_get(path: str, api_key: str, token: str, params: dict[str, Any] | None = None) -> Any:
    query = dict(params or {})
    query['key'] = api_key
    query['token'] = token
    try:
        resp = requests.get(
            f'{TRELLO_API_BASE}{path}',
            params=query,
            headers={'Accept': 'application/json'},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning('Trello API request error for %s: %s', path, exc)
        raise TrelloApiError('network_error', str(exc)) from exc

    if resp.status_code in (401, 403):
        raise TrelloApiError('unauthorized', 'Invalid Trello API key or token')
    if resp.status_code == 404:
        raise TrelloApiError('not_found', 'Trello resource not found')
    if resp.status_code >= 400:
        raise TrelloApiError('api_error', f'HTTP {resp.status_code}')

    try:
        return resp.json()
    except ValueError as exc:
        raise TrelloApiError('invalid_response', str(exc)) from exc


def validate_trello_credentials(api_key: str, token: str) -> dict[str, str]:
    """Validate API key + token against /1/members/me and return basic profile."""
    key = (api_key or '').strip()
    tok = (token or '').strip()
    if not key or not tok:
        raise TrelloApiError('missing_credentials', 'API key and token are required')
    data = _trello_get('/members/me', key, tok, {'fields': 'id,username,fullName'})
    return {
        'id': str(data.get('id') or ''),
        'username': str(data.get('username') or ''),
        'full_name': str(data.get('fullName') or data.get('username') or 'Trello'),
    }


def list_trello_boards(api_key: str, token: str) -> list[dict[str, Any]]:
    """Return open Trello boards accessible to the authenticated user."""
    boards = _trello_get(
        '/members/me/boards',
        api_key,
        token,
        {
            'filter': 'open',
            'fields': 'id,name,desc,url,prefs,dateLastActivity,closed',
        },
    )
    if not isinstance(boards, list):
        return []
    result: list[dict[str, Any]] = []
    for b in boards:
        if not isinstance(b, dict) or not b.get('id'):
            continue
        prefs = b.get('prefs') or {}
        result.append({
            'id': str(b['id']),
            'name': str(b.get('name') or 'Untitled'),
            'desc': str(b.get('desc') or ''),
            'url': str(b.get('url') or ''),
            'background_color': prefs.get('backgroundColor') or '',
            'last_activity': b.get('dateLastActivity') or '',
        })
    return result


def fetch_trello_board_json(api_key: str, token: str, board_id: str) -> dict[str, Any]:
    """Fetch a complete Trello board payload compatible with _import_trello_json."""
    bid = (board_id or '').strip()
    if not bid:
        raise TrelloApiError('not_found', 'Missing board id')
    data = _trello_get(
        f'/boards/{bid}',
        api_key,
        token,
        {
            'fields': 'all',
            'lists': 'all',
            'cards': 'all',
            'card_attachments': 'true',
            'checklists': 'all',
            'labels': 'all',
            'members': 'all',
            'memberships': 'all',
            'customFields': 'true',
            'card_customFieldItems': 'true',
        },
    )
    if not isinstance(data, dict):
        raise TrelloApiError('invalid_response', 'Expected JSON object')
    return data


def save_trello_session_auth(api_key: str, token: str, profile: dict[str, str]) -> None:
    session[_TRELLO_SESSION_KEY] = {
        'api_key': api_key.strip(),
        'token': token.strip(),
        'username': profile.get('username') or '',
        'full_name': profile.get('full_name') or '',
    }
    session.modified = True


def get_trello_session_auth() -> tuple[str, str] | None:
    entry = session.get(_TRELLO_SESSION_KEY)
    if not isinstance(entry, dict):
        return None
    key = (entry.get('api_key') or '').strip()
    tok = (entry.get('token') or '').strip()
    if not key or not tok:
        return None
    return (key, tok)


def get_trello_session_profile() -> dict[str, str] | None:
    entry = session.get(_TRELLO_SESSION_KEY)
    if not isinstance(entry, dict) or not entry.get('api_key') or not entry.get('token'):
        return None
    return {
        'username': str(entry.get('username') or ''),
        'full_name': str(entry.get('full_name') or ''),
    }


def clear_trello_session_auth() -> None:
    session.pop(_TRELLO_SESSION_KEY, None)
    session.modified = True
