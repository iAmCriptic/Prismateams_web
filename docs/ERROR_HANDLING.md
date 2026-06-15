# Team Portal – Error Handling

**Dokumentation:** [INSTALLATION.md](INSTALLATION.md) · [INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md) · [WARTUNG.md](WARTUNG.md)

Fehlerbehebung für typische Probleme nach der Installation.

## Skript-Installation schlägt fehl

Bei Problemen mit der automatischen Ubuntu-Installation:

- Terminal-Ausgabe und `[ERROR]`-Meldungen während der Installation prüfen
- `.env`-Datei im Installationsverzeichnis überprüfen
- Details zum Skript: [INSTALLATION_SCRIPT.md](INSTALLATION_SCRIPT.md)
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
sudo netstat -tlnp | grep 8080

# Prüfe OnlyOffice Logs
sudo docker logs onlyoffice-documentserver

# OnlyOffice neu starten
sudo docker restart onlyoffice-documentserver

# Teste ob OnlyOffice direkt auf Port 8080 erreichbar ist
curl http://127.0.0.1:8080/welcome/

# Teste ob OnlyOffice API über Nginx erreichbar ist
curl http://IHRE-DOMAIN/onlyoffice/web-apps/apps/api/documents/api.js | head -20

# Wenn die API HTML statt JavaScript zurückgibt, ist die Nginx-Konfiguration fehlerhaft
# Nginx-Konfiguration neu laden:
sudo nginx -t && sudo systemctl reload nginx
```

**Hinweis zur Nginx-Konfiguration:** Für OnlyOffice muss `proxy_pass` mit trailing slash gesetzt sein: `proxy_pass http://127.0.0.1:8080/;` — siehe [INSTALLATION.md – Schritt 11](INSTALLATION.md#schritt-11-nginx-konfigurieren).

## OnlyOffice JWT-Fehler (falls installiert)

- Stellen Sie sicher, dass `ONLYOFFICE_SECRET_KEY` in `.env` mit dem OnlyOffice `JWT_SECRET` übereinstimmt
- Prüfen Sie die OnlyOffice-Logs: `sudo docker logs onlyoffice-documentserver`
- Wenn OnlyOffice ohne JWT läuft, lassen Sie `ONLYOFFICE_SECRET_KEY` in der `.env` leer

## Excalidraw lädt nicht (falls installiert)

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

## Excalidraw-Room funktioniert nicht (falls installiert)

- Stellen Sie sicher, dass WebSocket-Support in Nginx aktiviert ist
- Prüfen Sie die Nginx-Logs: `sudo tail -f /var/log/nginx/error.log`
- Prüfen Sie die Room-Server-Logs: `sudo docker logs excalidraw-room`
- Nginx-Konfiguration: [INSTALLATION.md – Schritt 11](INSTALLATION.md#schritt-11-nginx-konfigurieren)

## Canvas-Modul kann nicht aktiviert werden (falls Excalidraw installiert)

- Prüfen Sie ob `EXCALIDRAW_ENABLED=True` in `.env` gesetzt ist
- Prüfen Sie ob Excalidraw unter `/excalidraw` erreichbar ist
- Starten Sie die Anwendung neu: `sudo systemctl restart teamportal`
- Führen Sie ggf. eine Migration aus: siehe [WARTUNG.md – Migrationen](WARTUNG.md#datenbank-migrationen-ausführen)

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

## Support

Bei anhaltenden Problemen:

1. Logs prüfen — [WARTUNG.md](WARTUNG.md#logs-überprüfen)
2. Dieses Dokument und [INSTALLATION.md](INSTALLATION.md) durchgehen
3. [GitHub Issues](https://github.com/iAmCriptic/Prismateams_web/issues) durchsuchen
4. Neues Issue mit detaillierter Fehlerbeschreibung und Log-Auszügen erstellen
