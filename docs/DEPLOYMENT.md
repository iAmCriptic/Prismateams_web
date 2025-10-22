# Team Portal - Deployment Guide

## 🚀 Schnellstart

### 1. Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```

### 2. Umgebungsvariablen konfigurieren
```bash
# Kopiere die Beispiel-Konfiguration
cp docs/env.example .env

# Bearbeite die .env-Datei mit deinen Einstellungen
nano .env
```

### 3. Datenbank initialisieren
```bash
# Automatische Datenbank-Initialisierung
python scripts/init_database.py
```

### 4. Deployment-Check durchführen
```bash
# Vollständiger Deployment-Check
python scripts/deploy.py
```

### 5. Anwendung starten
```bash
# Entwicklung
python app.py

# Produktion
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## 📋 Detaillierte Anleitung

### Umgebungsvariablen

#### Erforderliche Variablen
- `SECRET_KEY`: Geheimer Schlüssel für Flask (generiere einen sicheren Schlüssel!)

#### Optionale Variablen
- `DATABASE_URI`: Datenbankverbindung (Standard: SQLite)
- `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD`: E-Mail-Konfiguration
- `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`: Push-Benachrichtigungen

### Datenbank-Setup

#### SQLite (Standard)
```bash
# Keine weitere Konfiguration erforderlich
# Die Datenbank wird automatisch erstellt
```

#### MySQL/MariaDB
```bash
# 1. Datenbank erstellen
mysql -u root -p
CREATE DATABASE teamportal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

# 2. Benutzer erstellen (optional)
CREATE USER 'teamportal'@'localhost' IDENTIFIED BY 'sicheres_passwort';
GRANT ALL PRIVILEGES ON teamportal.* TO 'teamportal'@'localhost';
FLUSH PRIVILEGES;

# 3. DATABASE_URI in .env setzen
DATABASE_URI=mysql+pymysql://teamportal:sicheres_passwort@localhost/teamportal
```

### Verzeichnisstruktur

Die folgenden Verzeichnisse werden automatisch erstellt:
```
uploads/
├── files/          # Hochgeladene Dateien
├── chat/           # Chat-Anhänge
├── manuals/         # Handbücher
└── profile_pics/    # Profilbilder
```

### Produktions-Deployment

#### 1. Umgebungsvariablen für Produktion
```bash
# In .env für Produktion
FLASK_ENV=production
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax
```

#### 2. Gunicorn-Konfiguration
```bash
# Erstelle gunicorn.conf.py
cat > gunicorn.conf.py << EOF
bind = "0.0.0.0:5000"
workers = 4
worker_class = "sync"
worker_connections = 1000
timeout = 30
keepalive = 2
max_requests = 1000
max_requests_jitter = 100
preload_app = True
EOF

# Starte mit Gunicorn
gunicorn -c gunicorn.conf.py app:app
```

#### 3. Nginx-Konfiguration (optional)
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /static {
        alias /path/to/your/app/app/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

## 🔧 Troubleshooting

### Häufige Probleme

#### 1. Datenbank-Verbindungsfehler
```bash
# Überprüfe Datenbankverbindung
python -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.session.execute(db.text('SELECT 1'))"
```

#### 2. Fehlende Abhängigkeiten
```bash
# Installiere alle Abhängigkeiten
pip install -r requirements.txt

# Überprüfe Installation
python scripts/deploy.py
```

#### 3. Berechtigungsfehler
```bash
# Setze korrekte Berechtigungen
chmod -R 755 uploads/
chown -R www-data:www-data uploads/
```

### Logs überprüfen

#### Anwendungslogs
```bash
# Gunicorn-Logs
tail -f /var/log/gunicorn/access.log
tail -f /var/log/gunicorn/error.log

# Flask-Logs (wenn mit python app.py gestartet)
# Logs werden in der Konsole angezeigt
```

#### Datenbank-Logs
```bash
# MySQL-Logs
tail -f /var/log/mysql/error.log

# SQLite (keine separaten Logs)
```

## 📊 Monitoring

### Gesundheitscheck
```bash
# Führe regelmäßige Gesundheitschecks durch
python scripts/deploy.py
```

### Datenbank-Status
```bash
# Überprüfe Tabellen
python -c "
from app import create_app, db
from app.models import *
app = create_app()
with app.app_context():
    print('Tabellen:', db.engine.table_names())
    print('Benutzer:', User.query.count())
"
```

## 🔒 Sicherheit

### Produktions-Checkliste
- [ ] `SECRET_KEY` ist gesetzt und sicher
- [ ] `SESSION_COOKIE_SECURE=True` für HTTPS
- [ ] Datenbank-Benutzer hat minimale Rechte
- [ ] Upload-Verzeichnisse sind geschützt
- [ ] HTTPS ist konfiguriert
- [ ] Firewall ist konfiguriert

### Backup
```bash
# SQLite-Backup
cp teamportal.db teamportal_backup_$(date +%Y%m%d_%H%M%S).db

# MySQL-Backup
mysqldump -u username -p teamportal > teamportal_backup_$(date +%Y%m%d_%H%M%S).sql
```

## 📞 Support

Bei Problemen:
1. Überprüfe die Logs
2. Führe `python scripts/deploy.py` aus
3. Überprüfe die Umgebungsvariablen
4. Teste die Datenbankverbindung
