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

# Gzip (CSS/JS/JSON) — Ubuntu-Default komprimiert oft nur HTML
_gzip_src="${LIB_DIR}/nginx-gzip.conf"
if [ -f "$_gzip_src" ]; then
    cp "$_gzip_src" /etc/nginx/conf.d/teamportal-gzip.conf
    log_success "Gzip aktiviert: /etc/nginx/conf.d/teamportal-gzip.conf"
else
    log_warning "nginx-gzip.conf nicht gefunden unter ${LIB_DIR}"
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

# Document Server Cache (MUSS VOR /onlyoffice und /eurooffice kommen!)
# Euro-Office / OnlyOffice benötigen diesen Pfad für interne Cache-Dateien
# Entfernen Sie diesen Block, wenn der Document Server NICHT installiert ist
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

# Document Server – Legacy-Pfad /onlyoffice (bestehende .env)
# WICHTIG: MIT trailing slash bei proxy_pass, damit der Präfix entfernt wird
# Backend erwartet /web-apps/... nicht /onlyoffice/web-apps/...
location /onlyoffice {
    proxy_pass http://127.0.0.1:8080/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    
    add_header Access-Control-Allow-Origin * always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
    add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
    add_header Access-Control-Allow-Credentials true always;
    
    if (\$request_method = 'OPTIONS') {
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
        add_header Access-Control-Allow-Credentials true always;
        add_header Content-Length 0;
        add_header Content-Type text/plain;
        return 204;
    }
    
    proxy_connect_timeout 600;
    proxy_send_timeout 600;
    proxy_read_timeout 600;
    send_timeout 600;
    
    proxy_buffering off;
    proxy_request_buffering off;
}

# Document Server – Standard-Pfad /eurooffice (neue Installationen)
# Parallel zu /onlyoffice; ONLYOFFICE_DOCUMENT_SERVER_URL steuert, welchen die App nutzt
location /eurooffice {
    proxy_pass http://127.0.0.1:8080/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    
    add_header Access-Control-Allow-Origin * always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
    add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
    add_header Access-Control-Allow-Credentials true always;
    
    if (\$request_method = 'OPTIONS') {
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
        add_header Access-Control-Allow-Credentials true always;
        add_header Content-Length 0;
        add_header Content-Type text/plain;
        return 204;
    }
    
    proxy_connect_timeout 600;
    proxy_send_timeout 600;
    proxy_read_timeout 600;
    send_timeout 600;
    
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

# WebDAV (Windows Explorer / Netzlaufwerk) — MUSS VOR / kommen!
location /webdav {
    proxy_pass http://teamportal_backend;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header Authorization \$http_authorization;
    proxy_pass_header Authorization;
    proxy_http_version 1.1;
    proxy_request_buffering off;
    proxy_buffering off;
    gzip off;
    client_max_body_size 100M;
    proxy_connect_timeout 600;
    proxy_send_timeout 600;
    proxy_read_timeout 600;
    send_timeout 600;
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

# MiroTalk SFU: eigener vHost (kein Path-Prefix unter dem Portal)
# X-Forwarded-Proto an SERVER_HOST_URL / MIROTALK_URL koppeln — sonst liefert
# MiroTalk (TRUST_PROXY) oft https://… Join-URLs obwohl nur HTTP läuft.
_meet_host=$(mirotalk_meet_hostname)
_meet_scheme=$(mirotalk_public_scheme)
if is_yes "${INSTALL_MIROTALK:-n}" && [ -n "$_meet_host" ]; then
    cat > /etc/nginx/sites-available/teamportal-meet <<EOF
server {
    listen 80;
    server_name ${_meet_host};

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:${MIROTALK_HOST_PORT:-3010};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto ${_meet_scheme};
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_buffering off;
        proxy_request_buffering off;
    }
}
EOF
    ln -sf /etc/nginx/sites-available/teamportal-meet /etc/nginx/sites-enabled/teamportal-meet
    log_info "MiroTalk-vHost ${_meet_host} → 127.0.0.1:${MIROTALK_HOST_PORT:-3010} (X-Forwarded-Proto=${_meet_scheme})"
fi

# Site aktivieren
ln -sf /etc/nginx/sites-available/teamportal /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Optional Brotli (Paket variiert je Ubuntu-Release; nur wenn nginx -t damit durchläuft)
apt_install libnginx-mod-http-brotli >/dev/null 2>&1 || \
    apt_install libnginx-mod-brotli >/dev/null 2>&1 || true
_brotli_src="${LIB_DIR}/nginx-brotli.conf"
_brotli_dst="/etc/nginx/conf.d/teamportal-brotli.conf"
rm -f "$_brotli_dst"
if [ -f "$_brotli_src" ]; then
    cp "$_brotli_src" "$_brotli_dst"
    if nginx -t >/dev/null 2>&1; then
        log_success "Brotli aktiviert: ${_brotli_dst}"
    else
        rm -f "$_brotli_dst"
        log_info "Brotli-Modul nicht geladen — nur Gzip (optional: apt install libnginx-mod-http-brotli)"
    fi
fi

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
