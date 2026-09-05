<p align="center">
  <img src="../app/static/img/logo.png" alt="Prismateams Logo" width="96">
</p>

<h1 align="center">Prismateams – Installation</h1>

<p align="center">
  <strong>Dokumentation · Version 3.0.1</strong><br>
  <img src="https://img.shields.io/badge/version-3.0.1-7c3aed?style=flat-square" alt="Version 3.0.1">
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
</p>

<p align="center">
  <a href="README.md">Übersicht</a> ·
  <a href="INSTALLATION_SCRIPT.md">Ubuntu-Skript</a> ·
  <a href="WARTUNG.md">Wartung</a> ·
  <a href="ERROR_HANDLING.md">Fehlerbehebung</a>
</p>

---

> **Empfohlen: modularer Ubuntu-Installer**  
> Produktion auf Ubuntu 24.04 / 26.04 LTS: `sudo bash scripts/install_ubuntu.sh` — vollständig einsatzbereit. Alle Optionen: [INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md). Diese Seite beschreibt die **manuelle** Installation für Sonderfälle.

## Hinweis zu VAPID- und Encryption-Keys

Der Installer erzeugt Keys in der Regel automatisch. Bei manueller Installation ggf. in `.env` nachtragen (Benachrichtigungen, Zugangsdaten, Music):

```bash
# Encryption Keys (aus generate_encryption_keys.py kopieren)
CREDENTIAL_ENCRYPTION_KEY=your-credential-encryption-key-here
MUSIC_ENCRYPTION_KEY=your-music-encryption-key-here

VAPID_PUBLIC_KEY=your-vapid-public-key-here
VAPID_PRIVATE_KEY=your-vapid-private-key-here
```

Beispiel-Konfiguration: [env.example](env.example)

## Empfohlene Installation (Ubuntu)

```bash
sudo bash scripts/install_ubuntu.sh
```

CLI, Module und Beispiele: **[INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md)**

---

## Produktionsinstallation (Ubuntu Server) – Manuelle Methode

Schritt-für-Schritt-Installation von **Prismateams 3.0.1** auf Ubuntu Server (Alternative zum Skript), inkl. optionaler Integrationen (Excalidraw, OnlyOffice).

**⚠️ Wichtiger Hinweis zu optionalen Features:**
- **OnlyOffice** und **Excalidraw** sind **OPTIONAL** und nicht zwingend erforderlich
- **Media Downloader** ist **OPTIONAL** (benötigt FFmpeg, kein Docker)
- **Dateikonverter** ist **OPTIONAL** (Audio/Bilder/PDF ohne Extra-Tools; Dokumente benötigen LibreOffice)
- Wenn Sie diese Features **NICHT** benötigen, können Sie die entsprechenden Schritte überspringen
- In der `.env`-Datei müssen Sie dann `ONLYOFFICE_ENABLED=False` und/oder `EXCALIDRAW_ENABLED=False` setzen
- Die Nginx-Konfiguration muss entsprechend angepasst werden (optionalen Location-Blöcke entfernen)

### Schritt 1: System vorbereiten

```bash
# System aktualisieren
sudo apt update && sudo apt upgrade -y

# Notwendige Pakete installieren
sudo apt install -y python3 python3-pip python3-venv \
    nginx mariadb-server git \
    curl wget ufw certbot python3-certbot-nginx \
    apt-transport-https ca-certificates gnupg lsb-release
```

### Schritt 2: Docker installieren (für Excalidraw und OnlyOffice)

**Hinweis:** Docker ist nur erforderlich, wenn Sie Excalidraw oder OnlyOffice installieren möchten. Sie können diesen Schritt überspringen, wenn Sie diese Features nicht benötigen.

```bash
# Docker + Compose-Plugin installieren (empfohlen)
sudo apt install -y docker.io docker-compose-plugin

# Docker Service aktivieren und starten
sudo systemctl enable docker
sudo systemctl start docker

# Aktuellen Benutzer zur Docker-Gruppe hinzufügen
sudo usermod -aG docker $USER

# Abmelden und wieder anmelden, damit Docker-Gruppe aktiv wird
# Oder alternativ:
newgrp docker

# Docker Installation testen
sudo docker --version
sudo docker ps
```

### Schritt 3: MariaDB einrichten

**Wichtig:** Sie müssen nur die **leere Datenbank** erstellen. Alle Tabellen werden **automatisch** beim ersten Start der Anwendung erstellt!

```bash
# MariaDB absichern
sudo mysql_secure_installation

# Datenbank und Benutzer erstellen
sudo mysql -u root -p
```

In der MySQL-Konsole:
```sql
-- Nur die leere Datenbank erstellen (KEINE Tabellen!)
CREATE DATABASE teamportal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Datenbankbenutzer erstellen
CREATE USER 'teamportal'@'localhost' IDENTIFIED BY 'IhrSicheresPasswort123!';
GRANT ALL PRIVILEGES ON teamportal.* TO 'teamportal'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

**Wichtig:** 
- Ersetzen Sie `IhrSicheresPasswort123!` mit einem sicheren Passwort Ihrer Wahl
- Erstellen Sie **NUR** die leere Datenbank - alle Tabellen werden automatisch beim ersten Start erstellt

### Schritt 4: Anwendung von GitHub installieren

```bash
# Verzeichnis erstellen
sudo mkdir -p /var/www
cd /var/www

