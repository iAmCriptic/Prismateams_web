#!/bin/bash
# System-Pakete

step_system() {
    log_info "Aktualisiere Paketlisten..."
    export DEBIAN_FRONTEND=noninteractive
    if ! apt-get update -qq; then
        log_error "Paketlisten-Update fehlgeschlagen"
        return 1
    fi

    log_info "Installiere Basis-Pakete..."
    BASE_PACKAGES="curl wget git build-essential software-properties-common \
        apt-transport-https ca-certificates gnupg lsb-release \
        python3 python3-pip python3-venv python3-dev \
        libmysqlclient-dev pkg-config ufw supervisor openssl"

    if is_yes "$SETUP_MYSQL"; then
        BASE_PACKAGES="$BASE_PACKAGES mysql-server mysql-client"
    fi
    if is_yes "$SETUP_REDIS"; then
        BASE_PACKAGES="$BASE_PACKAGES redis-server"
    fi
    if is_yes "$SETUP_WEBSERVER" || is_yes "$SETUP_SSL"; then
        BASE_PACKAGES="$BASE_PACKAGES certbot"
    fi

    if is_yes "$SETUP_WEBSERVER"; then
        if [ "$WEBSERVER_TYPE" = "nginx" ]; then
            BASE_PACKAGES="$BASE_PACKAGES nginx python3-certbot-nginx"
            log_info "Installiere NGINX und Certbot..."
        elif [ "$WEBSERVER_TYPE" = "apache" ]; then
            BASE_PACKAGES="$BASE_PACKAGES apache2"
            if apt-cache show python3-certbot-apache &>/dev/null; then
                BASE_PACKAGES="$BASE_PACKAGES python3-certbot-apache"
            else
                log_warning "python3-certbot-apache nicht verfügbar"
            fi
            log_info "Installiere Apache2..."
        fi
    else
        log_info "Webserver-Pakete übersprungen (manuell)"
    fi

    # shellcheck disable=SC2086
    if ! apt-get install -y -qq $BASE_PACKAGES; then
        log_error "Paket-Installation fehlgeschlagen"
        return 1
    fi

    if ! command -v python3 &> /dev/null; then
        log_error "Python3 wurde nicht korrekt installiert"
        return 1
    fi

    if is_yes "$SETUP_WEBSERVER"; then
        if [ "$WEBSERVER_TYPE" = "nginx" ] && ! command -v nginx &> /dev/null; then
            log_error "Nginx wurde nicht korrekt installiert"
            return 1
        fi
        if [ "$WEBSERVER_TYPE" = "apache" ] && ! command -v apache2 &> /dev/null; then
            log_error "Apache2 wurde nicht korrekt installiert"
            return 1
        fi
    fi

    python3 -m pip install --upgrade pip --quiet || log_warning "pip Update fehlgeschlagen, fahre fort..."
    log_success "System-Vorbereitung abgeschlossen"
    return 0
}
