#!/bin/bash
# Firewall (UFW)

step_firewall() {
    ufw --force enable
    ufw allow 22/tcp

    if is_yes "$SETUP_WEBSERVER"; then
        if [ "$WEBSERVER_TYPE" = "nginx" ]; then
            ufw allow 'Nginx Full'
            log_info "NGINX Firewall-Regeln hinzugefügt"
        elif [ "$WEBSERVER_TYPE" = "apache" ]; then
            ufw allow 'Apache Full'
            log_info "Apache Firewall-Regeln hinzugefügt"
        else
            ufw allow 80/tcp
            ufw allow 443/tcp
        fi
    else
        log_info "Webserver manuell – nur SSH freigegeben"
        log_info "Firewall-Regeln für den Webserver bitte manuell setzen"
    fi

    log_success "Firewall konfiguriert"
    return 0
}
