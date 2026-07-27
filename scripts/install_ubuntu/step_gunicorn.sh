#!/bin/bash
# Gunicorn systemd-Service inkl. Worker-Logik

init_database_oneshot() {
    log_info "Datenbank-Initialisierung (Schema + Migrationen)..."
    cd "$INSTALL_DIR" || return 1
    # shellcheck disable=SC1091
    source venv/bin/activate

    local init_script="${INSTALL_DIR}/scripts/init_database.py"
    if [ ! -f "$init_script" ]; then
        log_error "init_database.py nicht gefunden: $init_script"
        return 1
    fi

    # Immer production + Force-Schema, damit DEBUG/Reloader-Logik nicht skippt
    local run_env=(
        "PATH=${INSTALL_DIR}/venv/bin:$PATH"
        "FLASK_ENV=production"
        "PRISMATEAMS_FORCE_SCHEMA_INIT=1"
        "PRISMATEAMS_SKIP_BACKGROUND_JOBS=1"
    )

    if sudo -u www-data env "${run_env[@]}" \
        "${INSTALL_DIR}/venv/bin/python" "$init_script"; then
        log_success "Datenbank initialisiert (www-data)"
        return 0
    fi

    log_warning "Init als www-data fehlgeschlagen – versuche als root..."
    if env "${run_env[@]}" "${INSTALL_DIR}/venv/bin/python" "$init_script"; then
        log_success "Datenbank initialisiert (root)"
        # Rechte für www-data sicherstellen falls SQLite-Fallbacks o.ä.
        chown -R www-data:www-data "${INSTALL_DIR}/instance" 2>/dev/null || true
        return 0
    fi

    log_error "Datenbank-Initialisierung fehlgeschlagen"
    return 1
}

step_database() {
    # Eigenständiger Schritt: Schema auch ohne Gunicorn / vor Service-Start
    if [ ! -d "${INSTALL_DIR}/venv" ] || [ ! -f "${INSTALL_DIR}/.env" ]; then
        log_error "venv oder .env fehlt – Database-Init nicht möglich"
        return 1
    fi
    init_database_oneshot
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

    # Schema nochmals sicherstellen (idempotent), falls step_database übersprungen wurde
    init_database_oneshot || return 1

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
Environment="PRISMATEAMS_SKIP_BACKGROUND_JOBS=0"
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
