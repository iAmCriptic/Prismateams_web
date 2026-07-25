#!/bin/bash
# Gunicorn systemd-Service inkl. Worker-Logik

init_database_oneshot() {
    log_info "One-Shot Datenbank-Initialisierung (für Multi-Worker)..."
    cd "$INSTALL_DIR" || return 1
    # shellcheck disable=SC1091
    source venv/bin/activate
    if ! sudo -u www-data env PATH="${INSTALL_DIR}/venv/bin:$PATH" \
        FLASK_ENV=production \
        "${INSTALL_DIR}/venv/bin/python" -c "
from app import create_app
app = create_app()
print('DB init via create_app OK')
"; then
        log_warning "One-Shot-Init als www-data fehlgeschlagen – versuche als root..."
        if ! FLASK_ENV=production "${INSTALL_DIR}/venv/bin/python" -c "
from app import create_app
app = create_app()
print('DB init via create_app OK')
"; then
            log_error "Datenbank-One-Shot-Init fehlgeschlagen"
            return 1
        fi
    fi
    log_success "Datenbank initialisiert"
    return 0
}

step_gunicorn() {
    if ! is_yes "$SETUP_GUNICORN"; then
        print_manual_gunicorn_hint
        return 2
    fi

    GUNICORN_WORKERS="${GUNICORN_WORKERS:-1}"

    if [ ! -f "${INSTALL_DIR}/venv/bin/gunicorn" ]; then
        log_info "Installiere Gunicorn..."
        cd "$INSTALL_DIR" || return 1
        # shellcheck disable=SC1091
        source venv/bin/activate
        pip install gunicorn --quiet || { log_error "Gunicorn Installation fehlgeschlagen"; return 1; }
    fi

    if [ "$GUNICORN_WORKERS" -gt 1 ]; then
        if ! is_yes "$SETUP_REDIS"; then
            log_warning "Worker > 1 ohne Redis – empfohlen: Redis aktivieren"
        fi
        init_database_oneshot || return 1
    fi

    cat > /etc/systemd/system/teamportal.service <<EOF
[Unit]
Description=Team Portal Gunicorn Application Server
After=network.target mysql.service redis-server.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/venv/bin"
Environment="FLASK_ENV=production"
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn \\
    --workers ${GUNICORN_WORKERS} \\
    --bind 127.0.0.1:${GUNICORN_PORT} \\
    --timeout 600 \\
    --access-logfile - \\
    --error-logfile - \\
    wsgi:app

Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload || { log_error "systemd daemon-reload fehlgeschlagen"; return 1; }
    systemctl enable teamportal || { log_error "Service-Aktivierung fehlgeschlagen"; return 1; }
    sleep 2
    systemctl start teamportal || {
        log_error "Service-Start fehlgeschlagen. Logs: journalctl -u teamportal -n 50"
        log_warning "Service aktiviert, bitte manuell prüfen"
    }

    sleep 3
    if systemctl is-active --quiet teamportal; then
        log_success "Gunicorn Service läuft (${GUNICORN_WORKERS} Worker, Port ${GUNICORN_PORT})"
    else
        log_warning "Service-Status unklar: systemctl status teamportal"
    fi
    return 0
}
