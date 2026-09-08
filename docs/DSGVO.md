# DSGVO / Datenschutz – Betriebsleitfaden

> Keine Rechtsberatung. Dieses Dokument hilft Betreibern, Prismateams datenschutzkonform
> zu betreiben. Rechtliche Bewertung und Verträge bleiben bei Ihrer Organisation /
> Ihrem Datenschutzbeauftragten.

## Schnellcheck vor Go-Live

- [ ] Verantwortlicher, Kontakt und Aufsichtsbehörde in Datenschutz/Impressum eingetragen
- [ ] Platzhalter in Admin → Rechtstexte durch konkrete Angaben ersetzt
- [ ] Speicherdauern (Sessions, Share-Logs, Papierkorb) geprüft und in der Datenschutzerklärung genannt
- [ ] Nur benötigte Module/Integrationen aktiviert; Rest deaktiviert
- [ ] Für jeden aktiven Drittdienst: AVV / SCC / DPA geprüft und abgelegt (siehe unten)
- [ ] Hosting, Backup und Log-Retention dokumentiert
- [ ] Prozess für Betroffenenanfragen (Auskunft, Löschung, Export) bekannt
- [ ] Freitext-Module: keine besondere Kategorien (Art. 9) / Minderjährigen-Prozess geklärt (siehe unten)

## Besondere Kategorien und Freitext (Art. 9 / Minderjährige)

Das Portal enthält **Freitextfelder** (Umfragen, Buchungsformulare, Kontakte-Notizen,
Assessment-Beschreibungen, Chat, Wiki u. a.). Dort können theoretisch auch
besondere Kategorien personenbezogener Daten (Gesundheit, Religion, politische
Meinung, biometrische Daten usw., Art. 9 DSGVO) eingetragen werden. Es gibt
**keine automatische Inhaltsfilterung** und **keine Altersprüfung**.

### Betreiber-Richtlinie (empfohlen)

1. In internen Nutzungsregeln / Schulungen festlegen: **keine Art.-9-Daten** in Freitext,
   sofern keine explizite Rechtsgrundlage und Schutzmaßnahmen vorliegen
2. Umfragen und Buchungsfelder so gestalten, dass keine sensiblen Angaben erfragt werden
3. Module mit hohem Risiko nur für geschulte Rollen freigeben oder deaktivieren
4. Bei beabsichtigter Erhebung besonderer Kategorien: Einwilligung / gesetzliche Grundlage,
   Zweckbindung, Zugriffsbeschränkung und Löschkonzept dokumentieren
5. Minderjährige: Portal ist kein Angebot an Kinder im Sinne von Art. 8 DSGVO ohne
   elterliche Zustimmung — Registrierung/Whitelist organisatorisch steuern

Produktseitig gibt es Hinweise im Umfrage-Builder, bei Kontakt-Notizen und in der
Datenschutz-/Nutzungsbedingungen-Vorlage.

Prismateams speichert personenbezogene Daten primär auf dem vom Betreiber betriebenen
Server. Zusätzlich können optionale Integrationen Daten an Dritte übermitteln oder
Dienste einbinden, die als **Auftragsverarbeiter** oder (bei Google/Spotify) teilweise
als **eigenständige Verantwortliche** agieren.

### Inventar möglicher Dienste

| Dienst / Integration | Typische Rolle | Wann aktiv? | Typische Daten | Drittland / Hinweis |
|---|---|---|---|---|
| Hosting / VPS / Cloud-VM | Auftragsverarbeiter | immer | alle Portaldaten, Backups | je nach Anbieter / Region |
| Datenbank-Host (falls extern) | Auftragsverarbeiter | bei managed DB | alle DB-Inhalte | je nach Anbieter |
| SMTP / IMAP-Anbieter | Auftragsverarbeiter | E-Mail konfiguriert | Absender, Empfänger, Betreff, ggf. Inhalt | oft EU; US-Anbieter prüfen |
| Google Login | i. d. R. eigener Verantwortlicher / gemeinsame Aspekte | Admin Google-Login | E-Mail, Name, Google-ID | USA / SCCs von Google |
| Google Drive Import | Auftragsverarbeitung / API-Nutzung | Cloud-Import Google | Dateimetadaten, Dateiinhalte beim Import | USA / SCCs |
| Nextcloud Import | je Hosting | Cloud-Import Nextcloud | Dateien beim Transfer | je Nextcloud-Host |
| Spotify (Musikmodul) | eigener Verantwortlicher / API | `module_music` + OAuth | Account-Token, Playlist-Metadaten | USA / Spotify-Bedingungen |
| Euro-Office Document Server (EU-Fork von ONLYOFFICE Open Source, AGPL) | Auftragsverarbeiter (wenn fremd gehostet) | `ONLYOFFICE_ENABLED` (ENV-Name historisch) | Dokumentinhalte zur Bearbeitung | Self-Host = oft keine Extra-Übermittlung; kein russischer Vendor |
| MiroTalk SFU (Meetings) | Auftragsverarbeiter (wenn fremd gehostet) | `MIROTALK_*` | Meeting-Metadaten, A/V-Streams | Self-Host bevorzugt |
| Excalidraw | Auftragsverarbeiter (wenn fremd gehostet) | `EXCALIDRAW_*` / Modul | Zeichnungsinhalte | Self-Host bevorzugt |
| Web-Push (Browser/OS) | technisch notwendig | VAPID konfiguriert | Push-Endpoint, Keys | Browser-Hersteller |
| Redis (optional) | Auftragsverarbeiter (wenn managed) | `REDIS_ENABLED` | Session-/Queue-Daten | je Anbieter |

