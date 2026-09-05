# QA-Audit – Sicherheit (defensiv)

**Datum:** 2026-09-05 (aktualisiert)  
**Methode:** Statische Code-Review · Fixes H1–H4, H6–H7  
**Scope:** Keine Exploit-PoCs

## High – Status

| ID | Status | Thema |
|----|--------|-------|
| H1 | Behoben | Gast-Zugriff Expiry |
| H2 | Behoben | Share-Mode bei Gast-Upload/Edit |
| H3 | Behoben | OnlyOffice JWT (Prod hart; Dev unsigned kompatibel) |
| H4 | Behoben | Credentials-Key fail-closed |
| H5 | **Bewusst offen** | WebDAV ohne 2FA (Produktentscheidung) |
| H6 | Behoben | Remember-Cookie Secure/HttpOnly/SameSite |
| H7 | Behoben | Assessment: nur Portal-Admins = Administrator; sonst Bewerter |

## H6 / H7 Details

**H6:** `REMEMBER_COOKIE_HTTPONLY`, `REMEMBER_COOKIE_SAMESITE='Lax'`; in Production `REMEMBER_COOKIE_SECURE` analog Session (override via `REMEMBER_COOKIE_SECURE`).

**H7:** `get_portal_assessment_roles()` — Portal-Admins → `Administrator`; andere Modul-Nutzer → `ASSESSMENT_PORTAL_DEFAULT_ROLES` (Default `Bewerter`). `Administrator` kann für Nicht-Admins nicht per Env eskaliert werden.

## Hinweis H5

WebDAV-2FA / App-Passwörter bewusst zurückgestellt.
