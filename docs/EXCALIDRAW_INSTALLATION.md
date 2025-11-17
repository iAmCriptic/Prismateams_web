# Installationsanleitung: Excalidraw Integration für Prismateams

Diese Anleitung führt Sie Schritt für Schritt durch die Installation von Excalidraw mit Excalidraw-Room für Kollaboration in Prismateams auf einem Ubuntu Server.

## 📋 Voraussetzungen

- Ubuntu Server 22.04 LTS oder neuer
- Mindestens 4 GB RAM (8 GB empfohlen für Excalidraw + Room)
- Mindestens 20 GB freier Speicherplatz
- Statische IP-Adresse oder Domain
- Root- oder sudo-Zugriff
- Docker und Docker Compose installiert (siehe OnlyOffice-Installation)
- Nginx konfiguriert (siehe OnlyOffice-Installation)

---

## Phase 1: Docker installieren (falls noch nicht vorhanden)

```bash
# Docker installieren
sudo apt install -y docker.io docker-compose
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER

# Abmelden und wieder anmelden damit Docker-Gruppe aktiv wird
# Oder: newgrp docker
```

---

## Phase 2: Excalidraw Client installieren

### Excalidraw Container starten

```bash
# Excalidraw Client Container starten (Port 8081)
sudo docker run -i -t -d -p 8081:80 --restart=always \
    --name excalidraw \
    excalidraw/excalidraw:latest

# Prüfen ob Excalidraw läuft
sudo docker ps | grep excalidraw
curl http://localhost:8081/
```

Der Excalidraw Client sollte jetzt unter `http://localhost:8081` erreichbar sein.

---

## Phase 3: Excalidraw-Room Server installieren

Der Excalidraw-Room Server ist für Echtzeit-Kollaboration notwendig.

### Option A: Docker-Container (EMPFOHLEN)

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

### Option B: Von Quelle bauen (für erweiterte Konfiguration)

Falls Sie den Room-Server von Quelle bauen möchten:

```bash
# Node.js installieren
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Repository klonen
cd /opt
sudo git clone https://github.com/excalidraw/excalidraw-room.git
cd excalidraw-room

# Dependencies installieren
sudo npm install

# Server starten (Port 8082)
sudo npm start
```

**Hinweis:** Für Produktion sollten Sie einen Process Manager wie PM2 verwenden:

```bash
sudo npm install -g pm2
cd /opt/excalidraw-room
sudo pm2 start npm --name "excalidraw-room" -- start
sudo pm2 save
sudo pm2 startup
```

---

## Phase 4: Nginx konfigurieren

Fügen Sie die folgenden Location-Blöcke zu Ihrer Nginx-Konfiguration hinzu:

```bash
sudo nano /etc/nginx/sites-available/teamportal
```

### Nginx-Konfiguration für Excalidraw

```nginx
# Excalidraw Client (Port 8081)
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

# Excalidraw Room Server (Port 8082)
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
```

### Nginx-Konfiguration testen und neu laden

```bash
# Konfiguration testen
sudo nginx -t

# Nginx neu laden
sudo systemctl reload nginx
```

---

## Phase 5: Prismateams konfigurieren

### 5.1 Umgebungsvariablen setzen

Bearbeiten Sie die `.env`-Datei:

```bash
sudo nano /var/www/teamportal/.env
```

Fügen Sie die folgenden Zeilen hinzu:

```env
# Excalidraw Configuration
EXCALIDRAW_ENABLED=True
EXCALIDRAW_URL=/excalidraw
EXCALIDRAW_ROOM_URL=/excalidraw-room
# EXCALIDRAW_PUBLIC_URL=http://ihre-domain.de  # Optional: Falls Excalidraw auf anderem Server läuft
```

### 5.2 Datenbank-Migration ausführen

Führen Sie die Migration aus, um die Canvas-Tabellen für Excalidraw anzupassen:

```bash
cd /var/www/teamportal
source venv/bin/activate
python migrations/migrate_to_excalidraw.py
```

**WICHTIG:** Diese Migration löscht alle alten Canvas-Daten! Stellen Sie sicher, dass Sie ein Backup haben, falls Sie alte Daten behalten möchten.

### 5.3 Anwendung neu starten

```bash
# Gunicorn neu starten (oder Supervisor)
sudo supervisorctl restart teamportal
```

---