# Repository klonen (ersetzen Sie die URL mit Ihrem GitHub-Repository)
sudo git clone https://github.com/yourusername/Prismateams_web.git teamportal
cd teamportal

# Virtual Environment erstellen
sudo python3 -m venv venv

# Dependencies installieren
sudo ./venv/bin/pip install --upgrade pip
sudo ./venv/bin/pip install -r requirements.txt
```

### Schritt 5: Optionale Installation - OnlyOffice Document Server (Docs)

**⚠️ OPTIONAL:** Nur nötig für Dokumentenbearbeitung im Portal. Sonst `ONLYOFFICE_ENABLED=False` in der `.env`.

**Wichtig:** Installieren Sie **ONLYOFFICE Docs (Document Server)**, nicht Community Server / Workspace.
Community Server ([Docker-CommunityServer](https://github.com/ONLYOFFICE/Docker-CommunityServer)) ist ein eigenes Portal und kollidiert mit Nginx/Apache (Port 80/443).
Offizielles Image: [Docker-DocumentServer](https://github.com/ONLYOFFICE/Docker-DocumentServer) → `onlyoffice/documentserver:latest`.

**Voraussetzungen:** ≥4 GB RAM, mehrere GB freier Disk, Architektur **amd64/x86_64**, Docker Engine ≥20.10.21.

```bash
# Volumes (Community Edition, offizielles Layout)
sudo mkdir -p /var/lib/onlyoffice/DocumentServer/{data,logs,lib,fonts}

# Neueste Docs-Version laden und starten (JWT aktiv, nur localhost)
sudo docker pull onlyoffice/documentserver:latest
sudo docker run -d --restart=always \
    --name onlyoffice-documentserver \
    -p 127.0.0.1:8080:80 \
    -v /var/lib/onlyoffice/DocumentServer/logs:/var/log/onlyoffice \
    -v /var/lib/onlyoffice/DocumentServer/data:/var/www/onlyoffice/Data \
    -v /var/lib/onlyoffice/DocumentServer/lib:/var/lib/onlyoffice \
    -v /var/lib/onlyoffice/DocumentServer/fonts:/usr/share/fonts/truetype/custom \
    -e JWT_ENABLED=true \
    -e JWT_SECRET=dein-jwt-secret-key-hier \
    -e JWT_HEADER=Authorization \
    -e ALLOW_PRIVATE_IP_ADDRESS=true \
    onlyoffice/documentserver:latest

# Prüfen (Erststart kann 1–3 Minuten dauern)
sudo docker ps | grep onlyoffice
curl -s http://127.0.0.1:8080/healthcheck
curl -s http://127.0.0.1:8080/welcome/ | head
```

**Wichtig:** Notieren Sie den `JWT_SECRET`-Wert – er muss mit `ONLYOFFICE_SECRET_KEY` in der `.env` übereinstimmen.

**Hinweis:** JWT ist seit Docs ≥7.2 standardmäßig aktiv. Ohne JWT lokal: `-e JWT_ENABLED=false` und `ONLYOFFICE_SECRET_KEY` leer lassen (Dev erlaubt unsigned Callbacks automatisch). In **Production** ohne Secret werden Callbacks abgelehnt – entweder Secret setzen oder explizit `ONLYOFFICE_ALLOW_UNSIGNED_CALLBACKS=true`.

#### Schriftarten für Rendering / PDF / Druck

PDF, Druck und serverseitiges Rendering brauchen TTF/OTF-Dateien, die das Document-Server-Image **nicht** mitbringt. Das sind vor allem die Microsoft Core Fonts (Arial, Times New Roman, Courier New, Georgia, Verdana). **Carlito, Caladea, Liberation und DejaVu** liegen bereits im Image – dieselben Familien zusätzlich ins Custom-Volume zu kopieren zerlegt den Font-Index (`font_selection.bin`, Calibri→Carlito) und führt zu Open-Fehlern in Word, Excel und PowerPoint.

```bash
# Nur Microsoft Core Fonts (fehlen im Image)
sudo apt update
echo ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true | sudo debconf-set-selections
sudo apt install -y ttf-mscorefonts-installer cabextract

# Volume leeren und nur mscorefonts kopieren (überlebt Container-Updates)
sudo mkdir -p /var/lib/onlyoffice/DocumentServer/fonts
sudo find /var/lib/onlyoffice/DocumentServer/fonts -maxdepth 1 -type f \
  \( -iname '*.ttf' -o -iname '*.otf' -o -iname '*.ttc' \) -delete
sudo find /usr/share/fonts/truetype/msttcorefonts \
  -type f \( -iname '*.ttf' -o -iname '*.otf' \) \
  -exec cp {} /var/lib/onlyoffice/DocumentServer/fonts/ \; 2>/dev/null || true

