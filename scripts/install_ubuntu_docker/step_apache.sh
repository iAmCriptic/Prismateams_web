#!/bin/bash
# Apache Reverse-Proxy → Docker-Container

step_apache() {
    if ! is_yes "${SETUP_WEBSERVER:-n}" || [ "${WEBSERVER_TYPE}" != "apache" ]; then
        return 2
    fi

    local app_port="${APP_HOST_PORT:-5000}"
    local oo_port="${EUROOFFICE_HOST_PORT:-8080}"
    local ex_port="${EXCALIDRAW_HOST_PORT:-8082}"
    local mt_port="${MIROTALK_HOST_PORT:-3010}"

    log_info "=== Apache (Proxy → Docker) ==="

    a2enmod proxy proxy_http proxy_wstunnel headers rewrite ssl >/dev/null 2>&1 || true

    cat > /etc/apache2/sites-available/teamportal.conf <<EOF
<VirtualHost *:80>
    ServerName ${DOMAIN}
    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "expr=%{REQUEST_SCHEME}"
    LimitRequestBody 104857600

$(if is_yes "${INSTALL_ONLYOFFICE:-n}"; then cat <<OO
    ProxyPass /eurooffice/ http://127.0.0.1:${oo_port}/
    ProxyPassReverse /eurooffice/ http://127.0.0.1:${oo_port}/
    ProxyPass /onlyoffice/ http://127.0.0.1:${oo_port}/
    ProxyPassReverse /onlyoffice/ http://127.0.0.1:${oo_port}/
    ProxyPass /cache http://127.0.0.1:${oo_port}/cache
    ProxyPassReverse /cache http://127.0.0.1:${oo_port}/cache
OO
fi)

$(if is_yes "${INSTALL_EXCALIDRAW:-n}"; then cat <<EX
    ProxyPass /excalidraw-room/ http://127.0.0.1:${ex_port}/
    ProxyPassReverse /excalidraw-room/ http://127.0.0.1:${ex_port}/
EX
fi)

    ProxyPass /socket.io/ ws://127.0.0.1:${app_port}/socket.io/
    ProxyPassReverse /socket.io/ ws://127.0.0.1:${app_port}/socket.io/
    ProxyPass / http://127.0.0.1:${app_port}/
    ProxyPassReverse / http://127.0.0.1:${app_port}/
</VirtualHost>
EOF

    local _meet_host
    _meet_host=$(mirotalk_meet_hostname)
    if is_yes "${INSTALL_MIROTALK:-n}" && [ -n "$_meet_host" ]; then
        cat > /etc/apache2/sites-available/teamportal-meet.conf <<EOF
<VirtualHost *:80>
    ServerName ${_meet_host}
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:${mt_port}/
    ProxyPassReverse / http://127.0.0.1:${mt_port}/
</VirtualHost>
EOF
        a2ensite teamportal-meet >/dev/null 2>&1 || true
    fi

    a2dissite 000-default >/dev/null 2>&1 || true
    a2ensite teamportal >/dev/null 2>&1 || true
    apache2ctl configtest || return 1
    systemctl enable apache2 >/dev/null 2>&1 || true
    systemctl reload apache2 || systemctl restart apache2 || return 1
    log_success "Apache konfiguriert → App :${app_port}"
    return 0
}
