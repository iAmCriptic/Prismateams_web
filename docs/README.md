# Team Portal
### Archiviert. eine Neue Versuion ist under Construcktion
Ein umfassendes, webbasiertes Team-Portal mit modernem Design und vollständiger Funktionalität für Teams. Entwickelt mit Flask (Python) und Bootstrap 5.

## 📋 Features

### Kernfunktionen
- **Dashboard** - Übersicht mit Widgets für Termine, Chats und E-Mails
- **Chat-System** - Haupt-Chat, Gruppen-Chats und Direktnachrichten mit Medien-Upload
- **Dateiverwaltung** - Cloud-Speicher mit Ordnerstruktur, Versionierung und Online-Editor
- **Kalender** - Gemeinsame Termine mit Teilnahmestatus
- **E-Mail-Client** - Zentrales E-Mail-Konto mit IMAP/SMTP-Integration
- **Zugangsdaten** - Sichere Passwortverwaltung mit Verschlüsselung
- **Bedienungsanleitungen** - PDF-Verwaltung (Admin-Upload)
- **Canvas** - Kreativbereich mit dynamischen Textfeldern
- **Einstellungen** - Benutzerprofile, Dark Mode, Akzentfarben

### Besonderheiten
- ✅ Mobile-First Design mit Bootstrap 5
- ✅ RESTful API für zukünftige mobile Apps
- ✅ Benutzerverwaltung mit Admin-Freischaltung
- ✅ Rollenbasierte Berechtigungen (User/Admin)
- ✅ Dark Mode Support
- ✅ Personalisierbare Akzentfarben
- ✅ Sichere Passwort-Verschlüsselung (Argon2)
- ✅ Dateiversionierung (letzte 3 Versionen)
- ✅ Responsive Navigation (Desktop Sidebar / Mobile Bottom Nav)

## 🚀 Installation

### Voraussetzungen
- Python 3.8+
- MariaDB/MySQL (oder SQLite für Entwicklung)
- pip und virtualenv

### Schritt 1: Repository klonen
```bash
git clone https://github.com/yourusername/teamportal.git
cd teamportal
```

### Schritt 2: Virtual Environment erstellen
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### Schritt 3: Dependencies installieren
```bash
pip install -r requirements.txt
```

### Schritt 4: Umgebungsvariablen konfigurieren
Kopieren Sie `.env.example` nach `.env` und passen Sie die Werte an:

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

Bearbeiten Sie `.env`:
```env
SECRET_KEY=ihr-geheimer-schluessel-hier
DATABASE_URI=mysql+pymysql://username:password@localhost/teamportal

# E-Mail-Konfiguration
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=team@example.com
MAIL_PASSWORD=ihr-email-passwort

# IMAP-Konfiguration
IMAP_SERVER=imap.example.com
IMAP_PORT=993
IMAP_USE_SSL=True
```

### Schritt 5: Datenbank initialisieren
```bash
python app.py
```

Die Datenbank wird automatisch beim ersten Start erstellt.

### Schritt 6: Ersten Admin-User erstellen
1. Starten Sie die Anwendung
2. Registrieren Sie sich über `/register`
3. Öffnen Sie die Datenbank und setzen Sie `is_active=1` und `is_admin=1` für Ihren User

**MySQL Beispiel:**
```sql
UPDATE users SET is_active=1, is_admin=1 WHERE email='ihre@email.de';
```

### Schritt 7: Anwendung starten
```bash
# Entwicklungsmodus
python app.py

# Produktion mit Gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

Die Anwendung ist jetzt unter `http://localhost:5000` verfügbar.

## 📦 Deployment auf Ubuntu Server

### 1. Server vorbereiten
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv nginx mariadb-server -y
```

### 2. MariaDB konfigurieren
```bash
sudo mysql_secure_installation
sudo mysql -u root -p
```

In MySQL:
```sql
CREATE DATABASE teamportal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'teamportal'@'localhost' IDENTIFIED BY 'sicheres-passwort';
GRANT ALL PRIVILEGES ON teamportal.* TO 'teamportal'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 3. Anwendung einrichten
```bash
cd /var/www
sudo git clone https://github.com/yourusername/teamportal.git
cd teamportal
sudo python3 -m venv venv
source venv/bin/activate
sudo pip install -r requirements.txt
```

### 4. .env konfigurieren
```bash
sudo nano .env
```

Setzen Sie die Produktions-Konfiguration mit der MariaDB-Verbindung.

### 5. Systemd Service erstellen
```bash
sudo nano /etc/systemd/system/teamportal.service
```

Inhalt:
```ini
[Unit]
Description=Team Portal
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/teamportal
Environment="PATH=/var/www/teamportal/venv/bin"
ExecStart=/var/www/teamportal/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 app:app

[Install]
WantedBy=multi-user.target
```

### 6. Service starten
```bash
sudo systemctl daemon-reload
sudo systemctl start teamportal
sudo systemctl enable teamportal
sudo systemctl status teamportal
```

### 7. Nginx als Reverse Proxy
```bash
sudo nano /etc/nginx/sites-available/teamportal
```

