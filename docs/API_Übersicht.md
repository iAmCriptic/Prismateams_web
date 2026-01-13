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

### 🔐 Authentifizierung (zusätzliche JSON-API)

Diese Endpunkte ergänzen die bestehenden formularbasierten Routen um API-freundliche JSON-Varianten.

#### API Login
```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123",
  "remember": true
}
```

**Ergebnis/Response:**
```json
{
  "success": true,
  "user": {
    "id": 1,
    "email": "user@example.com",
    "full_name": "Max Mustermann",
    "is_admin": false
  }
}
```
Hinweis: Bei Erfolg wird zusätzlich ein Session-Cookie per `Set-Cookie` gesetzt. Optional kann ein CSRF-Token im Header `X-CSRF-Token` ausgegeben werden, falls benötigt.

**Status Codes:** 200 bei Erfolg, 400 bei Validierung, 401 bei falschen Credentials

#### API Logout
```http
POST /api/auth/logout
```

**Ergebnis/Response:**
```json
{ "success": true }
```

**Status Codes:** 200 bei Erfolg, 401 wenn keine aktive Session vorhanden

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

**Parameter:**
- `year`: Jahr (z. B. 2025)
- `month`: Monat (1-12)

**Response:**
```json
[
  {
    "id": 1,
    "title": "Team Meeting",
    "start_time": "2025-01-23T10:00:00",
    "end_time": "2025-01-23T11:00:00",
    "start_date": "2025-01-23",
    "end_date": "2025-01-23",
    "duration_days": 1,
    "location": "Konferenzraum A",
    "description": "Wöchentliches Team Meeting",
    "day": 23,
    "time": "10:00",
    "participation_status": "accepted",
    "is_recurring": false,
    "url": "/calendar/view/1"
  }
]
```

#### Termine für Zeitraum abrufen
```http
GET /calendar/api/events/range/{start_date}/{end_date}
```

**Parameter:**
- `start_date`: YYYY-MM-DD Format
- `end_date`: YYYY-MM-DD Format

**Response:**
```json
[
  {
    "id": 1,
    "title": "Team Meeting",
    "start_time": "2025-01-23T10:00:00",
    "end_time": "2025-01-23T11:00:00",
    "start_date": "2025-01-23",
    "end_date": "2025-01-23",
    "duration_days": 1,
    "location": "Konferenzraum A",
    "description": "Wöchentliches Team Meeting",
    "day": 23,
    "time": "10:00",
    "participation_status": "accepted",
    "is_recurring": false,
    "url": "/calendar/view/1"
  }
]
```

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

### 📁 Dateien API (zusätzliche JSON-API)

Diese Endpunkte ergänzen die bestehenden Datei-/Download-Routen um konsistente JSON-Responses.

#### Dateien listen (JSON)
```http
GET /api/files?folder_id={folder_id}&limit=50&offset=0
```

**Response:**
```json
{
  "items": [
    {
      "id": 1,
      "name": "dokument.pdf",
      "size": 1024000,
      "mime_type": "application/pdf",
      "version": 1,
      "uploaded_by": "Max Mustermann",
      "uploaded_at": "2025-01-22T10:00:00"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

#### Datei-Details (JSON)
```http
GET /api/files/{file_id}
```

**Response:** identisch zu `GET /files/api/file-details/{file_id}` oben.

#### Datei hochladen (JSON)
```http
POST /api/files
Content-Type: multipart/form-data

