# API-Authentifizierung mit 2FA-Unterstützung

## Übersicht

Die API unterstützt zwei Authentifizierungsmethoden:
1. **Session-basiert**: Verwendet Flask-Session-Cookies (für Web-Anwendungen)
2. **Token-basiert**: Verwendet API-Tokens (für Mobile Apps und externe Clients)

## Login-Endpunkt

### POST `/api/auth/login`

Authentifiziert einen Benutzer mit E-Mail, Passwort und optional 2FA.

#### Request Body (JSON)

```json
{
  "email": "user@example.com",
  "password": "password123",
  "totp_code": "123456",      // Optional, nur wenn 2FA aktiviert ist
  "remember": true,            // Optional, für Session-basierte Auth
  "return_token": false        // Optional, gibt API-Token zurück statt Session
}
```

#### Response (2FA erforderlich)

Wenn 2FA aktiviert ist, aber kein Code übermittelt wurde:

```json
{
  "success": false,
  "requires_2fa": true,
  "message": "2FA-Code erforderlich",
  "error": "Bitte geben Sie den 2FA-Code ein"
}
```

**Status Code:** `200 OK`

#### Response (Erfolg)

```json
{
  "success": true,
  "user": {
    "id": 1,
    "email": "user@example.com",
    "full_name": "Max Mustermann",
    "first_name": "Max",
    "last_name": "Mustermann",
    "is_admin": false,
    "is_guest": false,
    "profile_picture": "/settings/profile-picture/...",
    "accent_color": "#0d6efd",
    "dark_mode": false,
    "totp_enabled": true
  },
  "token": "..."  // Nur wenn return_token=true
}
```

**Status Code:** `200 OK`

#### Fehler-Responses

**401 Unauthorized** - Ungültige Credentials:
```json
{
  "success": false,
  "error": "Ungültige Zugangsdaten"
}
```

**423 Locked** - Account gesperrt (Rate Limiting):
```json
{
  "success": false,
  "error": "Account gesperrt. Bitte warten Sie 120 Sekunden.",
  "account_locked": true,
  "remaining_seconds": 120
}
```

**403 Forbidden** - E-Mail-Bestätigung erforderlich:
```json
{
  "success": false,
  "requires_email_confirmation": true,
  "error": "E-Mail-Bestätigung erforderlich"
}
```

## Login-Flow mit 2FA

### Schritt 1: Login ohne 2FA-Code

```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "success": false,
  "requires_2fa": true,
  "message": "2FA-Code erforderlich"
}
```

### Schritt 2: Login mit 2FA-Code

```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123",
  "totp_code": "123456"
}
```

**Response:**
```json
{
  "success": true,
  "user": {...}
}
```

## Token-basierte Authentifizierung

### Token erhalten

Setze `return_token: true` im Login-Request:

```json
{
  "email": "user@example.com",
  "password": "password123",
  "totp_code": "123456",
  "return_token": true
}
```

**Response:**
```json
{
  "success": true,
  "user": {...},
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_expires_at": "2025-02-15T12:00:00"
}
```

### Token verwenden

Sende den Token im `Authorization` Header:

```http
GET /api/users
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Token verifizieren

```http
POST /api/auth/verify-token
Content-Type: application/json

{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response:**
```json
{
  "success": true,
  "user": {...}
}
```

## Logout

### POST `/api/auth/logout`

Meldet den Benutzer ab (Session oder Token).

**Request:**
- Session-basiert: Kein Body erforderlich (verwendet Session-Cookie)
- Token-basiert: Token im `Authorization` Header

**Response:**
```json
{
  "success": true,
  "message": "Erfolgreich abgemeldet"
}
```

## Rate Limiting

Der Login-Endpunkt ist mit Rate Limiting geschützt:
- **Limit:** 5 Versuche pro 15 Minuten pro IP-Adresse
- Bei Überschreitung: Account wird für 15 Minuten gesperrt

## Beispiel: Mobile App Login

### JavaScript/TypeScript Beispiel

```typescript
async function login(email: string, password: string, totpCode?: string) {
  const response = await fetch('http://your-server.com/api/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      email,
      password,
      totp_code: totpCode,
      return_token: true
    })
  });
  
  const data = await response.json();
  
  if (data.requires_2fa && !totpCode) {
    // 2FA erforderlich - zeige Eingabefeld
    return { requires2FA: true };
  }
  
  if (data.success) {
    // Login erfolgreich - speichere Token
    localStorage.setItem('api_token', data.token);
    return { success: true, user: data.user };
  }
  
  return { success: false, error: data.error };
}

// Verwendung
const result = await login('user@example.com', 'password123');
if (result.requires2FA) {
  const totpCode = prompt('Bitte geben Sie den 2FA-Code ein:');
  const finalResult = await login('user@example.com', 'password123', totpCode);
}
```

### Python Beispiel

```python
import requests

def login(email, password, totp_code=None):
    url = 'http://your-server.com/api/auth/login'
    data = {
        'email': email,
        'password': password,
        'return_token': True
    }
    
    if totp_code:
        data['totp_code'] = totp_code
    
    response = requests.post(url, json=data)
    result = response.json()
    
    if result.get('requires_2fa') and not totp_code:
        # 2FA erforderlich
        totp_code = input('Bitte geben Sie den 2FA-Code ein: ')
        return login(email, password, totp_code)
    
    if result.get('success'):
        token = result.get('token')
        # Speichere Token für weitere Requests
        return token
    
    return None

# Verwendung
token = login('user@example.com', 'password123')
headers = {'Authorization': f'Bearer {token}'}
response = requests.get('http://your-server.com/api/users', headers=headers)
```

## Weitere API-Endpunkte

Alle anderen API-Endpunkte unterstützen sowohl Session- als auch Token-basierte Authentifizierung:

- Session: Automatisch über Flask-Session-Cookie
- Token: `Authorization: Bearer <token>` Header

### Beispiel: Benutzer abrufen

```http
GET /api/users
Authorization: Bearer <token>
```

**Response:**
```json
[
  {
    "id": 1,
    "email": "user@example.com",
    "full_name": "Max Mustermann",
    ...
  }
]
```
