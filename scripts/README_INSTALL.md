# Ubuntu 24.04 Automatische Installation

Dieses Skript installiert und konfiguriert das Team Portal vollautomatisch auf Ubuntu 24.04.3 LTS.

## Voraussetzungen

- Ubuntu 24.04.3 LTS (oder kompatibel)
- Root-Zugriff (sudo)
- Internet-Verbindung
- Mindestens 4GB RAM empfohlen (für OnlyOffice und Excalidraw)

## Verwendung

1. **Repository klonen oder Dateien kopieren**
   ```bash
   # Option 1: Repository klonen
   git clone <repository-url>
   cd Prismateams_web
   
   # Option 2: Dateien bereits vorhanden
   cd /pfad/zum/projekt
   ```

2. **Skript ausführbar machen**
   ```bash
   chmod +x scripts/install_ubuntu.sh
   ```

3. **Skript als root ausführen**
   ```bash
   sudo ./scripts/install_ubuntu.sh
   ```

## Was wird installiert?

Das Skript installiert und konfiguriert automatisch:

- ✅ System-Updates und Basis-Pakete
- ✅ Python 3.12+ und pip
- ✅ MySQL/MariaDB mit automatischer Datenbank- und Benutzererstellung
- ✅ Nginx mit vollständiger Konfiguration
- ✅ Gunicorn als WSGI-Server
- ✅ Docker und Docker Compose
- ✅ OnlyOffice Document Server (Docker)
- ✅ Excalidraw Client und Room Server (Docker)
- ✅ Python Virtual Environment
- ✅ Automatische Generierung aller Keys:
  - Flask SECRET_KEY
  - VAPID Keys (für Push-Benachrichtigungen)
  - Encryption Keys (für Credentials und Music-Modul)
  - OnlyOffice Secret Key
- ✅ Automatische .env-Konfiguration
- ✅ Datenbank-Initialisierung
- ✅ Systemd Service für Gunicorn
- ✅ Firewall-Konfiguration (UFW)
- ✅ Optional: SSL mit Let's Encrypt

## Interaktive Abfragen

Das Skript fragt Sie nach:

1. **Installationspfad** (Standard: `/var/www/teamportal`)
   - Wo soll die Anwendung installiert werden?

2. **Domain oder IP-Adresse**
   - Für Nginx-Konfiguration und optional SSL

3. **SSL mit Let's Encrypt**
   - Soll SSL automatisch eingerichtet werden?
   - E-Mail-Adresse für Let's Encrypt

4. **MySQL Root-Passwort**
   - Lassen Sie leer für automatische Generierung
   - Oder geben Sie ein sicheres Passwort ein

## Automatisch generierte Werte

Das Skript generiert automatisch:

- MySQL Root-Passwort (falls nicht angegeben)
- Datenbank-Benutzer-Passwort
- Flask SECRET_KEY
- VAPID Keys
- Encryption Keys
- OnlyOffice Secret Key

**WICHTIG:** Speichern Sie die am Ende ausgegebenen Passwörter und Keys sicher!

## Nach der Installation

1. **E-Mail-Konfiguration**
   - Bearbeiten Sie `$INSTALL_DIR/.env`
   - Tragen Sie Ihre E-Mail-Einstellungen ein:
     - `MAIL_SERVER`
     - `MAIL_PORT`
     - `MAIL_USERNAME`
     - `MAIL_PASSWORD`
     - `IMAP_SERVER`
     - `IMAP_PORT`

2. **Anwendung öffnen**
   - Öffnen Sie `http://ihre-domain.de` (oder `https://` wenn SSL eingerichtet)
   - Erstellen Sie einen Admin-Benutzer über den Setup-Assistenten

3. **Service-Status prüfen**
   ```bash
   systemctl status teamportal
   systemctl status nginx
   docker ps
   ```

## Troubleshooting

### Service startet nicht
```bash
# Prüfe Logs
journalctl -u teamportal -n 100

# Prüfe Service-Status
systemctl status teamportal

# Prüfe ob Port 5000 belegt ist
netstat -tulpn | grep 5000
```

### Nginx-Fehler
```bash
# Teste Nginx-Konfiguration
nginx -t

# Prüfe Nginx-Logs
journalctl -u nginx -n 100
tail -f /var/log/nginx/error.log
```

### Datenbank-Verbindungsfehler
```bash
# Prüfe MySQL-Status
systemctl status mysql

# Teste Verbindung
mysql -u teamportal -p teamportal
```

### Docker-Container laufen nicht
```bash
# Prüfe Container-Status
docker ps -a

# Prüfe Logs
docker logs onlyoffice-documentserver
docker logs excalidraw
docker logs excalidraw-room

# Starte Container neu
docker start onlyoffice-documentserver
docker start excalidraw
docker start excalidraw-room
```

## Manuelle Anpassungen

### Gunicorn Worker-Anzahl ändern
```bash
sudo nano /etc/systemd/system/teamportal.service
# Ändere --workers 4 zu gewünschter Anzahl
sudo systemctl daemon-reload
sudo systemctl restart teamportal
```

### Nginx-Konfiguration anpassen
```bash
sudo nano /etc/nginx/sites-available/teamportal
sudo nginx -t
sudo systemctl reload nginx
```

## Deinstallation

Falls Sie die Installation entfernen möchten:

```bash
# Stoppe Services
sudo systemctl stop teamportal
sudo systemctl disable teamportal

# Entferne Service-Datei
sudo rm /etc/systemd/system/teamportal.service
sudo systemctl daemon-reload

# Entferne Nginx-Konfiguration
sudo rm /etc/nginx/sites-enabled/teamportal
sudo systemctl reload nginx

# Stoppe Docker-Container
sudo docker stop onlyoffice-documentserver excalidraw excalidraw-room
sudo docker rm onlyoffice-documentserver excalidraw excalidraw-room

# Entferne Installationsverzeichnis (optional)
sudo rm -rf /var/www/teamportal
```

## Unterstützung

Bei Problemen:
1. Prüfen Sie die Logs (siehe Troubleshooting)
2. Überprüfen Sie die Dokumentation in `docs/`
3. Öffnen Sie ein Issue auf GitHub

