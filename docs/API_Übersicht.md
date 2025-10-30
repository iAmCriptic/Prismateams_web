# Team Portal - Umfassende API-Übersicht

## 📋 Inhaltsverzeichnis

1. [Überblick](#überblick)
2. [REST API Endpunkte](#rest-api-endpunkte)
3. [WebSocket/SocketIO](#websocketsocketio)
4. [Push Notifications API](#push-notifications-api)
5. [Datei-Upload API](#datei-upload-api)
6. [E-Mail Integration](#e-mail-integration)
7. [Authentifizierung](#authentifizierung)
8. [Fehlerbehandlung](#fehlerbehandlung)
9. [Rate Limiting](#rate-limiting)
10. [Beispiele](#beispiele)

---

## Überblick

Das Team Portal bietet eine umfassende REST API für alle Hauptfunktionen. Die API ist unter dem `/api/` Pfad verfügbar und unterstützt JSON-Responses.

**Base URL:** `http://localhost:5000/api/`

Hinweis: Einige Endpunkte liegen bewusst außerhalb des `/api/` Pfades (z. B. `auth/`, `files/`, `email/`, `canvas/`, `credentials/`). Diese sind Session- und Formular-basiert, liefern aber in dieser Dokumentation jeweils das erwartete Ergebnis/Response-Schema für API-Clients.

**Authentifizierung:** Alle API-Endpunkte erfordern eine aktive Benutzer-Session (Login erforderlich).

---

## REST API Endpunkte

### 🔐 Authentifizierung

#### Login
```http
POST /auth/login
Content-Type: application/x-www-form-urlencoded

email=user@example.com&password=password123&remember=on
```

**Ergebnis/Response:**
- Bei Erfolg: 302 Redirect auf Startseite, Session-Cookie gesetzt
- Bei Fehler: `401 Unauthorized`
```json
{ "error": "Ungültige Zugangsdaten", "success": false }
```

#### Registrierung
```http
POST /auth/register
Content-Type: application/x-www-form-urlencoded

email=user@example.com&password=password123&password_confirm=password123&first_name=Max&last_name=Mustermann&phone=+49123456789
```

**Ergebnis/Response:**
- Bei Erfolg: 302 Redirect auf Login oder Startseite, Session optional
- Bei Fehler: `400 Bad Request`
```json
{ "error": "E-Mail bereits vergeben", "success": false }
```

#### Logout
```http
GET /auth/logout
```

**Ergebnis/Response:**
- Bei Erfolg: 302 Redirect auf Login, Session beendet
- Fehler sind unüblich; bei nicht eingeloggtem Nutzer ggf. 401

---

### 👥 Benutzer API

#### Alle Benutzer abrufen
```http
GET /api/users
```

**Response:**
```json
[
  {
    "id": 1,
    "email": "user@example.com",
    "full_name": "Max Mustermann",
    "first_name": "Max",
    "last_name": "Mustermann",
    "is_admin": false,
    "profile_picture": "/settings/profile-picture/1_20251022_131540_IMG-20250607-WA0016.jpg"
  }
]
```

#### Einzelnen Benutzer abrufen
```http
GET /api/users/{user_id}
```

**Response:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "full_name": "Max Mustermann",
  "first_name": "Max",
  "last_name": "Mustermann",
  "phone": "+49123456789",
  "is_admin": false,
  "profile_picture": "/settings/profile-picture/1_20251022_131540_IMG-20250607-WA0016.jpg",
  "accent_color": "#0d6efd",
  "dark_mode": false
}
```

---

### 💬 Chat API

#### Alle Chats abrufen
```http
GET /api/chats
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Haupt-Chat",
    "is_main_chat": true,
    "is_direct_message": false,
    "unread_count": 3,
    "last_message": {
      "content": "Hallo Team!",
      "created_at": "2025-01-22T10:30:00",
      "sender": "Max Mustermann"
    }
  }
]
```

#### Nachrichten eines Chats abrufen
```http
GET /api/chats/{chat_id}/messages
GET /api/chats/{chat_id}/messages?since=123
```

**Parameter:**
- `since` (optional): ID der letzten gelesenen Nachricht für inkrementelle Updates

**Response:**
```json
[
  {
    "id": 1,
    "sender_id": 1,
    "sender_name": "Max Mustermann",
    "sender": "Max Mustermann",
    "content": "Hallo Team!",
    "message_type": "text",
    "media_url": null,
    "created_at": "2025-01-22T10:30:00"
  }
]
```

#### Nachricht senden
```http
POST /chat/{chat_id}/send
Content-Type: multipart/form-data

content=Hallo Team!&file=@attachment.jpg
```

**Unterstützte Dateitypen:**
- Bilder: PNG, JPG, JPEG, GIF
- Videos: MP4, WEBM, OGG
- Audio: MP3, WAV, M4A

**Response:**
```json
{
  "id": 2,
  "sender_id": 1,
  "sender": "Max Mustermann",
  "content": "Hallo Team!",
  "message_type": "text",
  "media_url": null,
  "created_at": "2025-01-22T10:35:00"
}
```

**Status Codes:**
- 200 bei Erfolg, 400 bei Validierungsfehlern, 403/404 bei fehlenden Rechten/nicht gefunden

---

### 📅 Kalender API

#### Alle Termine abrufen
```http
GET /api/events
```

**Response:**
```json
[
  {
    "id": 1,
    "title": "Team Meeting",
    "description": "Wöchentliches Team Meeting",
    "start_time": "2025-01-23T10:00:00",
    "end_time": "2025-01-23T11:00:00",
    "location": "Konferenzraum A",
    "created_by": "Max Mustermann",
    "participation_status": "accepted"
  }
]
```

#### Einzelnen Termin abrufen
```http
GET /api/events/{event_id}
```

**Response:**
```json
{
  "id": 1,
  "title": "Team Meeting",
  "description": "Wöchentliches Team Meeting",
  "start_time": "2025-01-23T10:00:00",
  "end_time": "2025-01-23T11:00:00",
  "location": "Konferenzraum A",
  "created_by": "Max Mustermann",
  "participants": [
    {
      "user_id": 1,
      "user_name": "Max Mustermann",
      "status": "accepted"
    }
  ]
}
```

#### Termine für Monat abrufen
```http
GET /calendar/api/events/{year}/{month}
```

#### Termine für Zeitraum abrufen
```http
GET /calendar/api/events/range/{start_date}/{end_date}
```

**Parameter:**
- `start_date`: YYYY-MM-DD Format
- `end_date`: YYYY-MM-DD Format

#### Teilnahme an Termin
```http
POST /calendar/participate/{event_id}/{status}
```

**Status:** `accepted` oder `declined`

---

### 📁 Dateien API

#### Dateien in Ordner abrufen
```http
GET /api/files?folder_id={folder_id}
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "dokument.pdf",
    "size": 1024000,
    "mime_type": "application/pdf",
    "version": 1,
    "uploaded_by": "Max Mustermann",
    "uploaded_at": "2025-01-22T10:00:00"
  }
]
```

#### Unterordner abrufen
```http
GET /api/folders?parent_id={parent_id}
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Projekt Dokumente",
    "created_at": "2025-01-22T10:00:00"
  }
]
```

#### Datei hochladen
```http
POST /files/upload
Content-Type: multipart/form-data

file=@dokument.pdf&folder_id=1
```

**Ergebnis/Response:**
```json
{
  "success": true,
  "file": {
    "id": 42,
    "name": "dokument.pdf",
    "size": 1024000,
    "mime_type": "application/pdf",
    "version": 1,
    "folder_id": 1,
    "uploaded_at": "2025-01-22T10:00:00"
  }
}
```
**Status Codes:** 200 bei Erfolg, 400 bei Validierung, 413 bei zu großer Datei, 415 bei nicht unterstütztem Typ

#### Datei herunterladen
```http
GET /files/download/{file_id}
```

**Ergebnis:**
- Binary-Download mit korrekten `Content-Type`/`Content-Disposition`
- Fehler: `404 Not Found` wenn Datei/Version fehlt

#### Datei bearbeiten (Text/Markdown)
```http
GET /files/edit/{file_id}
POST /files/edit/{file_id}
Content-Type: application/x-www-form-urlencoded

content=Neuer Inhalt der Datei
```

**Ergebnis/Response (POST):**
```json
{ "success": true, "file_id": 1, "version": 2 }
```

#### Datei anzeigen
```http
GET /files/view/{file_id}
```

**Ergebnis:**
- HTML/Inline-Ansicht je nach Dateityp; bei API-Clients `200` mit darstellbarem Content oder `415` wenn nicht viewbar

#### Datei-Details abrufen
```http
GET /files/api/file-details/{file_id}
```

**Response:**
```json
{
  "success": true,
  "file": {
    "id": 1,
    "name": "dokument.pdf",
    "size": "1.0 MB",
    "type": "PDF",
    "uploader": "Max Mustermann",
    "created_at": "22.01.2025 10:00",
    "version": 1,
    "is_editable": false,
    "is_viewable": false
  },
  "versions": [
    {
      "id": 1,
      "version_number": 1,
      "is_current": true,
      "download_url": "/files/download-version/1"
    }
  ],
  "actions": {
    "download_url": "/files/download/1",
    "view_url": null,
    "edit_url": null
  }
}
```

**Status Codes:** 200 bei Erfolg, 404 wenn Datei fehlt

---

## Datei-Upload API

Zweck-spezifische Kurzreferenz für Uploads (ergänzend zur Dateien API):

- Endpoint: `POST /files/upload`
- Request: `multipart/form-data` mit Feldern `file`, optional `folder_id`
- Ergebnis: JSON mit `success` und `file`-Metadaten (siehe oben in Dateien API)
- Fehler: 400/413/415 wie oben beschrieben

---

### 📧 E-Mail API

#### E-Mails abrufen
```http
GET /email/
```

**Ergebnis:**
- HTML-Liste im Web; für API-Clients empfohlen: nutze spezifische View-Endpunkte unten. Optional kann eine JSON-Liste bereitgestellt werden, falls aktiviert.

#### E-Mail anzeigen
```http
GET /email/view/{email_id}
```

**Ergebnis (falls JSON verfügbar):**
```json
{
  "id": 1,
  "from": "absender@example.com",
  "to": ["empfaenger@example.com"],
  "subject": "Betreff",
  "body_html": "<p>…</p>",
  "body_text": "…",
  "attachments": [{"id": 9, "filename": "datei.pdf", "size": 12345}]
}
```
**Status Codes:** 200/404

#### E-Mail verfassen
```http
POST /email/compose
Content-Type: multipart/form-data

to=empfaenger@example.com&cc=cc@example.com&subject=Betreff&body=Nachricht&attachments=@datei.pdf
```

**Ergebnis/Response:**
```json
{ "success": true, "email_id": 101 }
```
**Status Codes:** 200 bei Erfolg, 400 bei Validierung, 403 bei fehlender Sendeberechtigung

#### E-Mails synchronisieren
```http
POST /email/sync
```

**Ergebnis/Response:**
```json
{ "success": true, "fetched": 12 }
```

#### E-Mail-Anhang herunterladen
```http
GET /email/attachment/{attachment_id}
```

**Ergebnis:**
- Binary-Download; 404 wenn Anhang fehlt

---

### 🔑 Zugangsdaten API

#### Alle Zugangsdaten abrufen
```http
GET /credentials/
```

#### Zugangsdaten erstellen
```http
POST /credentials/create
Content-Type: application/x-www-form-urlencoded

website_url=https://example.com&website_name=Example&username=user&password=pass123&notes=Notizen
```

**Ergebnis/Response:**
```json
{ "success": true, "credential_id": 7 }
```

#### Zugangsdaten bearbeiten
```http
GET /credentials/edit/{credential_id}
POST /credentials/edit/{credential_id}
```

**Ergebnis/Response (POST):**
```json
{ "success": true }
```

#### Passwort anzeigen
```http
GET /credentials/view-password/{credential_id}
```

**Response:**
```json
{
  "password": "entschlüsseltes_passwort"
}
```

---

### 🎨 Canvas API

#### Alle Canvas abrufen
```http
GET /canvas/
```

#### Canvas erstellen
```http
POST /canvas/create
Content-Type: application/x-www-form-urlencoded

name=Mein Canvas&description=Beschreibung
```

#### Canvas bearbeiten
```http
GET /canvas/edit/{canvas_id}
```

#### Textfeld hinzufügen
```http
POST /canvas/{canvas_id}/add-text-field
Content-Type: application/json

{
  "content": "Textinhalt",
  "pos_x": 100,
  "pos_y": 50,
  "width": 200,
  "height": 100,
  "font_size": 14,
  "color": "#000000",
  "background_color": "#ffffff"
}
```

**Ergebnis/Response:**
```json
{ "success": true, "field_id": 11 }
```

#### Textfeld aktualisieren
```http
PUT /canvas/text-field/{field_id}/update
Content-Type: application/json

{
  "content": "Neuer Textinhalt",
  "pos_x": 150,
  "pos_y": 75
}
```

**Ergebnis/Response:**
```json
{ "success": true }
```

#### Textfeld löschen
```http
DELETE /canvas/text-field/{field_id}/delete
```

**Ergebnis/Response:**
```json
{ "success": true }
```

---

### 📊 Dashboard API

#### Dashboard-Statistiken
```http
GET /api/dashboard/stats
```

**Response:**
```json
{
  "upcoming_events": 3,
  "unread_messages": 5,
  "unread_emails": 2,
  "total_files": 15
}
```

#### Ungelesene Chat-Nachrichten
```http
GET /api/chat/unread-count
```

**Response:**
```json
{
  "count": 5
}
```

#### Ungelesene E-Mails
```http
GET /api/email/unread-count
```

**Response:**
```json
{
  "count": 2
}
```

#### Anstehende Termine
```http
GET /api/calendar/upcoming-count
```

**Response:**
```json
{
  "count": 3
}
```

---

## WebSocket/SocketIO

Echtzeit-Updates werden über Socket.IO bereitgestellt. Der Client verbindet sich mit der Standard-URL der Anwendung (z. B. `http://localhost:5000`).

Beispiel (Client):
```javascript
const socket = io(); // nutzt aktuelle Origin

socket.on('connect', () => {
  console.log('verbunden');
});

socket.on('chat:new_message', (payload) => {
  // payload: { chat_id, message }
});
```

### Events
- `chat:new_message`
  - Beschreibung: Neue Chat-Nachricht in einem Chat
  - Payload:
  ```json
  {
    "chat_id": 1,
    "message": {
      "id": 123,
      "sender_id": 1,
      "sender": "Max Mustermann",
      "content": "Hallo Team!",
      "message_type": "text",
      "media_url": null,
      "created_at": "2025-01-22T10:35:00"
    }
  }
  ```

- `chat:typing`
  - Beschreibung: Nutzer tippt in einem Chat
  - Payload: `{ "chat_id": 1, "user_id": 1, "is_typing": true }`

- `chat:read_receipt`
  - Beschreibung: Lesebestätigung für eine Nachricht
  - Payload: `{ "chat_id": 1, "message_id": 123, "reader_id": 1, "read_at": "2025-01-22T10:40:00" }`

- `email:new`
  - Beschreibung: Neue E-Mail synchronisiert/verfügbar
  - Payload: `{ "email_id": 99, "subject": "…" }`

- `calendar:event_updated`
  - Beschreibung: Termin erstellt/aktualisiert/gelöscht
  - Payload: `{ "event_id": 5, "action": "updated" }`

Authentifizierung: Die bestehende Session (Cookie) wird für die Socket.IO-Verbindung verwendet. Nur eingeloggte Nutzer erhalten Events ihrer berechtigten Ressourcen.

---

## Push Notifications API

### Push-Subscription registrieren
```http
POST /api/push/subscribe
Content-Type: application/json

{
  "subscription": {
    "endpoint": "https://fcm.googleapis.com/fcm/send/...",
    "keys": {
      "p256dh": "...",
      "auth": "..."
    }
  },
  "user_agent": "Mozilla/5.0..."
}
```

### Push-Subscription deaktivieren
```http
POST /api/push/unsubscribe
```

### Test-Benachrichtigung senden
```http
POST /api/push/test
```

### Push-Status abrufen
```http
GET /api/push/status
```

**Response:**
```json
{
  "has_subscription": true,
  "subscription_count": 1,
  "notifications_enabled": true,
  "chat_notifications": true
}
```

---

## Benachrichtigungen API

### Benachrichtigungseinstellungen abrufen
```http
GET /api/notifications/settings
```

**Response:**
```json
{
  "chat_notifications_enabled": true,
  "file_notifications_enabled": true,
  "file_new_notifications": true,
  "file_modified_notifications": true,
  "email_notifications_enabled": true,
  "calendar_notifications_enabled": true,
  "calendar_all_events": false,
  "calendar_participating_only": true,
  "calendar_not_participating": false,
  "calendar_no_response": false,
  "reminder_times": [15, 60, 1440]
}
```

### Benachrichtigungseinstellungen aktualisieren
```http
POST /api/notifications/settings
Content-Type: application/json

{
  "chat_notifications_enabled": true,
  "file_notifications_enabled": true,
  "file_new_notifications": true,
  "file_modified_notifications": false,
  "email_notifications_enabled": true,
  "calendar_notifications_enabled": true,
  "calendar_all_events": false,
  "calendar_participating_only": true,
  "calendar_not_participating": false,
  "calendar_no_response": false,
  "reminder_times": [15, 60, 1440]
}
```

### Chat-spezifische Benachrichtigungen
```http
POST /api/notifications/chat/{chat_id}
Content-Type: application/json

{
  "enabled": true
}
```

### Ausstehende Benachrichtigungen abrufen
```http
GET /api/notifications/pending
```

**Response:**
```json
{
  "notifications": [
    {
      "id": 1,
      "title": "Neue Chat-Nachricht",
      "body": "Max Mustermann: Hallo Team!",
      "icon": "/static/img/chat-icon.png",
      "url": "/chat/1",
      "sent_at": "2025-01-22T10:30:00",
      "success": true
    }
  ],
  "count": 1
}
```

### Benachrichtigung als gelesen markieren
```http
POST /api/notifications/mark-read/{notification_id}
```

---

## Einstellungen API

### Benutzer-Einstellungen

#### Profil bearbeiten
```http
POST /settings/profile
Content-Type: multipart/form-data

first_name=Max&last_name=Mustermann&email=user@example.com&phone=+49123456789&new_password=neuespasswort&profile_picture=@bild.jpg
```

#### Darstellungseinstellungen
```http
POST /settings/appearance
Content-Type: application/x-www-form-urlencoded

color_type=solid&accent_color=#0d6efd&accent_gradient=&dark_mode=on
```

#### Benachrichtigungseinstellungen
```http
POST /settings/notifications
Content-Type: application/x-www-form-urlencoded

chat_notifications_enabled=on&file_notifications_enabled=on&email_notifications_enabled=on&calendar_notifications_enabled=on&reminder_times=15&reminder_times=60&reminder_times=1440
```

### Admin-Einstellungen

#### Benutzer verwalten
```http
POST /settings/admin/users/{user_id}/activate
POST /settings/admin/users/{user_id}/deactivate
POST /settings/admin/users/{user_id}/make-admin
POST /settings/admin/users/{user_id}/remove-admin
POST /settings/admin/users/{user_id}/delete
```

#### E-Mail-Berechtigungen
```http
POST /settings/admin/email-permissions/{user_id}/toggle-read
POST /settings/admin/email-permissions/{user_id}/toggle-send
```

#### System-Einstellungen
```http
POST /settings/admin/system
Content-Type: application/x-www-form-urlencoded

email_footer_text=Mit freundlichen Grüßen
```

#### Whitelist verwalten
```http
POST /settings/admin/whitelist/add
Content-Type: application/x-www-form-urlencoded

entry=user@example.com&entry_type=email&description=Test User

POST /settings/admin/whitelist/{entry_id}/toggle
POST /settings/admin/whitelist/{entry_id}/delete
```

---

## Authentifizierung

### Session-basierte Authentifizierung

Alle API-Endpunkte verwenden Flask-Login für die Authentifizierung. Benutzer müssen sich über `/auth/login` anmelden, um Zugriff auf die API zu erhalten.

### CSRF-Schutz

Formulare verwenden Flask-WTF für CSRF-Schutz. Bei AJAX-Requests muss der CSRF-Token im Header oder im Request-Body mitgesendet werden.

### Rollenbasierte Berechtigungen

- **Benutzer**: Standard-Zugriff auf alle eigenen Daten
- **Administratoren**: Zusätzlicher Zugriff auf Admin-Funktionen

---

## Fehlerbehandlung

### HTTP Status Codes

- `200 OK`: Erfolgreiche Anfrage
- `400 Bad Request`: Ungültige Anfrage
- `401 Unauthorized`: Nicht authentifiziert
- `403 Forbidden`: Keine Berechtigung
- `404 Not Found`: Ressource nicht gefunden
- `500 Internal Server Error`: Server-Fehler

### Fehler-Response Format

```json
{
  "error": "Fehlermeldung",
  "success": false
}
```

### Häufige Fehler

#### Authentifizierung
```json
{
  "error": "Nicht autorisiert"
}
```

#### Validierung
```json
{
  "error": "Bitte füllen Sie alle Pflichtfelder aus."
}
```

#### Berechtigung
```json
{
  "error": "Sie haben keine Berechtigung, E-Mails zu lesen."
}
```

---

## Rate Limiting

Aktuell ist kein explizites Rate Limiting implementiert. Empfohlene Limits:

- **Chat-Nachrichten**: 100 pro Minute
- **Datei-Uploads**: 10 pro Minute
- **API-Requests**: 1000 pro Stunde

---

## Beispiele

### Vollständiger Chat-Workflow

1. **Chats abrufen:**
```bash
curl -X GET "http://localhost:5000/api/chats" \
  -H "Cookie: session=your_session_cookie"
```

2. **Nachrichten abrufen:**
```bash
curl -X GET "http://localhost:5000/api/chats/1/messages" \
  -H "Cookie: session=your_session_cookie"
```

3. **Nachricht senden:**
```bash
curl -X POST "http://localhost:5000/chat/1/send" \
  -H "Cookie: session=your_session_cookie" \
  -F "content=Hallo Team!"
```

### Datei-Upload Workflow

1. **Ordner durchsuchen:**
```bash
curl -X GET "http://localhost:5000/api/folders?parent_id=1" \
  -H "Cookie: session=your_session_cookie"
```

2. **Datei hochladen:**
```bash
curl -X POST "http://localhost:5000/files/upload" \
  -H "Cookie: session=your_session_cookie" \
  -F "file=@dokument.pdf" \
  -F "folder_id=1"
```

3. **Datei herunterladen:**
```bash
curl -X GET "http://localhost:5000/files/download/1" \
  -H "Cookie: session=your_session_cookie" \
  -O
```

### Push Notifications Setup

1. **Service Worker registrieren:**
```javascript
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js');
}
```

2. **Push-Subscription registrieren:**
```javascript
const subscription = await registration.pushManager.subscribe({
  userVisibleOnly: true,
  applicationServerKey: 'your_vapid_public_key'
});

fetch('/api/push/subscribe', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    subscription: subscription,
    user_agent: navigator.userAgent
  })
});
```

---

## Technische Details

### Datenbank-Modelle

- **User**: Benutzer mit Authentifizierung
- **Chat/ChatMessage**: Chat-System
- **File/Folder**: Dateiverwaltung mit Versionierung
- **CalendarEvent/EventParticipant**: Kalender-System
- **EmailMessage**: E-Mail-Integration
- **Credential**: Verschlüsselte Zugangsdaten
- **Canvas/CanvasTextField**: Kreativbereich
- **NotificationSettings**: Benachrichtigungskonfiguration

### Sicherheit

- **Passwort-Hashing**: Argon2
- **Verschlüsselung**: Fernet (symmetrisch) für Zugangsdaten
- **CSRF-Schutz**: Flask-WTF
- **XSS-Schutz**: Jinja2 Auto-Escaping
- **SQL-Injection-Schutz**: SQLAlchemy ORM

### Datei-Upload

- **Maximale Dateigröße**: 100MB
- **Unterstützte Formate**: PDF, Bilder, Videos, Audio, Office-Dokumente
- **Versionierung**: Letzte 3 Versionen werden gespeichert
- **Sichere Dateinamen**: Werkzeug sichere Dateinamen

### E-Mail-Integration

- **IMAP**: E-Mail-Abruf
- **SMTP**: E-Mail-Versand
- **Attachments**: Unterstützung für Anhänge bis 100MB
- **Encoding**: Automatische Erkennung und Konvertierung

---

### API-Konventionen (Anfragen & Pagination)

- Allgemeine Parameter:
  - `limit` (optional, int): Anzahl Elemente pro Seite (Standard: 50, max: 200)
  - `offset` (optional, int): Startversatz für Pagination
  - `since` (optional, id/timestamp): Nur Elemente nach bestimmtem Zeitpunkt/ID (z. B. Chat-Nachrichten)
  - `sort` (optional, string): z. B. `created_at:desc`
- IDs sind numerisch und beziehen sich auf die in den Beispielen gezeigten Ressourcen.
- Zeitstempel sind im ISO-8601-Format (`YYYY-MM-DDTHH:mm:ss`).
- Responses enthalten bei Erfolg entweder die Ressource(n) oder `{ "success": true }`; bei Fehlern das [Fehler-Response Format](#fehlerbehandlung).

---

## Changelog

### Version 1.0.0
- Initiale API-Implementierung
- REST API für alle Hauptfunktionen
- Push Notifications
- Datei-Upload mit Versionierung
- E-Mail-Integration
- Chat-System
- Kalender-System
- Benutzerverwaltung

---

*Diese Dokumentation wird kontinuierlich aktualisiert. Bei Fragen oder Problemen wenden Sie sich an das Entwicklungsteam.*