## Phase 6: Verifizierung

### 6.1 Container-Status prüfen

```bash
# Excalidraw Container
sudo docker ps | grep excalidraw

# Excalidraw-Room Container
sudo docker ps | grep excalidraw-room
```

### 6.2 Erreichbarkeit testen

```bash
# Excalidraw Client
curl http://localhost:8081/

# Excalidraw Room
curl http://localhost:8082/
```

### 6.3 In Prismateams testen

1. Melden Sie sich in Prismateams an
2. Gehen Sie zu **Einstellungen** > **Module**
3. Prüfen Sie ob "Canvas" aktiviert werden kann (nur wenn Excalidraw aktiviert ist)
4. Gehen Sie zu **Canvas** > **Neuer Canvas**
5. Erstellen Sie einen neuen Canvas
6. Öffnen Sie den Canvas - Excalidraw sollte geladen werden

---

## Troubleshooting

### Excalidraw lädt nicht

```bash
# Prüfe ob Container läuft
sudo docker ps | grep excalidraw

# Prüfe Container-Logs
sudo docker logs excalidraw
sudo docker logs excalidraw-room

# Prüfe Ports
sudo netstat -tlnp | grep 8081
sudo netstat -tlnp | grep 8082
```

### Excalidraw-Room funktioniert nicht

- Stellen Sie sicher, dass WebSocket-Support in Nginx aktiviert ist
- Prüfen Sie die Nginx-Logs: `sudo tail -f /var/log/nginx/error.log`
- Prüfen Sie die Room-Server-Logs: `sudo docker logs excalidraw-room`

### Canvas-Modul kann nicht aktiviert werden

- Prüfen Sie ob `EXCALIDRAW_ENABLED=True` in `.env` gesetzt ist
- Prüfen Sie ob Excalidraw unter `/excalidraw` erreichbar ist
- Starten Sie die Anwendung neu: `sudo supervisorctl restart teamportal`

### Daten werden nicht gespeichert

- Prüfen Sie die Canvas-Speicher-Routen: `app/blueprints/canvas.py`
- Prüfen Sie die Datenbank-Berechtigungen
- Prüfen Sie die Anwendungs-Logs: `sudo tail -f /var/log/teamportal/err.log`

### WebSocket-Verbindung fehlgeschlagen

- Prüfen Sie die Nginx-Konfiguration für WebSocket-Support
- Stellen Sie sicher, dass `proxy_set_header Upgrade $http_upgrade` gesetzt ist
- Prüfen Sie die Firewall-Einstellungen (Port 8082 sollte erreichbar sein)

---

## Wartung

### Container aktualisieren

```bash
# Excalidraw Container stoppen
sudo docker stop excalidraw

# Neuestes Image pullen
sudo docker pull excalidraw/excalidraw:latest

# Container neu starten
sudo docker start excalidraw

# Excalidraw-Room Container stoppen
sudo docker stop excalidraw-room

# Neuestes Image pullen
sudo docker pull excalidraw/excalidraw-room:latest

# Container neu starten
sudo docker start excalidraw-room
```

### Container-Logs anzeigen

```bash
# Excalidraw Client Logs
sudo docker logs -f excalidraw

# Excalidraw Room Logs
sudo docker logs -f excalidraw-room
```

### Container neu starten

```bash
# Beide Container neu starten
sudo docker restart excalidraw
sudo docker restart excalidraw-room
```

---

## Weitere Informationen

- **Excalidraw Repository:** https://github.com/excalidraw/excalidraw
- **Excalidraw Room Repository:** https://github.com/excalidraw/excalidraw-room
- **Excalidraw Dokumentation:** https://docs.excalidraw.com
- **Docker Hub Excalidraw:** https://hub.docker.com/r/excalidraw/excalidraw
- **Docker Hub Excalidraw Room:** https://hub.docker.com/r/excalidraw/excalidraw-room

---

## Anmerkungen

- Excalidraw-Room benötigt WebSocket-Support für Echtzeit-Kollaboration
- Die Room-ID wird automatisch generiert basierend auf der Canvas-ID
- Benutzer-Authentifizierung erfolgt über Teamportal-Accounts
- Alle Canvas-Daten werden als Excalidraw-JSON in der Datenbank gespeichert
- Alte Canvas-Daten werden bei der Migration gelöscht (keine automatische Migration)

