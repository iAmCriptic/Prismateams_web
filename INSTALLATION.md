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

# Bearbeite .env und setze mindestens:
# - SECRET_KEY (generiere einen sicheren Schlüssel)
# - DATABASE_URI (für SQLite: sqlite:///teamportal.db)
```

### 4. Anwendung starten
```bash
python app.py
```

Die Anwendung läuft nun auf `http://localhost:5000`

### 5. Ersten Admin erstellen

1. Öffne `http://localhost:5000`
2. Registriere einen neuen Benutzer
3. Aktiviere den Benutzer manuell in der Datenbank:

**Für SQLite:**
```bash
sqlite3 teamportal.db
UPDATE users SET is_active=1, is_admin=1 WHERE email='ihre@email.de';
.exit
```

**Für MySQL/MariaDB:**
```bash
mysql -u root -p
USE teamportal;
UPDATE users SET is_active=1, is_admin=1 WHERE email='ihre@email.de';
EXIT;
```

4. Melde dich mit deinem neuen Admin-Account an!

## Produktionsinstallation (Ubuntu Server)

### Schritt 1: System vorbereiten
```bash
# System aktualisieren
sudo apt update && sudo apt upgrade -y

# Notwendige Pakete installieren
sudo apt install -y python3 python3-pip python3-venv \
    nginx mariadb-server git supervisor
```

### Schritt 2: MariaDB einrichten
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

### Schritt 3: Anwendung installieren
```bash
# Verzeichnis erstellen
sudo mkdir -p /var/www
cd /var/www

# Repository klonen
sudo git clone https://github.com/yourusername/teamportal.git
cd teamportal

# Virtual Environment erstellen
sudo python3 -m venv venv

# Dependencies installieren
sudo ./venv/bin/pip install -r requirements.txt
```

### Schritt 4: Konfiguration
```bash
# .env erstellen
sudo cp env.example .env
sudo nano .env
```

Setze folgende Werte in `.env`:
```env
SECRET_KEY=GeneriereSicherenSchlüsselMit32ZeichenOderMehr
DATABASE_URI=mysql+pymysql://teamportal:IhrSicheresPasswort123!@localhost/teamportal
FLASK_ENV=production

# E-Mail-Einstellungen
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=ihr-email@gmail.com
MAIL_PASSWORD=ihr-app-passwort

# IMAP
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
IMAP_USE_SSL=True
```

### Schritt 5: Berechtigungen setzen
```bash
# Upload-Verzeichnisse erstellen
sudo mkdir -p uploads/{files,chat,manuals,profile_pics}

# Berechtigungen setzen
sudo chown -R www-data:www-data /var/www/teamportal
sudo chmod -R 755 /var/www/teamportal
sudo chmod -R 775 /var/www/teamportal/uploads
```

### Schritt 6: Supervisor konfigurieren
```bash
sudo nano /etc/supervisor/conf.d/teamportal.conf
```

Inhalt:
```ini
[program:teamportal]
directory=/var/www/teamportal
command=/var/www/teamportal/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 app:app
user=www-data
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
stderr_logfile=/var/log/teamportal/err.log
stdout_logfile=/var/log/teamportal/out.log
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

### Schritt 7: Nginx konfigurieren
```bash
sudo nano /etc/nginx/sites-available/teamportal
```

Inhalt:
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

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support (für zukünftige Features)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location /static {
        alias /var/www/teamportal/app/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /uploads {
        alias /var/www/teamportal/uploads;
        expires 7d;
    }
}
```

```bash
# Site aktivieren
sudo ln -s /etc/nginx/sites-available/teamportal /etc/nginx/sites-enabled/

# Nginx testen und neu starten
sudo nginx -t
sudo systemctl restart nginx
```

### Schritt 8: SSL mit Let's Encrypt
```bash
# Certbot installieren
sudo apt install -y certbot python3-certbot-nginx

# SSL-Zertifikat erstellen
sudo certbot --nginx -d ihre-domain.de -d www.ihre-domain.de

# Automatische Erneuerung testen
sudo certbot renew --dry-run
```

### Schritt 9: Firewall konfigurieren
```bash
# UFW installieren (falls nicht vorhanden)
sudo apt install -y ufw

# Firewall-Regeln setzen
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

### Schritt 10: Ersten Admin erstellen
```bash
# Zur Anwendung gehen
cd /var/www/teamportal

# Flask Shell öffnen
sudo -u www-data ./venv/bin/python
```

In der Python-Shell:
```python
from app import create_app, db
from app.models.user import User

app = create_app('production')
with app.app_context():
    # Admin-Benutzer erstellen
    admin = User(
        email='admin@example.com',
        first_name='Admin',
        last_name='User',
        is_active=True,
        is_admin=True
    )
    admin.set_password('SicheresPasswort123!')
    db.session.add(admin)
    db.session.commit()
    print("Admin erstellt!")
exit()
```

## Wartung

### Logs überprüfen
```bash
# Supervisor Logs
sudo tail -f /var/log/teamportal/out.log
sudo tail -f /var/log/teamportal/err.log

# Nginx Logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Anwendung neu starten
```bash
sudo supervisorctl restart teamportal
```

### Updates einspielen
```bash
cd /var/www/teamportal
sudo git pull
sudo ./venv/bin/pip install -r requirements.txt
sudo supervisorctl restart teamportal
```

### Backup erstellen
```bash
# Datenbank-Backup
sudo mysqldump -u teamportal -p teamportal > backup_$(date +%Y%m%d).sql

# Upload-Verzeichnis sichern
sudo tar -czf uploads_backup_$(date +%Y%m%d).tar.gz uploads/
```

## Troubleshooting

### Anwendung startet nicht
```bash
# Logs prüfen
sudo supervisorctl tail teamportal stderr

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
sudo supervisorctl status teamportal

# Neu starten
sudo supervisorctl restart teamportal
```

## Performance-Optimierung

### Gunicorn-Worker anpassen
```bash
# In /etc/supervisor/conf.d/teamportal.conf
# Faustregel: (2 x CPU-Kerne) + 1
# Für 4 CPU-Kerne: -w 9
command=/var/www/teamportal/venv/bin/gunicorn -w 9 -b 127.0.0.1:5000 app:app
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

## Sicherheits-Checkliste

- [ ] Starken SECRET_KEY gesetzt
- [ ] Datenbank-Passwort ist sicher
- [ ] SSL/HTTPS ist aktiviert
- [ ] Firewall ist konfiguriert
- [ ] Regelmäßige Backups sind eingerichtet
- [ ] Standard-Ports sind geschützt
- [ ] Nur notwendige Services laufen
- [ ] System-Updates sind aktuell

## Support

Bei Problemen:
1. Logs überprüfen
2. GitHub Issues durchsuchen
3. Neues Issue erstellen mit detaillierter Fehlerbeschreibung



