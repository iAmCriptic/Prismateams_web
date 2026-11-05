#!/bin/bash
# Abschlussbericht Docker-Installer

print_summary() {
    echo
    echo "=========================================="
    if [ "${INSTALL_ABORTED:-0}" = "1" ]; then
        echo "Docker-Installation abgebrochen / mit Fehlern"
    else
        echo "Docker-Installation abgeschlossen"
    fi
    echo "=========================================="
    echo

    local i
    for i in "${!STEP_IDS[@]}"; do
        printf "  %-28s %s" "${STEP_TITLES[$i]}" "$(status_label "${STEP_STATUSES[$i]}")"
        [ -n "${STEP_NOTES[$i]}" ] && printf " (%s)" "${STEP_NOTES[$i]}"
        echo
    done
    echo

    log_info "Installationsverzeichnis: ${INSTALL_DIR:-?}"
    log_info "App (Container):          http://127.0.0.1:${APP_HOST_PORT:-5000}/"
    if [ -n "${DOMAIN:-}" ]; then
        if is_yes "${SETUP_SSL:-n}"; then
            log_info "Öffentlich:               https://${DOMAIN}/"
        else
            log_info "Öffentlich:               http://${DOMAIN}/"
        fi
    fi

    log_info "Aktive Dienste:"
    log_info "  - Kern:      App (Flask), DB (MySQL), Redis"
    [ -n "$(compose_profile_args)" ] && log_info "  - Sidecars:  $(compose_profile_args)"

    echo
    log_info "Wartung (im Install-Dir):"
    log_manual "  cd ${INSTALL_DIR:-/var/www/teamportal}"
    log_manual "  docker compose ps"
    log_manual "  docker compose logs -f app"
    log_manual "  docker compose pull && docker compose up -d --build"
    echo
    log_info "Tipp: Da COMPOSE_PROFILES in .env hinterlegt ist, starten alle gewählten"
    log_info "Sidecars automatisch auch bei 'docker compose up -d'."
    log_info "Kein systemd-Service teamportal – Steuerung nur über Docker Compose."
    log_info "Doku: docs/INSTALLATION_DOCKER.md"
    echo
}
