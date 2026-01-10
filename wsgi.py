#!/usr/bin/env python3
"""
WSGI Entry Point für Gunicorn in der Produktion.
Diese Datei wird von Gunicorn verwendet, um die Flask-Anwendung zu starten.
Wichtig: Socket.IO wird automatisch beim Import von create_app initialisiert.
"""

import os
from app import create_app, socketio

app = create_app(os.getenv('FLASK_ENV', 'production'))

# Stelle sicher, dass Socket.IO verfügbar ist (wird bereits beim Import initialisiert)
# Diese Zeile ist nur für den Fall, dass Gunicorn direkt socketio verwenden möchte
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)





