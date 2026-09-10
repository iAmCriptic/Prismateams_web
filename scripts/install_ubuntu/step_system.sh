#!/bin/bash
# System-Pakete

step_system() {
    log_info "Aktualisiere Paketlisten..."
    export DEBIAN_FRONTEND=noninteractive
    if ! apt_update -qq; then
        log_error "Paketlisten-Update fehlgeschlagen"
        return 1
    fi

    log_info "Aktiviere universe/multiverse (MySQL 8.4 / Schriften)..."
    # Kein Upgrade von software-properties-common erzwingen – das wurde auf 26.04-VMs OOM-Killed
    if ! command -v add-apt-repository >/dev/null 2>&1; then
        if ! apt_install --no-upgrade software-properties-common ca-certificates gnupg; then
            log_warning "software-properties-common nicht installierbar – versuche Sources direkt"
        fi
    fi
    enable_ubuntu_components
    if ! apt_update -qq; then
        log_error "Paketlisten-Update nach universe/multiverse fehlgeschlagen"
        return 1
    fi

    log_info "Installiere Basis-Pakete..."
    BASE_PACKAGES="curl wget git build-essential \
        apt-transport-https ca-certificates gnupg lsb-release \
        python3 python3-pip python3-venv python3-dev \
        libssl-dev libffi-dev pkg-config ufw supervisor openssl iptables"

    # PyMySQL braucht kein libmysqlclient – Paket trotzdem, mit Fallback (Name variiert)
    if apt-cache show libmysqlclient-dev &>/dev/null; then
        BASE_PACKAGES="$BASE_PACKAGES libmysqlclient-dev"
    elif apt-cache show default-libmysqlclient-dev &>/dev/null; then
        BASE_PACKAGES="$BASE_PACKAGES default-libmysqlclient-dev"
    fi

    if is_yes "$SETUP_MYSQL"; then
        if apt-cache show mysql-server &>/dev/null; then
            BASE_PACKAGES="$BASE_PACKAGES mysql-server mysql-client"
        elif apt-cache show default-mysql-server &>/dev/null; then
            log_warning "mysql-server nicht im Index – fallback default-mysql-server (oft MariaDB)"
            BASE_PACKAGES="$BASE_PACKAGES default-mysql-server default-mysql-client"
        else
            log_error "Weder mysql-server noch default-mysql-server verfügbar (universe aktiv?)"
            return 1
        fi
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
    if ! apt_install $BASE_PACKAGES; then
        log_error "Paket-Installation fehlgeschlagen"
        return 1
    fi

    if ! command -v python3 &> /dev/null; then
        log_error "Python3 wurde nicht korrekt installiert"
        return 1
    fi

    local py_ver
    py_ver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "?")
    log_info "Python ${py_ver} ($(python3 --version 2>/dev/null || true))"
    case "$py_ver" in
        3.1[0-9]|3.9)
            ;;
        *)
            log_warning "Unerwartete Python-Version ${py_ver} – pip-Wheels prüfen"
            ;;
    esac

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

    # System-pip nicht anfassen (PEP 668 / externally-managed auf 24.04+ und 26.04)
    log_success "System-Vorbereitung abgeschlossen (Ubuntu ${UBUNTU_VERSION_ID:-?} / Python ${py_ver})"
    return 0
}
