<p align="center">
  <img src="../app/static/img/logo.png" alt="Prismateams Logo" width="96">
</p>

<h1 align="center">Prismateams – API-Übersicht</h1>

<p align="center">
  <strong>Dokumentation · Version 3.0.0</strong><br>
  <img src="https://img.shields.io/badge/version-3.0.0-7c3aed?style=flat-square" alt="Version 3.0.0">
</p>

<p align="center">
  <a href="README.md">Übersicht</a> ·
  <a href="API_AUTH.md">Authentifizierung</a> ·
  <a href="INSTALLATION.md">Installation</a> ·
  <a href="WARTUNG.md">Wartung</a>
</p>

---

REST-API für Apps und Integrationen. Basis: **`/api/`**.

**Auth:** Session-Cookie **oder** `Authorization: Bearer <token>` — Details: [API_AUTH.md](API_AUTH.md).

Live-Liste (eingeloggt): `GET /api/endpoints`

> Viele Modul-APIs (Inventar, Wiki, Booking, Assessment, …) liegen zusätzlich unter den jeweiligen Blueprint-Pfaden. Hier: zentrale Routen aus `app/blueprints/api_modules/`.

## Meta & User

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/endpoints` | Übersicht registrierter API-Routen |
| `GET` | `/api/users/me` | Aktueller Benutzer |
| `GET` | `/api/modules/active` | Aktive Module |
| `GET` | `/api/appearance/me` | Darstellung |
| `GET` | `/api/users` | Benutzerliste |
| `GET` | `/api/users/<id>` | Benutzerdetails |
| `GET` | `/api/users/<id>/status` | Online-Status |
| `POST` | `/api/users/update-last-seen` | Last-seen |

## Authentifizierung

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `POST` | `/api/auth/login` | Login (+ optional 2FA, Token) |
| `POST` | `/api/auth/logout` | Logout |
| `POST` | `/api/auth/verify-token` | Session/Token prüfen |

→ [API_AUTH.md](API_AUTH.md)

## Dashboard & E-Mail

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/dashboard/stats` | Dashboard-Statistiken |
| `GET` | `/api/email/unread-count` | Ungelesene Mails |

## Chat

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/chats` | Chat-Liste |
| `GET` | `/api/chats/<id>` | Chat-Details |
| `POST` | `/api/chats/create` | Anlegen |
| `PUT`/`POST` | `/api/chats/<id>/update` | Aktualisieren |
| `DELETE` | `/api/chats/<id>` | Löschen |
| `POST` | `/api/chats/<id>/pin` | Anpinnen |
| `GET` | `/api/chats/<id>/messages` | Nachrichten |
| `POST` | `/api/chats/<id>/send` | Senden |
| `POST` | `/api/chats/<id>/mark-read` | Als gelesen |
| `GET` | `/api/chats/<id>/members` | Mitglieder |
| `GET` | `/api/chat/unread-count` | Ungelesen gesamt |
| `POST` | `/api/chats/<id>/messages/<mid>/calendar-rsvp` | Termin-RSVP |
| `POST` | `/api/chats/<id>/messages/<mid>/poll-vote` | Umfrage |

## Kalender

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/events` | Termine |
| `GET` | `/api/events/<id>` | Termin-Details |
| `GET` | `/api/calendar/upcoming-count` | Anstehende (Zähler) |

## Dateien

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/files` | Dateien |
| `GET` | `/api/folders` | Ordner |
| `GET` | `/api/files/recent` | Zuletzt genutzt |
| `GET` | `/api/files/<id>/details` | Details |
| `GET` | `/api/files/<id>/download` | Download |
| `GET`/`PUT` | `/api/files/<id>/content` | Text/Markdown |
| `POST` | `/api/files/<id>/rename` | Umbenennen |
| `POST` | `/api/folders/<id>/rename` | Ordner umbenennen |
| `POST` | `/api/files/move` | Verschieben |
| `DELETE` | `/api/files/<id>` | Löschen |
| `DELETE` | `/api/folders/<id>` | Ordner löschen |
| `POST` | `/api/files/<id>/share` | Freigabe |
| `POST` | `/api/folders/<id>/share` | Ordner-Freigabe |
| `GET`/`POST` | `/api/*/share-settings` | Share-Einstellungen |
| `POST`/`GET` | `/api/folders/<id>/dropbox*` | Dropbox-Mode |

## Benachrichtigungen

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/notifications/pending` | Offene |
| `GET`/`POST` | `/api/notifications/settings` | Einstellungen |
| `POST` | `/api/notifications/mark-read/<id>` | Als gelesen |
| `POST` | `/api/notifications/mark-all-read` | Alle gelesen |
| `DELETE` | `/api/notifications/<id>` | Löschen |
| `POST` | `/api/notifications/delete-all` | Alle löschen |
| `POST` | `/api/notifications/reset-push` | Push zurücksetzen |

## Web Push

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/push/vapid-key` | VAPID Public Key |
| `GET` | `/api/push/status` | Abo-Status |
| `POST` | `/api/push/subscribe` | Abonnieren |
| `POST` | `/api/push/unsubscribe` | Abmelden |
| `POST` | `/api/push/test` | Test-Push |

## Weitere Modul-APIs

| Bereich | Hinweis |
|---------|---------|
| Inventar | z. B. `/inventory/api/products`, Checkout/Scanner |
| Wiki / Booking / Events | jeweilige Blueprints |
| Assessment | `/assessment/...` (eigene Jury-Auth möglich) |
| Musik / Shortlinks | jeweilige Blueprint-Routen |

## WebSocket / Socket.IO

Echtzeit über `/socket.io/`. Bei mehreren Gunicorn-Workern: Redis (`REDIS_ENABLED=True`). Nginx-Upgrade siehe [INSTALLATION.md](INSTALLATION.md).

## Fehler

```json
{ "success": false, "error": "Authentifizierung erforderlich" }
```

| Status | Bedeutung |
|--------|-----------|
| `400` | Ungültige Anfrage |
| `401` | Nicht authentifiziert |
| `403` | Keine Berechtigung |
| `404` | Nicht gefunden |
| `423` | Temporär gesperrt |
| `429` | Rate-Limit |

## Quickstart

```bash
curl -s -X POST https://portal.example.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"…","return_token":true}'

curl -s https://portal.example.com/api/users/me \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

<p align="center">
  <img src="../app/static/img/logo.png" alt="" width="40"><br>
  <sub>Prismateams 3.0.0</sub>
</p>
