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

    log_info "Installiere Python-Dependencies..."
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet || {
        log_error "pip install requirements.txt fehlgeschlagen"
        return 1
    }

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
