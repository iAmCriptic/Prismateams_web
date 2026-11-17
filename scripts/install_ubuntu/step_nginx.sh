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

mkdir -p /etc/nginx/snippets
_ds_extra_src="${LIB_DIR}/nginx-documentserver-extra.conf"
if [ -f "$_ds_extra_src" ]; then
    cp "$_ds_extra_src" /etc/nginx/snippets/teamportal-documentserver-extra.conf
    log_info "Document-Server-Extra-Pfade: /etc/nginx/snippets/teamportal-documentserver-extra.conf"
else
    echo '# nginx-documentserver-extra.conf fehlt im Installer-Tree' > /etc/nginx/snippets/teamportal-documentserver-extra.conf
    log_warning "nginx-documentserver-extra.conf nicht gefunden unter ${LIB_DIR}"
fi

# Gzip (CSS/JS/JSON) — Ubuntu-Default komprimiert oft nur HTML
# Ubuntu 24.04+ hat bereits "gzip on;" im http-Block von nginx.conf.
# Ein zweites "gzip on;" in conf.d lässt nginx -t scheitern (duplicate).
_gzip_src="${LIB_DIR}/nginx-gzip.conf"
_gzip_dst="/etc/nginx/conf.d/teamportal-gzip.conf"
if [ -f "$_gzip_src" ]; then
    cp "$_gzip_src" "$_gzip_dst"
    if grep -qE '^\s*gzip on;' /etc/nginx/nginx.conf; then
        sed -i '/^[[:space:]]*gzip on;/d' "$_gzip_dst"
        log_info "gzip on; bereits in nginx.conf — kein Duplikat in conf.d"
    elif grep -qE '^\s*#[[:space:]]*gzip on;' /etc/nginx/nginx.conf; then
        sed -i -E 's/^([[:space:]]*)#[[:space:]]*gzip on;/\1gzip on;/' /etc/nginx/nginx.conf
        sed -i '/^[[:space:]]*gzip on;/d' "$_gzip_dst"
        log_success "gzip on; in nginx.conf aktiviert"
    elif ! grep -qE '^\s*gzip on;' "$_gzip_dst"; then
        sed -i '1a gzip on;' "$_gzip_dst"
    fi
    log_success "Gzip aktiviert: ${_gzip_dst}"
else
    log_warning "nginx-gzip.conf nicht gefunden unter ${LIB_DIR}"
fi

# Open-file-Cache (Static-Aliases unter Last)
_ofc_src="${LIB_DIR}/nginx-open-file-cache.conf"
_ofc_dst="/etc/nginx/conf.d/teamportal-open-file-cache.conf"
if [ -f "$_ofc_src" ]; then
    cp "$_ofc_src" "$_ofc_dst"
    log_success "Open-file-Cache: ${_ofc_dst}"
else
    log_warning "nginx-open-file-cache.conf nicht gefunden unter ${LIB_DIR}"
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

# Document Server ohne /eurooffice-Prefix (/sdkjs, /fonts, /doc, Versions-Hash)
include /etc/nginx/snippets/teamportal-documentserver-extra.conf;

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
    proxy_set_header Connection \$connection_upgrade;
    
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
    proxy_set_header Connection \$connection_upgrade;
    
    add_header Access-Control-Allow-Origin * always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
    add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
    add_header Access-Control-Allow-Credentials true always;
    # Chrome: unload opt-in; Document Server app.js registriert unload-Handler
    add_header Permissions-Policy "unload=(self)" always;
    
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
    proxy_set_header Connection \$connection_upgrade;
    
    add_header Access-Control-Allow-Origin * always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
    add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
    add_header Access-Control-Allow-Credentials true always;
    # Chrome: unload opt-in; Document Server app.js registriert unload-Handler
    add_header Permissions-Policy "unload=(self)" always;
    
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
# Browser-Cache + immutable — kein Nginx proxy_cache für HTML (Session/CSRF).
location /static {
    alias ${INSTALL_DIR}/app/static;
    expires 30d;
    add_header Cache-Control "public, immutable";
    access_log off;
    include /etc/nginx/mime.types;
    types {
        text/javascript mjs;
    }
}

# Service Worker: nie long-cachen (App setzt zusätzlich no-cache)
location = /sw.js {
    proxy_pass http://teamportal_backend;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    expires off;
}

# Uploads (MUSS VOR / kommen!)
location /uploads {
    alias ${INSTALL_DIR}/uploads;
    expires 7d;
    access_log off;
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
    proxy_set_header Connection \$connection_upgrade;
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
    proxy_set_header Connection \$connection_upgrade;
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

# Nginx testen (if-Form, damit ERR-Trap bei nginx -t nicht den Installer killt)
_nginx_test_out=""
if ! _nginx_test_out=$(nginx -t 2>&1); then
    # Ubuntu 24.04: gzip on; in nginx.conf + conf.d → duplicate
    if echo "$_nginx_test_out" | grep -qi 'gzip.*duplicate'; then
        log_warning "Nginx: doppeltes gzip on; — entferne Duplikat in conf.d"
        sed -i '/^[[:space:]]*gzip on;/d' /etc/nginx/conf.d/teamportal-gzip.conf 2>/dev/null || true
        if ! _nginx_test_out=$(nginx -t 2>&1); then
            :
        else
            _nginx_test_out=""
        fi
    fi
else
    _nginx_test_out=""
fi
if [ -n "$_nginx_test_out" ]; then
    log_error "Nginx-Konfigurationstest fehlgeschlagen"
    local line
    while IFS= read -r line; do
        [ -n "$line" ] && log_error "$line"
    done <<< "$_nginx_test_out"
    return 1
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
