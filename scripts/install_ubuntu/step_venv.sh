#!/bin/bash
# Python venv + Dependencies + Upload-Verzeichnisse

step_venv() {
    cd "$INSTALL_DIR" || return 1

    if [ -d "venv" ]; then
        log_warning "venv existiert bereits. Überspringe Erstellung."
    else
        log_info "Erstelle Virtual Environment..."
        python3 -m venv venv || return 1
    fi

    # shellcheck disable=SC1091
    source venv/bin/activate
    if [ ! -x venv/bin/pip ] && [ ! -x venv/bin/pip3 ]; then
        log_info "pip fehlt im venv – ensurepip..."
        python3 -m ensurepip --upgrade || {
            log_error "ensurepip fehlgeschlagen (Paket python3-venv / python3-pip prüfen)"
            return 1
        }
        # shellcheck disable=SC1091
        source venv/bin/activate
    fi

    log_info "Installiere Python-Dependencies ($(python3 --version 2>/dev/null))..."
    pip install --upgrade pip wheel setuptools || log_warning "pip/wheel Upgrade fehlgeschlagen, fahre fort..."
    # --prefer-binary: auf 26.04/Python 3.14 zuerst Wheels, kein Source-Build ohne rustc
    if ! pip install --prefer-binary -r requirements.txt; then
        log_error "pip install requirements.txt fehlgeschlagen"
        log_error "Python: $(python3 --version 2>/dev/null || true) auf Ubuntu ${UBUNTU_VERSION_ID:-?}"
        return 1
    fi

    log_success "Virtual Environment eingerichtet"
    return 0
}

step_uploads() {
    cd "$INSTALL_DIR" || return 1

    mkdir -p instance
    mkdir -p uploads/{files,chat,manuals,profile_pics,inventory/product_images,inventory/product_documents,system,attachments,booking_forms,bookings,email_attachments,veranstaltungen,wiki,excalidraw,excalidraw/thumbs}
    mkdir -p uploads/chat/avatars

    chown -R www-data:www-data instance uploads
    chmod -R 755 instance
    chmod -R 775 uploads

    log_success "Upload-Verzeichnisse erstellt"
    return 0
}

step_permissions() {
    chown -R www-data:www-data "$INSTALL_DIR"
    chmod -R 755 "$INSTALL_DIR"
    if [ -d "$INSTALL_DIR/uploads" ]; then
        chmod -R 775 "$INSTALL_DIR/uploads"
    fi
    if [ -f "$INSTALL_DIR/.env" ]; then
        chmod 600 "$INSTALL_DIR/.env"
        chown www-data:www-data "$INSTALL_DIR/.env"
    fi
    log_success "Berechtigungen gesetzt"
    return 0
}
