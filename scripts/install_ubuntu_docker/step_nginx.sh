#!/bin/bash
# Nginx Reverse-Proxy → Docker-Container (Loopback-Ports)

step_nginx() {
    if ! is_yes "${SETUP_WEBSERVER:-n}" || [ "${WEBSERVER_TYPE}" != "nginx" ]; then
        return 2
    fi

    local app_port="${APP_HOST_PORT:-5000}"
    local oo_port="${EUROOFFICE_HOST_PORT:-8080}"
    local ex_port="${EXCALIDRAW_HOST_PORT:-8082}"
    local mt_port="${MIROTALK_HOST_PORT:-3010}"
    local native_lib="${NATIVE_LIB_DIR:-$(dirname "$LIB_DIR")/install_ubuntu}"

    log_info "=== Nginx (Proxy → Docker) ==="

    if ! grep -q "map \$http_upgrade \$connection_upgrade" /etc/nginx/nginx.conf; then
        cp /etc/nginx/nginx.conf "/etc/nginx/nginx.conf.backup.$(date +%Y%m%d_%H%M%S)"
        if grep -q "^\s*http\s*{" /etc/nginx/nginx.conf; then
            sed -i '/^\s*http\s*{/a\    map $http_upgrade $connection_upgrade {\n        default upgrade;\n        '\'''\'' close;\n    }' /etc/nginx/nginx.conf
        fi
    fi

    mkdir -p /etc/nginx/snippets
    if [ -f "${native_lib}/nginx-documentserver-extra.conf" ]; then
        # Ports in Snippet sind fest 8080 – für Docker-Installer anpassen
        sed "s/127\.0\.0\.1:8080/127.0.0.1:${oo_port}/g" \
            "${native_lib}/nginx-documentserver-extra.conf" \
            > /etc/nginx/snippets/teamportal-documentserver-extra.conf
    else
        echo "# documentserver-extra fehlt" > /etc/nginx/snippets/teamportal-documentserver-extra.conf
    fi

    if [ -f "${native_lib}/nginx-gzip.conf" ]; then
        cp "${native_lib}/nginx-gzip.conf" /etc/nginx/conf.d/teamportal-gzip.conf
        if grep -qE '^\s*gzip on;' /etc/nginx/nginx.conf; then
            sed -i '/^[[:space:]]*gzip on;/d' /etc/nginx/conf.d/teamportal-gzip.conf
        fi
    fi

    cat > /etc/nginx/sites-available/teamportal <<EOF
upstream teamportal_backend {
    ip_hash;
    server 127.0.0.1:${app_port};
}

server {
    listen 80;
    server_name ${DOMAIN};

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    client_max_body_size 100M;

$(if is_yes "${INSTALL_ONLYOFFICE:-n}"; then cat <<OO
    include /etc/nginx/snippets/teamportal-documentserver-extra.conf;

    location /cache {
        proxy_pass http://127.0.0.1:${oo_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 600;
    }

    location /onlyoffice {
        proxy_pass http://127.0.0.1:${oo_port}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 600;
        add_header Permissions-Policy "unload=(self)" always;
    }

    location /eurooffice {
        proxy_pass http://127.0.0.1:${oo_port}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 600;
        add_header Permissions-Policy "unload=(self)" always;
    }
OO
fi)

$(if is_yes "${INSTALL_EXCALIDRAW:-n}"; then cat <<EX
    location /excalidraw-room/ {
        proxy_pass http://127.0.0.1:${ex_port}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_read_timeout 600;
    }
EX
fi)

    location /socket.io/ {
        proxy_pass http://teamportal_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 60s;
    }

    location /webdav {
        proxy_pass http://teamportal_backend;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Authorization \$http_authorization;
        proxy_pass_header Authorization;
        proxy_request_buffering off;
        client_max_body_size 100M;
    }

    location / {
        proxy_pass http://teamportal_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

    local _meet_host _meet_scheme
    _meet_host=$(mirotalk_meet_hostname)
    _meet_scheme=$(mirotalk_public_scheme)
    if is_yes "${INSTALL_MIROTALK:-n}" && [ -n "$_meet_host" ]; then
        cat > /etc/nginx/sites-available/teamportal-meet <<EOF
server {
    listen 80;
    server_name ${_meet_host};
    client_max_body_size 50M;
    location / {
        proxy_pass http://127.0.0.1:${mt_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto ${_meet_scheme};
        proxy_read_timeout 86400s;
        proxy_buffering off;
    }
}
EOF
        ln -sf /etc/nginx/sites-available/teamportal-meet /etc/nginx/sites-enabled/teamportal-meet
        log_info "MiroTalk-vHost ${_meet_host} → 127.0.0.1:${mt_port}"
    fi

    ln -sf /etc/nginx/sites-available/teamportal /etc/nginx/sites-enabled/teamportal
    rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

    if ! nginx -t; then
        log_error "nginx -t fehlgeschlagen"
        return 1
    fi
    systemctl enable nginx >/dev/null 2>&1 || true
    systemctl reload nginx || systemctl restart nginx || return 1
    log_success "Nginx konfiguriert → App :${app_port}"
    return 0
}