Ungenutzte Module in den Einstellungen bzw. per ENV deaktivieren (`ONLYOFFICE_ENABLED=False`,
`MIROTALK_ENABLED=False`, `EXCALIDRAW_ENABLED=False`, Modul-Flags im Admin).

### Checkliste je aktivem Dienst

Für jeden **aktiv** genutzten Eintrag oben:

1. Anbieter und Zweck in der **Datenschutzerklärung** nennen
2. Vertrag prüfen: **AVV (Art. 28)** bzw. Anbieter-DPA; bei Drittland **SCC / Transfermechanismus**
3. Speicherort / Subprozessoren notieren
4. Technische Maßnahmen (TLS, Zugriff, Löschung) mit dem Anbieter abstimmen
5. Nachweis ablegen (Vertrags-PDF, Datum, Ansprechpartner)

Vorlage für den Eintrag in Ihrer internen Liste:

```text
Dienst: […]
Zweck: […]
Rechtsgrundlage: Art. 6 Abs. 1 lit. […] DSGVO
AVV/DPA vorhanden: ja/nein · Datum: […]
Drittlandtransfer: nein / ja → Mechanismus: […]
Module/ENV: […]
Abgeschaltet am: […] (falls nicht mehr genutzt)
```

## Cookie-Consent

- Banner mit Kategorien: notwendig / funktional / Analyse
- UI-Speicherung: `localStorage` (`prismateams_cookie_consent`)
- Servernachweis: Tabelle `cookie_consent_logs` (append-only), Endpoint `POST /cookie-consent`
- Notwendiges Cookie `prismateams_consent_id` (anonyme Zuordnung, HttpOnly)
- **Status Produkt:** Es werden derzeit **keine** optionalen Analytics-/Marketing-Skripte
  geladen; `hasCookieConsent()` ist für künftige Hooks vorgesehen

## Application-Logs und E-Mail-Adressen

- Helper: `app.utils.log_privacy.mask_email` / `mask_emails_in_text`
- Mail-Versand, Registrierung und WebDAV-Auth loggen keine Klartext-Adressen mehr
- Betrieb: `LOG_LEVEL`, journald-/nginx-Retention — siehe `docs/WARTUNG.md` (Datenschutz in Logs)

## Speicherdauern (produktseitige Defaults)

| Bereich | Default | Konfiguration |
|---|---|---|
| Session-IP/UA (`UserSession`) | 30 Tage | Admin → System / `SESSION_RECORD_RETENTION_DAYS` |
| Share-Zugriffsprotokolle | 90 Tage | Admin → System / `SHARE_ACCESS_LOG_RETENTION_DAYS` |
| Datei-Papierkorb | 30 Tage | Admin → Datei-Einstellungen / `FILES_TRASH_DAYS` |
| Gastkonten nach Ablauf | +7 Tage Hard-Delete | `guest_cleanup` |
| Media Downloader | kurz (Stunden) | `MEDIA_DOWNLOADER_RETENTION_HOURS` |
| Dateikonverter | 24 Stunden | `FILE_CONVERTER_RETENTION_HOURS` |

`0` bei den Retention-Settings = kein Auto-Purge (nur bewusst setzen).

## Betroffenenrechte (Produktfunktionen)

| Recht | Wo im Portal |
|---|---|
| Berichtigung | Einstellungen → Profil |
| Datenexport (Art. 20) | Einstellungen → Datenschutz |
| Kontolöschung (Art. 17) | Einstellungen → Profil (E-Mail-Bestätigung; Super-Admin ausgenommen) |
| Admin-Löschung | Einstellungen → Benutzer (gleiche Erasure-Pipeline) |

Bei Anfragen außerhalb des Self-Service: Ticket/E-Mail dokumentieren, Frist beachten,
Export oder Löschung über Admin ausführen und Ergebnis festhalten.

## TOMs (kurz)

Siehe auch `docs/WARTUNG.md` und `docs/INSTALLATION.md`:

- Argon2-Passwörter, CSRF, Session-Cookies (`HttpOnly` / `SameSite` / `Secure` bei HTTPS)
- In Production/Staging: Startup-Warnung und Admin-Anzeige, wenn `SESSION_COOKIE_SECURE=False`
- Fernet-Verschlüsselung für Secrets (Credentials, Mailbox, Musik, TOTP)
- Modul- und Rollenrechte, Rate-Limits
- HTTPS in Produktion (`SESSION_COOKIE_SECURE=True`)

## Verwandte Dateien

- Rechtstext-Vorlage: `app/utils/legal_pages.py` (`DEFAULT_PRIVACY`)
- Retention: `app/utils/access_log_retention.py`, `app/utils/files_trash_retention.py`
- Kontolöschung: `app/utils/account_deletion.py`
- ENV-Beispiel: `docs/env.example`
