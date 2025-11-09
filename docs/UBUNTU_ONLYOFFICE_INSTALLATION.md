# Installationsanleitung: Prismateams mit OnlyOffice auf Ubuntu Server

Diese Anleitung führt Sie Schritt für Schritt durch die Installation von Prismateams mit OnlyOffice Document Server auf einem Ubuntu Server.

## 📋 Voraussetzungen

- Ubuntu Server 22.04 LTS oder neuer
- Mindestens 4 GB RAM (8 GB empfohlen für OnlyOffice)
- Mindestens 20 GB freier Speicherplatz
- Statische IP-Adresse oder Domain
- Root- oder sudo-Zugriff

---

## Phase 1: Ubuntu Server Installation

### 1. Ubuntu Server installieren

1. Laden Sie Ubuntu Server 22.04 LTS oder neuer herunter
2. Installieren Sie Ubuntu Server auf Ihrem System
3. Stellen Sie sicher, dass Sie eine statische IP-Adresse oder Domain konfiguriert haben

### 2. System aktualisieren

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

---

## Phase 2: Basis-System Setup

```bash
# Notwendige Pakete installieren
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    nginx \
    mariadb-server \
    git \
    supervisor \
    curl \
    wget \
    ufw \
    certbot \
    python3-certbot-nginx \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release
```

---

## Phase 3: OnlyOffice Document Server installieren

Sie haben zwei Optionen für die Installation von OnlyOffice:

### Option A: OnlyOffice Community Edition (Docker) - **EMPFOHLEN**

```bash
# Docker installieren
sudo apt install -y docker.io docker-compose
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER

# OnlyOffice Document Server starten
sudo docker run -i -t -d -p 8080:80 --restart=always \
    -v /var/lib/onlyoffice/DocumentServer/data:/var/www/onlyoffice/Data \
    -v /var/lib/onlyoffice/DocumentServer/logs:/var/log/onlyoffice \
    onlyoffice/documentserver

# Prüfen ob OnlyOffice läuft
sudo docker ps
curl http://localhost:8080/welcome/
```

**Wichtig für JWT-Authentifizierung:**

Wenn Sie JWT aktivieren möchten (empfohlen für Produktion), starten Sie OnlyOffice mit einem Secret Key:

```bash
# OnlyOffice Container stoppen (falls bereits gestartet)
sudo docker stop $(sudo docker ps -q --filter ancestor=onlyoffice/documentserver)

# OnlyOffice mit JWT starten
sudo docker run -i -t -d -p 8080:80 --restart=always \
    -v /var/lib/onlyoffice/DocumentServer/data:/var/www/onlyoffice/Data \
    -v /var/lib/onlyoffice/DocumentServer/logs:/var/log/onlyoffice \
    -e JWT_SECRET=dein-jwt-secret-key-hier \
    onlyoffice/documentserver
```

**Notieren Sie sich den JWT_SECRET!** Sie benötigen ihn später für die Konfiguration.

### Option B: OnlyOffice Community Edition (DEB-Paket)

```bash
# OnlyOffice GPG-Key hinzufügen
sudo mkdir -p /usr/share/keyrings
curl -fsSL https://download.onlyoffice.com/GPG-KEY-ONLYOFFICE | sudo gpg --dearmor -o /usr/share/keyrings/onlyoffice.gpg

# Repository hinzufügen
echo "deb [signed-by=/usr/share/keyrings/onlyoffice.gpg] https://download.onlyoffice.com/repo/debian squeeze main" | sudo tee /etc/apt/sources.list.d/onlyoffice.list

# OnlyOffice Document Server installieren
sudo apt update
sudo apt install -y onlyoffice-documentserver

# OnlyOffice konfigurieren
sudo onlyoffice-documentserver-jwt-status
```

**Wichtig:** Notieren Sie sich den JWT-Secret-Key, der während der Installation angezeigt wird. Sie benötigen ihn später für die Konfiguration.

---

## Phase 4: MariaDB einrichten

```bash
# MariaDB absichern
sudo mysql_secure_installation

# Datenbank und Benutzer erstellen
sudo mysql -u root -p
```

In der MySQL-Konsole:

