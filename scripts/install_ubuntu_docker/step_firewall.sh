#!/bin/bash
# UFW

step_firewall() {
    ufw --force enable
    ufw allow 22/tcp

    if is_yes "${SETUP_WEBSERVER:-n}"; then
        if [ "${WEBSERVER_TYPE}" = "nginx" ]; then
            ufw allow 'Nginx Full'
        elif [ "${WEBSERVER_TYPE}" = "apache" ]; then
            ufw allow 'Apache Full'
        else
            ufw allow 80/tcp
            ufw allow 443/tcp
        fi
    else
        ufw allow "${APP_HOST_PORT:-5000}/tcp"
        log_info "Kein Webserver – Port ${APP_HOST_PORT:-5000} freigegeben (nur wenn öffentlich nötig)"
    fi

    if is_yes "${INSTALL_MIROTALK:-n}"; then
        ufw allow "${MIROTALK_UDP_MIN:-40000}:${MIROTALK_UDP_MAX:-40100}/udp"
        ufw allow "${MIROTALK_UDP_MIN:-40000}:${MIROTALK_UDP_MAX:-40100}/tcp"
        if ! domain_is_hostname "${DOMAIN:-}"; then
            ufw allow "${MIROTALK_HOST_PORT:-3010}/tcp"
        fi
        log_info "MiroTalk-Medienports freigegeben"
    fi

    log_success "Firewall konfiguriert"
    return 0
}
