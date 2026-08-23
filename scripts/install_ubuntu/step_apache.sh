#!/bin/bash
# apache reverse proxy

step_apache() {
    if ! is_yes "$SETUP_WEBSERVER" || [ "$WEBSERVER_TYPE" != "apache" ]; then
        return 2
    fi

log_info "=== Apache Konfiguration ==="

# Apache-Module aktivieren
log_info "Aktiviere erforderliche Apache-Module..."
a2enmod proxy proxy_http proxy_wstunnel headers rewrite ssl 2>/dev/null || true

# Apache Virtual Host-Konfiguration erstellen
log_info "Erstelle Apache Virtual Host-Konfiguration..."
cat > /etc/apache2/sites-available/teamportal.conf <<EOF
<VirtualHost *:80>
ServerName ${DOMAIN}

# Security headers
Header always set X-Frame-Options "SAMEORIGIN"
Header always set X-Content-Type-Options "nosniff"
Header always set X-XSS-Protection "1; mode=block"

# File upload limit
LimitRequestBody 104857600

# Proxy-Einstellungen
ProxyPreserveHost On
ProxyRequests Off

# OnlyOffice Cache (MUSS VOR /onlyoffice kommen!)
# OnlyOffice benötigt diesen Pfad für interne Cache-Dateien
# Entfernen Sie diesen Block, wenn OnlyOffice NICHT installiert ist
<Location /cache>
    ProxyPass http://127.0.0.1:8080/cache
    ProxyPassReverse http://127.0.0.1:8080/cache
    ProxyPassReverse http://127.0.0.1:8080/cache
    
    ProxyPreserveHost On
    RequestHeader set Host "\${HTTP_HOST}"
    RequestHeader set X-Real-IP "\${REMOTE_ADDR}"
    RequestHeader set X-Forwarded-For "\${HTTP_X_FORWARDED_FOR}"
    RequestHeader set X-Forwarded-Proto "\${REQUEST_SCHEME}"
</Location>

# OnlyOffice Document Server (OPTIONAL - nur wenn installiert)
# Entfernen Sie diesen Block, wenn OnlyOffice NICHT installiert ist
<Location /onlyoffice>
    ProxyPass http://127.0.0.1:8080/
    ProxyPassReverse http://127.0.0.1:8080/
    
    ProxyPreserveHost On
    RequestHeader set Host "\${HTTP_HOST}"
    RequestHeader set X-Real-IP "\${REMOTE_ADDR}"
    RequestHeader set X-Forwarded-For "\${HTTP_X_FORWARDED_FOR}"
    RequestHeader set X-Forwarded-Proto "\${REQUEST_SCHEME}"
    
    # CORS headers for OnlyOffice
    Header always set Access-Control-Allow-Origin "*"
    Header always set Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE"
    Header always set Access-Control-Allow-Headers "Authorization, Content-Type"
    Header always set Access-Control-Allow-Credentials "true"
</Location>

# Excalidraw Room (OPTIONAL - nur wenn installiert)
<Location /excalidraw-room>
    ProxyPass ws://127.0.0.1:8082/
    ProxyPassReverse http://127.0.0.1:8082/
    ProxyPreserveHost On
    RequestHeader set Host "\${HTTP_HOST}"
    RequestHeader set X-Real-IP "\${REMOTE_ADDR}"
    RequestHeader set X-Forwarded-For "\${HTTP_X_FORWARDED_FOR}"
    RequestHeader set X-Forwarded-Proto "\${REQUEST_SCHEME}"
</Location>

# Statische Dateien (MUSS VOR / kommen!)
Alias /static ${INSTALL_DIR}/app/static
<Directory "${INSTALL_DIR}/app/static">
    Require all granted
    ExpiresActive On
    ExpiresDefault "access plus 30 days"
</Directory>

# Uploads (MUSS VOR / kommen!)
Alias /uploads ${INSTALL_DIR}/uploads
<Directory "${INSTALL_DIR}/uploads">
    Require all granted
    ExpiresActive On
    ExpiresDefault "access plus 7 days"
</Directory>

# Socket.IO spezifische Konfiguration (MUSS VOR / kommen!)
# Socket.IO verwendet /socket.io/ für Polling und WebSocket-Verbindungen
<Location /socket.io/>
    ProxyPass http://127.0.0.1:${GUNICORN_PORT}/socket.io/
    ProxyPassReverse http://127.0.0.1:${GUNICORN_PORT}/socket.io/
    ProxyPassReverse ws://127.0.0.1:${GUNICORN_PORT}/socket.io/
    
    ProxyPreserveHost On
    RequestHeader set Host "\${HTTP_HOST}"
    RequestHeader set X-Real-IP "\${REMOTE_ADDR}"
    RequestHeader set X-Forwarded-For "\${HTTP_X_FORWARDED_FOR}"
    RequestHeader set X-Forwarded-Proto "\${REQUEST_SCHEME}"
    
    # CORS für Socket.IO (falls nötig)
    Header always set Access-Control-Allow-Origin "*"
    Header always set Access-Control-Allow-Methods "GET, POST, OPTIONS"
    Header always set Access-Control-Allow-Headers "Content-Type"
    Header always set Access-Control-Allow-Credentials "true"
</Location>

# Hauptanwendung (MUSS ZULETZT kommen!)
<Location />
    ProxyPass http://127.0.0.1:${GUNICORN_PORT}/
    ProxyPassReverse http://127.0.0.1:${GUNICORN_PORT}/
    ProxyPassReverse ws://127.0.0.1:${GUNICORN_PORT}/
    
    ProxyPreserveHost On
    RequestHeader set Host "\${HTTP_HOST}"
    RequestHeader set X-Real-IP "\${REMOTE_ADDR}"
    RequestHeader set X-Forwarded-For "\${HTTP_X_FORWARDED_FOR}"
    RequestHeader set X-Forwarded-Proto "\${REQUEST_SCHEME}"
</Location>

# Logging
ErrorLog \${APACHE_LOG_DIR}/teamportal_error.log
CustomLog \${APACHE_LOG_DIR}/teamportal_access.log combined
</VirtualHost>
EOF

# Site aktivieren
log_info "Aktiviere Apache-Site..."
a2ensite teamportal.conf || { log_error "Site-Aktivierung fehlgeschlagen"; return 1; }

# Standard-Site deaktivieren
a2dissite 000-default.conf 2>/dev/null || true

# Apache-Konfiguration testen
log_info "Teste Apache-Konfiguration..."
if ! apache2ctl configtest; then
    { log_error "Apache-Konfigurationstest fehlgeschlagen"; return 1; }
fi

# Apache neu starten
log_info "Starte Apache..."
systemctl enable apache2 || { log_error "Apache-Aktivierung fehlgeschlagen"; return 1; }
systemctl restart apache2 || { log_error "Apache-Neustart fehlgeschlagen"; return 1; }

# Prüfe Status
sleep 2
if systemctl is-active --quiet apache2; then
    log_success "Apache läuft"
else
    { log_error "Apache läuft nicht. Prüfe Logs: journalctl -u apache2 -n 50"; return 1; }
fi

log_success "Apache konfiguriert"
    return 0
}
