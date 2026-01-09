"""
Helper-Funktionen für Dashboard-Event-Emission über Socket.IO.
"""

from app import socketio
from flask import current_app
import logging

logger = logging.getLogger(__name__)


def emit_dashboard_update(user_id, event_type, data):
    """
    Emittiere ein Dashboard-Update-Event an einen spezifischen Benutzer.
    
    Args:
        user_id: ID des Benutzers, der das Update erhalten soll
        event_type: Typ des Events ('chat_update', 'email_update', 'calendar_update', 'files_update', 'canvas_update')
        data: Daten, die mit dem Event gesendet werden sollen
    """
    if not user_id:
        return
    
    room = f'dashboard_user_{user_id}'
    event_name = f'dashboard:{event_type}'
    
    try:
        socketio.emit(event_name, data, room=room)
        if current_app:
            try:
                current_app.logger.debug(f"Dashboard-Update gesendet: {event_name} an Benutzer {user_id}")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Fehler beim Senden des Dashboard-Updates {event_name} an Benutzer {user_id}: {e}")


def emit_dashboard_update_multiple(user_ids, event_type, data):
    """
    Emittiere ein Dashboard-Update-Event an mehrere Benutzer.
    
    Args:
        user_ids: Liste von Benutzer-IDs, die das Update erhalten sollen
        event_type: Typ des Events ('chat_update', 'email_update', 'calendar_update', 'files_update', 'canvas_update')
        data: Daten, die mit dem Event gesendet werden sollen
    """
    if not user_ids:
        return
    
    event_name = f'dashboard:{event_type}'
    
    for user_id in user_ids:
        if user_id:
            emit_dashboard_update(user_id, event_type, data)
