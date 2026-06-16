# Team Portal - Installationsanleitung

**Dokumentation:** [INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md) · [WARTUNG.md](WARTUNG.md) · [ERROR_HANDLING.md](ERROR_HANDLING.md)

## Hinweis zu VAPID- und Encryption-Keys

Zurzeit kann eine nachträgliche Eintragung der VAPID- und Secret Keys für Benachrichtigungen, Passwörter und Music erforderlich sein:

```bash
# Encryption Keys (aus generate_encryption_keys.py kopieren)
CREDENTIAL_ENCRYPTION_KEY=your-credential-encryption-key-here
MUSIC_ENCRYPTION_KEY=your-music-encryption-key-here

VAPID_PUBLIC_KEY=your-vapid-public-key-here
VAPID_PRIVATE_KEY=your-vapid-private-key-here
```

## Empfohlene Installation (Ubuntu)

Für Ubuntu Server 24.04 existiert ein automatisches Installationsskript: `scripts/install_ubuntu.sh`

```bash
sudo bash scripts/install_ubuntu.sh
```

Alle Details, CLI-Optionen und interaktive Abfragen: **[INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md)**

---
## Produktionsinstallation (Ubuntu Server) - Manuelle Methode

Diese Anleitung führt Sie Schritt für Schritt durch die vollständige Installation von Prismateams auf einem Ubuntu Server, inklusive optionaler Integrationen für Excalidraw und OnlyOffice.

**⚠️ Wichtiger Hinweis zu optionalen Features:**
- **OnlyOffice** und **Excalidraw** sind **OPTIONAL** und nicht zwingend erforderlich
- **Media Downloader** ist **OPTIONAL** (benötigt FFmpeg, kein Docker)
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

### Schritt 5: Optionale Installation - OnlyOffice Document Server

**⚠️ OPTIONAL:** Dieser Schritt ist nur erforderlich, wenn Sie OnlyOffice für die Dokumentenbearbeitung verwenden möchten. Wenn nicht, setzen Sie `ONLYOFFICE_ENABLED=False` in der `.env`-Datei.

```bash
# OnlyOffice Document Server Container starten (Port 8080)
sudo docker run -i -t -d -p 8080:80 --restart=always \
    --name onlyoffice-documentserver \
    -v /var/lib/onlyoffice/DocumentServer/data:/var/www/onlyoffice/Data \
    -v /var/lib/onlyoffice/DocumentServer/logs:/var/log/onlyoffice \
    -e JWT_SECRET=dein-jwt-secret-key-hier \
    onlyoffice/documentserver

# Prüfen ob OnlyOffice läuft
sudo docker ps | grep onlyoffice
curl http://localhost:8080/welcome/
```

**Wichtig:** Notieren Sie sich den `JWT_SECRET`-Wert! Sie benötigen ihn später für die Konfiguration in der `.env`-Datei.

**Hinweis:** Wenn Sie OnlyOffice ohne JWT-Authentifizierung betreiben möchten, können Sie die `-e JWT_SECRET=...` Zeile weglassen. In diesem Fall lassen Sie `ONLYOFFICE_SECRET_KEY` in der `.env` leer.

### Schritt 6: Optionale Installation - Excalidraw

**⚠️ OPTIONAL:** Dieser Schritt ist nur erforderlich, wenn Sie Excalidraw für das Canvas-Modul verwenden möchten. Wenn nicht, setzen Sie `EXCALIDRAW_ENABLED=False` in der `.env`-Datei.

#### 6.1 Excalidraw Client installieren

```bash
# Excalidraw Client Container starten (Port 8081)
sudo docker run -i -t -d -p 8081:80 --restart=always \
    --name excalidraw \
    excalidraw/excalidraw:latest

# Prüfen ob Excalidraw läuft
sudo docker ps | grep excalidraw
curl http://localhost:8081/
```

#### 6.2 Excalidraw-Room Server installieren

Der Excalidraw-Room Server ist für Echtzeit-Kollaboration notwendig.