```sql
CREATE DATABASE teamportal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'teamportal'@'localhost' IDENTIFIED BY 'IhrSicheresPasswort123!';
GRANT ALL PRIVILEGES ON teamportal.* TO 'teamportal'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

**Wichtig:** Ersetzen Sie `IhrSicheresPasswort123!` mit einem sicheren Passwort Ihrer Wahl.

---

## Phase 5: Prismateams installieren

```bash
# Verzeichnis erstellen
sudo mkdir -p /var/www
cd /var/www

# Repository klonen (ersetze mit deinem Repository-URL)
sudo git clone https://github.com/iAmCriptic/Primsateams_web_V0.git teamportal
cd teamportal

# Virtual Environment erstellen
sudo python3 -m venv venv

# Dependencies installieren
sudo ./venv/bin/pip install --upgrade pip
sudo ./venv/bin/pip install -r requirements.txt

# Upload-Verzeichnisse erstellen
sudo mkdir -p uploads/{files,chat,manuals,profile_pics,inventory/product_images,system}

# Berechtigungen setzen
sudo chown -R www-data:www-data /var/www/teamportal
sudo chmod -R 755 /var/www/teamportal
sudo chmod -R 775 /var/www/teamportal/uploads
```

---

## Phase 6: Konfiguration (.env-Datei)

```bash
# .env erstellen
sudo cp docs/env.example .env
sudo nano .env
```

Wichtige Einstellungen in `.env`:

```env
# Flask Configuration
SECRET_KEY=GeneriereSicherenSchlüsselMit32ZeichenOderMehr
FLASK_ENV=production

# Database Configuration
DATABASE_URI=mysql+pymysql://teamportal:IhrSicheresPasswort123!@localhost/teamportal

# ONLYOFFICE Configuration
ONLYOFFICE_ENABLED=True
ONLYOFFICE_DOCUMENT_SERVER_URL=/onlyoffice
ONLYOFFICE_SECRET_KEY=dein-jwt-secret-key-von-onlyoffice

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

**Wichtige Hinweise:**

- `SECRET_KEY`: Generieren Sie einen sicheren Schlüssel (z.B. mit `openssl rand -hex 32`)
- `DATABASE_URI`: Verwenden Sie das Passwort, das Sie in Phase 4 erstellt haben
- `ONLYOFFICE_SECRET_KEY`: Muss mit dem JWT-Secret von OnlyOffice übereinstimmen (siehe Phase 3)
- Wenn OnlyOffice ohne JWT läuft, können Sie `ONLYOFFICE_SECRET_KEY` leer lassen

---

## Phase 7: Nginx konfigurieren

```bash
sudo nano /etc/nginx/sites-available/teamportal
```

Nginx-Konfiguration mit OnlyOffice-Integration:

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

    # OnlyOffice Document Server (wenn Docker auf Port 8080 läuft)
    location /onlyoffice {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # OnlyOffice spezifische Header
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts für große Dokumente
        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
        send_timeout 600;
    }

    # Hauptanwendung
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
    }

    # Statische Dateien
    location /static {
        alias /var/www/teamportal/app/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Uploads
    location /uploads {
        alias /var/www/teamportal/uploads;
        expires 7d;
    }
}
```

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

**Hinweis:** Ersetzen Sie `ihre-domain.de` mit Ihrer tatsächlichen Domain oder IP-Adresse.

---

## Phase 8: Supervisor/Gunicorn einrichten

### Schritt 1: Supervisor-Konfiguration erstellen

```bash
sudo nano /etc/supervisor/conf.d/teamportal.conf
```

**WICHTIG:** Für den ersten Start verwenden wir `-w 1` (nur 1 Worker), um Probleme bei der Datenbank-Initialisierung zu vermeiden!

Inhalt für den ersten Start:

```ini
[program:teamportal]
directory=/var/www/teamportal
command=/var/www/teamportal/venv/bin/gunicorn -w 1 -b 127.0.0.1:5000 --timeout 600 wsgi:app
user=www-data
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
stderr_logfile=/var/log/teamportal/err.log
stdout_logfile=/var/log/teamportal/out.log
environment=PATH="/var/www/teamportal/venv/bin",FLASK_ENV="production"
```

```bash
# Log-Verzeichnis erstellen
sudo mkdir -p /var/log/teamportal
sudo chown www-data:www-data /var/log/teamportal

