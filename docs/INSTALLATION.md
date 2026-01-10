# Team Portal - Installationsanleitung

## Schnellstart (Entwicklung)

### 1. Voraussetzungen prüfen
```bash
python --version  # Python 3.8+ erforderlich
```

### 2. Projekt einrichten
```bash
# Repository klonen
git clone https://github.com/yourusername/teamportal.git
cd teamportal

# Virtual Environment erstellen
python -m venv venv

# Virtual Environment aktivieren
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Dependencies installieren
pip install -r requirements.txt
```

### 3. Umgebungsvariablen konfigurieren
```bash
# Kopiere die Beispiel-Datei
# Windows:
copy env.example .env
# Linux/Mac:
cp env.example .env

# Generiere Verschlüsselungsschlüssel
# Windows:
python scripts/generate_encryption_keys.py
# Linux/Mac:
python3 scripts/generate_encryption_keys.py

# Bearbeite .env und setze mindestens:
# - SECRET_KEY (generiere einen sicheren Schlüssel, z.B. mit: openssl rand -hex 32)
# - DATABASE_URI (für SQLite: sqlite:///teamportal.db)
# - CREDENTIAL_ENCRYPTION_KEY (aus dem Script kopieren)
# - MUSIC_ENCRYPTION_KEY (aus dem Script kopieren)
```

### 4. Datenbank-Setup (Entwicklung)

**Wichtig:** Die Datenbank wird **automatisch** beim ersten Start der Anwendung erstellt. Sie müssen **KEINE** Tabellen manuell anlegen!

#### Für SQLite (Standard):
Die Datenbank wird automatisch erstellt. Keine weiteren Schritte erforderlich.

#### Für MySQL/MariaDB:
Erstellen Sie nur die **leere Datenbank** (ohne Tabellen):

```bash
# Datenbank erstellen
sudo mysql -u root -p
```

In der MySQL-Konsole:
```sql
CREATE DATABASE teamportal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
EXIT;
```

**Datenbankbenutzer erstellen (optional, aber empfohlen):**
```sql
CREATE USER 'teamportal'@'localhost' IDENTIFIED BY 'IhrSicheresPasswort123!';
GRANT ALL PRIVILEGES ON teamportal.* TO 'teamportal'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

#### Automatische Tabellenerstellung

Die Anwendung erstellt **alle Tabellen automatisch** beim ersten Start. Führen Sie einfach `app.py` einmal aus:

```bash
# Anwendung starten
python app.py
```

**Warten Sie etwa 1 Minute**, damit die Datenbank vollständig initialisiert wird. Dann können Sie die Anwendung mit `Ctrl+C` stoppen.

Die Datenbank ist jetzt vollständig eingerichtet und alle Tabellen wurden automatisch erstellt. Sie müssen keine SQL-Befehle manuell ausführen!

### 5. Anwendung starten
```bash
python app.py
```

Die Anwendung läuft nun auf `http://localhost:5000`

### 6. Ersten Admin erstellen

**Wichtig:** Der erste Admin wird **per Browser** eingerichtet, nicht über die Datenbank!

1. Öffne `http://localhost:5000` im Browser
2. Die Anwendung zeigt automatisch einen **Setup-Assistenten** an
3. Folgen Sie den Anweisungen im Browser, um den ersten Admin-Benutzer zu erstellen
4. Geben Sie die gewünschten Daten ein (E-Mail, Name, Passwort, etc.)
5. Nach der Registrierung wird der erste Benutzer automatisch als Admin aktiviert

**Hinweis:** Falls der Setup-Assistent nicht automatisch erscheint, können Sie direkt zur Registrierungsseite navigieren und sich dort registrieren. Der erste registrierte Benutzer wird automatisch als Admin eingerichtet.

## Produktionsinstallation (Ubuntu Server)

Diese Anleitung führt Sie Schritt für Schritt durch die vollständige Installation von Prismateams auf einem Ubuntu Server, inklusive optionaler Integrationen für Excalidraw und OnlyOffice.

**⚠️ Wichtiger Hinweis zu optionalen Features:**
- **OnlyOffice** und **Excalidraw** sind **OPTIONAL** und nicht zwingend erforderlich
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
# Docker installieren
sudo apt install -y docker.io docker-compose

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