file=@dokument.pdf&folder_id=1
```

**Response:**
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

#### Datei herunterladen (API)
```http
GET /api/files/{file_id}/download
```

**Ergebnis:** Binary-Stream mit korrekten Headern. 404 wenn nicht gefunden.

**Status Codes allgemein:** 200/400/404/413/415 je nach Fall

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

### 📝 Wiki API

#### Wiki-Seite als Favorit hinzufügen
```http
POST /wiki/api/favorite/{page_id}
```

**Response:**
```json
{
  "success": true,
  "is_favorite": true,
  "message": "Zur Favoritenliste hinzugefügt."
}
```

**Status Codes:** 200 bei Erfolg, 400 wenn bereits favorisiert oder Limit erreicht (max. 5 Favoriten), 403 wenn Modul deaktiviert, 404 wenn Seite nicht gefunden

#### Wiki-Seite aus Favoriten entfernen
```http
DELETE /wiki/api/favorite/{page_id}
```

**Response:**
```json
{
  "success": true,
  "is_favorite": false,
  "message": "Von Favoritenliste entfernt."
}
```

**Status Codes:** 200 bei Erfolg, 404 wenn nicht favorisiert

#### Favoriten-Status prüfen
```http
GET /wiki/api/favorite/check/{page_id}
```

**Response:**
```json
{
  "is_favorite": true
}
```

**Status Codes:** 200 bei Erfolg, 403 wenn Modul deaktiviert, 404 wenn Seite nicht gefunden

---

### 📧 E-Mail API (zusätzliche JSON-API)

Diese Endpunkte ergänzen die HTML-zentrierten E-Mail-Routen um JSON-Varianten für Apps.

#### E-Mails abrufen (JSON)
```http
GET /api/email?limit=50&offset=0
```

**Response:**
```json
{
  "items": [
    {
      "id": 1,
      "from": "absender@example.com",
      "to": ["empfaenger@example.com"],
      "subject": "Betreff",
      "snippet": "Erste Zeilen…",
      "received_at": "2025-01-22T10:30:00",
      "unread": true
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

#### E-Mail anzeigen (JSON)
```http
GET /api/email/{email_id}
```

**Response:**
```json
{
  "id": 1,
  "from": "absender@example.com",
  "to": ["empfaenger@example.com"],
  "cc": [],
  "subject": "Betreff",
  "body_html": "<p>…</p>",
  "body_text": "…",
  "attachments": [{"id": 9, "filename": "datei.pdf", "size": 12345}],
  "received_at": "2025-01-22T10:30:00",
  "unread": false
}
```

#### E-Mail verfassen (JSON)
```http
POST /api/email
Content-Type: application/json

{
  "to": ["empfaenger@example.com"],
  "cc": ["cc@example.com"],
  "subject": "Betreff",
  "body": "Nachricht",
  "attachments": [
    { "filename": "dokument.pdf", "content_base64": "...", "mime_type": "application/pdf" }
  ]
}
```

**Response:**
```json
{ "success": true, "email_id": 101 }
```

#### E-Mails synchronisieren (JSON)
```http
POST /api/email/sync
```

**Response:**
```json
{ "success": true, "fetched": 12 }
```

#### E-Mail-Anhang herunterladen (API)
```http
GET /api/email/attachments/{attachment_id}
```

**Ergebnis:** Binary-Stream; 404 wenn nicht gefunden

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

### 🔑 Zugangsdaten API (zusätzliche JSON-API)

Diese Endpunkte ergänzen die formularbasierten Routen um JSON-Varianten mit klaren Responses.

#### Zugangsdaten listen (JSON)
```http
GET /api/credentials?limit=50&offset=0
```

**Response:**
```json
{
  "items": [
    {
      "id": 7,
      "website_url": "https://example.com",
      "website_name": "Example",
      "username": "user",
      "notes": "Notizen",
      "created_at": "2025-01-22T10:00:00"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

#### Zugangsdaten erstellen (JSON)
```http
POST /api/credentials
Content-Type: application/json

{
  "website_url": "https://example.com",
  "website_name": "Example",
  "username": "user",
  "password": "pass123",
  "notes": "Notizen"
}
```

**Response:**
```json
{ "success": true, "credential_id": 7 }
```

#### Zugangsdaten anzeigen (JSON)
```http
GET /api/credentials/{credential_id}
```

**Response:**
```json
{
  "id": 7,
  "website_url": "https://example.com",
  "website_name": "Example",
  "username": "user",
  "notes": "Notizen",
  "created_at": "2025-01-22T10:00:00"
}
```

#### Zugangsdaten aktualisieren (JSON)
```http
PUT /api/credentials/{credential_id}
Content-Type: application/json

{
  "website_url": "https://example.com",
  "website_name": "Example",
  "username": "user",
  "password": "neuesPasswortOptional",
  "notes": "Aktualisierte Notizen"
}
```

**Response:**
```json
{ "success": true }
```

#### Zugangsdaten löschen (JSON)
```http
DELETE /api/credentials/{credential_id}
```

**Response:**
```json
{ "success": true }
```

#### Passwort im Klartext anzeigen (JSON)
```http
GET /api/credentials/{credential_id}/password
```

**Response:**
```json
{ "password": "entschlüsseltes_passwort" }
```

Sicherheits-Hinweis: Zugriff nur für berechtigte Nutzer; Zugriffe werden geloggt. Optional kann eine zusätzliche Bestätigung (z. B. Re-Auth) verlangt werden.

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

#### Dashboard-Konfiguration abrufen
```http
GET /api/dashboard/config
```

**Response:**
```json
{
  "enabled_widgets": ["termine", "chats", "emails"],
  "quick_access_links": [
    {"name": "Chat", "url": "/chat", "icon": "chat"}
  ]
}
```

#### Dashboard-Konfiguration aktualisieren
```http
POST /api/dashboard/config
Content-Type: application/json

{
  "enabled_widgets": ["termine", "chats", "emails", "dateien"],
  "quick_access_links": [
    {"name": "Chat", "url": "/chat", "icon": "chat"}
  ]
}
```

**Response:**
```json
{
  "success": true,
  "config": {
    "enabled_widgets": ["termine", "chats", "emails", "dateien"],
    "quick_access_links": [
      {"name": "Chat", "url": "/chat", "icon": "chat"}
    ]
  }
}
```

#### Update-Banner verwalten
```http
POST /api/dashboard/update-banner
Content-Type: application/json

{
  "action": "dismiss"
}
```

**Parameter:**
- `action`: `dismiss` (Banner schließen) oder `disable` (Update-Benachrichtigungen deaktivieren)

**Response:**
```json
{
  "success": true,
  "message": "Banner geschlossen."
}
```

**Hinweis:** Nur für Administratoren verfügbar.

---

### 🎵 Music API

#### Öffentlichen Link abrufen
```http
GET /music/api/public-link
```

**Response:**
```json
{
  "link": "https://portal.example.com/music/public-wishlist"
}
```

#### QR-Code generieren
```http
GET /music/api/qr-code?url={url}
```

**Parameter:**
- `url` (optional): URL für QR-Code (Standard: öffentliche Wunschliste-URL)

**Response:** PNG-Bild (image/png)

#### QR-Code PDF herunterladen
```http
GET /music/api/public-link/pdf
```

**Response:** PDF-Datei (A5-Format mit QR-Code)
**Content-Type:** application/pdf
**Content-Disposition:** attachment; filename=musikwuensche.pdf

#### Wunschliste Anzahl
```http
GET /music/api/wishlist/count
```

**Response:**
```json
{
  "count": 42
}
```

#### Queue Anzahl
```http
GET /music/api/queue/count
```

**Response:**
```json
{
  "count": 15
}
```

#### Queue Liste
```http
GET /music/api/queue/list
```

**Response:**
```json
{
  "queue": [
    {
      "id": 1,
      "position": 1,
      "wish": {
        "id": 10,
        "title": "Song Title",
        "artist": "Artist Name",
        "provider": "spotify",
        "image_url": "https://...",
        "wish_count": 5
      }
    }
  ]
}
```

#### Wunschliste Liste
```http
GET /music/api/wishlist/list?page=1&per_page=50
```

**Parameter:**
- `page` (optional): Seitennummer (Standard: 1)
- `per_page` (optional): Einträge pro Seite (Standard: 50, Maximum: 50)

**Response:**
```json
{
  "wishes": [
    {
      "id": 1,
      "title": "Song Title",
      "artist": "Artist Name",
      "provider": "spotify",
      "image_url": "https://...",
      "wish_count": 5,
      "created_at": "2025-01-22T10:00:00"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 50,
    "total": 42,
    "pages": 1,
    "has_next": false,
    "has_prev": false
  }
}
```

#### Gespielte Lieder Anzahl
```http
GET /music/api/played/count
```

**Response:**
```json
{
  "count": 128
}
```

#### Gespielte Lieder Liste
```http
GET /music/api/played/list?page=1&per_page=50
```

**Parameter:**
- `page` (optional): Seitennummer (Standard: 1)
- `per_page` (optional): Einträge pro Seite (Standard: 50, Maximum: 50)

**Response:**
```json
{
  "played": [
    {
      "id": 1,
      "title": "Song Title",
      "artist": "Artist Name",
      "provider": "spotify",
      "image_url": "https://...",
      "wish_count": 5,
      "updated_at": "2025-01-22T10:00:00"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 50,
    "total": 128,
    "pages": 3,
    "has_next": true,
    "has_prev": false
  }
}
```

---

### 📦 Inventar API

#### Produkte abrufen
```http
GET /inventory/api/products?search={search}&category={category}&status={status}&sort_by={sort_by}&sort_dir={sort_dir}
```

**Parameter:**
- `search` (optional): Suchbegriff (Name, Seriennummer, Beschreibung)
- `category` (optional): Kategorie-Filter
- `status` (optional): Status-Filter (available, borrowed, missing)
- `sort_by` (optional): Sortierung nach (name, category, status, condition, folder, created_at, length) - Standard: name
- `sort_dir` (optional): Sortierrichtung (asc, desc) - Standard: asc

**Response:**
```json
[
  {
    "id": 1,
    "name": "Produktname",
    "description": "Beschreibung",
    "category": "Kategorie",
    "serial_number": "SN12345",
    "condition": "Gut",
    "location": "Lager A",
    "length": "5.5m",
    "length_meters": 5.5,
    "folder_id": 1,
    "folder_name": "Ordner",
    "purchase_date": "2024-01-01",
    "status": "available",
    "image_path": "image.jpg",
    "qr_code_data": "product:1",
    "created_at": "2025-01-22T10:00:00",
    "created_by": 1
  }
]
```

#### Einzelnes Produkt abrufen
```http
GET /inventory/api/products/{product_id}
```

**Response:**
```json
{
  "id": 1,
  "name": "Produktname",
  "description": "Beschreibung",
  "category": "Kategorie",
  "serial_number": "SN12345",
  "condition": "Gut",
  "location": "Lager A",
  "length": "5.5m",
  "length_meters": 5.5,
  "folder_id": 1,
  "folder_name": "Ordner",
  "purchase_date": "2024-01-01",
  "status": "available",
  "image_path": "image.jpg",
  "qr_code_data": "product:1",
  "created_at": "2025-01-22T10:00:00",
  "created_by": 1
}
```

#### Produkt erstellen
```http
POST /inventory/api/products
Content-Type: application/json

{
  "name": "Produktname",
  "description": "Beschreibung",
  "category": "Kategorie",
  "serial_number": "SN12345",
  "condition": "Gut",
  "location": "Lager A",
  "length": "5.5",
  "purchase_date": "2024-01-01"
}
```

**Response:**
```json
{
  "id": 1,
  "name": "Produktname",
  "qr_code_data": "product:1"
}
```

**Status Codes:** 201 bei Erfolg, 400 bei Validierungsfehlern, 403 für Gast-Accounts

#### Produkt aktualisieren
```http
PUT /inventory/api/products/{product_id}
Content-Type: application/json

{
  "name": "Neuer Produktname",
  "category": "Neue Kategorie"
}
```

**Response:**
```json
{
  "success": true
}
```

**Status Codes:** 200 bei Erfolg, 400 bei Validierungsfehlern, 403 für Gast-Accounts, 404 wenn nicht gefunden

#### Produkt löschen
```http
DELETE /inventory/api/products/{product_id}
```

**Response:**
```json
{
  "message": "Produkt gelöscht."
}
```

**Status Codes:** 200 bei Erfolg, 400 wenn ausgeliehen, 403 für Gast-Accounts, 404 wenn nicht gefunden

#### Produkte Massen-Update
```http
POST /inventory/api/products/bulk-update
Content-Type: application/json

{
  "product_ids": [1, 2, 3],
  "updates": {
    "category": "Neue Kategorie",
    "status": "available"
  }
}
```

**Response:**
```json
{
  "success": true,
  "updated_count": 3
}
```

#### Produkte Massen-Löschung
```http
POST /inventory/api/products/bulk-delete
Content-Type: application/json

{
  "product_ids": [1, 2, 3]
}
```

**Response:**
```json
{
  "success": true,
  "deleted_count": 3
}
```

#### Bestand abrufen
```http
GET /inventory/api/stock?search={search}&category={category}&status={status}
```

**Parameter:**
- `search` (optional): Suchbegriff
- `category` (optional): Kategorie-Filter
- `status` (optional): Status-Filter

**Response:** Siehe `/api/products` (vereinfachte Produktliste)

#### Filter-Optionen abrufen
```http
GET /inventory/api/inventory/filter-options?folder_id={folder_id}
```

**Parameter:**
- `folder_id` (optional): Ordner-ID (0 = Root, keine Ordner)

**Response:**
```json
{
  "categories": ["Kategorie 1", "Kategorie 2"],
  "conditions": ["Gut", "Ausgezeichnet"],
  "locations": ["Lager A", "Lager B"],
  "lengths": ["5.5m", "10m"],
  "purchase_years": ["2024", "2023"]
}
```

#### Ordner abrufen
```http
GET /inventory/api/folders
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Ordner",
    "parent_id": null,
    "created_at": "2025-01-22T10:00:00"
  }
]
```

#### Ordner erstellen
```http
POST /inventory/api/folders
Content-Type: application/json

{
  "name": "Neuer Ordner",
  "parent_id": null
}
```

**Response:**
```json
{
  "id": 1,
  "name": "Neuer Ordner",
  "parent_id": null
}
```

#### Ordner aktualisieren
```http
PUT /inventory/api/folders/{folder_id}
Content-Type: application/json

{
  "name": "Umbenannter Ordner"
}
```

**Response:**
```json
{
  "success": true
}
```

#### Ordner löschen
```http
DELETE /inventory/api/folders/{folder_id}
```

**Response:**
```json
{
  "success": true
}
```

#### Ausleihen
```http
POST /inventory/api/borrow
Content-Type: application/json

{
  "product_id": 1,
  "borrower_id": 2,
  "expected_return_date": "2025-02-01"
}
```

**Parameter:**
- `product_id`: Produkt-ID (erforderlich)
- `borrower_id` (optional): Ausleiher-ID (Standard: aktueller Benutzer)
- `expected_return_date`: Erwartetes Rückgabedatum (YYYY-MM-DD, erforderlich)

**Response:**
```json
{
  "transaction_id": 1,
  "transaction_number": "BOR-20250122-001",
  "borrow_group_id": null,
  "qr_code_data": "borrow:BOR-20250122-001"
}
```

**Status Codes:** 201 bei Erfolg, 400 bei Validierungsfehlern, 403 bei fehlender Berechtigung, 404 wenn nicht gefunden

#### Alle Ausleihen abrufen
```http
GET /inventory/api/borrows
```

**Response:**
```json
[
  {
    "id": 1,
    "transaction_number": "BOR-20250122-001",
    "borrow_group_id": null,
    "product_id": 1,
    "product_name": "Produktname",
    "borrower_id": 2,
    "borrower_name": "Max Mustermann",
    "borrow_date": "2025-01-22T10:00:00",
    "expected_return_date": "2025-02-01",
    "is_overdue": false,
    "qr_code_data": "borrow:BOR-20250122-001"
  }
]
```

#### Meine Ausleihen abrufen
```http
GET /inventory/api/borrows/my
```

**Response:** Siehe `/api/borrows` (nur eigene Ausleihen)

#### Meine Ausleihen gruppiert
```http
GET /inventory/api/borrows/my/grouped
```

**Response:**
```json
[
  {
    "borrow_group_id": null,
    "borrow_date": "2025-01-22T10:00:00",
    "expected_return_date": "2025-02-01",
    "product_count": 2,
    "is_overdue": false,
    "products": ["Produkt 1", "Produkt 2"],
    "transactions": [
      {
        "id": 1,
        "transaction_number": "BOR-20250122-001",
        "product_id": 1,
        "product_name": "Produkt 1",
        "expected_return_date": "2025-02-01",
        "is_overdue": false,
        "qr_code_data": "borrow:BOR-20250122-001"
      }
    ]
  }
]
```

#### Rückgabe registrieren
```http
POST /inventory/api/return
Content-Type: application/json

{
  "qr_code": "borrow:BOR-20250122-001"
}
```

**Oder:**
```json
{
  "transaction_number": "BOR-20250122-001"
}
```

**Response:**
```json
{
  "message": "Rückgabe erfolgreich registriert.",
  "transaction_id": 1
}
```

**Status Codes:** 200 bei Erfolg, 404 wenn nicht gefunden

#### Ausleihschein PDF
```http
GET /inventory/api/borrow/{transaction_id}/pdf
```

**Response:** PDF-Datei (Ausleihschein)
**Content-Type:** application/pdf

#### QR-Code-Druckbogen generieren
```http
POST /inventory/api/print-qr-codes
Content-Type: application/json

{
  "product_ids": [1, 2, 3],
  "label_type": "device"
}
```

**Parameter:**
- `product_ids`: Array von Produkt-IDs (erforderlich)
- `label_type` (optional): "device" oder "cable" (Standard: "device")

**Response:** PDF-Datei (QR-Code-Druckbogen)
**Content-Type:** application/pdf

#### Produktsets abrufen
```http
GET /inventory/api/sets
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Set Name",
    "description": "Beschreibung",
    "created_at": "2025-01-22T10:00:00"
  }
]
```

#### Einzelnes Produktset abrufen
```http
GET /inventory/api/sets/{set_id}
```

**Response:**
```json
{
  "id": 1,
  "name": "Set Name",
  "description": "Beschreibung",
  "items": [
    {
      "id": 1,
      "product_id": 1,
      "product_name": "Produktname",
      "quantity": 1
    }
  ],
  "created_at": "2025-01-22T10:00:00"
}
```

#### Produkt-Dokumente abrufen
```http
GET /inventory/api/products/{product_id}/documents
```

**Response:**
```json
[
  {
    "id": 1,
    "file_name": "dokument.pdf",
    "file_type": "manual",
    "uploaded_by": 1,
    "uploaded_at": "2025-01-22T10:00:00"
  }
]
```

#### Suche
```http
GET /inventory/api/search?q={query}
```

**Parameter:**
- `q`: Suchbegriff (erforderlich)

**Response:**
```json
[
  {
    "id": 1,
    "name": "Produktname",
    "category": "Kategorie",
    "status": "available",
    "qr_code_data": "product:1"
  }
]
```

#### Gespeicherte Filter abrufen
```http
GET /inventory/api/filters
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Mein Filter",
    "filter_data": {
      "category": "Kategorie",
      "status": "available"
    },
    "created_at": "2025-01-22T10:00:00"
  }
]
```

#### Filter speichern
```http
POST /inventory/api/filters/save
Content-Type: application/json

