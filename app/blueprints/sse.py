"""
Server-Sent Events (SSE) Blueprint für Live-Updates.
Funktioniert perfekt mit mehreren Gunicorn-Workern ohne Session-Probleme.
"""

from flask import Blueprint, Response, stream_with_context, current_app, request, has_app_context, jsonify
from flask_login import current_user, login_required
import json
import time
import redis
import threading
import os
from queue import Queue, Empty

sse_bp = Blueprint('sse', __name__)

# Redis-Verbindung für Pub/Sub
_redis_client = None
_redis_lock = threading.Lock()
_redis_url = None  # Wird beim ersten Aufruf gesetzt

# Sync-/gthread-Worker nicht endlos blockieren: Stream nach TTL schließen.
# EventSource reconnectet automatisch; unter gunicorn --timeout halten.
# Clamp: zu kurz = Reconnect-Sturm; zu lang = Thread-Hunger (QA F09).
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def sse_stream_limits():
    """(max_age_seconds, heartbeat_seconds) — per Env, hart geclampt."""
    max_age = max(15, min(120, _env_int('SSE_MAX_STREAM_SECONDS', 45)))
    heartbeat = max(5, min(max(max_age // 3, 5), _env_int('SSE_HEARTBEAT_SECONDS', 15)))
    return max_age, heartbeat


# Rückwärtskompatibel für Imports/Tests
SSE_MAX_STREAM_SECONDS = sse_stream_limits()[0]
SSE_HEARTBEAT_SECONDS = sse_stream_limits()[1]


def get_redis_client():
    """Lazy-load Redis client."""
    global _redis_client, _redis_url
    if has_app_context() and not current_app.config.get('REDIS_ENABLED', False):
        return None

    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                try:
                    # Versuche Redis-URL aus current_app oder Umgebungsvariable zu holen
                    if has_app_context():
                        _redis_url = current_app.config.get('REDIS_URL', 'redis://localhost:6379/0')
                    elif _redis_url is None:
                        _redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
                    
                    _redis_client = redis.Redis.from_url(_redis_url, decode_responses=True)
                    _redis_client.ping()
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Redis nicht verfügbar für SSE: {e}")
                    _redis_client = None
    return _redis_client


def publish_event(channel, event_type, data):
    """Veröffentlicht ein Event über Redis Pub/Sub."""
    try:
        client = get_redis_client()
        if client:
            message = json.dumps({
                'event': event_type,
                'data': data,
                'timestamp': time.time()
            })
            client.publish(channel, message)
            return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"SSE publish fehlgeschlagen: {e}")
    return False


def _sse_stream_headers():
    """
    SSE-Response-Header ohne Access-Control-Allow-Origin: *.

    EventSource läuft same-origin (relative URLs). Cross-Origin nur, wenn
    Origin zum Request-Host passt oder in SOCKETIO_CORS_ORIGINS / PUBLIC_BASE_URL liegt.
    """
    headers = {
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
    }
    origin = (request.headers.get('Origin') or '').strip().rstrip('/')
    if not origin:
        return headers

    try:
        from urllib.parse import urlparse
        from app.factory._util import resolve_socketio_cors_origins

        allowed = resolve_socketio_cors_origins(current_app)
        parsed = urlparse(origin)
        origin_host = (parsed.netloc or '').lower()
        req_host = (request.host or '').lower()

        ok = False
        if allowed is None:
            ok = bool(origin_host) and origin_host == req_host
        elif isinstance(allowed, (list, tuple)):
            normalized = {o.rstrip('/') for o in allowed if o}
            ok = origin in normalized
        # allowed == '*': bewusst nicht spiegeln — SSE bleibt same-origin / Allowlist

        if ok:
            headers['Access-Control-Allow-Origin'] = origin
            headers['Vary'] = 'Origin'
    except Exception:
        pass
    return headers


def event_stream(channels, user_id=None):
    """Generator für SSE-Stream mit Redis Pub/Sub."""
    client = get_redis_client()
    
    if not client:
        # Fallback: Polling-basierte Updates ohne Redis
        yield f"event: error\ndata: {json.dumps({'message': 'Redis nicht verfügbar'})}\n\n"
        return
    
    pubsub = client.pubsub()
    
    try:
        # Abonniere die Kanäle
        for channel in channels:
            pubsub.subscribe(channel)
        
        yield f"event: connected\ndata: {json.dumps({'channels': channels})}\n\n"

        started = time.time()
        last_heartbeat = started
        max_age, heartbeat_s = sse_stream_limits()

        while True:
            try:
                if (time.time() - started) >= max_age:
                    # Graceful close → Browser EventSource reconnects; frees worker/thread.
                    yield f"event: reconnect\ndata: {json.dumps({'reason': 'ttl', 'after': max_age})}\n\n"
                    break

                message = pubsub.get_message(timeout=5.0)

                if message and message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        event_type = data.get('event', 'update')
                        event_data = data.get('data', {})

                        target_user = event_data.get('user_id')
                        if target_user and user_id and target_user != user_id:
                            continue

                        yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"
                    except json.JSONDecodeError:
                        pass

                if time.time() - last_heartbeat > heartbeat_s:
                    yield f"event: heartbeat\ndata: {json.dumps({'time': time.time()})}\n\n"
                    last_heartbeat = time.time()

            except GeneratorExit:
                break
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"SSE stream error: {e}")
                break

    finally:
        try:
            pubsub.unsubscribe()
            pubsub.close()
        except Exception:
            pass


@sse_bp.route('/events/dashboard')
@login_required
def dashboard_events():
    """SSE-Endpoint für Dashboard-Updates."""
    user_id = current_user.id
    channels = [
        f'dashboard:user:{user_id}',  # User-spezifische Updates
        'dashboard:global'  # Globale Updates
    ]
    
    def generate():
        yield from event_stream(channels, user_id)
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers=_sse_stream_headers(),
    )