### Schritt 7: Konfiguration (.env-Datei)

```bash
# .env erstellen
cd /var/www/teamportal
sudo cp docs/env.example .env

# Generiere Verschlüsselungsschlüssel
sudo -u www-data bash -c "source venv/bin/activate && python scripts/generate_encryption_keys.py"

# Bearbeite .env
sudo nano .env
```

**Wichtige Konfiguration in `.env`:**

```env
# Flask Configuration
SECRET_KEY=GeneriereSicherenSchlüsselMit32ZeichenOderMehr
FLASK_ENV=production

# Database Configuration
DATABASE_URI=mysql+pymysql://teamportal:IhrSicheresPasswort123!@localhost/teamportal

# Encryption Keys (aus generate_encryption_keys.py kopieren)
CREDENTIAL_ENCRYPTION_KEY=your-credential-encryption-key-here
MUSIC_ENCRYPTION_KEY=your-music-encryption-key-here

# ONLYOFFICE Configuration (OPTIONAL)
# Setzen Sie ONLYOFFICE_ENABLED=False, wenn OnlyOffice NICHT installiert ist
ONLYOFFICE_ENABLED=True
ONLYOFFICE_DOCUMENT_SERVER_URL=/onlyoffice
ONLYOFFICE_SECRET_KEY=dein-jwt-secret-key-von-onlyoffice
# Wenn OnlyOffice ohne JWT läuft, lassen Sie ONLYOFFICE_SECRET_KEY leer

# Excalidraw Configuration (OPTIONAL)
# Setzen Sie EXCALIDRAW_ENABLED=False, wenn Excalidraw NICHT installiert ist
EXCALIDRAW_ENABLED=True
EXCALIDRAW_URL=/excalidraw
EXCALIDRAW_ROOM_URL=/excalidraw-room

# Email Configuration (falls benötigt)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=ihr-email@gmail.com
MAIL_PASSWORD=ihr-app-passwort

# IMAP Configuration (falls benötigt)
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
IMAP_USE_SSL=True

# Production Settings
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax
```

**Wichtige Hinweise zur Konfiguration:**

- **SECRET_KEY:** Generieren Sie einen sicheren Schlüssel (z.B. mit `openssl rand -hex 32`)
- **CREDENTIAL_ENCRYPTION_KEY:** Kopieren Sie den Key aus der Ausgabe von `generate_encryption_keys.py`
- **MUSIC_ENCRYPTION_KEY:** Kopieren Sie den Key aus der Ausgabe von `generate_encryption_keys.py`
- **ONLYOFFICE_ENABLED:** 
  - Setzen Sie auf `True`, wenn OnlyOffice installiert ist (Schritt 5)
  - Setzen Sie auf `False`, wenn OnlyOffice NICHT installiert ist
- **EXCALIDRAW_ENABLED:**
  - Setzen Sie auf `True`, wenn Excalidraw installiert ist (Schritt 6)
  - Setzen Sie auf `False`, wenn Excalidraw NICHT installiert ist
- **ONLYOFFICE_SECRET_KEY:** Muss mit dem JWT_SECRET übereinstimmen, den Sie in Schritt 5 gesetzt haben (oder leer lassen, wenn ohne JWT)

**Wichtig zu den Encryption Keys:**
- Die Keys werden verwendet, um sensible Daten zu verschlüsseln (Passwörter im Credentials-Modul, OAuth-Tokens im Music-Modul)
- Wenn Sie die Keys ändern, können bereits verschlüsselte Daten nicht mehr entschlüsselt werden
- Bewahren Sie die Keys sicher auf und teilen Sie sie niemals öffentlich

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
# Gunicorn installieren (falls noch nicht installiert)
cd /var/www/teamportal
source venv/bin/activate
pip install gunicorn

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

