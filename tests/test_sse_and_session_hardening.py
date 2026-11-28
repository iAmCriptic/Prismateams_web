"""Tests for Gunicorn gthread / SSE / Redis / healthz hardening."""

from unittest.mock import MagicMock, patch

from app import db
from app.blueprints import sse
from app.utils import server_session


def test_healthz_returns_ok(client):
    resp = client.get('/healthz')
    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'ok'}


def test_server_session_redis_uses_timeouts(app, monkeypatch):
    mock_client = MagicMock()
    mock_client.ping.return_value = True
    captured_kwargs = {}

    def fake_from_url(url, **kwargs):
        captured_kwargs['url'] = url
        captured_kwargs.update(kwargs)
        return mock_client

    monkeypatch.setattr(app, 'session_interface', app.session_interface)
    monkeypatch.setitem(app.config, 'REDIS_ENABLED', True)
    monkeypatch.setitem(app.config, 'REDIS_URL', 'redis://localhost:6379/0')

    with patch('redis.Redis.from_url', side_effect=fake_from_url):
        backend = server_session.configure_server_sessions(app)

    assert backend == 'redis'
    assert captured_kwargs.get('socket_connect_timeout', 0) > 0
    assert captured_kwargs.get('socket_timeout', 0) > 0
    assert captured_kwargs.get('health_check_interval', 0) > 0


def test_sse_redis_uses_timeouts(app, monkeypatch):
    mock_client = MagicMock()
    mock_client.ping.return_value = True
    captured_kwargs = {}

    def fake_from_url(url, **kwargs):
        captured_kwargs['url'] = url
        captured_kwargs.update(kwargs)
        return mock_client

    monkeypatch.setattr(sse, '_redis_client', None)
    monkeypatch.setattr(sse, '_redis_url', None)
    monkeypatch.setattr(app, 'session_interface', app.session_interface)
    monkeypatch.setitem(app.config, 'REDIS_ENABLED', True)
    monkeypatch.setitem(app.config, 'REDIS_URL', 'redis://localhost:6379/0')

    with patch('redis.Redis.from_url', side_effect=fake_from_url):
        client = sse.get_redis_client()

    assert client is mock_client
    assert captured_kwargs.get('socket_connect_timeout', 0) > 0
    assert captured_kwargs.get('socket_timeout', 0) > 0
    assert captured_kwargs.get('health_check_interval', 0) > 0


def test_sse_event_stream_releases_db_session(app, monkeypatch):
    monkeypatch.setattr(sse, 'get_redis_client', lambda: None)
    with patch.object(db.session, 'remove') as mock_remove:
        chunks = list(sse.event_stream(['music:updates']))
    assert mock_remove.called
    assert any('event: error' in c for c in chunks)


def test_sse_concurrency_cap_returns_503_and_releases_slot(client, monkeypatch):
    monkeypatch.setenv('SSE_MAX_CONCURRENT_PER_WORKER', '1')
    monkeypatch.setattr(sse, '_active_sse_streams', 0)
    monkeypatch.setattr(sse, 'get_redis_client', lambda: None)

    assert sse._acquire_sse_slot() is True
    try:
        resp_busy = client.get('/sse/events/music')
        assert resp_busy.status_code == 503
        assert resp_busy.headers.get('Retry-After') == '10'
    finally:
        sse._release_sse_slot()

    resp_ok = client.get('/sse/events/music')
    assert resp_ok.status_code == 200
    assert b'event: error' in resp_ok.data
    assert sse._active_sse_streams == 0
