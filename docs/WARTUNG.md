# Team Portal – Wartung

**Dokumentation:** [INSTALLATION.md](INSTALLATION.md) · [INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md) · [ERROR_HANDLING.md](ERROR_HANDLING.md)

Anleitungen für den laufenden Betrieb: Logs, Neustart, Updates, Migrationen, Backups und Performance.

Bei Fehlern: [ERROR_HANDLING.md](ERROR_HANDLING.md)

## Logs überprüfen

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

## Anwendung neu starten

```bash
sudo systemctl restart teamportal
sudo systemctl status teamportal
```

## Docker-Container neu starten (falls installiert)

```bash
# OnlyOffice neu starten (falls installiert)
sudo docker restart onlyoffice-documentserver

# Excalidraw neu starten (falls installiert)
sudo docker restart excalidraw
sudo docker restart excalidraw-room
```

## Updates einspielen

**WICHTIG:** Erstellen Sie vor jedem Update ein Backup der Datenbank und des Upload-Verzeichnisses! (siehe [Backup erstellen](#backup-erstellen))

**Force Update (empfohlen, überschreibt lokale Änderungen)**

Diese Variante ist die empfohlene Update-Methode, sofern Sie keine eigenen Code-Änderungen im Repository haben. Bei lokalen Anpassungen besser mit `git stash` arbeiten.

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

## Datenbank-Migrationen ausführen

**Wichtig:** Bei einer Neuinstallation werden die Datenbank und alle Tabellen automatisch beim ersten Start angelegt. Sie müssen keine Tabellen manuell erstellen!

**Migrationen sind nur erforderlich, wenn Sie von einer älteren Version aktualisieren.**

```bash
cd /var/www/teamportal
# Beispiel Migration:
sudo -u www-data bash -c "source venv/bin/activate && python migrations/migrate_to_2_4_3.py"
```

**Hinweis:** Prüfen Sie die verfügbaren Migrationsdateien im `migrations/` Verzeichnis und führen Sie die entsprechende Migration für Ihre Zielversion aus.

## Docker-Container aktualisieren (falls installiert)

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

## Backup erstellen

```bash
# Datenbank-Backup
sudo mysqldump -u teamportal -p teamportal > backup_$(date +%Y%m%d).sql

# Upload-Verzeichnis sichern
sudo tar -czf uploads_backup_$(date +%Y%m%d).tar.gz /var/www/teamportal/uploads/

# OnlyOffice Daten sichern (falls installiert)
sudo tar -czf onlyoffice_backup_$(date +%Y%m%d).tar.gz /var/lib/onlyoffice/
```

## Optionale Services deaktivieren

### OnlyOffice deaktivieren

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

### Excalidraw deaktivieren

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

**Hinweis:** Für mehrere Worker muss Redis installiert und in `.env` konfiguriert sein (`REDIS_ENABLED=True`).

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
- WebSocket-Support in Nginx (siehe [INSTALLATION.md – Schritt 11](INSTALLATION.md#schritt-11-nginx-konfigurieren))

## Bei Problemen

1. Logs prüfen (siehe oben)
2. [ERROR_HANDLING.md](ERROR_HANDLING.md) durchgehen
3. GitHub Issues durchsuchen oder neues Issue erstellen
