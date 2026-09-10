<p align="center">
  <img src="../app/static/img/logo.png" alt="Prismateams Logo" width="96">
</p>

<h1 align="center">Prismateams – Wartung</h1>

<p align="center">
  <strong>Dokumentation · Version 3.4.12</strong><br>
  <img src="https://img.shields.io/badge/version-3.4.12-7c3aed?style=flat-square" alt="Version 3.4.12">
</p>

<p align="center">
  <a href="README.md">Übersicht</a> ·
  <a href="INSTALLATION.md">Installation</a> ·
  <a href="INSTALLATION_SCRIPT.md">Ubuntu-Skript</a> ·
  <a href="ERROR_HANDLING.md">Fehlerbehebung</a>
</p>

---

Laufender Betrieb von **Prismateams 3.4.12**: Logs, Neustart, Updates, Migrationen, Backups und Performance.

Bei Fehlern: [ERROR_HANDLING.md](ERROR_HANDLING.md)

> **Hinweis:** Standard nach Skript-Installation: Installationsverzeichnis oft `/var/www/teamportal`, systemd-Service `teamportal`. Abweichungen stehen in `$INSTALL_DIR/install-report.txt`.

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

# Euro-Office / Document Server Logs (falls installiert)
sudo docker logs -f eurooffice-documentserver
# Legacy: sudo docker logs -f onlyoffice-documentserver

# Excalidraw-Room Logs (falls installiert)
sudo docker logs -f excalidraw-room

# MiroTalk SFU Logs (falls installiert)
sudo docker logs -f mirotalksfu
```

### Datenschutz in Logs

- App-Logs maskieren E-Mail-Adressen über `app.utils.log_privacy.mask_email` (z. B. `j***@e***.com`).
- Log-Level: `LOG_LEVEL=INFO` (Produktion) bzw. `WARNING` für weniger Detail; siehe `docs/env.example`.
- journald-Retention begrenzen, z. B. in `/etc/systemd/journald.conf`:
  - `SystemMaxUse=500M` und/oder `MaxRetentionSec=30day`
  - danach `sudo systemctl restart systemd-journald`
- Nginx-Access-Logs können weiterhin Query-Strings enthalten — Rotation/Retention über `logrotate` steuern; Zugriffe auf Log-Dateien beschränken.

## Anwendung neu starten

```bash
sudo systemctl restart teamportal
sudo systemctl status teamportal
```

## Docker-Container neu starten (falls installiert)

```bash
# Euro-Office neu starten (falls installiert)
sudo docker restart eurooffice-documentserver
# Legacy: sudo docker restart onlyoffice-documentserver

# Excalidraw-Room neu starten (falls installiert)
sudo docker restart excalidraw-room

# MiroTalk SFU neu starten (falls installiert)
sudo docker restart mirotalksfu
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

**Migrationen sind nur erforderlich, wenn Sie von einer älteren Version aktualisieren** (z. B. von 2.5 auf 3.x).

```bash
cd /var/www/teamportal

# Empfohlen: alle ausstehenden Migrationen (inkl. Voll-Upgrade)
sudo -u www-data bash -c "source venv/bin/activate && python migrations/run_all.py"

# Gezielt: modellbasierter Voll-Upgrade/Repair von Legacy 2.5+ (ab 3.1.0)
# sudo -u www-data bash -c "source venv/bin/activate && python migrations/migrate_to_3_1_0.py"
# Erneut erzwingen:
# sudo -u www-data bash -c "source venv/bin/activate && python migrations/migrate_to_3_1_0.py --force"
```

**Hinweis:** `migrate_to_3_1_0.py` ist die konsolidierte Upgrade-Migration (ersetzt frühere Einzel-Skripte und 3.0.1). Sie zieht fehlende Tabellen und Spalten aus den Models nach und führt Daten-Backfills aus (Kalender, Shares, Quotas, Multi-Mailbox, Google Login, …). Das Skript ist idempotent und für Upgrades von 2.5+ gedacht. Timeout bei großen DBs ggf. über `PRISMATEAMS_MIGRATION_TIMEOUT` erhöhen (Standard 900s).

## Docker-Container aktualisieren (falls installiert)

