#!/bin/bash
# nginx reverse proxy

step_nginx() {
    if ! is_yes "$SETUP_WEBSERVER" || [ "$WEBSERVER_TYPE" != "nginx" ]; then
        return 2
    fi

log_info "=== Nginx Konfiguration ==="

# Connection-Upgrade Map in nginx.conf hinzufügen (für WebSocket-Support)
log_info "Füge WebSocket-Connection-Map zu nginx.conf hinzu..."
if ! grep -q "map \$http_upgrade \$connection_upgrade" /etc/nginx/nginx.conf; then
    # Backup erstellen
    cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup.$(date +%Y%m%d_%H%M%S)
    
    # Prüfe ob http-Block existiert
    if grep -q "^\s*http\s*{" /etc/nginx/nginx.conf; then
        # Füge Map vor den include-Zeilen im http-Block ein
        sed -i '/^\s*http\s*{/a\    # WebSocket Connection Header Map (MUSS im http-Block sein!)\n    map $http_upgrade $connection_upgrade {\n        default upgrade;\n        '\'''\'' close;\n    }' /etc/nginx/nginx.conf
        log_success "Connection-Upgrade Map zu nginx.conf hinzugefügt"
    else
        log_warning "http-Block nicht gefunden in nginx.conf - Map muss manuell hinzugefügt werden"
    fi
else
    log_info "Connection-Upgrade Map bereits vorhanden in nginx.conf"
fi

# Nginx Site-Konfiguration erstellen
cat > /etc/nginx/sites-available/teamportal <<EOF
# Upstream-Block für Session-Stickiness (MUSS VOR server-Block sein!)
# WICHTIG: ip_hash sorgt dafür, dass alle Requests eines Clients an denselben Worker gehen
# Dies ist erforderlich für Socket.IO mit Multi-Worker-Setups
upstream teamportal_backend {
ip_hash;  # Session-Stickiness für Socket.IO Multi-Worker
server 127.0.0.1:${GUNICORN_PORT};
}

server {
listen 80;
server_name ${DOMAIN};

# Security headers
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;

# File upload limit
client_max_body_size 100M;

# OnlyOffice Cache (MUSS VOR /onlyoffice kommen!)
# OnlyOffice benötigt diesen Pfad für interne Cache-Dateien
# Entfernen Sie diesen Block, wenn OnlyOffice NICHT installiert ist
location /cache {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    
    proxy_connect_timeout 600;
    proxy_send_timeout 600;
    proxy_read_timeout 600;
    send_timeout 600;
    
    proxy_buffering off;
    proxy_request_buffering off;
}

# OnlyOffice Document Server (OPTIONAL - nur wenn installiert)
# WICHTIG: MIT trailing slash bei proxy_pass, damit der /onlyoffice Präfix entfernt wird
# OnlyOffice erwartet /web-apps/... nicht /onlyoffice/web-apps/...
location /onlyoffice {
    proxy_pass http://127.0.0.1:8080/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    
    # OnlyOffice spezifische Header
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # WICHTIG: Content-Type Header vom Backend übernehmen
    # Standardmäßig sollte Nginx den Content-Type vom Backend übernehmen,
    # aber wir stellen sicher, dass er nicht überschrieben wird
    
    # CORS headers for OnlyOffice (wichtig für API-Zugriff)
    add_header Access-Control-Allow-Origin * always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
    add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
    add_header Access-Control-Allow-Credentials true always;
    
    # Handle preflight requests
    if (\$request_method = 'OPTIONS') {
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
        add_header Access-Control-Allow-Credentials true always;
        add_header Content-Length 0;
        add_header Content-Type text/plain;
        return 204;
    }
    
    # Timeouts für große Dokumente
    proxy_connect_timeout 600;
    proxy_send_timeout 600;
    proxy_read_timeout 600;
    send_timeout 600;
    
    # Disable buffering for OnlyOffice (wichtig für Streaming)
    proxy_buffering off;
    proxy_request_buffering off;
}

# Statische Dateien (MUSS VOR / kommen!)
location /static {
    alias ${INSTALL_DIR}/app/static;
    expires 30d;
    add_header Cache-Control "public, immutable";
    include /etc/nginx/mime.types;
    types {
        text/javascript mjs;
    }
}

# Uploads (MUSS VOR / kommen!)
location /uploads {
    alias ${INSTALL_DIR}/uploads;
    expires 7d;
}

# Socket.IO spezifische Konfiguration (MUSS VOR / kommen!)
# Socket.IO verwendet /socket.io/ für Polling und WebSocket-Verbindungen
# WICHTIG: Session-Stickiness für Multi-Worker (ip_hash im upstream-Block)
location /socket.io/ {
    proxy_pass http://teamportal_backend;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    
    # WebSocket support - WICHTIG: Connection Header dynamisch setzen
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    # Connection Header dynamisch setzen für WebSocket-Upgrades (wss://)
    # Verwendet die Map aus nginx.conf: $connection_upgrade
    proxy_set_header Connection \$connection_upgrade;
    
    # WICHTIG: Buffering für Socket.IO deaktivieren (verhindert 400-Fehler)
    proxy_buffering off;
    proxy_request_buffering off;
    
    # Längere Timeouts für Socket.IO Polling und WebSocket
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    send_timeout 60s;
    
    # CORS für Socket.IO (falls nötig)
    add_header Access-Control-Allow-Origin * always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
    add_header Access-Control-Allow-Headers "Content-Type" always;
    add_header Access-Control-Allow-Credentials true always;
}

# Excalidraw Room (OPTIONAL - nur wenn installiert)
# Prefix wird entfernt: /excalidraw-room/socket.io -> /socket.io
location /excalidraw-room/ {
    proxy_pass http://127.0.0.1:8082/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_connect_timeout 600;
    proxy_send_timeout 600;
    proxy_read_timeout 600;
    send_timeout 600;
    proxy_buffering off;
}

# Hauptanwendung (MUSS ZULETZT kommen!)
location / {
    proxy_pass http://teamportal_backend;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
}
}
EOF

# Site aktivieren
ln -sf /etc/nginx/sites-available/teamportal /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Nginx testen
if ! nginx -t; then
    { log_error "Nginx-Konfigurationstest fehlgeschlagen"; return 1; }
fi

# Nginx neu laden
systemctl enable nginx || { log_error "Nginx-Aktivierung fehlgeschlagen"; return 1; }
systemctl restart nginx || { log_error "Nginx-Neustart fehlgeschlagen"; return 1; }

# Prüfe Status
sleep 2
if systemctl is-active --quiet nginx; then
    log_success "Nginx läuft"
else
    { log_error "Nginx läuft nicht. Prüfe Logs: journalctl -u nginx -n 50"; return 1; }
fi

log_success "Nginx konfiguriert"
    return 0
}