{
  "name": "Mein Filter",
  "filter_data": {
    "category": "Kategorie",
    "status": "available"
  }
}
```

**Response:**
```json
{
  "id": 1,
  "name": "Mein Filter",
  "success": true
}
```

#### Filter löschen
```http
DELETE /inventory/api/filters/{filter_id}
```

**Response:**
```json
{
  "success": true
}
```

#### Favoriten abrufen
```http
GET /inventory/api/favorites
```

**Response:**
```json
[
  {
    "id": 1,
    "product_id": 1,
    "product_name": "Produktname",
    "created_at": "2025-01-22T10:00:00"
  }
]
```

#### Produkt als Favorit hinzufügen
```http
POST /inventory/api/favorites/{product_id}
```

**Response:**
```json
{
  "success": true
}
```

#### Produkt aus Favoriten entfernen
```http
DELETE /inventory/api/favorites/{product_id}
```

**Response:**
```json
{
  "success": true
}
```

#### Statistiken abrufen
```http
GET /inventory/api/statistics
```

**Response:**
```json
{
  "total_products": 150,
  "available": 120,
  "borrowed": 25,
  "missing": 5,
  "total_categories": 10,
  "total_borrows": 45
}
```

#### Inventur-Items abrufen
```http
GET /inventory/api/inventory/{inventory_id}/items
```

**Response:**
```json
[
  {
    "id": 1,
    "product_id": 1,
    "product_name": "Produktname",
    "checked": false,
    "checked_by": null,
    "checked_at": null
  }
]
```

#### Inventur-Item aktualisieren
```http
POST /inventory/api/inventory/{inventory_id}/item/{product_id}/update
Content-Type: application/json

