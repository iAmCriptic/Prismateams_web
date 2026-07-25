#!/bin/bash
# Abschlussübersicht, Credentials, install-report.txt

print_step_table() {
    echo
    echo "Schritt-Übersicht"
    echo "=============="
    printf "%-18s %-14s %s\n" "SCHRITT" "STATUS" "NOTIZ"
    printf "%-18s %-14s %s\n" "------" "------" "-----"
    local i
    for i in "${!STEP_IDS[@]}"; do
        printf "%-18s %-14s %s\n" \
            "${STEP_TITLES[$i]}" \
            "$(status_label "${STEP_STATUSES[$i]}")" \
            "${STEP_NOTES[$i]}"
    done
    echo
}

write_install_report() {
    local report_file="${INSTALL_DIR}/install-report.txt"
    if [ -z "${INSTALL_DIR:-}" ] || [ ! -d "${INSTALL_DIR:-}" ]; then
        report_file="/tmp/teamportal-install-report.txt"
    fi

    {
        echo "Team Portal – Installationsbericht"
        echo "Erstellt: $(date -Iseconds 2>/dev/null || date)"
        echo "Abbruch: ${INSTALL_ABORTED:-0}"
        echo
        echo "Konfiguration"
        echo "-------------"
        echo "Installationspfad: ${INSTALL_DIR:-}"
        echo "Repository: ${REPO_URL:-}"
        echo "Branch: ${GIT_BRANCH:-<default>}"
        echo "Gunicorn-Port: ${GUNICORN_PORT:-}"
        echo "Gunicorn-Worker: ${GUNICORN_WORKERS:-}"
        echo "Gunicorn-Service: ${SETUP_GUNICORN:-}"
        echo "Webserver: ${WEBSERVER_TYPE:-manuell} (Setup=${SETUP_WEBSERVER:-})"
        echo "Domain: ${DOMAIN:-}"
        echo "SSL: ${SETUP_SSL:-}"
        echo "MySQL: ${SETUP_MYSQL:-}"
        echo "Redis: ${SETUP_REDIS:-}"
        echo "OnlyOffice: ${INSTALL_ONLYOFFICE:-}"
        echo "FFmpeg: ${INSTALL_MEDIA_DOWNLOADER:-}"
        echo ".env-Modus: ${ENV_MODE:-}"
        echo
        echo "Schritte"
        echo "--------"
        local i
        for i in "${!STEP_IDS[@]}"; do
            echo "${STEP_IDS[$i]} | ${STEP_STATUSES[$i]} | ${STEP_TITLES[$i]} | ${STEP_NOTES[$i]}"
        done
        echo
        echo "Zugangsdaten (sicher aufbewahren!)"
        echo "----------------------------------"
        if is_yes "${SETUP_MYSQL:-n}"; then
            echo "Datenbank: ${DB_NAME:-}"
            echo "DB-Benutzer: ${DB_USER:-}"
            echo "DB-Passwort: ${DB_PASS:-}"
            echo "MySQL Root-Passwort: ${MYSQL_ROOT_PASS:-}"
        fi
        if [ -n "${ONLYOFFICE_SECRET:-}" ]; then
            echo "OnlyOffice JWT / ONLYOFFICE_SECRET_KEY: ${ONLYOFFICE_SECRET}"
        fi
        echo
        echo "Weitere Keys liegen in: ${INSTALL_DIR}/.env"
        echo "  SECRET_KEY, VAPID_*, CREDENTIAL_ENCRYPTION_KEY, MUSIC_ENCRYPTION_KEY, TOTP_ENCRYPTION_KEY"
    } > "$report_file"

    chmod 600 "$report_file" 2>/dev/null || true
    chown www-data:www-data "$report_file" 2>/dev/null || true
    echo "$report_file"
}