```bash
# Euro-Office aktualisieren (falls installiert)
# Fonts-Volume beibehalten (nur mscorefonts, keine Carlito-/Liberation-Duplikate).
# Der neue Container indexiert das Volume beim Start selbst.
sudo docker stop eurooffice-documentserver
sudo docker rm eurooffice-documentserver
sudo docker pull ghcr.io/euro-office/documentserver:latest
sudo docker run -d --restart=always \
    --name eurooffice-documentserver \
    -p 127.0.0.1:8080:80 \
    -v /var/lib/eurooffice/DocumentServer/logs:/var/log/euro-office/documentserver \
    -v /var/lib/eurooffice/DocumentServer/data:/var/lib/euro-office/documentserver \
    -v /var/lib/eurooffice/DocumentServer/config:/etc/euro-office/documentserver \
    -v /var/lib/eurooffice/DocumentServer/fonts:/usr/share/fonts/truetype/custom \
    -e JWT_ENABLED=true \
    -e JWT_SECRET=dein-jwt-secret-key-hier \
    -e JWT_HEADER=Authorization \
    -e ALLOW_PRIVATE_IP_ADDRESS=true \
    ghcr.io/euro-office/documentserver:latest

# Font-Index: der neue Container indexiert das Fonts-Volume beim Start selbst.
# documentserver-generate-allfonts.sh nicht extra gegen den laufenden Editor ausführen
# (zerstört Calibri→Carlito). Nur mscorefonts im Volume, keine Carlito-/Liberation-Duplikate.

# Excalidraw aktualisieren (falls installiert)
sudo docker stop excalidraw-room
sudo docker rm excalidraw-room
sudo docker pull excalidraw/excalidraw-room:latest
sudo docker run -d -p 127.0.0.1:8082:80 --restart=always \
    --name excalidraw-room \
    -e PORT=80 \
    excalidraw/excalidraw-room:latest
```

### Optional: OnlyOffice → Euro-Office wechseln

Bestehende Installationen **müssen nicht** umstellen. `/onlyoffice` in der `.env` und der Legacy-Container bleiben gültig.

Freiwilliger Wechsel:

1. Nginx/Apache um `/eurooffice`-Location ergänzen (siehe Installer-Templates) und reload
2. Alten Container stoppen/entfernen: `docker stop onlyoffice-documentserver && docker rm onlyoffice-documentserver`
3. Euro-Office-Container wie oben starten (neues Volume-Layout; Fonts ggf. neu kopieren)
4. In `.env` entweder `ONLYOFFICE_DOCUMENT_SERVER_URL=/eurooffice` setzen **oder** `/onlyoffice` behalten (beide Prefixe zeigen auf denselben Port)
5. `ONLYOFFICE_SECRET_KEY` unverändert lassen (gleicher JWT_SECRET)
6. `systemctl restart teamportal`

## Backup erstellen

```bash
# Datenbank-Backup
sudo mysqldump -u teamportal -p teamportal > backup_$(date +%Y%m%d).sql

# Upload-Verzeichnis sichern
sudo tar -czf uploads_backup_$(date +%Y%m%d).tar.gz /var/www/teamportal/uploads/

# Euro-Office Daten sichern (falls installiert)
sudo tar -czf eurooffice_backup_$(date +%Y%m%d).tar.gz /var/lib/eurooffice/
# Legacy: sudo tar -czf onlyoffice_backup_$(date +%Y%m%d).tar.gz /var/lib/onlyoffice/
```

## Optionale Services deaktivieren

### Euro-Office / Document Server deaktivieren

```bash
# 1. Container stoppen
sudo docker stop eurooffice-documentserver
# Legacy: sudo docker stop onlyoffice-documentserver

# 2. .env-Datei bearbeiten
sudo nano /var/www/teamportal/.env
# Setzen Sie: ONLYOFFICE_ENABLED=False

# 3. Nginx-Konfiguration bearbeiten
sudo nano /etc/nginx/sites-available/teamportal
# Entfernen Sie die /eurooffice-, /onlyoffice- und /cache-Location-Blöcke

# 4. Nginx neu laden
sudo nginx -t
sudo systemctl reload nginx

# 5. Anwendung neu starten
sudo systemctl restart teamportal
```

### Excalidraw deaktivieren

```bash
# 1. Container stoppen
sudo docker stop excalidraw-room

# 2. .env-Datei bearbeiten
sudo nano /var/www/teamportal/.env
# Setzen Sie: EXCALIDRAW_ENABLED=False

# 3. Nginx-Konfiguration bearbeiten
sudo nano /etc/nginx/sites-available/teamportal
# Entfernen Sie den /excalidraw-room/ Location-Block

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
# Produktion: 2–4 Worker (mit Redis). Ein Worker reicht nur ohne Redis.
# Timeout 180s: hängende Requests geben den Worker frei; Converter/Downloads laufen im Thread.
sudo nano /etc/systemd/system/teamportal.service
# --workers 2  (oder 3–4 bei mehr CPU/RAM)
# --timeout 180
# --max-requests 1000 --max-requests-jitter 100
sudo systemctl daemon-reload
sudo systemctl restart teamportal
```

