#!/bin/bash
# Interaktive Abfragen – Docker-Installer

gather_information() {
    log_info "=== Konfigurationsabfrage (Docker) ==="

    prompt_or_default INSTALL_DIR "Installationspfad" "/var/www/teamportal"
    prompt_or_default REPO_URL "Git-Repository-URL" "$DEFAULT_REPO_URL"
    if [ -z "$GIT_BRANCH" ] && ! is_yes "$NON_INTERACTIVE"; then
        read -r -p "Git-Branch (leer = Default-Branch): " GIT_BRANCH
    elif [ -n "$GIT_BRANCH" ]; then
        log_info "Git-Branch (via Option): $GIT_BRANCH"
    fi

    prompt_or_default APP_HOST_PORT "App Host-Port (Loopback → Container)" "5000"
    prompt_or_default TIMEZONE "Zeitzone" "Europe/Berlin"
    prompt_or_default VAPID_CLAIM_EMAIL "VAPID Claim E-Mail" "admin@example.com"

    log_info ""
    log_info "=== Optionale Sidecars (Compose-Profiles) ==="
    prompt_yes_no INSTALL_ONLYOFFICE "Euro-Office Document Server installieren? (≥4 GB RAM)" "n"
    prompt_yes_no INSTALL_EXCALIDRAW "Excalidraw-Room installieren?" "n"
    prompt_yes_no INSTALL_MIROTALK "MiroTalk SFU (Meetings) installieren?" "n"

    if is_yes "$INSTALL_ONLYOFFICE"; then
        local mem_kb mem_gb
        mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
        mem_gb=$((mem_kb / 1024 / 1024))
        if [ "$mem_gb" -gt 0 ] && [ "$mem_gb" -lt 4 ]; then
            log_warning "Nur ca. ${mem_gb} GB RAM – Euro-Office kann OOM verursachen"
        fi
    fi

    log_info ""
    log_info "=== Webserver (Host-Reverse-Proxy) ==="
    prompt_yes_no SETUP_WEBSERVER "Nginx/Apache als Proxy vor den Containern einrichten?" "j"
    if is_yes "$SETUP_WEBSERVER"; then
        prompt_or_default WEBSERVER_TYPE "Webserver (nginx/apache)" "nginx"
        if [[ "$WEBSERVER_TYPE" != "nginx" && "$WEBSERVER_TYPE" != "apache" ]]; then
            log_warning "Ungültig – verwende nginx"
            WEBSERVER_TYPE="nginx"
        fi
        prompt_or_default DOMAIN "Domain oder IP-Adresse" ""
        if [ -z "$DOMAIN" ]; then
            error_exit "Domain/IP ist für den Webserver erforderlich"
        fi
        prompt_yes_no SETUP_SSL "SSL mit Let's Encrypt einrichten?" "n"
        if is_yes "$SETUP_SSL"; then
            prompt_or_default LETSENCRYPT_EMAIL "E-Mail für Let's Encrypt" "webmaster@$DOMAIN"
        fi
    else
        WEBSERVER_TYPE=""
        SETUP_SSL="n"
        if [ -z "$DOMAIN" ] && ! is_yes "$NON_INTERACTIVE"; then
            read -r -p "Domain oder IP (optional, für URLs/Doku): " DOMAIN
        fi
    fi

    log_info ""
    log_info "Zusammenfassung vor Start:"
    log_info "  Install-Dir: $INSTALL_DIR"
    log_info "  App-Port:    127.0.0.1:${APP_HOST_PORT}"
    log_info "  OnlyOffice:  $INSTALL_ONLYOFFICE | Excalidraw: $INSTALL_EXCALIDRAW | MiroTalk: $INSTALL_MIROTALK"
    log_info "  Webserver:   ${SETUP_WEBSERVER:-n} (${WEBSERVER_TYPE:-none}) Domain=${DOMAIN:-}"
    if ! is_yes "$NON_INTERACTIVE"; then
        read -r -p "Fortfahren? (j/n): " -n 1 REPLY
        echo
        if [[ ! $REPLY =~ ^[JjYy]$ ]]; then
            error_exit "Abgebrochen"
        fi
    fi
}