```bash
# Excalidraw-Room Container starten (Port 8082)
sudo docker run -i -t -d -p 8082:80 --restart=always \
    --name excalidraw-room \
    -e PORT=80 \
    excalidraw/excalidraw-room:latest

# Prüfen ob Excalidraw-Room läuft
sudo docker ps | grep excalidraw-room
curl http://localhost:8082/
```

### Schritt 6b: Optionale Installation - Media Downloader

**⚠️ OPTIONAL:** Dieser Schritt ist nur erforderlich, wenn Sie YouTube-/YouTube-Music-Downloads im Portal nutzen möchten.

```bash
# FFmpeg installieren (von yt-dlp für Konvertierung benötigt)
sudo apt install -y ffmpeg

# Installation prüfen
ffmpeg -version
```

**Hinweise:**
- Kein Docker oder Nginx-Proxy erforderlich
- Python-Paket `yt-dlp` wird über `requirements.txt` im Virtual Environment installiert
- **Aktivierung im Portal:** Einstellungen → Administration → Module → **Media Downloader**
- Heruntergeladene Dateien werden standardmäßig nach **1 Stunde** automatisch gelöscht (`MEDIA_DOWNLOADER_RETENTION_HOURS` in `.env`, optional)
- **Rechtlicher Hinweis:** Nutzer sind für die Einhaltung von Urheberrecht und Plattform-Nutzungsbedingungen verantwortlich

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
- **Excalidraw:** `EXCALIDRAW_URL`, `EXCALIDRAW_ROOM_URL`, `EXCALIDRAW_PUBLIC_URL`
- **Redis:** `REDIS_URL` (Standard: `redis://localhost:6379/0`)
- **Portal-Fallbacks:** `APP_NAME`, `APP_LOGO` (optional, wenn nicht über Setup/System-Einstellungen gesetzt)
- **E-Mail (SMTP):** `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`, `MAIL_SENDER_NAME`
- **E-Mail-Speicherlimits:** `EMAIL_HTML_MAX_LENGTH`, `EMAIL_TEXT_MAX_LENGTH`, `EMAIL_HTML_STORAGE_TYPE`
- **IMAP:** `IMAP_SERVER`, `IMAP_PORT`, `IMAP_USE_SSL`
- **Uploads/Limits:** `UPLOAD_FOLDER`, `MAX_CONTENT_LENGTH`
- **Media Downloader:** `MEDIA_DOWNLOADER_RETENTION_HOURS`, `MEDIA_DOWNLOADER_MAX_CONCURRENT`, `FFMPEG_PATH`
- **Session/Cookies (Produktion):** `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE`

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
    # WICHTIG: Muss VOR /excalidraw kommen!
    # Entfernen Sie diesen Block, wenn Excalidraw NICHT installiert ist
    location /excalidraw-room {
        proxy_pass http://127.0.0.1:8082;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support (wichtig für Echtzeit-Kollaboration)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts für WebSocket-Verbindungen
        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
        send_timeout 600;
    }

    # Excalidraw Client (OPTIONAL - nur wenn installiert)
    # Entfernen Sie diesen Block, wenn Excalidraw NICHT installiert ist
    location /excalidraw {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts
        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
        send_timeout 600;
    }

    # Statische Dateien (MUSS VOR / kommen!)
    location /static {
        alias /var/www/teamportal/app/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
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
- Entfernen Sie die Excalidraw-Location-Blöcke (`/excalidraw` und `/excalidraw-room`), wenn Excalidraw NICHT installiert ist
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
- **Docker Hub Excalidraw:** https://hub.docker.com/r/excalidraw/excalidraw
- **Docker Hub OnlyOffice:** https://hub.docker.com/r/onlyoffice/documentserver

## Support

Bei Problemen:

1. [ERROR_HANDLING.md](ERROR_HANDLING.md) durchgehen
2. [WARTUNG.md](WARTUNG.md) für Logs und Updates
3. GitHub Issues durchsuchen oder neues Issue erstellen