{
  "note": "Notiz"
}
```

**Response:**
```json
{
  "success": true
}
```

#### Inventur-Item abhaken
```http
POST /inventory/api/inventory/{inventory_id}/item/{product_id}/check
Content-Type: application/json

{
  "checked": true
}
```

**Response:**
```json
{
  "success": true,
  "checked": true,
  "checked_by": 1,
  "checked_at": "2025-01-22T10:00:00"
}
```

#### Inventur scannen
```http
POST /inventory/api/inventory/{inventory_id}/scan
Content-Type: application/json

{
  "qr_code": "product:1"
}
```

**Response:**
```json
{
  "success": true,
  "product": {
    "id": 1,
    "name": "Produktname"
  }
}
```

#### Kategorien abrufen
```http
GET /inventory/api/categories
```

**Response:**
```json
["Kategorie 1", "Kategorie 2"]
```

#### Kategorie erstellen
```http
POST /inventory/api/categories
Content-Type: application/json

{
  "name": "Neue Kategorie"
}
```

**Response:**
```json
{
  "success": true,
  "name": "Neue Kategorie"
}
```

#### Kategorie aktualisieren
```http
PUT /inventory/api/categories/{category_name}
Content-Type: application/json

{
  "name": "Umbenannte Kategorie"
}
```

**Response:**
```json
{
  "success": true
}
```

#### Kategorie löschen
```http
DELETE /inventory/api/categories/{category_name}
```

**Response:**
```json
{
  "success": true
}
```

#### Mobile Token erstellen
```http
POST /inventory/api/mobile/token
Content-Type: application/json

