"""
API v2 with Flask-RESTX for automatic Swagger documentation.

This module provides:
- OpenAPI 3.0 specification
- Swagger UI at /api/docs
- Structured API namespaces
"""
from flask import Blueprint
from flask_restx import Api

from .auth import api as auth_ns
from .users import api as users_ns
from .chats import api as chats_ns
from .files import api as files_ns
from .calendar import api as calendar_ns
from .webhooks import api as webhooks_ns
from .oauth import api as oauth_ns

# Create the Blueprint
api_v2_bp = Blueprint('api_v2', __name__)

# Create the API with Swagger documentation
api = Api(
    api_v2_bp,
    version='2.0',
    title='Prismateams API',
    description='''
# Prismateams REST API

Willkommen zur Prismateams API-Dokumentation. Diese API ermöglicht die Integration 
externer Anwendungen mit der Prismateams-Plattform.

## Authentifizierung

Die API unterstützt zwei Authentifizierungsmethoden:

1. **Session-basiert**: Für Web-Anwendungen (Cookie-basiert)
2. **OAuth2**: Für externe Anwendungen und Mobile Apps

### OAuth2 Flows

- **Authorization Code + PKCE**: Für Mobile Apps und SPAs
- **Client Credentials**: Für Server-zu-Server Kommunikation
- **Refresh Token**: Für Token-Erneuerung

### Bearer Token

Nach erfolgreicher Authentifizierung können Sie den Access Token im Header verwenden:

```
Authorization: Bearer <access_token>
```

## Rate Limiting

Die API ist rate-limited. Standardlimits:
- Login: 5 Versuche pro 15 Minuten
- API-Requests: 1000 pro Stunde

## Webhooks

Externe Systeme können über Webhooks über Events benachrichtigt werden.
Verfügbare Events: Chat, Kalender, Dateien, E-Mail, Inventar, Benutzer, Wiki.
    ''',
    doc='/docs',
    authorizations={
        'Bearer': {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'Geben Sie den Token im Format "Bearer <token>" ein'
        },
        'OAuth2': {
            'type': 'oauth2',
            'flow': 'accessCode',
            'authorizationUrl': '/oauth/authorize',
            'tokenUrl': '/oauth/token',
            'scopes': {
                'openid': 'Grundlegende Identität',
                'profile': 'Profilinformationen',
                'email': 'E-Mail-Adresse',
                'read:users': 'Benutzer lesen',
                'read:chats': 'Chats lesen',
                'write:chats': 'Chats schreiben',
                'read:files': 'Dateien lesen',
                'write:files': 'Dateien schreiben',
                'read:calendar': 'Kalender lesen',
                'write:calendar': 'Kalender schreiben',
                'read:inventory': 'Inventar lesen',
                'write:inventory': 'Inventar schreiben',
                'webhooks': 'Webhooks verwalten',
                'admin': 'Admin-Funktionen'
            }
        }
    },
    security='Bearer'
)

# Add namespaces
api.add_namespace(auth_ns, path='/auth')
api.add_namespace(users_ns, path='/users')
api.add_namespace(chats_ns, path='/chats')
api.add_namespace(files_ns, path='/files')
api.add_namespace(calendar_ns, path='/calendar')
api.add_namespace(webhooks_ns, path='/webhooks')
api.add_namespace(oauth_ns, path='/oauth')
