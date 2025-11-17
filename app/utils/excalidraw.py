"""
Excalidraw helper functions and utilities.
"""
from flask import current_app


def is_excalidraw_enabled():
    """Check if Excalidraw is enabled in configuration."""
    return current_app.config.get('EXCALIDRAW_ENABLED', False)


def get_excalidraw_url():
    """Get the Excalidraw URL from configuration."""
    return current_app.config.get('EXCALIDRAW_URL', '/excalidraw')


def get_excalidraw_room_url():
    """Get the Excalidraw Room URL from configuration."""
    return current_app.config.get('EXCALIDRAW_ROOM_URL', '/excalidraw-room')


def get_excalidraw_public_url():
    """Get the public URL for Flask app (required when Excalidraw runs on different server)."""
    return current_app.config.get('EXCALIDRAW_PUBLIC_URL', '')

