#!/usr/bin/env python3
"""
WSGI Entry Point für Gunicorn in der Produktion.
Diese Datei wird von Gunicorn verwendet, um die Flask-Anwendung zu starten.
"""

import os
from app import create_app

app = create_app(os.getenv('FLASK_ENV', 'production'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)