@sse_bp.route('/events/music')
def music_events():
    """SSE-Endpoint für Musik-Updates (öffentlich für Wishlist)."""
    channels = ['music:updates']
    
    def generate():
        yield from event_stream(channels)
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers=_sse_stream_headers(),
    )


@sse_bp.route('/events/email')
@login_required
def email_events():
    """SSE-Endpoint für E-Mail-Sync-Status-Updates."""
    user_id = current_user.id
    channels = [f'email:sync:user:{user_id}']
    
    def generate():
        yield from event_stream(channels, user_id)
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers=_sse_stream_headers(),
    )


# Helper-Funktionen zum Senden von Events

def emit_dashboard_update(user_id, event_type, data):
    """Sendet ein Dashboard-Update an einen bestimmten Benutzer."""
    channel = f'dashboard:user:{user_id}'
    return publish_event(channel, f'dashboard:{event_type}', data)


def emit_dashboard_global(event_type, data):
    """Sendet ein globales Dashboard-Update an alle Benutzer."""
    channel = 'dashboard:global'
    return publish_event(channel, f'dashboard:{event_type}', data)


def emit_music_update(event_type, data):
    """Sendet ein Musik-Update an alle verbundenen Clients."""
    channel = 'music:updates'
    return publish_event(channel, f'music:{event_type}', data)


def emit_email_sync_status(user_id, event_type, data):
    """Sendet ein E-Mail-Sync-Status-Update an einen bestimmten Benutzer."""
    channel = f'email:sync:user:{user_id}'
    return publish_event(channel, f'email:{event_type}', data)


def emit_kanban_update(board_id, event_type, data):
    """Sendet ein Kanban-Board-Update an alle verbundenen Clients des Boards."""
    channel = f'kanban:board:{board_id}'
    return publish_event(channel, f'kanban:{event_type}', data)


def emit_chat_update(chat_id, event_type, data):
    """Sendet ein Chat-Live-Update an alle verbundenen Clients des Chats."""
    channel = f'chat:{chat_id}'
    payload = dict(data or {})
    payload.setdefault('chat_id', chat_id)
    return publish_event(channel, f'chat:{event_type}', payload)


def emit_inventory_update(inventory_id, event_type, data=None):
    """Sendet ein Inventur-Update an alle verbundenen Clients der Session."""
    channel = f'inventory:{inventory_id}'
    payload = dict(data or {})
    payload.setdefault('inventory_id', inventory_id)
    return publish_event(channel, f'inventory:{event_type}', payload)


@sse_bp.route('/events/chat/<int:chat_id>')
@login_required
def chat_events(chat_id):
    """SSE-Endpoint für Chat-Live-Updates (Nachrichten, Polls, RSVP)."""
    from app.models.chat import Chat, ChatMember

    Chat.query.get_or_404(chat_id)
    membership = ChatMember.query.filter_by(
        chat_id=chat_id,
        user_id=current_user.id,
    ).first()
    if not membership:
        return jsonify({'error': 'Forbidden'}), 403

    if not get_redis_client():
        return jsonify({'error': 'SSE unavailable'}), 503

    channels = [f'chat:{chat_id}']

    def generate():
        yield from event_stream(channels, current_user.id)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers=_sse_stream_headers(),
    )


@sse_bp.route('/events/kanban/<int:board_id>')
@login_required
def kanban_events(board_id):
    """SSE-Endpoint für Kanban-Board-Live-Updates."""
    from app.models.kanban import KanbanBoard
    from app.utils.kanban_access import can_view_board

    board = KanbanBoard.query.get_or_404(board_id)
    if not can_view_board(current_user, board) and not (
        board.closed_at and getattr(current_user, 'is_admin', False)
    ):
        return jsonify({'error': 'Forbidden'}), 403

    if not get_redis_client():
        return jsonify({'error': 'SSE unavailable'}), 503

    channels = [f'kanban:board:{board_id}']

    def generate():
        yield from event_stream(channels, current_user.id)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers=_sse_stream_headers(),
    )


@sse_bp.route('/events/inventory/<int:inventory_id>')
@login_required
def inventory_events(inventory_id):
    """SSE-Endpoint für Inventur-Session-Live-Updates."""
    from app.models.inventory import Inventory
    from app.utils.access_control import has_module_access
    from app.utils.common import is_module_enabled

    if not is_module_enabled('module_inventory') or not has_module_access(
        current_user, 'module_inventory'
    ):
        return jsonify({'error': 'Forbidden'}), 403

    Inventory.query.get_or_404(inventory_id)
    channels = [f'inventory:{inventory_id}']

    def generate():
        yield from event_stream(channels, current_user.id)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers=_sse_stream_headers(),
    )
