# Team Portal – Installationsskript (Ubuntu)

**Dokumentation:** [INSTALLATION.md](INSTALLATION.md) · [WARTUNG.md](WARTUNG.md) · [ERROR_HANDLING.md](ERROR_HANDLING.md)

Für Ubuntu Server 24.04 existiert ein vollautomatisiertes Installationsskript: [`scripts/install_ubuntu.sh`](../scripts/install_ubuntu.sh).

## Voraussetzungen

- Ubuntu 24.04.3 LTS (oder kompatibel)
- Root-Zugriff (sudo)
- Internet-Verbindung
- Mindestens 4 GB RAM empfohlen (für OnlyOffice und Excalidraw)

## Schnellstart

1. **Repository klonen oder Dateien kopieren**
   ```bash
   git clone <repository-url>
   cd Prismateams_web
   ```

2. **Skript ausführbar machen**
   ```bash
   chmod +x scripts/install_ubuntu.sh
   ```

3. **Skript als root ausführen**
   ```bash
   sudo bash scripts/install_ubuntu.sh
   ```

## Was wird installiert?

Das Skript installiert und konfiguriert automatisch:

- System-Updates und Basis-Pakete
- Python 3.12+ und pip
- MySQL/MariaDB mit automatischer Datenbank- und Benutzererstellung
- Nginx oder Apache mit vollständiger Konfiguration (optional)
- Gunicorn als WSGI-Server
- Docker (nur wenn OnlyOffice oder Excalidraw gewählt)
- OnlyOffice Document Server (Docker, optional)
- Excalidraw Client und Room Server (Docker, optional)
- Python Virtual Environment
- Automatische Generierung aller Keys:
  - Flask `SECRET_KEY`
  - VAPID Keys (Push-Benachrichtigungen)
  - Encryption Keys (Credentials und Music-Modul)
  - OnlyOffice Secret Key
- Automatische `.env`-Konfiguration
- Datenbank-Initialisierung (automatisch beim ersten Gunicorn-Start)
- Systemd-Service für Gunicorn
- Firewall-Konfiguration (UFW)
- Optional: SSL mit Let's Encrypt

## Interaktive Abfragen

Das Skript fragt Sie nach:

1. **Installationspfad** (Standard: `/var/www/teamportal`)
2. **Gunicorn-Port** (Standard: `5000`) — frei wählbar; der Webserver muss auf diesen Port weiterleiten
3. **Webserver automatisch einrichten** (Standard: ja) — Nginx oder Apache vHost inkl. Reverse-Proxy; bei **Nein** nur Gunicorn-Systemd-Service mit `[MANUELL]`-Hinweisen
4. **Domain oder IP-Adresse** — erforderlich bei automatischer Webserver-Einrichtung
5. **SSL mit Let's Encrypt** — nur bei automatischer Webserver-Einrichtung
6. **Docker-Services** (OnlyOffice, Excalidraw — Standard: ja) — einzeln überspringbar
7. **MySQL Root-Passwort** — leer lassen für automatische Generierung
8. **E-Mail-Konfiguration** — SMTP/IMAP (optional)

## Kommandozeilen-Optionen

Ohne Optionen führt das Skript interaktive Abfragen durch. Optionen können einzelne Fragen vorbelegen:

```bash
sudo bash scripts/install_ubuntu.sh --help

# Beispiele:
sudo bash scripts/install_ubuntu.sh --port 8000
sudo bash scripts/install_ubuntu.sh --no-webserver --port 8000
sudo bash scripts/install_ubuntu.sh --webserver nginx --skip-excalidraw
```

### CLI-Referenz

| Option | Beschreibung |
|--------|--------------|
| `--port PORT` | Gunicorn-Port (Standard: 5000) |
| `--no-webserver` | Kein Nginx/Apache vHost einrichten |
| `--webserver nginx\|apache` | Webserver-Typ vorgeben |
| `--skip-docker` | Docker, OnlyOffice und Excalidraw überspringen |
| `--skip-onlyoffice` | OnlyOffice Document Server überspringen |
| `--skip-excalidraw` | Excalidraw Client und Room Server überspringen |
| `--help`, `-h` | Hilfe anzeigen |

Bei übersprungenen Schritten gibt das Skript `[MANUELL]`-Hinweise mit den Standard-Einstellungen aus, die es sonst gesetzt hätte.

### Manuelle Nacharbeit

Wenn Schritte übersprungen wurden (z. B. `--no-webserver`, `--skip-docker`):

- **Webserver / SSL / Firewall:** [INSTALLATION.md – Schritt 11–13](INSTALLATION.md#schritt-11-nginx-konfigurieren)
- **Docker / OnlyOffice:** [INSTALLATION.md – Schritt 2 und 5](INSTALLATION.md#schritt-2-docker-installieren-für-excalidraw-und-onlyoffice)
- **Excalidraw:** [INSTALLATION.md – Schritt 6](INSTALLATION.md#schritt-6-optionale-installation---excalidraw)

## Automatisch generierte Werte

Das Skript generiert automatisch:

- MySQL Root-Passwort (falls nicht angegeben)
- Datenbank-Benutzer-Passwort
- Flask `SECRET_KEY`
- VAPID Keys
- Encryption Keys
- OnlyOffice Secret Key (falls OnlyOffice installiert)

**WICHTIG:** Speichern Sie die am Ende ausgegebenen Passwörter und Keys sicher!

## Nach der Installation

1. **E-Mail-Konfiguration prüfen** — Einstellungen liegen in `$INSTALL_DIR/.env`
2. **Anwendung öffnen** — `http://ihre-domain.de` (oder `https://` bei SSL)
3. **Admin anlegen** — Setup-Assistent im Browser
4. **Service-Status prüfen**
   ```bash
   systemctl status teamportal
   systemctl status nginx   # falls Webserver eingerichtet
   docker ps              # falls Docker-Services installiert
   ```

Weitere Schritte (Updates, Backups): [WARTUNG.md](WARTUNG.md)

## Vorteile der automatischen Installation

- **Vollautomatisch:** Alle Schritte werden automatisch ausgeführt
- **Konsistent:** Gleiche Konfiguration bei jeder Installation
- **Schnell:** Installation in wenigen Minuten
- **Sicher:** Automatische Generierung sicherer Passwörter und Keys

## Bei Problemen

- Logs während der Installation im Terminal prüfen
- `.env`-Datei überprüfen
- [ERROR_HANDLING.md](ERROR_HANDLING.md) — Fehlerbehebung
- Manuelle Installation als Alternative: [INSTALLATION.md](INSTALLATION.md)
