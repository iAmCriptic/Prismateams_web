#!/bin/bash
# Minimale Host-Pakete (kein MySQL/Redis/Python-venv für die App)

step_system() {
    log_info "Installiere Basis-Pakete..."
    apt_update -qq || return 1
    apt_install \
        ca-certificates \
        curl \
        git \
        gnupg \
        lsb-release \
        openssl \
        ufw \
        || return 1

    if is_yes "${SETUP_WEBSERVER:-n}"; then
        if [ "${WEBSERVER_TYPE}" = "nginx" ]; then
            apt_install nginx || return 1
        elif [ "${WEBSERVER_TYPE}" = "apache" ]; then
            apt_install apache2 || return 1
        fi
    fi

    log_success "System-Pakete installiert"
    return 0
}
