"""
Server-Sent Events (SSE) Blueprint für Live-Updates.
Funktioniert perfekt mit mehreren Gunicorn-Workern ohne Session-Probleme.
"""

from flask import Blueprint, Response, stream_with_context, current_app, request, has_app_context
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


def get_redis_client():
    """Lazy-load Redis client."""
    global _redis_client, _redis_url
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
        
        # Sende initiales Heartbeat
        yield f"event: connected\ndata: {json.dumps({'channels': channels})}\n\n"
        
        # Heartbeat-Thread starten
        last_heartbeat = time.time()
        
        while True:
            try:
                # Warte auf Nachrichten (mit Timeout für Heartbeat)
                message = pubsub.get_message(timeout=5.0)
                
                if message and message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        event_type = data.get('event', 'update')
                        event_data = data.get('data', {})
                        
                        # Filter nach User-ID wenn angegeben
                        target_user = event_data.get('user_id')
                        if target_user and user_id and target_user != user_id:
                            continue
                        
                        yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"
                    except json.JSONDecodeError:
                        pass
                
                # Heartbeat alle 30 Sekunden
                if time.time() - last_heartbeat > 30:
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
        except:
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
    
    response = Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',  # Nginx: Buffering deaktivieren
            'Access-Control-Allow-Origin': '*'
        }
    )
    return response


@sse_bp.route('/events/music')
def music_events():
    """SSE-Endpoint für Musik-Updates (öffentlich für Wishlist)."""
    channels = ['music:updates']
    
    def generate():
        yield from event_stream(channels)
    
    response = Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': '*'
        }
    )
    return response


@sse_bp.route('/events/email')
@login_required
def email_events():
    """SSE-Endpoint für E-Mail-Sync-Status-Updates."""
    user_id = current_user.id
    channels = [f'email:sync:user:{user_id}']
    
    def generate():
        yield from event_stream(channels, user_id)
    
    response = Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': '*'
        }
    )
    return response


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
