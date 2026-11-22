# QA-Audit – Modul-Funktionalität

**Datum:** 2026-11-22T18:06:44

**Testnutzer:** e.r.matzke@outlook.de (ID 1, Admin: True)

## Zusammenfassung

| Status | Anzahl |
|--------|--------|
| Funktioniert | 41 |
| Warnung | 0 |
| Fehler | 1 |
| Modul deaktiviert | 1 |
| Übersprungen | 0 |

## Modul-Checks

| Modul | URL | Status | HTTP | Detail |
|-------|-----|--------|------|--------|
| Dashboard | `/dashboard` | **OK** | 200 | Seite/API antwortet normal |
| Chat | `/chat/` | **OK** | 200 | OK nach Redirect-Kette -> /chat/1 |
| Dateien | `/files/` | **OK** | 200 | Seite/API antwortet normal |
| Kalender | `/calendar/` | **OK** | 200 | Seite/API antwortet normal |
| Veranstaltungen | `/events/` | **OK** | 200 | Seite/API antwortet normal |
| E-Mail | `/email/` | **OK** | 200 | Seite/API antwortet normal |
| Kontakte | `/contacts/` | **OK** | 200 | Seite/API antwortet normal |
| Zugangsdaten | `/credentials/` | **OK** | 200 | Seite/API antwortet normal |
| Anleitungen | `/manuals/` | **OK** | 200 | Seite/API antwortet normal |
| Lagerverwaltung | `/inventory/` | **OK** | 200 | Seite/API antwortet normal |
| Wiki | `/wiki/` | **OK** | 200 | Seite/API antwortet normal |
| Kurzlinks | `/shortlinks` | **OK** | 200 | Seite/API antwortet normal |
| Kanban | `/kanban/` | **OK** | 200 | Seite/API antwortet normal |
| Excalidraw | `/excalidraw/` | **OK** | 200 | OK nach Redirect-Kette -> /excalidraw/?view=private |
| Umfragen | `/surveys/` | **OK** | 200 | Seite/API antwortet normal |
| Buchungen | `/booking/requests` | **OK** | 200 | Seite/API antwortet normal |
| Musik | `/music/` | **OK** | 200 | Seite/API antwortet normal |
| Media Downloader | `/media-downloader/` | **OK** | 200 | Seite/API antwortet normal |
| Dateikonverter | `/file-converter/` | **OK** | 200 | Seite/API antwortet normal |
| Meetings | `/meetings/` | **–** | 200 | Modul in Systemeinstellungen deaktiviert |
| Bewertungen | `/assessment/` | **OK** | 200 | OK nach Redirect-Kette -> /assessment/home |
| Einstellungen | `/settings/` | **OK** | 200 | Seite/API antwortet normal |
| API: Benachrichtigungen (pending) | `/api/notifications/pending?limit=1` | **OK** | 200 | Seite/API antwortet normal |
| API: Dashboard-Optionen | `/api/dashboard/options` | **OK** | 200 | Seite/API antwortet normal |
| API: E-Mail Unread-Count | `/api/email/unread-count` | **OK** | 200 | Seite/API antwortet normal |
| API: Dateien Speicher | `/files/api/storage-usage` | **OK** | 200 | Seite/API antwortet normal |
| API: Dateien Presence | `/files/api/presence?folder_id=` | **OK** | 200 | Seite/API antwortet normal |
| API: Push VAPID-Key | `/api/push/vapid-key` | **FAIL** | 500 | HTTP 500 Serverfehler |
| API: Manifest | `/manifest.json` | **OK** | 200 | Seite/API antwortet normal |
| Lager: Bestand | `/inventory/stock` | **OK** | 200 | Seite/API antwortet normal |
| Lager: Ausleihen | `/inventory/borrows` | **OK** | 200 | Seite/API antwortet normal |
| Lager: Sets | `/inventory/sets` | **OK** | 200 | Seite/API antwortet normal |
| Kalender: Erstellen | `/calendar/create` | **OK** | 200 | Seite/API antwortet normal |
| Wiki: Erstellen | `/wiki/create` | **OK** | 200 | Seite/API antwortet normal |
| Umfragen: Erstellen | `/surveys/create` | **OK** | 200 | Seite/API antwortet normal |
| Kurzlinks: Erstellen | `/shortlinks/create` | **OK** | 200 | Seite/API antwortet normal |
| Kanban: Templates-API | `/kanban/api/templates` | **OK** | 200 | Seite/API antwortet normal |
| Bewertungen: Home | `/assessment/home` | **OK** | 200 | Seite/API antwortet normal |
| Buchungen: Formular-Liste | `/booking/` | **OK** | 200 | Seite/API antwortet normal |
| Einstellungen: Profil | `/settings/profile` | **OK** | 200 | Seite/API antwortet normal |
| Einstellungen: Admin | `/settings/admin` | **OK** | 200 | OK nach Redirect-Kette -> /settings/#admin |
| Auth: Login-Seite | `/login` | **OK** | 200 | OK nach Redirect-Kette -> /dashboard |
| Startseite (/) | `/` | **OK** | 200 | OK nach Redirect-Kette -> /dashboard |

## Kritische Fehler

- **API: Push VAPID-Key** (`/api/push/vapid-key`): HTTP 500 Serverfehler

## Deaktivierte Module (nicht geprüft)

- Meetings

---
*Rein funktionales Audit – keine Sicherheitsprüfungen.*