#!/bin/bash
# Let's Encrypt hinter Host-Proxy

step_ssl() {
    if ! is_yes "${SETUP_WEBSERVER:-n}"; then
        return 2
    fi
    if ! is_yes "${SETUP_SSL:-n}"; then
        return 2
    fi

    log_info "=== SSL (Let's Encrypt) ==="

    if ! command -v certbot >/dev/null 2>&1; then
        if [ "${WEBSERVER_TYPE}" = "nginx" ]; then
            apt_install certbot python3-certbot-nginx || return 1
        else
            apt_install certbot python3-certbot-apache || apt_install certbot || return 1
        fi
    fi

    if [ "${WEBSERVER_TYPE}" = "nginx" ]; then
        if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$LETSENCRYPT_EMAIL" --redirect; then
            log_success "SSL für ${DOMAIN}"
            systemctl reload nginx
        else
            log_warning "SSL fehlgeschlagen – manuell: certbot --nginx -d $DOMAIN"
            return 1
        fi
        local _meet_host
        _meet_host=$(mirotalk_meet_hostname)
        if is_yes "${INSTALL_MIROTALK:-n}" && [ -n "$_meet_host" ]; then
            certbot --nginx -d "$_meet_host" --non-interactive --agree-tos --email "$LETSENCRYPT_EMAIL" --redirect \
                && systemctl reload nginx \
                || log_warning "SSL für ${_meet_host} fehlgeschlagen (DNS prüfen)"
        fi
    else
        if certbot --apache -d "$DOMAIN" --non-interactive --agree-tos --email "$LETSENCRYPT_EMAIL" --redirect; then
            log_success "SSL für ${DOMAIN}"
            systemctl reload apache2
        else
            log_warning "SSL fehlgeschlagen – manuell: certbot --apache -d $DOMAIN"
            return 1
        fi
        local _meet_host
        _meet_host=$(mirotalk_meet_hostname)
        if is_yes "${INSTALL_MIROTALK:-n}" && [ -n "$_meet_host" ]; then
            certbot --apache -d "$_meet_host" --non-interactive --agree-tos --email "$LETSENCRYPT_EMAIL" --redirect \
                && systemctl reload apache2 \
                || log_warning "SSL für ${_meet_host} fehlgeschlagen"
        fi
    fi

    # Secure-Cookies nach erfolgreichem SSL
    if [ -f "${INSTALL_DIR}/.env" ]; then
        set_env_var "SESSION_COOKIE_SECURE" "True" "${INSTALL_DIR}/.env"
        cd "$INSTALL_DIR" && docker_compose $(compose_profile_args) up -d app >/dev/null 2>&1 || true
    fi

    return 0
}