**Hinweis:** Für mehrere Worker und Kanban-SSE muss Redis installiert und in `.env` konfiguriert sein (`REDIS_ENABLED=True`). Ohne Redis pollt das Kanban-Board inkrementell (kein Full-Redraw).

### Nginx Caching

Statische Assets werden von Flask mit `SEND_FILE_MAX_AGE_DEFAULT` (Default 1 Jahr)
ausgeliefert. Zusätzlich sollte Nginx immutable setzen — Pflicht bei Produktion ohne
direkten Flask-Static-Serve:

```bash
sudo nano /etc/nginx/sites-available/teamportal
```

Füge hinzu:

```nginx
# Cache für statische Dateien
# Sicher nur mit Cache-Busting: App hängt ?v=<ABOUT_BUILD_NUMBER> an Static-URLs.
location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
    expires 30d;
    add_header Cache-Control "public, immutable";
}

# Service Worker darf nicht long-gecacht werden
location = /sw.js {
    proxy_pass http://teamportal_backend;
    proxy_set_header Host $host;
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    expires off;
}
```

**Wichtig:** `/sw.js` nicht unter die allgemeine Static-/immutable-Regel legen. Die App setzt zusätzlich `Cache-Control: no-cache` beim Ausliefern von `/sw.js`.

### Document-Server Performance (falls installiert)

Euro-Office / Document Server kann viel Speicherplatz und RAM benötigen. Überwachen Sie regelmäßig:

```bash
# Speicherplatz prüfen
df -h
du -sh /var/lib/eurooffice/DocumentServer/data
# Legacy: du -sh /var/lib/onlyoffice/DocumentServer/data

# RAM-Verbrauch prüfen
sudo docker stats eurooffice-documentserver
```

**Empfohlene Systemanforderungen für den Document Server:**
- Mindestens 4 GB RAM (8 GB empfohlen)
- Mindestens 20 GB freier Speicherplatz
- Mehrere CPU-Kerne für bessere Performance

### Excalidraw Performance (falls installiert)

Excalidraw ist relativ leichtgewichtig, benötigt aber WebSocket-Support für Echtzeit-Kollaboration:

```bash
# Container-Status prüfen
sudo docker stats excalidraw-room
```

**Empfohlene Systemanforderungen für Excalidraw:**
- Mindestens 2 GB RAM
- WebSocket-Support in Nginx (siehe [INSTALLATION.md – Schritt 11](INSTALLATION.md#schritt-11-nginx-konfigurieren))

## Session-Cookies (HTTP vs HTTPS)

In Production steuert `SESSION_COOKIE_SECURE` in `.env`, ob der Browser Session-Cookies nur über HTTPS annimmt.

| Zugriff | Empfohlener Wert |
|---------|------------------|
| `https://…` (Let's Encrypt / SSL) | `SESSION_COOKIE_SECURE=True` |
| `http://…` (IP, Domain ohne SSL) | `SESSION_COOKIE_SECURE=False` |

```bash
# Wert prüfen / setzen
grep SESSION_COOKIE_SECURE /var/www/teamportal/.env
sudo nano /var/www/teamportal/.env
sudo systemctl restart teamportal
```

Nach nachträglichem SSL (Certbot): Flag auf `True` setzen und Service neu starten. Sonst bleiben Cookies unsicher über HTTP nutzbar.

**Produkt-Checks:** In `production`/`staging` schreibt die App eine Startup-Warnung, wenn `SESSION_COOKIE_SECURE` oder `REMEMBER_COOKIE_SECURE` False ist bzw. `PUBLIC_BASE_URL` mit `https://` beginnt, das Secure-Flag aber aus ist. Admins sehen den Ist-Zustand unter Einstellungen → System → Session-Cookies.

**Stuck-Setup:** Wenn nach Admin-Anlage nur noch der Login erscheint — siehe [ERROR_HANDLING.md – Setup hängt](ERROR_HANDLING.md#setup-hängt-nach-account-erstellung-login-schleife).

## Bei Problemen

1. Logs prüfen (siehe oben)
2. [ERROR_HANDLING.md](ERROR_HANDLING.md) durchgehen
3. GitHub Issues durchsuchen oder neues Issue erstellen

---

<p align="center">
  <img src="../app/static/img/logo.png" alt="" width="40"><br>
  <sub>Prismateams 3.4.12</sub>
</p>