# Supervisor neu laden
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start teamportal
sudo supervisorctl status teamportal
```

### Schritt 2: Auf regulären Betrieb umstellen

**Nach dem ersten Start** (die Datenbank wird automatisch beim Start angelegt) können Sie auf mehrere Worker umstellen:

```bash
sudo nano /etc/supervisor/conf.d/teamportal.conf
```

Ändern Sie die `command`-Zeile von `-w 1` zu `-w 4`:

```ini
[program:teamportal]
directory=/var/www/teamportal
command=/var/www/teamportal/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 --timeout 600 wsgi:app
user=www-data
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
stderr_logfile=/var/log/teamportal/err.log
stdout_logfile=/var/log/teamportal/out.log
environment=PATH="/var/www/teamportal/venv/bin",FLASK_ENV="production"
```

```bash
# Supervisor neu laden und neu starten
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl restart teamportal
sudo supervisorctl status teamportal
```

**Wichtig:** 
- Der erste Start **muss** mit `-w 1` erfolgen, um Datenbank-Initialisierungsprobleme zu vermeiden
- Die Datenbank wird automatisch beim ersten Start der Anwendung angelegt
- Nach dem ersten erfolgreichen Start können Sie auf `-w 4` (oder mehr) umstellen
- Der `command` verwendet `wsgi:app` (die `wsgi.py` Datei ist bereits im Repository enthalten)

---

## Phase 9: SSL mit Let's Encrypt

```bash
# SSL-Zertifikat erstellen
sudo certbot --nginx -d ihre-domain.de -d www.ihre-domain.de

# Automatische Erneuerung testen
sudo certbot renew --dry-run
```

**Hinweis:** Diese Phase ist optional, aber dringend empfohlen für Produktionsumgebungen.

---

## Phase 10: Firewall konfigurieren

```bash
# Firewall-Regeln setzen
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

---

## Phase 11: Überprüfung und Tests

### 1. OnlyOffice testen

```bash
# OnlyOffice sollte erreichbar sein
curl http://localhost:8080/welcome/
```

### 2. Anwendung testen

1. Öffnen Sie `https://ihre-domain.de` (oder `http://ihre-domain.de` wenn kein SSL) im Browser
2. Die Datenbank wird automatisch beim ersten Start angelegt
3. Registrieren Sie sich über die Registrierungsseite und aktivieren Sie den ersten Benutzer manuell als Admin in der Datenbank (falls erforderlich)
4. Laden Sie eine .docx-Datei hoch und testen Sie die OnlyOffice-Integration

### 3. Logs prüfen

```bash
# Application Logs
sudo tail -f /var/log/teamportal/out.log
sudo tail -f /var/log/teamportal/err.log

# Nginx Logs
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log

# OnlyOffice Logs (Docker)
sudo docker logs -f $(sudo docker ps -q --filter ancestor=onlyoffice/documentserver)
```

---

## Troubleshooting

### OnlyOffice nicht erreichbar

```bash
# Prüfe ob OnlyOffice läuft
sudo docker ps  # Für Docker-Installation
sudo systemctl status ds-docservice  # Für DEB-Installation

# Prüfe Port 8080
sudo netstat -tlnp | grep 8080
```

### JWT-Fehler

- Stellen Sie sicher, dass `ONLYOFFICE_SECRET_KEY` in `.env` mit dem OnlyOffice JWT-Secret übereinstimmt
- Bei Docker: Der `JWT_SECRET` beim Start muss identisch sein
- Prüfen Sie die OnlyOffice-Logs auf JWT-Fehler

### 502 Bad Gateway

```bash
# Prüfe ob Gunicorn läuft
sudo supervisorctl status teamportal

# Prüfe die Logs
sudo tail -50 /var/log/teamportal/err.log

# Starte Gunicorn neu
sudo supervisorctl restart teamportal
```

### Datenbankverbindungsfehler

```bash
# Teste die Datenbankverbindung
mysql -u teamportal -p teamportal

# Prüfe die .env-Datei
sudo cat /var/www/teamportal/.env | grep DATABASE_URI
```

### Berechtigungsprobleme

```bash
# Setze Berechtigungen neu
sudo chown -R www-data:www-data /var/www/teamportal
sudo chmod -R 755 /var/www/teamportal
sudo chmod -R 775 /var/www/teamportal/uploads
```

---

## Wartung

### Anwendung neu starten

```bash
sudo supervisorctl restart teamportal
```

### Updates einspielen

**Option 1: Mit lokalen Änderungen (empfohlen für Produktion)**

