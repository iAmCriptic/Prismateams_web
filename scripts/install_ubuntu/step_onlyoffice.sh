#!/bin/bash
# OnlyOffice Document Server (Docker) + JWT-Verdrahtung

step_onlyoffice() {
    if ! is_yes "$INSTALL_ONLYOFFICE"; then
        print_manual_onlyoffice_hint
        return 2
    fi

    if [ -z "${ONLYOFFICE_SECRET:-}" ]; then
        ONLYOFFICE_SECRET=$(generate_secret)
    fi

    mkdir -p /var/lib/onlyoffice/DocumentServer/data
    mkdir -p /var/lib/onlyoffice/DocumentServer/logs

    log_info "Starte OnlyOffice Container (JWT aktiv)..."
    if docker ps -a --format '{{.Names}}' | grep -q "^onlyoffice-documentserver$"; then
        log_info "Entferne bestehenden OnlyOffice-Container..."
        docker stop onlyoffice-documentserver 2>/dev/null || true
        docker rm onlyoffice-documentserver 2>/dev/null || true
    fi

    if ! docker run -d -p 8080:80 --restart=always \
        --name onlyoffice-documentserver \
        -v /var/lib/onlyoffice/DocumentServer/data:/var/www/onlyoffice/Data \
        -v /var/lib/onlyoffice/DocumentServer/logs:/var/log/onlyoffice \
        -e JWT_SECRET="${ONLYOFFICE_SECRET}" \
        -e JWT_ENABLED=true \
        -e JWT_HEADER=Authorization \
        onlyoffice/documentserver:latest; then
        log_error "OnlyOffice Container konnte nicht gestartet werden"
        return 1
    fi

    log_info "Warte auf OnlyOffice (bis 90s)..."
    OO_READY=0
    for i in {1..90}; do
        if curl -s http://127.0.0.1:8080/welcome/ > /dev/null 2>&1; then
            OO_READY=1
            log_success "OnlyOffice ist bereit"
            break
        fi
        sleep 1
    done

    if [ $OO_READY -eq 0 ]; then
        log_warning "OnlyOffice antwortet noch nicht – JWT/Secret trotzdem gesetzt, Service ggf. später prüfen"
    fi

    log_info "OnlyOffice JWT_SECRET = ONLYOFFICE_SECRET_KEY (für .env)"
    log_success "OnlyOffice installiert"
    return 0
}