print_summary() {
    if [ "${INSTALL_ABORTED:-0}" = "1" ]; then
        log_warning "=== Installation abgebrochen / unvollständig ==="
    else
        log_success "=== Installation abgeschlossen ==="
    fi

    print_step_table

    echo "Konfiguration"
    echo "============="
    echo "Installationspfad: ${INSTALL_DIR:-}"
    echo "Repository: ${REPO_URL:-}"
    echo "Branch: ${GIT_BRANCH:-<default>}"
    echo "Gunicorn-Port: ${GUNICORN_PORT:-}"
    if is_yes "${SETUP_GUNICORN:-n}"; then
        echo "Gunicorn: eingerichtet (${GUNICORN_WORKERS:-1} Worker)"
    else
        echo "Gunicorn: manuell"
    fi
    if is_yes "${SETUP_WEBSERVER:-n}"; then
        echo "Webserver: ${WEBSERVER_TYPE} (${DOMAIN})"
    else
        echo "Webserver: manuell"
    fi
    echo

    echo "Zugangsdaten"
    echo "============"
    if is_yes "${SETUP_MYSQL:-n}"; then
        echo "Datenbank: ${DB_NAME}"
        echo "Datenbank-Benutzer: ${DB_USER}"
        echo "Datenbank-Passwort: ${DB_PASS}"
        echo "MySQL Root-Passwort: ${MYSQL_ROOT_PASS}"
        if [ "${MYSQL_ROOT_PASS_GENERATED:-0}" = "1" ] || [ "${DB_PASS_GENERATED:-0}" = "1" ]; then
            echo "(Passwörter wurden vom Skript generiert – bitte sicher speichern!)"
        fi
    else
        echo "MySQL: nicht vom Skript eingerichtet"
    fi
    if [ -n "${ONLYOFFICE_SECRET:-}" ]; then
        echo "OnlyOffice JWT / ONLYOFFICE_SECRET_KEY: ${ONLYOFFICE_SECRET}"
    fi
    echo "Weitere Secrets: ${INSTALL_DIR}/.env"
    echo

    local report_path
    report_path=$(write_install_report)
    log_info "Bericht gespeichert: $report_path"
    echo

    echo "Nächste Schritte"
    echo "================"
    if [ -z "${MAIL_SERVER:-}" ]; then
        echo "1. Optional E-Mail in ${INSTALL_DIR}/.env konfigurieren"
    else
        echo "1. E-Mail-Einstellungen wurden gesetzt"
    fi
    if ! is_yes "${SETUP_WEBSERVER:-n}"; then
        echo "2. Webserver manuell einrichten (docs/INSTALLATION.md)"
    else
        echo "2. Domain erreichbar prüfen"
    fi
    if is_yes "${SETUP_GUNICORN:-n}"; then
        echo "3. Logs: journalctl -u teamportal -n 50"
        echo "4. Portal öffnen und Admin über Setup-Assistent anlegen"
    else
        echo "3. Gunicorn manuell starten, dann Setup-Assistent"
    fi
    echo

    if ! is_yes "${SETUP_WEBSERVER:-n}"; then print_manual_webserver_hint; fi
    if ! is_yes "${INSTALL_ONLYOFFICE:-n}"; then print_manual_onlyoffice_hint; fi
    if ! is_yes "${INSTALL_MEDIA_DOWNLOADER:-n}"; then print_manual_media_downloader_hint; fi
    if ! is_yes "${SETUP_GUNICORN:-n}"; then print_manual_gunicorn_hint; fi
    if ! is_yes "${SETUP_MYSQL:-n}"; then print_manual_mysql_hint; fi
    if ! is_yes "${SETUP_REDIS:-n}"; then print_manual_redis_hint; fi

    echo "Service-Status:"
    echo "  systemctl status teamportal"
    if is_yes "${SETUP_WEBSERVER:-n}"; then
        if [ "$WEBSERVER_TYPE" = "nginx" ]; then
            echo "  systemctl status nginx"
        elif [ "$WEBSERVER_TYPE" = "apache" ]; then
            echo "  systemctl status apache2"
        fi
    fi
    if is_yes "${INSTALL_ONLYOFFICE:-n}"; then
        echo "  docker ps"
    fi
    echo
}