Inhalt:
```nginx
server {
    listen 80;
    server_name ihre-domain.de;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /var/www/teamportal/app/static;
    }

    location /uploads {
        alias /var/www/teamportal/uploads;
    }

    client_max_body_size 100M;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/teamportal /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 8. SSL mit Let's Encrypt (Optional, aber empfohlen)
```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d ihre-domain.de
```

### 9. Berechtigungen setzen
```bash
sudo chown -R www-data:www-data /var/www/teamportal
sudo chmod -R 755 /var/www/teamportal
sudo chmod -R 775 /var/www/teamportal/uploads
```

## 🗂️ Projektstruktur

```
teamportal/
├── app/
│   ├── __init__.py           # Flask App Factory
│   ├── models/               # Datenbank-Modelle
│   │   ├── user.py
│   │   ├── chat.py
│   │   ├── file.py
│   │   ├── calendar.py
│   │   ├── email.py
│   │   ├── credential.py
│   │   ├── manual.py
│   │   ├── canvas.py
│   │   └── settings.py
│   ├── blueprints/           # Flask Blueprints (Module)
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── chat.py
│   │   ├── files.py
│   │   ├── calendar.py
│   │   ├── email.py
│   │   ├── credentials.py
│   │   ├── manuals.py
│   │   ├── canvas.py
│   │   ├── settings.py
│   │   └── api.py
│   ├── templates/            # Jinja2 Templates
│   │   ├── base.html
│   │   ├── auth/
│   │   ├── dashboard/
│   │   ├── chat/
│   │   ├── files/
│   │   ├── calendar/
│   │   ├── email/
│   │   ├── credentials/
│   │   ├── manuals/
│   │   ├── canvas/
│   │   └── settings/
│   └── static/               # Statische Dateien
│       ├── css/
│       │   └── style.css
│       ├── js/
│       │   └── app.js
│       └── img/
├── uploads/                  # Upload-Verzeichnis
│   ├── files/
│   ├── chat/
│   ├── manuals/
│   └── profile_pics/
├── app.py                    # Einstiegspunkt
├── config.py                 # Konfiguration
├── requirements.txt          # Python Dependencies
├── .env.example              # Beispiel-Umgebungsvariablen
├── .gitignore
└── README.md
```

## 🔑 API-Endpunkte

Alle API-Endpunkte sind unter `/api/` verfügbar:

### Benutzer
- `GET /api/users` - Alle aktiven Benutzer
- `GET /api/users/<id>` - Einzelner Benutzer

### Chats
- `GET /api/chats` - Alle Chats des Benutzers
- `GET /api/chats/<id>/messages` - Nachrichten eines Chats

### Kalender
- `GET /api/events` - Alle Termine
- `GET /api/events/<id>` - Einzelner Termin

### Dateien
- `GET /api/files?folder_id=<id>` - Dateien in einem Ordner
- `GET /api/folders?parent_id=<id>` - Unterordner

### Dashboard
- `GET /api/dashboard/stats` - Dashboard-Statistiken

## 🎨 Anpassung

### Akzentfarbe ändern
Benutzer können ihre persönliche Akzentfarbe unter **Einstellungen → Darstellung** festlegen.

### Dark Mode
Der Dark Mode kann pro Benutzer unter **Einstellungen → Darstellung** aktiviert werden.

### E-Mail-Footer
Administratoren können den globalen E-Mail-Footer unter **Einstellungen → Administration → System-Einstellungen** bearbeiten.

## 🔒 Sicherheit

- Passwörter werden mit **Argon2** gehasht
- Zugangsdaten werden mit **Fernet** (symmetrische Verschlüsselung) gespeichert
- CSRF-Schutz durch Flask-WTF
- XSS-Schutz durch Jinja2 Auto-Escaping
- SQL-Injection-Schutz durch SQLAlchemy ORM
- Rollenbasierte Zugriffskontrolle

## 📝 Standardmäßige Berechtigungen

### Benutzer
- Dashboard anzeigen
- Chats lesen und schreiben
- Dateien hochladen, bearbeiten, löschen
- Termine erstellen, bearbeiten, Teilnahme zusagen/absagen
- E-Mails lesen und senden (wenn berechtigt)
- Zugangsdaten erstellen, bearbeiten, löschen
- Anleitungen anzeigen
- Canvas erstellen und bearbeiten

### Administratoren
Alle Benutzer-Rechte plus:
- Benutzer aktivieren/deaktivieren/löschen
- Admin-Rechte vergeben
- Termine löschen
- Teilnehmer von Terminen entfernen
- E-Mail-Berechtigungen verwalten
- Anleitungen hochladen und löschen
- System-Einstellungen bearbeiten

## 🐛 Troubleshooting

### Problem: Datenbank-Verbindungsfehler
**Lösung:** Überprüfen Sie die `DATABASE_URI` in `.env` und stellen Sie sicher, dass MariaDB/MySQL läuft.

### Problem: E-Mails werden nicht gesendet
**Lösung:** Überprüfen Sie SMTP-Einstellungen in `.env`. Testen Sie die Verbindung manuell.

### Problem: Uploads schlagen fehl
**Lösung:** Überprüfen Sie Berechtigungen des `uploads/` Verzeichnisses:
```bash
sudo chmod -R 775 uploads/
sudo chown -R www-data:www-data uploads/
```

### Problem: Static Files werden nicht geladen
**Lösung:** Stellen Sie sicher, dass Nginx korrekt konfiguriert ist und auf das richtige Verzeichnis zeigt.

## 📜 Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert. Siehe [LICENSE](LICENSE) für Details.

## 👥 Beitrag

Beiträge sind willkommen! Bitte erstellen Sie einen Pull Request oder öffnen Sie ein Issue.

## 📧 Kontakt

Bei Fragen oder Problemen öffnen Sie bitte ein Issue auf GitHub.

---

**Entwickelt mit ❤️ für effiziente Team-Zusammenarbeit**