Wenn lokale Änderungen vorhanden sind (z.B. durch Systemnutzung), werden diese temporär gespeichert:

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
sudo supervisorctl restart teamportal
```

**Option 2: Lokale Änderungen verwerfen (nur wenn lokale Änderungen unwichtig sind)**

⚠️ **VORSICHT:** Diese Methode verwirft alle lokalen Änderungen!

```bash
cd /var/www/teamportal

# Alle lokalen Änderungen verwerfen und auf Remote-Stand zurücksetzen
sudo -u www-data git fetch origin
sudo -u www-data git reset --hard origin/main

# Dependencies aktualisieren
sudo ./venv/bin/pip install -r requirements.txt

# Anwendung neu starten
sudo supervisorctl restart teamportal
```

**Option 3: Ohne lokale Änderungen (wenn alles sauber ist)**

```bash
cd /var/www/teamportal

# Git Pull als www-data ausführen (vermeidet "dubious ownership" Fehler)
sudo -u www-data git pull

# Dependencies aktualisieren
sudo ./venv/bin/pip install -r requirements.txt

# Anwendung neu starten
sudo supervisorctl restart teamportal
```

**Empfehlung:** 
- Verwenden Sie **Option 1** (mit stash), wenn Sie lokale Änderungen behalten möchten
- Verwenden Sie **Option 2** (hard reset), wenn lokale Änderungen unwichtig sind (z.B. nur temporäre Dateien)
- Die meisten System-Dateien (uploads, logs, etc.) sind bereits in `.gitignore` und werden nicht von Git verfolgt

### Backup erstellen

```bash
# Datenbank-Backup
sudo mysqldump -u teamportal -p teamportal > backup_$(date +%Y%m%d).sql

# Upload-Verzeichnis sichern
sudo tar -czf uploads_backup_$(date +%Y%m%d).tar.gz /var/www/teamportal/uploads/
```

### Logs rotieren

```bash
# Logs regelmäßig leeren (optional)
sudo truncate -s 0 /var/log/teamportal/out.log
sudo truncate -s 0 /var/log/teamportal/err.log
```

---

## Sicherheits-Checkliste

- [ ] Starken `SECRET_KEY` gesetzt
- [ ] Datenbank-Passwort ist sicher
- [ ] SSL/HTTPS ist aktiviert
- [ ] Firewall ist konfiguriert
- [ ] OnlyOffice JWT ist aktiviert (empfohlen)
- [ ] Regelmäßige Backups sind eingerichtet
- [ ] System-Updates sind aktuell
- [ ] Nur notwendige Services laufen

---

## Wichtige Hinweise

### OnlyOffice JWT

- **WOPI ist NICHT erforderlich** - Die Anwendung verwendet die native OnlyOffice Document Server API
- JWT-Authentifizierung ist optional, aber für Produktionsumgebungen empfohlen
- Der JWT-Secret muss in OnlyOffice und in der `.env`-Datei identisch sein

### Performance-Optimierung

Für Server mit mehr CPU-Kernen können Sie die Anzahl der Gunicorn-Worker anpassen:

```ini
# Faustregel: (2 x CPU-Kerne) + 1
# Für 4 CPU-Kerne: -w 9
command=/var/www/teamportal/venv/bin/gunicorn -w 9 -b 127.0.0.1:5000 --timeout 600 wsgi:app
```

### Speicherplatz

OnlyOffice kann viel Speicherplatz benötigen. Überwachen Sie regelmäßig:

```bash
df -h
du -sh /var/lib/onlyoffice/DocumentServer/data
```

---

## Support

Bei Problemen:

1. Prüfen Sie die Logs (siehe Phase 13)
2. Überprüfen Sie die Konfiguration
3. Stellen Sie sicher, dass alle Services laufen
4. Prüfen Sie die Netzwerkverbindungen

---

## Zusammenfassung

Nach erfolgreicher Installation haben Sie:

✅ Prismateams Team Portal auf Ubuntu Server  
✅ OnlyOffice Document Server für Dokumentenbearbeitung  
✅ MariaDB Datenbank  
✅ Nginx als Reverse Proxy  
✅ SSL-Zertifikat (optional)  
✅ Supervisor für Prozessverwaltung  
✅ Firewall-Konfiguration  

Die Anwendung sollte nun unter `https://ihre-domain.de` erreichbar sein!

