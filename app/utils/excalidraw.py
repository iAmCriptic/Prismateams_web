"""
Excalidraw helper functions and utilities.
"""
from flask import current_app, request
from urllib.parse import urlparse, urljoin
import logging

logger = logging.getLogger(__name__)


def is_excalidraw_enabled():
    """Check if Excalidraw is enabled in configuration."""
    return current_app.config.get('EXCALIDRAW_ENABLED', False)


def get_excalidraw_url():
    """Get the Excalidraw URL from configuration.
    Returns an absolute URL if the configured URL is relative.
    """
    url = current_app.config.get('EXCALIDRAW_URL', '/excalidraw')
    
    # Wenn die URL bereits absolut ist (mit http:// oder https://), gib sie zurück
    if url.startswith('http://') or url.startswith('https://'):
        return url
    
    # Stelle sicher, dass die URL mit / beginnt
    if not url.startswith('/'):
        url = '/' + url
    
    # Wenn die URL relativ ist, mache sie absolut basierend auf der aktuellen Request-URL
    try:
        if hasattr(request, 'host'):
            scheme = request.scheme
            host = request.host
            return f"{scheme}://{host}{url}"
    except RuntimeError:
        # Kein Request-Kontext verfügbar
        pass
    
    # Fallback: gib die relative URL zurück
    return url


def get_excalidraw_room_url():
    """Get the Excalidraw Room URL from configuration.
    Returns an absolute URL if the configured URL is relative.
    """
    url = current_app.config.get('EXCALIDRAW_ROOM_URL', '/excalidraw-room')
    
    # Wenn die URL bereits absolut ist (mit http:// oder https://), gib sie zurück
    if url.startswith('http://') or url.startswith('https://'):
        return url
    
    # Stelle sicher, dass die URL mit / beginnt
    if not url.startswith('/'):
        url = '/' + url
    
    # Wenn die URL relativ ist, mache sie absolut basierend auf der aktuellen Request-URL
    try:
        if hasattr(request, 'host'):
            scheme = request.scheme
            host = request.host
            return f"{scheme}://{host}{url}"
    except RuntimeError:
        # Kein Request-Kontext verfügbar
        pass
    
    # Fallback: gib die relative URL zurück
    return url


def get_excalidraw_public_url():
    """Get the public URL for Flask app (required when Excalidraw runs on different server)."""
    public_url = current_app.config.get('EXCALIDRAW_PUBLIC_URL', '')
    
    # Wenn EXCALIDRAW_PUBLIC_URL gesetzt ist, verwende sie
    if public_url:
        # Stelle sicher, dass die URL nicht mit / endet (da url_for bereits / hinzufügt)
        public_url = public_url.rstrip('/')
        return public_url
    
    # Fallback: verwende die aktuelle Request-URL
    try:
        if hasattr(request, 'host'):
            scheme = request.scheme
            host = request.host
            return f"{scheme}://{host}"
    except RuntimeError:
        # Kein Request-Kontext verfügbar
        pass
    
    return ''


def validate_excalidraw_config():
    """Validiert die Excalidraw-Konfiguration und gibt eine Liste von Warnungen zurück."""
    warnings = []
    
    if not is_excalidraw_enabled():
        return warnings
    
    excalidraw_url = get_excalidraw_url()
    room_url = get_excalidraw_room_url()
    
    # Prüfe, ob URLs gesetzt sind
    if not excalidraw_url or excalidraw_url.strip() == '':
        warnings.append("EXCALIDRAW_URL ist nicht gesetzt oder leer")
    
    if not room_url or room_url.strip() == '':
        warnings.append("EXCALIDRAW_ROOM_URL ist nicht gesetzt oder leer")
    
    # Prüfe, ob URLs gültig sind
    if excalidraw_url:
        if not excalidraw_url.startswith('http://') and not excalidraw_url.startswith('https://') and not excalidraw_url.startswith('/'):
            warnings.append(f"EXCALIDRAW_URL scheint ungültig zu sein: {excalidraw_url}")
    
    if room_url:
        if not room_url.startswith('http://') and not room_url.startswith('https://') and not room_url.startswith('/'):
            warnings.append(f"EXCALIDRAW_ROOM_URL scheint ungültig zu sein: {room_url}")
    
    return warnings