{
  "name": "Mein Gerät"
}
```

**Response:**
```json
{
  "token": "abc123...",
  "token_id": 1,
  "name": "Mein Gerät",
  "created_at": "2025-01-22T10:00:00"
}
```

#### Mobile Tokens abrufen
```http
GET /inventory/api/mobile/tokens
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Mein Gerät",
    "created_at": "2025-01-22T10:00:00",
    "last_used_at": "2025-01-22T12:00:00"
  }
]
```

#### Mobile Token löschen
```http
DELETE /inventory/api/mobile/tokens/{token_id}
```

**Response:**
```json
{
  "success": true
}
```

#### Mobile Produkte abrufen
```http
GET /inventory/api/mobile/products
Authorization: Bearer {token}
```

**Response:** Siehe `/api/products` (vereinfachte Produktliste)

#### Mobile Produkt abrufen
```http
GET /inventory/api/mobile/products/{product_id}
Authorization: Bearer {token}
```

**Response:** Siehe `/api/products/{product_id}` (vereinfachte Produktdetails)

#### Mobile Ausleihen
```http
POST /inventory/api/mobile/borrow
Authorization: Bearer {token}
Content-Type: application/json

{
  "product_id": 1,
  "expected_return_date": "2025-02-01"
}
```

**Response:** Siehe `/api/borrow`

#### Mobile Rückgabe
```http
POST /inventory/api/mobile/return
Authorization: Bearer {token}
Content-Type: application/json

{
  "qr_code": "borrow:BOR-20250122-001"
}
```

**Response:** Siehe `/api/return`

#### Mobile scannen
```http
POST /inventory/api/mobile/scan
Authorization: Bearer {token}
Content-Type: application/json

{
  "qr_code": "product:1"
}
```

**Response:**
```json
{
  "success": true,
  "product": {
    "id": 1,
    "name": "Produktname",
    "status": "available"
  }
}
```

#### Mobile Statistiken
```http
GET /inventory/api/mobile/statistics
Authorization: Bearer {token}
```

**Response:** Siehe `/api/statistics`

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
