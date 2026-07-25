#!/bin/bash
# Let's Encrypt SSL

step_ssl() {
    if ! is_yes "$SETUP_WEBSERVER"; then
        log_info "SSL-Setup übersprungen (kein automatischer Webserver)"
        return 2
    fi
    if ! is_yes "$SETUP_SSL"; then
        return 2
    fi

    log_info "=== SSL Setup mit Let's Encrypt ==="

    if ! command -v certbot &> /dev/null; then
        log_warning "Certbot nicht gefunden. Installiere..."
        if [ "$WEBSERVER_TYPE" = "nginx" ]; then
            apt-get install -y -qq certbot python3-certbot-nginx || {
                log_warning "Certbot Installation fehlgeschlagen"
                return 1
            }
        elif [ "$WEBSERVER_TYPE" = "apache" ]; then
            if apt-cache show python3-certbot-apache &>/dev/null; then
                apt-get install -y -qq certbot python3-certbot-apache || {
                    log_warning "Certbot Installation fehlgeschlagen"
                    return 1
                }
            else
                apt-get install -y -qq certbot || {
                    log_warning "Certbot Installation fehlgeschlagen"
                    return 1
                }
            fi
        fi
    fi

    log_info "Prüfe Domain-Erreichbarkeit..."
    if ! curl -s -o /dev/null -w "%{http_code}" "http://${DOMAIN}" | grep -q "200\|301\|302\|403"; then
        log_warning "Domain $DOMAIN scheint nicht erreichbar zu sein."
        if is_yes "$NON_INTERACTIVE"; then
            log_warning "Non-interactive: SSL trotzdem versuchen"
        else
            read -r -p "Trotzdem fortfahren? (j/n): " -n 1 REPLY
            echo
            if [[ ! $REPLY =~ ^[JjYy]$ ]]; then
                log_info "SSL-Setup übersprungen"
                return 2
            fi
        fi
    fi

    if [ "$WEBSERVER_TYPE" = "nginx" ]; then
        if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$LETSENCRYPT_EMAIL" --redirect; then
            log_success "SSL konfiguriert"
            systemctl reload nginx
        else
            log_warning "SSL-Setup fehlgeschlagen. Manuell: certbot --nginx -d $DOMAIN"
            return 1
        fi
    elif [ "$WEBSERVER_TYPE" = "apache" ]; then
        if certbot --apache -d "$DOMAIN" --non-interactive --agree-tos --email "$LETSENCRYPT_EMAIL" --redirect; then
            log_success "SSL konfiguriert"
            systemctl reload apache2
        else
            log_warning "SSL-Setup fehlgeschlagen. Manuell: certbot --apache -d $DOMAIN"
            return 1
        fi
    fi
    return 0
}
