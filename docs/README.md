# Prismateams - Team Portal

Ein umfassendes, webbasiertes Team-Portal mit modernem Design und vollständiger Funktionalität für Teams. Entwickelt mit Flask (Python) und Bootstrap 5.

### Disclaimer
Das Portal und auch die Dazugehörige Dokumentation wurde zum Teil mit der IDE Cursor und den damit Verbunden KI Tools erstellt. Bei Fehlerhafter Dokuemntation & daraus resultierenden Problemen bitten wir dies zu entschuldigen, da dies ein schulprojekt ist und uns die Zeit fehlt alles ins detail zu überprüfen.
Wir übernehmen keine Haftung wir ausgenutze Sicherlücken, fehlerhaftes verhalten, datenverlust oder ähnliches die Nutzung dieses Repos erfolgt auf eigene Gefahr.  

## 📋 Inhaltsverzeichnis

- [Features](#-features)
- [Module](#-module)
- [Installation](#-installation)
- [Technische Details](#-technische-details)
- [API-Dokumentation](#-api-dokumentation)
- [Projektstruktur](#️-projektstruktur)
- [Dokumentation](#-dokumentation)
- [Lizenz & Support](#-lizenz--support)

## ✨ Features

### Technische Features

- ✅ **Mobile-First Design** mit Bootstrap 5
- ✅ **RESTful API** für zukünftige mobile Apps
- ✅ **Push-Benachrichtigungen** mit Web Push API (VAPID)
- ✅ **Service Worker** für Offline-Funktionalität
- ✅ **WebSocket/Socket.IO** für Echtzeit-Updates
- ✅ **Redis-Integration** für Multi-Worker-Setups
- ✅ **OnlyOffice Document Server Integration** (optional) für Online-Dokumentenbearbeitung
- ✅ **Benutzerverwaltung** mit Admin-Freischaltung
- ✅ **Gast-Accounts** für temporären Zugriff
- ✅ **Rollenbasierte Berechtigungen** (User/Admin/Gast)
- ✅ **Modulbasierte Zugriffskontrolle**
- ✅ **Dark Mode Support**
- ✅ **Personalisierbare Akzentfarben**
- ✅ **Sichere Passwort-Verschlüsselung** (Argon2)
- ✅ **Verschlüsselte Credentials-Speicherung** (Fernet)
- ✅ **Dateiversionierung** (letzte 3 Versionen)
- ✅ **Responsive Navigation** (Desktop Sidebar / Mobile Bottom Nav)
- ✅ **Setup-Assistent** für einfache Erstkonfiguration
- ✅ **Modulare Architektur** - Module können aktiviert/deaktiviert werden
- ✅ **Mehrsprachigkeit** (Deutsch, Englisch, Portugiesisch, Spanisch, Russisch)
- ✅ **Automatische Installation** für Ubuntu Server
- ✅ **Datenbank-Migrationen** für einfache Updates

## 📦 Module

Prismateams besteht aus verschiedenen Modulen, die je nach Bedarf aktiviert oder deaktiviert werden können:

### 📊 Dashboard
Übersicht mit Widgets für Termine, Chats und E-Mails. Schnellzugriff auf wichtige Informationen, personalisierbare Ansicht und konfigurierbare Banner.

### 💬 Chat-System
Haupt-Chat für alle Teammitglieder, Gruppen-Chats für spezifische Teams, Direktnachrichten zwischen Benutzern. Medien-Upload (Bilder, Videos, Dokumente), Echtzeit-Nachrichten mit WebSocket-Unterstützung, Push-Benachrichtigungen und Lesebestätigungen.

### 📁 Dateiverwaltung
Cloud-Speicher mit Ordnerstruktur, Dateiversionierung (letzte 3 Versionen), OnlyOffice Integration (optional) für Online-Bearbeitung von Office-Dokumenten, Datei-Sharing mit temporären Links, Markdown-Vorschau und Text-Editor.

### 📅 Kalender
Gemeinsame Termine mit Teilnahmestatus, Termine erstellen/bearbeiten/löschen, Teilnahme zusagen/absagen, öffentliche Kalender-Feeds (iCal), Benachrichtigungen für anstehende Termine, monatliche und zeitraumbasierte Ansichten.

### 📧 E-Mail-Client
Zentrales E-Mail-Konto mit IMAP/SMTP-Integration, E-Mails lesen/senden/verwalten, Anhänge unterstützt, E-Mail-Berechtigungen pro Benutzer (Admin-Verwaltung), HTML-E-Mail-Unterstützung, E-Mail-Synchronisation im Hintergrund.

### 🔐 Zugangsdaten-Verwaltung
Sichere Passwortverwaltung mit Verschlüsselung (Fernet), verschlüsselte Speicherung sensibler Daten, Kategorisierung und Organisation von Zugangsdaten, Passwort-Anzeige mit Berechtigungskontrolle.

### 📚 Bedienungsanleitungen
PDF-Verwaltung (Admin-Upload), zentrale Sammlung von Anleitungen und Dokumentationen, einfacher Zugriff für alle Teammitglieder.

### 📦 Inventar-Verwaltung
Produktverwaltung mit Kategorien und Ordnern, QR-Code-Generierung für Produkte, Ausleihsystem mit Transaktionsverfolgung, Inventurlisten und PDF-Export, Produktbilder und Metadaten, Statusverwaltung (verfügbar, ausgeliehen, fehlend), Scanner-Funktion für QR-Codes, Sets und Kategorien, Mobile-API für Scanner-Apps.

### 📝 Wiki
Internes Wiki-System mit Versionsverwaltung, Kategorien und Tags, Markdown-Unterstützung, Favoriten-Funktion, Volltext-Suche.

### 💬 Kommentare
Kommentar-System für verschiedene Module, Erwähnungen von Benutzern, Benachrichtigungen bei neuen Kommentaren.

### 📋 Buchungen
Buchungssystem mit anpassbaren Formularen, öffentliche Buchungsformulare, Genehmigungsworkflows, Datei-Uploads für Buchungen, PDF-Export.

### ⚙️ Einstellungen
Benutzerprofile verwalten, Dark Mode Support, personalisierbare Akzentfarben, Benachrichtigungseinstellungen, System-Einstellungen (nur für Admins), Modulverwaltung (Admin), Whitelist-Verwaltung (Admin).

## 🚀 Installation

Für Ubuntu Server 24.04 wird die **automatische Installation** empfohlen:

```bash
sudo bash scripts/install_ubuntu.sh
```

**Dokumentation:**

- **[INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md)** — Installationsskript, CLI-Optionen
- **[INSTALLATION.md](INSTALLATION.md)** — Manuelle Schritt-für-Schritt-Installation
- **[WARTUNG.md](WARTUNG.md)** — Updates, Migrationen, Backups
- **[ERROR_HANDLING.md](ERROR_HANDLING.md)** — Fehlerbehebung

## 🔧 Technische Details

### Systemanforderungen

**Minimal:**
- Python 3.8+
- MySQL/MariaDB oder SQLite
- 2GB RAM
- 10GB Speicherplatz

**Empfohlen (Produktion):**
- Python 3.12+
- MySQL/MariaDB
- 4GB+ RAM
- 20GB+ Speicherplatz
- Redis (für Multi-Worker-Setups)

**Mit OnlyOffice:**
- 8GB+ RAM
- 20GB+ zusätzlicher Speicherplatz


## 🔑 API-Dokumentation

Eine vollständige API-Dokumentation mit allen Endpunkten finden Sie in:

**[📖 API_Übersicht.md](API_Übersicht.md)**

Die REST API ist unter `/api/` verfügbar und unterstützt alle Hauptfunktionen des Systems:

- Benutzer-API
- Chat-API
- Dateien-API
- Kalender-API
- E-Mail-API
- Zugangsdaten-API
- Dashboard-API
- Inventar-API
- Wiki-API
- Musik-API
- Push Notifications API
- WebSocket/Socket.IO Events

## 🗂️ Projektstruktur

```
Prismateams_web/
├── app/
│   ├── __init__.py              # Flask App Factory
│   ├── models/                   # Datenbank-Modelle
│   │   ├── user.py              # Benutzer, Gast-Accounts
│   │   ├── chat.py              # Chat-System
│   │   ├── file.py              # Dateiverwaltung
│   │   ├── calendar.py          # Kalender
│   │   ├── email.py             # E-Mail-Integration
│   │   ├── credential.py        # Zugangsdaten
│   │   ├── manual.py            # Bedienungsanleitungen
│   │   ├── inventory.py         # Inventar-Verwaltung
│   │   ├── notification.py      # Benachrichtigungen
│   │   ├── settings.py          # Einstellungen
│   │   ├── whitelist.py         # Whitelist
│   │   ├── wiki.py              # Wiki
│   │   ├── comment.py           # Kommentare
│   │   ├── booking.py           # Buchungen
│   │   ├── role.py              # Rollen/Berechtigungen
│   │   ├── guest.py             # Gast-Accounts
│   │   └── api_token.py         # API-Tokens
│   ├── blueprints/               # Flask Blueprints (Module)
│   │   ├── auth.py              # Authentifizierung
│   │   ├── dashboard.py         # Dashboard
│   │   ├── chat.py              # Chat
│   │   ├── files.py             # Dateiverwaltung
│   │   ├── calendar.py          # Kalender
│   │   ├── email.py             # E-Mail
│   │   ├── credentials.py       # Zugangsdaten
│   │   ├── manuals.py           # Bedienungsanleitungen
│   │   ├── inventory.py         # Inventar
│   │   ├── settings.py          # Einstellungen
│   │   ├── setup.py             # Setup-Assistent
│   │   ├── api.py               # REST API
│   │   ├── wiki.py              # Wiki
│   │   ├── comments.py          # Kommentare
│   │   └── booking.py           # Buchungen
│   ├── templates/                # Jinja2 Templates
│   ├── static/                   # Statische Dateien
│   ├── tasks/                     # Hintergrund-Tasks
│   └── utils/                     # Hilfsfunktionen
├── docs/                          # Dokumentation
│   ├── README.md                 # Diese Datei
│   ├── INSTALLATION.md           # Manuelle Installation
│   ├── INSTALLATION_SCRIPT.md    # Ubuntu-Installationsskript
│   ├── WARTUNG.md                # Updates, Migrationen, Backups
│   ├── ERROR_HANDLING.md         # Fehlerbehebung
│   ├── API_Übersicht.md          # API-Dokumentation
│   └── env.example               # Konfigurationsbeispiel
├── migrations/                    # Datenbank-Migrationen
│   └── migrate_to_2.3.3.py      # Aktuelle Migration
├── scripts/                       # Hilfsskripte
│   ├── install_ubuntu.sh         # Automatische Installation
│   ├── generate_encryption_keys.py
│   └── generate_vapid_keys.py
├── uploads/                       # Upload-Verzeichnis
├── app.py                         # Einstiegspunkt (Entwicklung)
├── wsgi.py                        # WSGI-Einstiegspunkt (Produktion)
├── config.py                      # Konfiguration
└── requirements.txt               # Python Dependencies
```

## 📚 Dokumentation

### Lokale Dokumentation

- **[README.md](README.md)** - Diese Datei (Überblick)
- **[INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md)** - Ubuntu-Installationsskript und CLI
- **[INSTALLATION.md](INSTALLATION.md)** - Manuelle Schritt-für-Schritt-Installation
- **[WARTUNG.md](WARTUNG.md)** - Updates, Migrationen, Backups
- **[ERROR_HANDLING.md](ERROR_HANDLING.md)** - Fehlerbehebung
- **[API_Übersicht.md](API_Übersicht.md)** - Vollständige API-Dokumentation
- **[env.example](env.example)** - Beispiel-Konfigurationsdatei

### GitHub Wiki

Für detaillierte Informationen zu einzelnen Modulen, Troubleshooting, Sicherheit und weiteren Themen besuchen Sie das [GitHub Wiki](https://github.com/iAmCriptic/Prismateams_web/wiki).

Das Wiki enthält:
- Detaillierte Modul-Dokumentationen
- Troubleshooting-Anleitungen
- Sicherheitsrichtlinien
- Entwickler-Dokumentation
- Q&A-Bereich

## 📜 Lizenz & Support

### Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert. Siehe [LICENSE](../LICENSE) für Details.

### Beitrag

Beiträge sind willkommen! Bitte erstellen Sie einen Pull Request oder öffnen Sie ein Issue auf GitHub.

### Support

Bei Fragen oder Problemen:

1. Prüfen Sie die [Dokumentation](INSTALLATION.md) bzw. [ERROR_HANDLING.md](ERROR_HANDLING.md)
2. Überprüfen Sie die [API-Dokumentation](API_Übersicht.md)
3. Besuchen Sie das [GitHub Wiki](https://github.com/iAmCriptic/Prismateams_web/wiki)
4. Überprüfen Sie die Logs
5. Öffnen Sie ein [Issue auf GitHub](https://github.com/iAmCriptic/Prismateams_web/issues)

---

**Entwickelt mit ❤️ für effiziente Team-Zusammenarbeit**
