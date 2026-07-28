<p align="center">
  <img src="../app/static/img/logo.png" alt="Prismateams Logo" width="96">
</p>

<h1 align="center">Prismateams – API-Authentifizierung</h1>

<p align="center">
  <strong>Dokumentation · Version 3.0.1</strong><br>
  <img src="https://img.shields.io/badge/version-3.0.1-7c3aed?style=flat-square" alt="Version 3.0.1">
</p>

<p align="center">
  <a href="README.md">Übersicht</a> ·
  <a href="API_Übersicht.md">API-Endpunkte</a> ·
  <a href="INSTALLATION.md">Installation</a> ·
  <a href="ERROR_HANDLING.md">Fehlerbehebung</a>
</p>

---

Die Mobile-/REST-API unter `/api/` unterstützt **Session** (Cookies) und **Bearer-Token**. Login inkl. optionaler **2FA (TOTP)**.

## Methoden

| Methode | Verwendung | Header / Cookie |
|---------|------------|-----------------|
| **Session** | Web / Browser | Session-Cookie nach Login |
| **Token** | Apps / Skripte | `Authorization: Bearer <token>` |

Geschützte Routen nutzen `require_api_auth` (Session **oder** gültiges Token).

---

## Login

### `POST /api/auth/login`

Rate-Limit: **5 / 15 Minuten**.

```json
{
  "email": "user@example.com",
  "password": "password123",
  "totp_code": "123456",
  "remember": true,
  "return_token": false
}
```

| Feld | Pflicht | Beschreibung |
|------|---------|--------------|
| `email` | ja | E-Mail oder Gast (`name@gast.system.local`) |
| `password` | ja | Passwort |
| `totp_code` | wenn 2FA an | 6-stelliger TOTP |
| `remember` | nein | Längere Session |
| `return_token` | nein | Bei `true`: API-Token statt nur Session |

#### 2FA erforderlich (noch kein Code)

Status `200`:

```json
{
  "success": false,
  "requires_2fa": true,
  "message": "2FA-Code erforderlich",
  "error": "Bitte geben Sie den 2FA-Code ein"
}
```

#### Erfolg

```json
{
  "success": true,
  "user": {
    "id": 1,
    "email": "user@example.com",
    "full_name": "Max Mustermann",
    "is_admin": false,
    "totp_enabled": true
  },
  "token": "…"
}
```

`token` nur bei `return_token: true`.

#### Fehler (Auswahl)

| Status | Bedeutung |
|--------|-----------|
| `400` | Keine / unvollständige Daten |
| `401` | Ungültige Zugangsdaten / 2FA-Code / Gast abgelaufen |
| `403` | Account nicht aktiv / E-Mail nicht bestätigt |
| `423` | Account zeitweise gesperrt (Brute-Force) |

---

## Token verwenden

```http
GET /api/users/me
Authorization: Bearer <api-token>
Accept: application/json
```

---

## Logout & Token prüfen

### `POST /api/auth/logout`

Beendet die Session (bei Session-Auth).

### `POST /api/auth/verify-token`

Prüft Session bzw. Token und liefert User-Payload bei Erfolg.

---

## Tipps für Clients

1. Login ohne `totp_code` → bei `requires_2fa` Code abfragen und Login wiederholen
2. Mobile: `return_token: true`, Token sicher speichern
3. Web: Cookies / Session reicht oft ohne Token
4. Bei `423`: `remaining_seconds` beachten

Mehr Endpunkte: **[API_Übersicht.md](API_Übersicht.md)**

---

<p align="center">
  <img src="../app/static/img/logo.png" alt="" width="40"><br>
  <sub>Prismateams 3.0.1</sub>
</p>