# Font-Index: Container neu starten (Entrypoint indexiert das Volume selbst).
# documentserver-generate-allfonts.sh nicht gegen einen laufenden Editor ausführen.
sudo docker restart onlyoffice-documentserver
```

**Hinweise:**
- **Carlito** (im Image) ist metric-kompatibel zu **Calibri**. Neue Dateien behalten den OOXML-Namen Calibri; OnlyOffice rendert sie als Carlito.
- Echte `Calibri.ttf` können Sie zusätzlich ins Fonts-Volume legen und den Container **neu starten** (kein Live-Generate-allfonts).
- Browser-Cache leeren (Strg+F5 bzw. Cmd+Shift+R). Ab OnlyOffice Docs 8.2 oft nicht mehr nötig.
- `ttf-mscorefonts-installer` lädt Schriften von SourceForge; bei Download-Fehlern nutzt OnlyOffice die Image-Fonts weiter.

### Schritt 6: Optionale Installation - Excalidraw Room

**⚠️ ARCHITEKTUR & VENDOR-ASSETS:** Der Excalidraw-Zeichnungs-Editor ist **nativ in Flask** integriert. React, ReactDOM, Excalidraw 0.18.1 und Socket.IO werden beim Install (`scripts/download_excalidraw_vendor.py`) nach `app/static/vendor/` geladen und gehören **nicht** ins Git-Repository. Fehlen lokale Dateien, nutzt der Editor CDN-Fallbacks (unpkg/esm.sh). Docker ist für den Editor selbst nicht nötig.

**⚠️ DOCKER (OPTIONAL):** Docker ist **nur für Live-Kollaboration** (echtzeit-gemeinsames Zeichnen mehrerer Benutzer) nötig. Zeichnen, Versionierung und automatisches Speichern funktionieren auch ohne Docker. Wenn der Room-Server fehlt, funktioniert das Zeichnen lokal; setzen Sie `EXCALIDRAW_ENABLED=False` in der `.env`, falls Sie Kollaboration deaktivieren möchten.

Der Editor läuft nativ im Portal unter `/excalidraw` (kein Iframe der öffentlichen Excalidraw-SPA).

```bash
# Excalidraw-Room nur auf Loopback (Port 8082) für Live-Kollaboration
sudo docker pull excalidraw/excalidraw-room:latest
sudo docker run -d --restart=always \
    --name excalidraw-room \
    -p 127.0.0.1:8082:80 \
    -e PORT=80 \
    excalidraw/excalidraw-room:latest

sudo docker ps | grep excalidraw-room
curl -I http://127.0.0.1:8082/
```

### Schritt 6b: Optionale Installation - Media Downloader

**⚠️ OPTIONAL:** Dieser Schritt ist nur erforderlich, wenn Sie YouTube-/YouTube-Music-Downloads im Portal nutzen möchten.

```bash
# FFmpeg installieren (für serverseitige Konvertierung nach Browser-Download)
sudo apt install -y ffmpeg

# Installation prüfen
ffmpeg -version
```

**Hinweise:**
- Kein Docker oder Nginx-Proxy erforderlich
- **Downloads** erfolgen im Browser des Nutzers (youtubei.js); YouTube-API- und Stream-Requests laufen über den Portal-Server (`/media-downloader/youtube-proxy`), weil Browser YouTube sonst per CORS blockieren
- **Konvertierung** (MP3/MP4) erfolgt serverseitig via FFmpeg
- **Aktivierung im Portal:** Einstellungen → Administration → Module → **Media Downloader**
- Heruntergeladene Dateien werden standardmäßig nach **1 Stunde** automatisch gelöscht (`MEDIA_DOWNLOADER_RETENTION_HOURS` in `.env`, optional)
- **Playlists:** YouTube- und YouTube-Music-Playlists können über die Weboberfläche als Batch heruntergeladen werden; parallel laufende Downloads begrenzt `MEDIA_DOWNLOADER_MAX_CONCURRENT` (Standard: 2)
- **Rechtlicher Hinweis:** Nutzer sind für die Einhaltung von Urheberrecht und Plattform-Nutzungsbedingungen verantwortlich
- Bei altersbeschränkten Videos muss der Nutzer im selben Browser bei YouTube angemeldet sein

### Schritt 6c: Optionale Installation - Dateikonverter (LibreOffice)

**⚠️ OPTIONAL:** Für Audio-, Bild- und PDF-Konvertierung reichen FFmpeg (bereits für Media Downloader) bzw. die Python-Pakete Pillow/`pypdf`/`img2pdf`. **LibreOffice** wird nur für Office-Dokumente (DOCX, XLSX, PPTX, ODT, …) benötigt.

```bash
# LibreOffice installieren (headless Konvertierung)
sudo apt install -y libreoffice-writer libreoffice-calc libreoffice-impress

