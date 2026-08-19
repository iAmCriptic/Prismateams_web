<p align="center">
  <img src="../app/static/img/logo.png" alt="Prismateams Logo" width="96">
</p>

<h1 align="center">Prismateams – Fehlerbehebung</h1>

<p align="center">
  <strong>Dokumentation · Version 3.0.1</strong><br>
  <img src="https://img.shields.io/badge/version-3.0.1-7c3aed?style=flat-square" alt="Version 3.0.1">
</p>

<p align="center">
  <a href="README.md">Übersicht</a> ·
  <a href="INSTALLATION.md">Installation</a> ·
  <a href="INSTALLATION_SCRIPT.md">Ubuntu-Skript</a> ·
  <a href="WARTUNG.md">Wartung</a>
</p>

---

Fehlerbehebung für typische Probleme nach der Installation von **Prismateams 3.0.1**.

> **Installer:** Modularer Ubuntu-Installer ist einsatzbereit — [INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md). Bei Skript-Problemen Terminal-Ausgabe und `$INSTALL_DIR/install-report.txt` prüfen.

## Skript-Installation schlägt fehl

Bei Problemen mit der automatischen Ubuntu-Installation:

- Terminal-Ausgabe und `[ERROR]`-Meldungen während der Installation prüfen
- `$INSTALL_DIR/install-report.txt` und Schritt-Status (`ok` / `failed` / `skipped`) prüfen
- `.env`-Datei im Installationsverzeichnis überprüfen
- Doku zum Skript: [INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md)
- Manuelle Nacharbeit (Webserver, Docker): [INSTALLATION.md](INSTALLATION.md)
- Logs nach abgeschlossener Installation: [WARTUNG.md – Logs](WARTUNG.md#logs-überprüfen)

## Anwendung startet nicht

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

## Datenbankverbindung schlägt fehl

```bash
# MariaDB-Status prüfen
sudo systemctl status mariadb

# Verbindung testen
mysql -u teamportal -p teamportal

# Prüfe die .env-Datei
sudo cat /var/www/teamportal/.env | grep DATABASE_URI
```

## Upload schlägt fehl

```bash
# Berechtigungen prüfen
ls -la /var/www/teamportal/uploads

# Berechtigungen korrigieren
sudo chown -R www-data:www-data /var/www/teamportal/uploads
sudo chmod -R 775 /var/www/teamportal/uploads
```

## Nginx zeigt 502 Bad Gateway

```bash
# Prüfen ob Gunicorn läuft
sudo systemctl status teamportal

# Neu starten
sudo systemctl restart teamportal

# Prüfe die Logs
sudo journalctl -u teamportal -n 100
```

**Häufige Ursache:** Gunicorn lauscht auf einem anderen Port als in der Nginx-Konfiguration (Standard: `127.0.0.1:5000`). Siehe [INSTALLATION.md – Schritt 10 und 11](INSTALLATION.md#schritt-10-systemd-service-konfigurieren).

## OnlyOffice nicht erreichbar (falls installiert)

```bash
# Prüfe ob OnlyOffice Container läuft
sudo docker ps | grep onlyoffice

# Prüfe Port 8080
sudo ss -ltnp | grep 8080

# Prüfe OnlyOffice Logs
sudo docker logs onlyoffice-documentserver

# OnlyOffice neu starten
sudo docker restart onlyoffice-documentserver

# Healthcheck / Welcome (Installer bindet 127.0.0.1:8080)
curl -s http://127.0.0.1:8080/healthcheck
curl -s http://127.0.0.1:8080/welcome/ | head

# Teste ob OnlyOffice API über Nginx erreichbar ist
curl http://IHRE-DOMAIN/onlyoffice/web-apps/apps/api/documents/api.js | head -20

# Wenn die API HTML statt JavaScript zurückgibt, ist die Nginx-Konfiguration fehlerhaft
sudo nginx -t && sudo systemctl reload nginx
```

**Installer: `OnlyOffice FEHLGESCHLAGEN Fehlercode 1`:** meist `docker pull`/`docker run` fehlgeschlagen (zu wenig RAM/Disk, kein amd64, Port 8080 belegt, Daemon down). Installer-Output und `docker logs onlyoffice-documentserver` prüfen. Neu: `sudo docker pull onlyoffice/documentserver:latest`.

**Hinweis:** Portal braucht **Document Server (Docs)**, nicht Community Server/Workspace.

**Hinweis zur Nginx-Konfiguration:** Für OnlyOffice muss `proxy_pass` mit trailing slash gesetzt sein: `proxy_pass http://127.0.0.1:8080/;` — siehe [INSTALLATION.md – Schritt 11](INSTALLATION.md#schritt-11-nginx-konfigurieren).

## OnlyOffice JWT-Fehler (falls installiert)

- Stellen Sie sicher, dass `ONLYOFFICE_SECRET_KEY` in `.env` mit dem OnlyOffice `JWT_SECRET` übereinstimmt
- Prüfen Sie die OnlyOffice-Logs: `sudo docker logs onlyoffice-documentserver`
- Wenn OnlyOffice ohne JWT läuft, lassen Sie `ONLYOFFICE_SECRET_KEY` in der `.env` leer

## OnlyOffice: Schriften fehlen / PDF sieht falsch aus (falls installiert)

PDF, Druck und Konvertierung brauchen TTFs, die das Image nicht mitbringt (Microsoft Core Fonts). **Carlito/Liberation nicht** ins Custom-Volume kopieren – Duplikate zerlegen `font_selection.bin` und führen zu „Fehler beim Öffnen der Datei“.

```bash
sudo apt update
echo ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true | sudo debconf-set-selections
sudo apt install -y ttf-mscorefonts-installer cabextract

sudo mkdir -p /var/lib/onlyoffice/DocumentServer/fonts
sudo find /var/lib/onlyoffice/DocumentServer/fonts -maxdepth 1 -type f \
  \( -iname '*.ttf' -o -iname '*.otf' -o -iname '*.ttc' \) -delete
sudo find /usr/share/fonts/truetype/msttcorefonts \
  -type f \( -iname '*.ttf' -o -iname '*.otf' \) \
  -exec cp {} /var/lib/onlyoffice/DocumentServer/fonts/ \; 2>/dev/null || true

sudo docker restart onlyoffice-documentserver
```

Danach Browser hart neu laden (Strg+F5). **Carlito** (im Image) ersetzt Calibri. Echte Calibri-TTFs optional ins selbe Volume, dann Container neu starten – nicht `documentserver-generate-allfonts.sh` gegen den laufenden Editor. Beim Container-Update das Fonts-Volume nicht vergessen – siehe [WARTUNG.md](WARTUNG.md#docker-container-aktualisieren-falls-installiert).

## Excalidraw-Kollaboration funktioniert nicht (falls Room installiert)

```bash
# Prüfe ob der Room-Container läuft
sudo docker ps | grep excalidraw-room

# Prüfe Container-Logs
sudo docker logs excalidraw-room

# Prüfe Loopback-Port
sudo ss -ltn | grep 8082

# Container neu starten
sudo docker restart excalidraw-room
```

- Stellen Sie sicher, dass WebSocket-Support in Nginx aktiviert ist (`location /excalidraw-room/`)
- Prüfen Sie die Nginx-Logs: `sudo tail -f /var/log/nginx/error.log`
- Prüfen Sie ob `EXCALIDRAW_ENABLED=True` in `.env` gesetzt ist
- Zeichnen und Speichern funktionieren auch ohne Room-Server; nur Live-Kollaboration braucht ihn
- Starten Sie die Anwendung neu: `sudo systemctl restart teamportal`

## Redis-Probleme

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

- **SocketIO funktioniert nicht mit mehreren Workern:** Redis installiert und `REDIS_ENABLED=True` in `.env` setzen
- **Redis startet nicht:** Logs mit `sudo journalctl -u redis-server -n 50` prüfen
- **Verbindungsfehler:** `REDIS_URL=redis://localhost:6379/0` in `.env` prüfen

## Socket.IO 400-Fehler (Bad Request) bei mehreren Workern

Wenn Sie viele 400-Fehler in der Browser-Konsole sehen (z. B. bei `/socket.io/?EIO=4&transport=polling`):

1. **Redis nicht korrekt konfiguriert:**

```bash
sudo cat /var/www/teamportal/.env | grep REDIS
redis-cli ping
```

2. **Nginx-Konfiguration fehlt Socket.IO Location:**
   - `/socket.io/` Location-Block muss vorhanden sein — [INSTALLATION.md – Schritt 11](INSTALLATION.md#schritt-11-nginx-konfigurieren)
   - Nginx neu starten: `sudo systemctl restart nginx`

3. **Eventlet nicht installiert:**

```bash
cd /var/www/teamportal
source venv/bin/activate
pip install -r requirements.txt
```

4. **Anwendung neu starten:**

```bash
sudo systemctl daemon-reload
sudo systemctl restart teamportal
sudo journalctl -u teamportal -f | grep -i socket
```

5. **Browser-Cache leeren** oder Inkognito-Modus testen

**Wichtig:** Nach Änderungen an der Socket.IO-Konfiguration die Anwendung immer neu starten.

## WebSocket-Verbindungsfehler (wss:// fehlgeschlagen)

Wenn Fehler wie „WebSocket connection to 'wss://...' failed“ erscheinen:

1. **Nginx Connection-Header-Map prüfen:**

```bash
sudo grep -A 3 "map \$http_upgrade" /etc/nginx/nginx.conf
```

Falls nicht vorhanden: Map im `http`-Block von `nginx.conf` ergänzen — [INSTALLATION.md – Schritt 11](INSTALLATION.md#schritt-11-nginx-konfigurieren).

2. **Nginx testen und neu starten:**

```bash
sudo nginx -t
sudo systemctl restart nginx
```

3. **Socket.IO Fallback:** Bei WebSocket-Fehlern kann Polling als Fallback greifen — in der Browser-Konsole auf „SocketIO verbunden“ prüfen.

4. **Firewall/Proxy:** WebSocket-Upgrades dürfen nicht blockiert werden (Cloudflare, Reverse-Proxy-Einstellungen prüfen).

## Setup hängt nach Account-Erstellung (Login-Schleife)

Symptom: Nach Setup-Schritt 2 (Admin-Account) landet man dauerhaft auf `/login` und kann sich nicht anmelden.

**Ursache:** In Production ist `SESSION_COOKIE_SECURE=True`, der Server wird aber über HTTP erreicht. Der Browser verwirft den Session-Cookie.

**Sofortmaßnahme (HTTP ohne SSL):**

```bash
cd /var/www/teamportal   # oder Ihr INSTALL_DIR
# In .env setzen bzw. ergänzen:
# SESSION_COOKIE_SECURE=False
sudo nano .env
sudo systemctl restart teamportal
```

**Wenn inzwischen HTTPS aktiv ist:** `SESSION_COOKIE_SECURE=True` belassen bzw. setzen und Service neu starten.

**Setup-Flag prüfen** (falls Setup fälschlich als abgeschlossen gilt):

```bash
# MySQL-Beispiel – Key setup_completed in system_settings
mysql -u ROOT_USER -p -e "SELECT * FROM teamportal.system_settings WHERE \`key\`='setup_completed';"
# Bei value=true und unvollständigem Wizard:
# UPDATE teamportal.system_settings SET value='false' WHERE \`key\`='setup_completed';
```

Danach `/setup` erneut öffnen bzw. mit dem angelegten Admin einloggen. Details: [WARTUNG.md – Session-Cookies](WARTUNG.md#session-cookies-http-vs-https).

## Support

Bei anhaltenden Problemen:

1. Logs prüfen — [WARTUNG.md](WARTUNG.md#logs-überprüfen)
2. Dieses Dokument und [INSTALLATION.md](INSTALLATION.md) durchgehen
3. [GitHub Issues](https://github.com/iAmCriptic/Prismateams_web/issues) durchsuchen
4. Neues Issue mit detaillierter Fehlerbeschreibung und Log-Auszügen erstellen

---

<p align="center">
  <img src="../app/static/img/logo.png" alt="" width="40"><br>
  <sub>Prismateams 3.0.1</sub>
</p>