Ändern Sie die `--workers 1` Zeile zu `--workers 4` (oder mehr, siehe Performance-Optimierung):

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
    location /socket.io/ {
        proxy_pass http://127.0.0.1:5000;
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
        proxy_pass http://127.0.0.1:5000;
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

### Schritt 14: Datenbank-Migrationen ausführen (falls erforderlich)

**Wichtig:** Die Datenbank und alle Tabellen werden **automatisch** beim ersten Start der Anwendung (Schritt 10) angelegt. Sie müssen **KEINE** Tabellen manuell erstellen!

Falls Sie von einer älteren Version aktualisieren, müssen Sie nach dem ersten Start die entsprechende Migrationsdatei ausführen:

```bash
cd /var/www/teamportal
# Beispiel für Migration zu Version 2.2.0:
sudo -u www-data bash -c "source venv/bin/activate && python migrations/migrate_to_2.2.0.py"
```

**Hinweis:** Prüfen Sie die verfügbaren Migrationsdateien im `migrations/` Verzeichnis und führen Sie die entsprechende Migration für Ihre Zielversion aus (z.B. `migrate_to_2.2.0.py`).

### Schritt 15: Ersten Admin erstellen

**Wichtig:** Der erste Admin wird **per Browser** eingerichtet, nicht über die Shell!

1. Öffnen Sie `https://ihre-domain.de` (oder `http://ihre-domain.de` wenn kein SSL) im Browser
2. Die Anwendung zeigt automatisch einen **Setup-Assistenten** an
3. Folgen Sie den Anweisungen im Browser, um den ersten Admin-Benutzer zu erstellen
4. Geben Sie die gewünschten Daten ein (E-Mail, Name, Passwort, etc.)
5. Nach der Registrierung wird der erste Benutzer automatisch als Admin aktiviert

**Hinweis:** Falls der Setup-Assistent nicht automatisch erscheint, können Sie direkt zur Registrierungsseite navigieren und sich dort registrieren. Der erste registrierte Benutzer wird automatisch als Admin eingerichtet.

### Schritt 16: Datenbank-Initialisierung prüfen

**Wichtig:** Die Datenbank wurde beim ersten Start in Schritt 10 automatisch erstellt. Prüfen Sie die Logs, um sicherzustellen, dass alles erfolgreich war:

```bash
# Prüfen Sie die Logs auf Erfolg
sudo journalctl -u teamportal -n 100 | grep -i "database\|table\|create"

# Oder prüfen Sie direkt in der Datenbank
mysql -u teamportal -p teamportal -e "SHOW TABLES;"
```

Falls die Datenbank nicht automatisch erstellt wurde, können Sie die Anwendung manuell einmal starten:

```bash
cd /var/www/teamportal
sudo -u www-data bash -c "source venv/bin/activate && python app.py"
```

**Warten Sie etwa 1 Minute**, damit die Datenbank vollständig initialisiert wird, dann stoppen Sie die Anwendung mit `Ctrl+C`. Die Datenbank ist jetzt vollständig eingerichtet.

### Schritt 17: Verifizierung und Tests

#### 16.1 Container-Status prüfen (falls Docker-Services installiert)

```bash
# OnlyOffice Container (falls installiert)
sudo docker ps | grep onlyoffice

# Excalidraw Container (falls installiert)
sudo docker ps | grep excalidraw
```

#### 16.2 Services testen

```bash
# OnlyOffice testen (falls installiert)
curl http://localhost:8080/welcome/

# Excalidraw testen (falls installiert)
curl http://localhost:8081/
curl http://localhost:8082/

# Hauptanwendung testen
curl http://localhost:5000/
```

#### 16.3 In Browser testen

1. Öffnen Sie `https://ihre-domain.de` (oder `http://ihre-domain.de` wenn kein SSL) im Browser
2. Melden Sie sich mit dem erstellten Admin-Account an
3. Testen Sie die optionalen Features:
   - **OnlyOffice:** Laden Sie eine .docx-Datei hoch und öffnen Sie sie
   - **Excalidraw:** Gehen Sie zu Canvas > Neuer Canvas und erstellen Sie einen Canvas

## Wartung

### Logs überprüfen
```bash
# Team Portal Service Logs (Systemd)
sudo journalctl -u teamportal -f
sudo journalctl -u teamportal -n 100

# Nginx Logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Redis Logs
sudo journalctl -u redis-server -f

# OnlyOffice Logs (falls installiert)
sudo docker logs -f onlyoffice-documentserver

# Excalidraw Logs (falls installiert)
sudo docker logs -f excalidraw
sudo docker logs -f excalidraw-room
```

### Anwendung neu starten
```bash
sudo systemctl restart teamportal
sudo systemctl status teamportal
```

### Docker-Container neu starten (falls installiert)
```bash
# OnlyOffice neu starten (falls installiert)
sudo docker restart onlyoffice-documentserver

# Excalidraw neu starten (falls installiert)
sudo docker restart excalidraw
sudo docker restart excalidraw-room
```

### Updates einspielen

**⚠️ WICHTIG:** Erstellen Sie vor jedem Update ein Backup der Datenbank und des Upload-Verzeichnisses! (siehe Backup erstellen)

**Option 1: Force Update (empfohlen, überschreibt lokale Änderungen)**

Diese Variante ist die **empfohlene Update-Methode**, da alle Daten in der Datenbank gespeichert sind und lokale Code-Änderungen überschrieben werden können. Lokale Änderungen werden komplett verworfen.

```bash
cd /var/www/teamportal

# Aktuelle Änderungen vom Remote-Repository abrufen
sudo -u www-data git fetch origin

# Lokale Änderungen verwerfen und auf den neuesten Stand bringen
# Ersetzen Sie "main" durch "master", falls Sie den master-Branch verwenden
sudo -u www-data git reset --hard origin/main

# Dependencies aktualisieren
sudo ./venv/bin/pip install -r requirements.txt

# Anwendung neu starten
sudo systemctl restart teamportal
```

**Hinweis:** Wenn Sie den `master`-Branch statt `main` verwenden, ersetzen Sie `origin/main` durch `origin/master` im `git reset`-Befehl.

**Option 2: Mit lokalen Änderungen (git stash)**

Diese Variante behält lokale Änderungen und versucht sie nach dem Update wieder anzuwenden. Verwenden Sie diese Variante nur, wenn Sie lokale Code-Änderungen beibehalten möchten.

```bash
cd /var/www/teamportal

# Lokale Änderungen temporär speichern
sudo -u www-data git stash

# Updates pullen
sudo -u www-data git pull

# Gespeicherte Änderungen wieder anwenden (falls nötig)
sudo -u www-data git stash pop

# Dependencies aktualisieren
sudo ./venv/bin/pip install -r requirements.txt

# Anwendung neu starten
sudo systemctl restart teamportal
```

**Option 3: Ohne lokale Änderungen (einfacher git pull)**

Diese Variante funktioniert nur, wenn keine lokalen Änderungen vorhanden sind.

```bash
cd /var/www/teamportal

# Git Pull als www-data ausführen
sudo -u www-data git pull

# Dependencies aktualisieren
sudo ./venv/bin/pip install -r requirements.txt

# Anwendung neu starten
sudo systemctl restart teamportal
```

### Docker-Container aktualisieren (falls installiert)

```bash
# OnlyOffice aktualisieren (falls installiert)
sudo docker stop onlyoffice-documentserver
sudo docker rm onlyoffice-documentserver
sudo docker pull onlyoffice/documentserver:latest
sudo docker run -i -t -d -p 8080:80 --restart=always \
    --name onlyoffice-documentserver \
    -v /var/lib/onlyoffice/DocumentServer/data:/var/www/onlyoffice/Data \
    -v /var/lib/onlyoffice/DocumentServer/logs:/var/log/onlyoffice \
    -e JWT_SECRET=dein-jwt-secret-key-hier \
    onlyoffice/documentserver

# Excalidraw aktualisieren (falls installiert)
sudo docker stop excalidraw excalidraw-room
sudo docker rm excalidraw excalidraw-room
sudo docker pull excalidraw/excalidraw:latest
sudo docker pull excalidraw/excalidraw-room:latest
sudo docker run -i -t -d -p 8081:80 --restart=always \
    --name excalidraw \
    excalidraw/excalidraw:latest
sudo docker run -i -t -d -p 8082:80 --restart=always \
    --name excalidraw-room \
    -e PORT=80 \
    excalidraw/excalidraw-room:latest
```

### Backup erstellen
```bash
# Datenbank-Backup
sudo mysqldump -u teamportal -p teamportal > backup_$(date +%Y%m%d).sql

# Upload-Verzeichnis sichern
sudo tar -czf uploads_backup_$(date +%Y%m%d).tar.gz /var/www/teamportal/uploads/

# OnlyOffice Daten sichern (falls installiert)
sudo tar -czf onlyoffice_backup_$(date +%Y%m%d).tar.gz /var/lib/onlyoffice/
```

## Troubleshooting

### Anwendung startet nicht
```bash
# Logs prüfen
sudo journalctl -u teamportal -n 100
sudo journalctl -u teamportal -f

# Service-Status prüfen
sudo systemctl status teamportal

# Manuell starten zum Testen
cd /var/www/teamportal
sudo -u www-data ./venv/bin/python app.py
```

### Datenbankverbindung schlägt fehl
```bash
# MariaDB-Status prüfen
sudo systemctl status mariadb

# Verbindung testen
mysql -u teamportal -p teamportal

# Prüfe die .env-Datei
sudo cat /var/www/teamportal/.env | grep DATABASE_URI
```

### Upload schlägt fehl
```bash
# Berechtigungen prüfen
ls -la /var/www/teamportal/uploads

# Berechtigungen korrigieren
sudo chown -R www-data:www-data /var/www/teamportal/uploads
sudo chmod -R 775 /var/www/teamportal/uploads
```

### Nginx zeigt 502 Bad Gateway
```bash
# Prüfen ob Gunicorn läuft
sudo systemctl status teamportal

# Neu starten
sudo systemctl restart teamportal

# Prüfe die Logs
sudo journalctl -u teamportal -n 100
```

### OnlyOffice nicht erreichbar (falls installiert)
```bash
# Prüfe ob OnlyOffice Container läuft
sudo docker ps | grep onlyoffice

# Prüfe Port 8080
sudo netstat -tlnp | grep 8080

# Prüfe OnlyOffice Logs
sudo docker logs onlyoffice-documentserver

# OnlyOffice neu starten
sudo docker restart onlyoffice-documentserver

# Teste ob OnlyOffice direkt auf Port 8080 erreichbar ist
curl http://127.0.0.1:8080/welcome/

# Teste ob OnlyOffice API über Nginx erreichbar ist
curl http://192.168.188.142/onlyoffice/web-apps/apps/api/documents/api.js | head -20

# Wenn die API HTML statt JavaScript zurückgibt, ist die Nginx-Konfiguration fehlerhaft
# Überprüfen Sie:
# 1. proxy_pass sollte KEINEN trailing slash haben: proxy_pass http://127.0.0.1:8080;
# 2. Nginx-Konfiguration neu laden: sudo nginx -t && sudo systemctl reload nginx

# Prüfe OnlyOffice Logs
sudo docker logs onlyoffice-documentserver

# OnlyOffice neu starten
sudo docker restart onlyoffice-documentserver
```

### OnlyOffice JWT-Fehler (falls installiert)
- Stellen Sie sicher, dass `ONLYOFFICE_SECRET_KEY` in `.env` mit dem OnlyOffice JWT_SECRET übereinstimmt
- Prüfen Sie die OnlyOffice-Logs: `sudo docker logs onlyoffice-documentserver`
- Wenn OnlyOffice ohne JWT läuft, lassen Sie `ONLYOFFICE_SECRET_KEY` in der `.env` leer

### Excalidraw lädt nicht (falls installiert)
```bash
# Prüfe ob Container laufen
sudo docker ps | grep excalidraw

# Prüfe Container-Logs
sudo docker logs excalidraw
sudo docker logs excalidraw-room

# Prüfe Ports
sudo netstat -tlnp | grep 8081
sudo netstat -tlnp | grep 8082

# Container neu starten
sudo docker restart excalidraw
sudo docker restart excalidraw-room
```

### Excalidraw-Room funktioniert nicht (falls installiert)
- Stellen Sie sicher, dass WebSocket-Support in Nginx aktiviert ist
- Prüfen Sie die Nginx-Logs: `sudo tail -f /var/log/nginx/error.log`
- Prüfen Sie die Room-Server-Logs: `sudo docker logs excalidraw-room`

### Canvas-Modul kann nicht aktiviert werden (falls Excalidraw installiert)
- Prüfen Sie ob `EXCALIDRAW_ENABLED=True` in `.env` gesetzt ist
- Prüfen Sie ob Excalidraw unter `/excalidraw` erreichbar ist
- Starten Sie die Anwendung neu: `sudo systemctl restart teamportal`
- Führen Sie die entsprechende Migrationsdatei aus (z.B. `migrate_to_2.2.0.py`): `sudo -u www-data bash -c "source venv/bin/activate && python migrations/migrate_to_2.2.0.py"`

### Redis-Probleme
```bash
# Prüfe ob Redis läuft
sudo systemctl status redis-server

# Redis neu starten
sudo systemctl restart redis-server

# Redis-Verbindung testen
redis-cli ping
# Sollte "PONG" zurückgeben

# Prüfe Redis-Konfiguration in .env
sudo cat /var/www/teamportal/.env | grep REDIS

# Redis-Logs prüfen
sudo journalctl -u redis-server -n 50
```

**Häufige Probleme:**
- **SocketIO funktioniert nicht mit mehreren Workern:** Stellen Sie sicher, dass Redis installiert ist und `REDIS_ENABLED=True` in `.env` gesetzt ist
- **Redis startet nicht:** Prüfen Sie die Logs mit `sudo journalctl -u redis-server -n 50`
- **Verbindungsfehler:** Stellen Sie sicher, dass `REDIS_URL=redis://localhost:6379/0` in `.env` korrekt ist

### Socket.IO 400-Fehler (Bad Request) bei mehreren Workern

Wenn Sie viele 400-Fehler in der Browser-Konsole sehen (z.B. bei `/socket.io/?EIO=4&transport=polling`), kann das folgende Ursachen haben:

1. **Redis nicht korrekt konfiguriert:**
```bash
# Prüfen Sie die .env-Datei
sudo cat /var/www/teamportal/.env | grep REDIS

# Sollte zeigen:
# REDIS_ENABLED=True
# REDIS_URL=redis://localhost:6379/0

# Redis-Verbindung testen
redis-cli ping
# Sollte "PONG" zurückgeben
```

2. **Nginx-Konfiguration fehlt Socket.IO Location:**
   - Stellen Sie sicher, dass die Nginx-Konfiguration den `/socket.io/` Location-Block enthält (siehe Schritt 11)
   - Nginx neu starten: `sudo systemctl restart nginx`

3. **Eventlet nicht installiert:**
```bash
cd /var/www/teamportal
source venv/bin/activate
pip install eventlet
# Oder alle Dependencies neu installieren:
pip install -r requirements.txt
```

4. **Application neu starten:**
```bash
# Systemd-Service neu starten
sudo systemctl daemon-reload
sudo systemctl restart teamportal

# Prüfen Sie die Logs auf Socket.IO-Initialisierung
sudo journalctl -u teamportal -f | grep -i socket
# Sollte zeigen: "SocketIO mit Redis Message Queue konfiguriert: redis://..."
```

5. **Browser-Cache leeren:**
   - Leeren Sie den Browser-Cache und versuchen Sie es erneut
   - Oder verwenden Sie einen Inkognito-Modus für Tests

**Wichtig:** Nach Änderungen an der Socket.IO-Konfiguration müssen Sie die Anwendung **immer neu starten**, damit die Änderungen wirksam werden!

### WebSocket-Verbindungsfehler (wss:// fehlgeschlagen)

Wenn Sie Fehler wie "WebSocket connection to 'wss://...' failed" sehen:

1. **Nginx Connection-Header-Map prüfen:**
```bash
# Prüfen Sie ob die Map in nginx.conf definiert ist
sudo grep -A 3 "map \$http_upgrade" /etc/nginx/nginx.conf

# Sollte zeigen:
# map $http_upgrade $connection_upgrade {
#     default upgrade;
#     '' close;
# }

# Falls nicht vorhanden, fügen Sie es hinzu (siehe Nginx-Konfiguration oben)
```

2. **Nginx-Konfiguration testen:**
```bash
sudo nginx -t
```

3. **Nginx neu starten:**
```bash
sudo systemctl restart nginx
```

4. **Socket.IO verwendet Polling als Fallback:**
   - Wenn WebSocket fehlschlägt, sollte Socket.IO automatisch auf Polling zurückfallen
   - Das ist normalerweise kein kritisches Problem, aber weniger effizient
   - Prüfen Sie die Browser-Console - Sie sollten sehen: "SocketIO verbunden" trotz des WebSocket-Fehlers

5. **Firewall/Proxy prüfen:**
   - Stellen Sie sicher, dass WebSocket-Upgrades nicht blockiert werden
   - Bei Cloudflare oder anderen Proxies: Prüfen Sie die WebSocket-Einstellungen

### Optionalen Service deaktivieren

#### OnlyOffice deaktivieren
```bash
# 1. Container stoppen
sudo docker stop onlyoffice-documentserver

# 2. .env-Datei bearbeiten
sudo nano /var/www/teamportal/.env
# Setzen Sie: ONLYOFFICE_ENABLED=False

# 3. Nginx-Konfiguration bearbeiten
sudo nano /etc/nginx/sites-available/teamportal
# Entfernen Sie den /onlyoffice Location-Block

# 4. Nginx neu laden
sudo nginx -t
sudo systemctl reload nginx

# 5. Anwendung neu starten
sudo systemctl restart teamportal
```

#### Excalidraw deaktivieren
```bash
# 1. Container stoppen
sudo docker stop excalidraw excalidraw-room

# 2. .env-Datei bearbeiten
sudo nano /var/www/teamportal/.env
# Setzen Sie: EXCALIDRAW_ENABLED=False

# 3. Nginx-Konfiguration bearbeiten
sudo nano /etc/nginx/sites-available/teamportal
# Entfernen Sie die /excalidraw und /excalidraw-room Location-Blöcke

# 4. Nginx neu laden
sudo nginx -t
sudo systemctl reload nginx

# 5. Anwendung neu starten
sudo systemctl restart teamportal
```

## Performance-Optimierung

### Gunicorn-Worker anpassen
```bash
# In /etc/systemd/system/teamportal.service
# Faustregel: (2 x CPU-Kerne) + 1
# Für 4 CPU-Kerne: --workers 9
sudo nano /etc/systemd/system/teamportal.service
# Ändern Sie die Zeile: --workers 1 zu --workers 9
sudo systemctl daemon-reload
sudo systemctl restart teamportal
```

### Nginx Caching
```bash
sudo nano /etc/nginx/sites-available/teamportal
```

Füge hinzu:
```nginx
# Cache für statische Dateien
location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

### OnlyOffice Performance (falls installiert)
OnlyOffice kann viel Speicherplatz und RAM benötigen. Überwachen Sie regelmäßig:

```bash
# Speicherplatz prüfen
df -h
du -sh /var/lib/onlyoffice/DocumentServer/data

# RAM-Verbrauch prüfen
sudo docker stats onlyoffice-documentserver
```

**Empfohlene Systemanforderungen für OnlyOffice:**
- Mindestens 4 GB RAM (8 GB empfohlen)
- Mindestens 20 GB freier Speicherplatz
- Mehrere CPU-Kerne für bessere Performance

### Excalidraw Performance (falls installiert)
Excalidraw ist relativ leichtgewichtig, benötigt aber WebSocket-Support für Echtzeit-Kollaboration:

```bash
# Container-Status prüfen
sudo docker stats excalidraw excalidraw-room
```

**Empfohlene Systemanforderungen für Excalidraw:**
- Mindestens 2 GB RAM
- WebSocket-Support in Nginx (bereits konfiguriert)

## Sicherheits-Checkliste

- [ ] Starken `SECRET_KEY` gesetzt
- [ ] Datenbank-Passwort ist sicher
- [ ] SSL/HTTPS ist aktiviert
- [ ] Firewall ist konfiguriert
- [ ] Regelmäßige Backups sind eingerichtet
- [ ] Standard-Ports sind geschützt
- [ ] Nur notwendige Services laufen
- [ ] System-Updates sind aktuell
- [ ] OnlyOffice JWT ist aktiviert (falls OnlyOffice installiert)
- [ ] `.env`-Datei hat korrekte Berechtigungen (nicht öffentlich lesbar)
- [ ] Docker-Container laufen mit `--restart=always` (falls installiert)

## Zusammenfassung der Installation

### Pflichtschritte (immer erforderlich)
1. ✅ System vorbereiten (Pakete installieren)
2. ✅ MariaDB einrichten (nur leere Datenbank erstellen - Tabellen werden automatisch erstellt!)
3. ✅ Anwendung von GitHub installieren
4. ✅ Konfiguration (.env-Datei)
5. ✅ Berechtigungen setzen
6. ✅ Redis installieren (erforderlich für Multi-Worker-Setups)
7. ✅ Systemd-Service konfigurieren und starten (Datenbank wird beim ersten Start automatisch erstellt!)
8. ✅ Nginx konfigurieren
9. ✅ SSL mit Let's Encrypt (empfohlen)
10. ✅ Firewall konfigurieren
11. ✅ Datenbank-Initialisierung prüfen
12. ✅ Ersten Admin erstellen

### Optionale Schritte (nur bei Bedarf)
- **Docker installieren:** Nur erforderlich für OnlyOffice oder Excalidraw
- **OnlyOffice installieren:** Optional, für Dokumentenbearbeitung
- **Excalidraw installieren:** Optional, für Canvas-Modul
- **Excalidraw-Migration:** Nur erforderlich, wenn Excalidraw installiert ist

### Wichtige Hinweise

1. **.env-Konfiguration:**
   - Setzen Sie `ONLYOFFICE_ENABLED=False`, wenn OnlyOffice NICHT installiert ist
   - Setzen Sie `EXCALIDRAW_ENABLED=False`, wenn Excalidraw NICHT installiert ist
   - Diese Einstellungen sind bereits in `docs/env.example` auf `False` gesetzt

2. **Nginx-Konfiguration:**
   - Entfernen Sie die OnlyOffice-Location-Blöcke, wenn OnlyOffice NICHT installiert ist
   - Entfernen Sie die Excalidraw-Location-Blöcke, wenn Excalidraw NICHT installiert ist

3. **Docker-Container:**
   - Nur starten, wenn die entsprechenden Features benötigt werden
   - Container können jederzeit gestoppt und entfernt werden

4. **Datenbank-Erstellung:**
   - Die Datenbank wird **automatisch** beim ersten Start erstellt
   - Sie müssen **KEINE** Tabellen manuell anlegen
   - Erstellen Sie nur die leere Datenbank in MariaDB
   - Beim ersten Start mit Systemd-Service wird alles automatisch initialisiert
   - Verwenden Sie `--workers 1` (1 Worker) für den ersten Start
   - Nach erfolgreichem Start können Sie auf mehrere Worker umstellen

5. **Redis-Konfiguration:**
   - Redis wird automatisch installiert und konfiguriert
   - Erforderlich für Multi-Worker-Setups mit SocketIO (Echtzeit-Updates)
   - Ohne Redis funktionieren SocketIO-Events nur mit einem Worker
   - Redis wird automatisch in `.env` konfiguriert (`REDIS_ENABLED=True`, `REDIS_URL=redis://localhost:6379/0`)

## Support

Bei Problemen:
1. Logs überprüfen (siehe Wartung)
2. Troubleshooting-Abschnitt durchgehen
3. GitHub Issues durchsuchen
4. Neues Issue erstellen mit detaillierter Fehlerbeschreibung

## Weitere Informationen

- **Excalidraw Dokumentation:** https://docs.excalidraw.com
- **OnlyOffice Dokumentation:** https://api.onlyoffice.com/
- **Docker Hub Excalidraw:** https://hub.docker.com/r/excalidraw/excalidraw
- **Docker Hub OnlyOffice:** https://hub.docker.com/r/onlyoffice/documentserver