# Installation prüfen
soffice --version
```

**Hinweise:**
- Optionaler Pfad über `LIBREOFFICE_PATH` in der `.env`, falls `soffice` nicht im PATH liegt
- **Aktivierung im Portal:** Einstellungen → Administration → Module → **Dateikonverter**
- Konvertierte Dateien werden standardmäßig nach **24 Stunden** gelöscht (`FILE_CONVERTER_RETENTION_HOURS`)
- Parallel laufende Jobs begrenzt `FILE_CONVERTER_MAX_CONCURRENT` (Standard: 2)
- Ohne LibreOffice bleiben Audio-/Bild-/PDF-Funktionen nutzbar; Dokument-Optionen fehlen dann in der UI

### Schritt 7: Konfiguration (.env-Datei)

```bash
# .env erstellen
cd /var/www/teamportal
sudo cp docs/env.example .env

# Generiere Verschlüsselungsschlüssel
sudo -u www-data bash -c "source venv/bin/activate && python scripts/generate_encryption_keys.py"

# Generiere VAPID-Keys für Push-Benachrichtigungen
sudo -u www-data bash -c "source venv/bin/activate && python scripts/generate_vapid_keys.py"

# Bearbeite .env
sudo nano .env
```

`docs/env.example` ist bewusst minimal gehalten. Tragen Sie mindestens folgende Werte ein:

```env
SECRET_KEY=GeneriereSicherenSchlüsselMit32ZeichenOderMehr
FLASK_ENV=production
DATABASE_URI=mysql+pymysql://teamportal:IhrSicheresPasswort123!@localhost/teamportal
CREDENTIAL_ENCRYPTION_KEY=your-credential-encryption-key-here
MUSIC_ENCRYPTION_KEY=your-music-encryption-key-here
TOTP_ENCRYPTION_KEY=your-fernet-key-here
VAPID_PUBLIC_KEY=your-vapid-public-key-here
VAPID_PRIVATE_KEY=your-vapid-private-key-here
ONLYOFFICE_ENABLED=True
EXCALIDRAW_ENABLED=True
REDIS_ENABLED=True
REDIS_URL=redis://localhost:6379/0
```

**Wichtige Hinweise zur Konfiguration:**

- **SECRET_KEY:** Generieren Sie einen sicheren Schlüssel (z.B. mit `openssl rand -hex 32`)
- **CREDENTIAL_ENCRYPTION_KEY:** Kopieren Sie den Key aus der Ausgabe von `generate_encryption_keys.py`
- **MUSIC_ENCRYPTION_KEY:** Kopieren Sie den Key aus der Ausgabe von `generate_encryption_keys.py`
- **VAPID_PUBLIC_KEY:** Kopieren Sie den Public Key aus der Ausgabe von `generate_vapid_keys.py`
- **VAPID_PRIVATE_KEY:** Kopieren Sie den Private Key aus der Ausgabe von `generate_vapid_keys.py`
- **TOTP_ENCRYPTION_KEY:** Optional, aber empfohlen für stabile 2FA/TOTP-Verschlüsselung
- **ONLYOFFICE_ENABLED:** 
  - Setzen Sie auf `True`, wenn OnlyOffice installiert ist (Schritt 5)
  - Setzen Sie auf `False`, wenn OnlyOffice NICHT installiert ist
- **EXCALIDRAW_ENABLED:**
  - Setzen Sie auf `True`, wenn Excalidraw installiert ist (Schritt 6)
  - Setzen Sie auf `False`, wenn Excalidraw NICHT installiert ist
- **REDIS_ENABLED:** Setzen Sie auf `True`, wenn mehrere Gunicorn-Worker genutzt werden
- **REDIS_URL:** Standard ist `redis://localhost:6379/0`, nur bei abweichender Redis-Konfiguration ändern

**Wichtig zu den Encryption Keys:**
- Die Keys werden verwendet, um sensible Daten zu verschlüsseln (Passwörter im Credentials-Modul, OAuth-Tokens im Music-Modul)
- Wenn Sie die Keys ändern, können bereits verschlüsselte Daten nicht mehr entschlüsselt werden
- Bewahren Sie die Keys sicher auf und teilen Sie sie niemals öffentlich

**Weitere optionale `.env`-Variablen (nicht in `env.example`):**

