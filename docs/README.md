# Prismateams - Team Portal

Ein umfassendes, webbasiertes Team-Portal mit modernem Design und vollständiger Funktionalität für Teams. Entwickelt mit Flask (Python) und Bootstrap 5.

## 📋 Inhaltsverzeichnis

- [Features](#-features)
- [Module](#-module)
- [Installation](#-installation)
- [Projektstruktur](#️-projektstruktur)
- [API-Dokumentation](#-api-dokumentation)
- [Weitere Dokumentation](#-weitere-dokumentation)

## ✨ Features

### Technische Features

- ✅ **Mobile-First Design** mit Bootstrap 5
- ✅ **RESTful API** für zukünftige mobile Apps
- ✅ **Push-Benachrichtigungen** mit Web Push API (VAPID)
- ✅ **Service Worker** für Offline-Funktionalität
- ✅ **OnlyOffice Document Server Integration** für Online-Dokumentenbearbeitung
- ✅ **Excalidraw Integration** für kollaborative Zeichnungen
- ✅ **Benutzerverwaltung** mit Admin-Freischaltung
- ✅ **Rollenbasierte Berechtigungen** (User/Admin)
- ✅ **Dark Mode Support**
- ✅ **Personalisierbare Akzentfarben**
- ✅ **Sichere Passwort-Verschlüsselung** (Argon2)
- ✅ **Dateiversionierung** (letzte 3 Versionen)
- ✅ **Responsive Navigation** (Desktop Sidebar / Mobile Bottom Nav)
- ✅ **Setup-Assistent** für einfache Erstkonfiguration
- ✅ **Modulare Architektur** - Module können aktiviert/deaktiviert werden
- ✅ **Mehrsprachigkeit** (Deutsch, Englisch, Portugiesisch, Spanisch, Russisch)

## 📦 Module

Prismateams besteht aus verschiedenen Modulen, die je nach Bedarf aktiviert oder deaktiviert werden können:

#### 📊 Dashboard
Übersicht mit Widgets für Termine, Chats und E-Mails. Schnellzugriff auf wichtige Informationen und personalisierbare Ansicht.

#### 💬 Chat-System
Haupt-Chat für alle Teammitglieder, Gruppen-Chats für spezifische Teams, Direktnachrichten zwischen Benutzern. Medien-Upload (Bilder, Videos, Dokumente), Echtzeit-Nachrichten mit WebSocket-Unterstützung und Push-Benachrichtigungen.

#### 📁 Dateiverwaltung
Cloud-Speicher mit Ordnerstruktur, Dateiversionierung (letzte 3 Versionen), OnlyOffice Integration für Online-Bearbeitung, Excalidraw Integration für Zeichnungen, Datei-Sharing, Markdown-Vorschau.

#### 📅 Kalender
Gemeinsame Termine mit Teilnahmestatus, Termine erstellen/bearbeiten/löschen, Teilnahme zusagen/absagen, öffentliche Kalender-Feeds, Benachrichtigungen für anstehende Termine.

#### 📧 E-Mail-Client
Zentrales E-Mail-Konto mit IMAP/SMTP-Integration, E-Mails lesen/senden/verwalten, Anhänge unterstützt, E-Mail-Berechtigungen pro Benutzer (Admin-Verwaltung), HTML-E-Mail-Unterstützung.

#### 🔐 Zugangsdaten-Verwaltung
Sichere Passwortverwaltung mit Verschlüsselung (Fernet), verschlüsselte Speicherung sensibler Daten, Kategorisierung und Organisation von Zugangsdaten.

#### 📚 Bedienungsanleitungen
PDF-Verwaltung (Admin-Upload), zentrale Sammlung von Anleitungen und Dokumentationen, einfacher Zugriff für alle Teammitglieder.

#### 🎨 Canvas
Kreativbereich mit dynamischen Textfeldern, freies Layout für Notizen und Ideen, Speicherung von Canvas-Inhalten.

#### 📦 Inventar-Verwaltung
Produktverwaltung mit Kategorien und Ordnern, QR-Code-Generierung für Produkte, Ausleihsystem mit Transaktionsverfolgung, Inventurlisten und PDF-Export, Produktbilder und Metadaten, Statusverwaltung (verfügbar, ausgeliehen, fehlend), Scanner-Funktion für QR-Codes.

#### 📝 Wiki
Internes Wiki-System mit Versionsverwaltung, Kategorien und Tags, Markdown-Unterstützung, Favoriten-Funktion.

#### 💬 Kommentare
Kommentar-System für verschiedene Module, Erwähnungen von Benutzern, Benachrichtigungen bei neuen Kommentaren.

#### 📋 Buchungen
Buchungssystem mit anpassbaren Formularen, öffentliche Buchungsformulare, Genehmigungsworkflows, Datei-Uploads für Buchungen.

#### ⚙️ Einstellungen
Benutzerprofile verwalten, Dark Mode Support, personalisierbare Akzentfarben, Benachrichtigungseinstellungen, System-Einstellungen (nur für Admins), Modulverwaltung (Admin).

## 🚀 Installation

Eine detaillierte Installationsanleitung finden Sie in:

**[📖 INSTALLATION.md](INSTALLATION.md)**

Für die Installation mit OnlyOffice Document Server Integration:

**[📖 UBUNTU_ONLYOFFICE_INSTALLATION.md](UBUNTU_ONLYOFFICE_INSTALLATION.md)**

Für die Installation mit Excalidraw Integration:

**[📖 EXCALIDRAW_INSTALLATION.md](EXCALIDRAW_INSTALLATION.md)**

## 🗂️ Projektstruktur

```
Prismateams_web/
├── app/
│   ├── __init__.py              # Flask App Factory
│   ├── models/                   # Datenbank-Modelle
│   │   ├── user.py
│   │   ├── chat.py
│   │   ├── file.py
│   │   ├── calendar.py
│   │   ├── email.py
│   │   ├── credential.py
│   │   ├── manual.py
│   │   ├── canvas.py
│   │   ├── inventory.py
│   │   ├── notification.py
│   │   ├── settings.py
│   │   ├── whitelist.py
│   │   ├── wiki.py
│   │   ├── comment.py
│   │   ├── booking.py
│   │   ├── role.py
│   │   └── api_token.py
│   ├── blueprints/               # Flask Blueprints (Module)
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── chat.py
│   │   ├── files.py
│   │   ├── calendar.py
│   │   ├── email.py
│   │   ├── credentials.py
│   │   ├── manuals.py
│   │   ├── canvas.py
│   │   ├── inventory.py
│   │   ├── settings.py
│   │   ├── setup.py
│   │   ├── api.py
│   │   ├── wiki.py
│   │   ├── comments.py
│   │   └── booking.py
│   ├── templates/                # Jinja2 Templates
│   ├── static/                   # Statische Dateien
│   ├── tasks/                     # Hintergrund-Tasks
│   └── utils/                     # Hilfsfunktionen
├── docs/                          # Dokumentation
│   ├── README.md
│   ├── INSTALLATION.md
│   ├── UBUNTU_ONLYOFFICE_INSTALLATION.md
│   ├── EXCALIDRAW_INSTALLATION.md
│   ├── API_Übersicht.md
│   └── env.example
├── migrations/                    # Datenbank-Migrationen
├── scripts/                       # Hilfsskripte
├── uploads/                       # Upload-Verzeichnis
├── app.py                         # Einstiegspunkt (Entwicklung)
├── wsgi.py                        # WSGI-Einstiegspunkt (Produktion)
├── config.py                      # Konfiguration
└── requirements.txt               # Python Dependencies
```

## 🔑 API-Dokumentation

Eine vollständige API-Dokumentation mit allen Endpunkten finden Sie in:

**[📖 API_Übersicht.md](API_Übersicht.md)**

Die REST API ist unter `/api/` verfügbar und unterstützt alle Hauptfunktionen des Systems.

## 📚 Weitere Dokumentation

### Lokale Dokumentation

- **[INSTALLATION.md](INSTALLATION.md)** - Detaillierte Installationsanleitung
- **[UBUNTU_ONLYOFFICE_INSTALLATION.md](UBUNTU_ONLYOFFICE_INSTALLATION.md)** - Ubuntu Server Installation mit OnlyOffice
- **[EXCALIDRAW_INSTALLATION.md](EXCALIDRAW_INSTALLATION.md)** - Excalidraw Integration Setup
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

## 📜 Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert. Siehe [LICENSE](../LICENSE) für Details.

## 👥 Beitrag

Beiträge sind willkommen! Bitte erstellen Sie einen Pull Request oder öffnen Sie ein Issue auf GitHub.

## 📧 Support

Bei Fragen oder Problemen:
1. Prüfen Sie die [Dokumentation](https://github.com/iAmCriptic/Prismateams_web/wiki)
2. Überprüfen Sie die Logs
3. Öffnen Sie ein [Issue auf GitHub](https://github.com/iAmCriptic/Prismateams_web/issues)

---

**Entwickelt mit ❤️ für effiziente Team-Zusammenarbeit**