- **OnlyOffice:** `ONLYOFFICE_DOCUMENT_SERVER_URL`, `ONLYOFFICE_SECRET_KEY`, `ONLYOFFICE_PUBLIC_URL`
- **Excalidraw:** `EXCALIDRAW_ROOM_URL` (Standard `/excalidraw-room`)
- **Redis:** `REDIS_URL` (Standard: `redis://localhost:6379/0`)
- **Portal-Fallbacks:** `APP_NAME`, `APP_LOGO` (optional, wenn nicht über Setup/System-Einstellungen gesetzt)
- **E-Mail (SMTP):** `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`, `MAIL_SENDER_NAME`
- **E-Mail-Speicherlimits:** `EMAIL_HTML_MAX_LENGTH`, `EMAIL_TEXT_MAX_LENGTH`, `EMAIL_HTML_STORAGE_TYPE`
- **IMAP:** `IMAP_SERVER`, `IMAP_PORT`, `IMAP_USE_SSL`
- **Uploads:** `UPLOAD_FOLDER` (Dateigrößenlimits werden in den Datei-Einstellungen verwaltet)
- **Media Downloader:** `MEDIA_DOWNLOADER_RETENTION_HOURS`, `MEDIA_DOWNLOADER_MAX_CONCURRENT`, `FFMPEG_PATH`
- **Dateikonverter:** `FILE_CONVERTER_RETENTION_HOURS`, `FILE_CONVERTER_MAX_CONCURRENT`, `LIBREOFFICE_PATH`
- **Session/Cookies (Produktion):** `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE`
  - `SESSION_COOKIE_SECURE=True` nur bei HTTPS (z. B. Let's Encrypt). Bei Zugriff über `http://` muss der Wert `False` sein, sonst speichert der Browser die Session nicht und Setup/Login scheitern nach der Account-Erstellung.
  - Der Ubuntu-Installer setzt das Flag automatisch passend zu `--ssl` / SSL-Prompt.

### Schritt 8: Berechtigungen setzen

```bash
# Upload-Verzeichnisse erstellen
sudo mkdir -p uploads/{files,chat,manuals,profile_pics,inventory/product_images,system}

# Berechtigungen setzen
sudo chown -R www-data:www-data /var/www/teamportal
sudo chmod -R 755 /var/www/teamportal
sudo chmod -R 775 /var/www/teamportal/uploads
```

### Schritt 9: Redis installieren (für Multi-Worker-Setups)

**⚠️ WICHTIG:** Redis ist **erforderlich**, wenn Sie mehrere Gunicorn-Worker verwenden möchten (z.B. `-w 4`). Ohne Redis funktionieren SocketIO-Events (Echtzeit-Updates im Musikmodul, Chat) nur mit einem Worker.

**Redis Installation:**

```bash
# Redis installieren
sudo apt-get update
sudo apt-get install -y redis-server

# Redis starten und aktivieren
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Redis-Status prüfen
sudo systemctl status redis-server
```

**Redis in .env konfigurieren:**

```bash
cd /var/www/teamportal
sudo nano .env
```

Fügen Sie folgende Zeilen hinzu oder aktualisieren Sie sie:

```env
# Redis für SocketIO Message Queue (erforderlich für Multi-Worker)
REDIS_ENABLED=True
REDIS_URL=redis://localhost:6379/0
```

**Hinweis:** Wenn Sie nur einen Worker verwenden (`-w 1`), können Sie Redis deaktiviert lassen (`REDIS_ENABLED=False`). Für Production mit mehreren Workern ist Redis jedoch dringend empfohlen.

### Schritt 10: Systemd-Service konfigurieren

```bash
sudo nano /etc/systemd/system/teamportal.service
```

**WICHTIG:** Für den ersten Start verwenden wir `--workers 1` (nur 1 Worker), damit die Datenbank automatisch initialisiert wird!

Inhalt für den ersten Start:
```ini
[Unit]
Description=Team Portal Gunicorn Application Server
After=network.target mysql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/teamportal
Environment="PATH=/var/www/teamportal/venv/bin"
Environment="FLASK_ENV=production"
ExecStart=/var/www/teamportal/venv/bin/gunicorn \
    --workers 1 \
    --bind 127.0.0.1:5000 \
    --timeout 600 \
    --access-logfile - \
    --error-logfile - \
    wsgi:app

Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
# Gunicorn ist bereits in requirements.txt enthalten.
# Optional nur bei Bedarf:
# cd /var/www/teamportal
# source venv/bin/activate
# pip install gunicorn

# Systemd-Service aktivieren und starten
sudo systemctl daemon-reload
sudo systemctl enable teamportal
sudo systemctl start teamportal
sudo systemctl status teamportal
```

**Wichtig:** Beim ersten Start wird die Datenbank **automatisch** initialisiert und alle Tabellen werden erstellt. Warten Sie etwa 1 Minute, dann prüfen Sie die Logs:

```bash
# Prüfen Sie die Logs, ob die Datenbank erfolgreich erstellt wurde
sudo journalctl -u teamportal -n 50 -f
```

**Nach dem ersten erfolgreichen Start** (wenn die Datenbank erstellt wurde) können Sie auf mehrere Worker umstellen:

**WICHTIG:** Wenn Sie mehrere Worker verwenden möchten, stellen Sie sicher, dass Redis installiert und konfiguriert ist (siehe Schritt 9)!

```bash
sudo nano /etc/systemd/system/teamportal.service
```

Ändern Sie die `--workers 1` Zeile zu `--workers 4` (oder mehr, siehe [WARTUNG.md – Performance](WARTUNG.md#performance-optimierung)):

```ini
[Unit]
Description=Team Portal Gunicorn Application Server
After=network.target mysql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/teamportal
Environment="PATH=/var/www/teamportal/venv/bin"
Environment="FLASK_ENV=production"
ExecStart=/var/www/teamportal/venv/bin/gunicorn \
    --workers 4 \
    --bind 127.0.0.1:5000 \
    --timeout 600 \
    --access-logfile - \
    --error-logfile - \
    wsgi:app

Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
# Systemd neu laden und Service neu starten
sudo systemctl daemon-reload
sudo systemctl restart teamportal
sudo systemctl status teamportal
```

**Hinweis zu Multi-Worker-Setups:**
- **Mit Redis:** SocketIO funktioniert korrekt mit mehreren Workern. Echtzeit-Updates (Musikmodul, Chat) funktionieren für alle Benutzer.
- **Ohne Redis:** SocketIO funktioniert nur mit einem Worker (`-w 1`). Für Development ausreichend, für Production mit mehreren Workern ist Redis erforderlich.

### Schritt 11: Nginx konfigurieren

```bash
sudo nano /etc/nginx/sites-available/teamportal
```

**WICHTIG für WebSocket-Support:** Bevor Sie die Site-Konfiguration erstellen, müssen Sie die Connection-Header-Map in der Haupt-Nginx-Konfiguration definieren:

```bash
sudo nano /etc/nginx/nginx.conf
```

Fügen Sie im `http`-Block (vor den `include`-Zeilen) folgendes hinzu:

```nginx
http {
    # ... bestehende Konfiguration ...
    
    # WebSocket Connection Header Map (MUSS im http-Block sein!)
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }
    
    # ... rest der Konfiguration ...
    include /etc/nginx/sites-enabled/*;
}
```

Dann erstellen Sie die Site-Konfiguration:

```bash
sudo nano /etc/nginx/sites-available/teamportal
```

**Vollständige Nginx-Konfiguration mit optionalen Services:**

```nginx
# Upstream-Block für Session-Stickiness (MUSS VOR server-Block sein!)
upstream teamportal_backend {
    ip_hash;  # WICHTIG: Session-Stickiness für Socket.IO Multi-Worker
    server 127.0.0.1:5000;
}

server {
    listen 80;
    server_name ihre-domain.de www.ihre-domain.de;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # File upload limit
    client_max_body_size 100M;

    # OnlyOffice Cache (MUSS VOR /onlyoffice kommen!)
    # OnlyOffice benötigt diesen Pfad für interne Cache-Dateien
    # Entfernen Sie diesen Block, wenn OnlyOffice NICHT installiert ist
    location /cache {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
        send_timeout 600;
        
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # OnlyOffice Document Server (OPTIONAL - nur wenn installiert)
    # Entfernen Sie diesen Block, wenn OnlyOffice NICHT installiert ist
    location /onlyoffice {
        # WICHTIG: MIT trailing slash bei proxy_pass, damit der /onlyoffice Präfix entfernt wird
        # OnlyOffice erwartet /web-apps/... nicht /onlyoffice/web-apps/...
        proxy_pass http://127.0.0.1:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # OnlyOffice spezifische Header
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # WICHTIG: Content-Type Header vom Backend übernehmen
        # Standardmäßig sollte Nginx den Content-Type vom Backend übernehmen,
        # aber wir stellen sicher, dass er nicht überschrieben wird
        
        # CORS headers für OnlyOffice (wichtig für API-Zugriff)
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
        add_header Access-Control-Allow-Credentials true always;
        
        # Handle preflight requests
        if ($request_method = 'OPTIONS') {
            add_header Access-Control-Allow-Origin * always;
            add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
            add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
            add_header Access-Control-Allow-Credentials true always;
            add_header Content-Length 0;
            add_header Content-Type text/plain;
            return 204;
        }
        
        # Timeouts für große Dokumente
        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
        send_timeout 600;
        
        # Disable buffering für OnlyOffice (wichtig für Streaming)
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # Excalidraw Room Server (OPTIONAL - nur wenn installiert)
    # Prefix wird entfernt, damit Socket.IO unter /socket.io ankommt
    location /excalidraw-room/ {
        proxy_pass http://127.0.0.1:8082/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
        send_timeout 600;
        proxy_buffering off;
    }

    # Statische Dateien (MUSS VOR / kommen!)
    # Hinweis: "immutable" ist nur sicher, weil Templates Static-URLs mit ?v=<BUILD> ausliefern
    # (Cache-Busting). Ohne Versions-Query würden Browser CSS/JS nach Deploys nicht aktualisieren.
    location /static {
        alias /var/www/teamportal/app/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Service Worker: niemals long-cachen (sonst bleiben PWAs auf altem SW hängen)
    location = /sw.js {
        proxy_pass http://teamportal_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
        expires off;
    }

    # Uploads (MUSS VOR / kommen!)
    location /uploads {
        alias /var/www/teamportal/uploads;
        expires 7d;
    }

    # Socket.IO spezifische Konfiguration (MUSS VOR / kommen!)
    # Socket.IO verwendet /socket.io/ für Polling und WebSocket-Verbindungen
    # WICHTIG: Session-Stickiness für Multi-Worker (ip_hash im upstream-Block)
    location /socket.io/ {
        proxy_pass http://teamportal_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support - WICHTIG: Connection Header dynamisch setzen
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        # Connection Header dynamisch setzen für WebSocket-Upgrades (wss://)
        # Verwendet die Map aus nginx.conf: $connection_upgrade
        proxy_set_header Connection $connection_upgrade;
        
        # WICHTIG: Buffering für Socket.IO deaktivieren (verhindert 400-Fehler)
        proxy_buffering off;
        proxy_request_buffering off;
        
        # Längere Timeouts für Socket.IO Polling und WebSocket
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        send_timeout 60s;
        
        # CORS für Socket.IO (falls nötig)
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Content-Type" always;
        add_header Access-Control-Allow-Credentials true always;
    }

    # WebDAV (Windows Explorer / Netzlaufwerk) — MUSS VOR / kommen!
    # Details: docs/WEBDAV.md
    location /webdav {
        proxy_pass http://teamportal_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization $http_authorization;
        proxy_pass_header Authorization;
        proxy_http_version 1.1;
        proxy_request_buffering off;
        proxy_buffering off;
        client_max_body_size 100M;
        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
        send_timeout 600;
    }

    # Hauptanwendung (MUSS ZULETZT kommen!)
    location / {
        proxy_pass http://teamportal_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

**Wichtig:** 
- Entfernen Sie die OnlyOffice-Location-Blöcke (`/onlyoffice`), wenn OnlyOffice NICHT installiert ist
- Entfernen Sie den Excalidraw-Location-Block (`/excalidraw-room/`), wenn der Room-Server NICHT installiert ist
- Ersetzen Sie `ihre-domain.de` mit Ihrer tatsächlichen Domain oder IP-Adresse

```bash
# Site aktivieren
sudo ln -s /etc/nginx/sites-available/teamportal /etc/nginx/sites-enabled/

# Standard-Site deaktivieren (falls vorhanden)
sudo rm -f /etc/nginx/sites-enabled/default

# Nginx testen
sudo nginx -t

# Nginx starten/neu starten
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### Schritt 12: SSL mit Let's Encrypt

```bash
# SSL-Zertifikat erstellen
sudo certbot --nginx -d ihre-domain.de -d www.ihre-domain.de

# Automatische Erneuerung testen
sudo certbot renew --dry-run
```

**Hinweis:** Diese Phase ist optional, aber dringend empfohlen für Produktionsumgebungen.

### Schritt 13: Firewall konfigurieren

```bash
# Firewall-Regeln setzen
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

### Schritt 14: Ersten Admin erstellen

**Wichtig:** Der erste Admin wird **per Browser** eingerichtet, nicht über die Shell!

1. Öffnen Sie `https://ihre-domain.de` (oder `http://ihre-domain.de` wenn kein SSL) im Browser
2. Die Anwendung zeigt automatisch einen **Setup-Assistenten** an
3. Folgen Sie den Anweisungen im Browser, um den ersten Admin-Benutzer zu erstellen
4. Geben Sie die gewünschten Daten ein (E-Mail, Name, Passwort, etc.)
5. Nach der Registrierung wird der erste Benutzer automatisch als Admin aktiviert

**Hinweis:** Falls der Setup-Assistent nicht automatisch erscheint, können Sie direkt zur Registrierungsseite navigieren und sich dort registrieren. Der erste registrierte Benutzer wird automatisch als Admin eingerichtet.

## Zusammenfassung der Installation

### Pflichtschritte (immer erforderlich)

1. System vorbereiten (Pakete installieren)
2. MariaDB einrichten (nur leere Datenbank erstellen - Tabellen werden automatisch erstellt!)
3. Anwendung von GitHub installieren
4. Konfiguration (.env-Datei)
5. Berechtigungen setzen
6. Redis installieren (erforderlich für Multi-Worker-Setups)
7. Systemd-Service konfigurieren und starten (Datenbank wird beim ersten Start automatisch erstellt!)
8. Nginx konfigurieren
9. SSL mit Let's Encrypt (empfohlen)
10. Firewall konfigurieren
11. Ersten Admin erstellen

### Optionale Schritte (nur bei Bedarf)

- **Docker installieren:** Nur erforderlich für OnlyOffice oder Excalidraw
- **OnlyOffice installieren:** Optional, für Dokumentenbearbeitung
- **Excalidraw installieren:** Optional, für Canvas-Modul
- **Media Downloader installieren:** Optional, FFmpeg installieren und Modul in Admin aktivieren
- **Dateikonverter installieren:** Optional, LibreOffice für Dokumente; Audio/Bilder/PDF ohne LibreOffice nutzbar

### Wichtige Hinweise

1. **.env-Konfiguration:** `ONLYOFFICE_ENABLED=False` / `EXCALIDRAW_ENABLED=False` wenn nicht installiert
2. **Nginx-Konfiguration:** OnlyOffice- und Excalidraw-Location-Blöcke entfernen wenn nicht genutzt
3. **Datenbank:** Nur leere DB anlegen; Tabellen beim ersten Gunicorn-Start; `--workers 1` für ersten Start
4. **Redis:** Erforderlich für Multi-Worker mit SocketIO

## Sicherheits-Checkliste

- [ ] Starken `SECRET_KEY` gesetzt
- [ ] Datenbank-Passwort ist sicher
- [ ] SSL/HTTPS ist aktiviert
- [ ] Firewall ist konfiguriert
- [ ] Regelmäßige Backups sind eingerichtet ([WARTUNG.md](WARTUNG.md))
- [ ] Standard-Ports sind geschützt
- [ ] Nur notwendige Services laufen
- [ ] System-Updates sind aktuell
- [ ] OnlyOffice JWT ist aktiviert (falls OnlyOffice installiert)
- [ ] 2FA (TOTP) für Admin-Accounts empfohlen
- [ ] Redis aktiv, wenn Gunicorn mit mehreren Workern läuft
- [ ] `TOTP_ENCRYPTION_KEY` / Encryption-Keys gesetzt ([env.example](env.example))
- [ ] `.env`-Datei hat korrekte Berechtigungen (nicht öffentlich lesbar)
- [ ] Docker-Container laufen mit `--restart=always` (falls installiert)

## Bewertungsmodul

Das Bewertungsmodul (`module_assessment`) unterstützt mehrere **Bewertungslisten** parallel (z. B. Stände nach Typ „Essen“ / „Aktivität“ oder eine separate Liste für Maskottchen).

### Konzepte

- **Stand-Typen:** Jeder Stand hat genau einen Typ (Essen, Aktivität, …), verwaltbar unter *Bewertung → Stand-Typen*.
- **Bewertungslisten:** Eigene Kriterien und Jury-Rangliste pro Liste. Modus *Stände* filtert nach Stand-Typen; Modus *Eigene Ziele* für frei definierbare Einträge (z. B. Maskottchen).
- **Portal-Zugriff:** Benutzer mit freigeschaltetem Modul `module_assessment` haben im Bewertungsmodul Administrator-Rechte. Zusätzliche Assessment-Accounts (Benutzername-Login) eignen sich für Jury-Rollen ohne Portal-Konto.
- **Migration:** Beim App-Start werden bestehende Daten einer Default-Liste „Hauptbewertung“ zugeordnet. Vor Updates auf Produktivsystemen Backup anlegen.

### Darstellung und Branding

- Das Bewertungsmodul nutzt **dieselbe Oberfläche wie das Portal** (Sidebar, Karten, Akzentfarbe). Logo und Portalname kommen aus den globalen Portal-Einstellungen; ein separates Modul-Logo gibt es nicht mehr.
- **Portal-Benutzer** (`module_assessment`): Dark Mode, OLED und Akzentfarbe unter *Einstellungen → Darstellung* im Profil – gelten auch im Bewertungsmodul.
- **Jury-Accounts** (reiner Assessment-Login, isolierte Sidebar): Dark Mode und OLED unter *Bewertung → Einstellungen → Darstellung*; Akzentfarbe folgt dem Portal-Standard.
- Der frühere Theme-Schalter in der Bewertungs-Sidebar und die API `/assessment/api/theme` entfallen.

### Excel-Import

- Beispiel-Dateien liegen unter `app/static/assessment/` (`beispiel_staende.xlsx`, `beispiel_kriterien.xlsx`, `beispiel_benutzer.xlsx`, `beispiel_bewertungsziele.xlsx`) und können in der Verwaltung heruntergeladen werden.
- **Stände / Benutzer:** global unter *Stände* bzw. *Benutzer*.
- **Kriterien:** pro Bewertungsliste unter *Kriterien* oder direkt auf der Seite *Bewertungslisten* (Listen-Auswahl).
- **Bewertungsziele:** nur für Custom-Listen, auf *Bewertungslisten* oder unter *Bewertungsziele* der jeweiligen Liste.
- Abhängigkeit: `openpyxl` (wie für Excel-Erstellung im Dateien-Modul).

Der frühere **Lageplan-Editor** und die **Besucherbewertung / Besucherrangliste** wurden entfernt. Die Rangliste basiert nur noch auf Jury-Bewertungen.

## Weitere Informationen

- **Excalidraw Dokumentation:** https://docs.excalidraw.com
- **OnlyOffice Dokumentation:** https://api.onlyoffice.com/
- **Docker Hub Excalidraw Room:** https://hub.docker.com/r/excalidraw/excalidraw-room
- **Docker Hub OnlyOffice:** https://hub.docker.com/r/onlyoffice/documentserver

## Support

Bei Problemen:

1. [ERROR_HANDLING.md](ERROR_HANDLING.md) durchgehen
2. [WARTUNG.md](WARTUNG.md) für Logs und Updates
3. GitHub Issues durchsuchen oder neues Issue erstellen

---

<p align="center">
  <img src="../app/static/img/logo.png" alt="" width="40"><br>
  <sub>Prismateams 3.0.1</sub>
</p>
