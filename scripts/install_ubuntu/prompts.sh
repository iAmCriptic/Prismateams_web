#!/bin/bash
# Interaktive Abfragen – nur wenn Wert noch leer

gather_information() {
    log_info "=== Konfigurationsabfrage ==="

    prompt_or_default INSTALL_DIR "Installationspfad" "/var/www/teamportal"
    prompt_or_default REPO_URL "Git-Repository-URL" "$DEFAULT_REPO_URL"
    if [ -z "$GIT_BRANCH" ] && ! is_yes "$NON_INTERACTIVE"; then
        read -r -p "Git-Branch (leer = Default-Branch): " GIT_BRANCH
    elif [ -n "$GIT_BRANCH" ]; then
        log_info "Git-Branch (via Option): $GIT_BRANCH"
    fi

    prompt_or_default GUNICORN_PORT "Gunicorn-Port" "5000"
    validate_gunicorn_port || error_exit "Ungültiger Gunicorn-Port"

    prompt_yes_no SETUP_GUNICORN "Gunicorn systemd-Service einrichten?" "j"
    if is_yes "$SETUP_GUNICORN"; then
        prompt_or_default GUNICORN_WORKERS "Anzahl Gunicorn-Worker" "1"
        if ! [[ "$GUNICORN_WORKERS" =~ ^[0-9]+$ ]] || [ "$GUNICORN_WORKERS" -lt 1 ]; then
            error_exit "Ungültige Worker-Anzahl: $GUNICORN_WORKERS"
        fi
    else
        GUNICORN_WORKERS="${GUNICORN_WORKERS:-1}"
        print_manual_gunicorn_hint
    fi

    # Webserver
    log_info ""
    log_info "=== Webserver-Konfiguration ==="
    prompt_yes_no SETUP_WEBSERVER "Webserver automatisch einrichten (Nginx/Apache)?" "j"

    if is_yes "$SETUP_WEBSERVER"; then
        prompt_or_default WEBSERVER_TYPE "Welchen Webserver verwenden? (nginx/apache)" "nginx"
        if [[ "$WEBSERVER_TYPE" != "nginx" && "$WEBSERVER_TYPE" != "apache" ]]; then
            log_warning "Ungültiger Webserver-Typ. Verwende nginx."
            WEBSERVER_TYPE="nginx"
        fi
        prompt_or_default DOMAIN "Domain oder IP-Adresse für ${WEBSERVER_TYPE}" ""
        if [ -z "$DOMAIN" ]; then
            error_exit "Domain/IP ist erforderlich für automatische Webserver-Einrichtung!"
        fi
        prompt_yes_no SETUP_SSL "SSL mit Let's Encrypt einrichten?" "n"
        if is_yes "$SETUP_SSL"; then
            prompt_or_default LETSENCRYPT_EMAIL "E-Mail für Let's Encrypt" "webmaster@$DOMAIN"
        fi
    else
        WEBSERVER_TYPE=""
        SETUP_SSL="n"
        LETSENCRYPT_EMAIL=""
        if [ -z "$DOMAIN" ] && ! is_yes "$NON_INTERACTIVE"; then
            read -r -p "Domain oder IP-Adresse (optional, für Dokumentation): " DOMAIN
        fi
        print_manual_webserver_hint
        print_manual_custom_port_hint
    fi

    # MySQL / Redis
    log_info ""
    log_info "=== Datenbank / Redis ==="
    prompt_yes_no SETUP_MYSQL "MySQL/MariaDB automatisch einrichten?" "j"
    if is_yes "$SETUP_MYSQL"; then
        prompt_or_default DB_NAME "Datenbankname" "teamportal"
        prompt_or_default DB_USER "Datenbank-Benutzer" "teamportal"
        if [ -z "$DB_PASS" ]; then
            if is_yes "$NON_INTERACTIVE"; then
                DB_PASS=$(generate_password)
                DB_PASS_GENERATED=1
                log_info "DB-Passwort automatisch generiert"
            else
                read -r -sp "DB-Passwort (leer = automatisch generieren): " _dbp
                echo
                if [ -z "$_dbp" ]; then
                    DB_PASS=$(generate_password)
                    DB_PASS_GENERATED=1
                    log_info "DB-Passwort automatisch generiert"
                else
                    DB_PASS="$_dbp"
                fi
            fi
        fi
        if [ -z "$MYSQL_ROOT_PASS" ]; then
            if is_yes "$NON_INTERACTIVE"; then
                MYSQL_ROOT_PASS=$(generate_password)
                MYSQL_ROOT_PASS_GENERATED=1
                log_info "MySQL Root-Passwort automatisch generiert"
            else
                read -r -p "MySQL Root-Passwort (leer = automatische Generierung): " MYSQL_ROOT_PASS
                if [ -z "$MYSQL_ROOT_PASS" ]; then
                    MYSQL_ROOT_PASS=$(generate_password)
                    MYSQL_ROOT_PASS_GENERATED=1
                    log_info "MySQL Root-Passwort wurde automatisch generiert"
                fi
            fi
        fi
    else
        DB_NAME="${DB_NAME:-teamportal}"
        DB_USER="${DB_USER:-teamportal}"
        DB_PASS="${DB_PASS:-}"
        print_manual_mysql_hint
    fi

    prompt_yes_no SETUP_REDIS "Redis automatisch einrichten?" "j"
    if ! is_yes "$SETUP_REDIS"; then
        print_manual_redis_hint
        if is_yes "$SETUP_GUNICORN" && [ "${GUNICORN_WORKERS:-1}" -gt 1 ]; then
            log_warning "Mehrere Worker ohne Redis: SocketIO/Rate-Limit eingeschränkt"
        fi
    fi

    # Docker-Services
    log_info ""
    log_info "=== Optionale Docker-Services ==="
    if [ -z "$INSTALL_DOCKER" ] && [ -z "$INSTALL_ONLYOFFICE" ]; then
        prompt_yes_no INSTALL_DOCKER "Docker für OnlyOffice installieren?" "j"
    fi
    if [ -z "$INSTALL_DOCKER" ]; then
        if is_yes "$INSTALL_ONLYOFFICE"; then
            INSTALL_DOCKER="j"
        else
            INSTALL_DOCKER="n"
        fi
    fi

    if is_yes "$INSTALL_DOCKER"; then
        prompt_yes_no INSTALL_ONLYOFFICE "OnlyOffice Document Server (Docs) installieren?" "j"
        if ! is_yes "$INSTALL_ONLYOFFICE"; then
            print_manual_onlyoffice_hint
        fi
    else
        INSTALL_ONLYOFFICE="${INSTALL_ONLYOFFICE:-n}"
        if ! is_yes "$INSTALL_ONLYOFFICE"; then
            print_manual_onlyoffice_hint
        fi
    fi
    # OnlyOffice Docs braucht immer Docker
    if is_yes "$INSTALL_ONLYOFFICE"; then
        INSTALL_DOCKER="j"
    fi

    if is_yes "$INSTALL_DOCKER"; then
        prompt_yes_no INSTALL_EXCALIDRAW "Excalidraw-Room (Live-Kollaboration) installieren?" "j"
        if ! is_yes "$INSTALL_EXCALIDRAW"; then
            print_manual_excalidraw_hint
        fi
    else
        INSTALL_EXCALIDRAW="${INSTALL_EXCALIDRAW:-n}"
        if ! is_yes "$INSTALL_EXCALIDRAW"; then
            print_manual_excalidraw_hint
        fi
    fi
    if is_yes "$INSTALL_EXCALIDRAW"; then
        INSTALL_DOCKER="j"
    fi

    log_info ""
    log_info "=== Media Downloader ==="
    prompt_yes_no INSTALL_MEDIA_DOWNLOADER "Media Downloader (FFmpeg) installieren?" "n"
    if is_yes "$INSTALL_MEDIA_DOWNLOADER"; then
        log_info "yt-dlp nutzt Standard-Player-Clients (ios,web_creator,mweb)."
        log_info "Optionaler Cookie-Fallback: MEDIA_DOWNLOADER_COOKIES_FILE in .env (siehe docs/INSTALLATION.md)."
        if [ -z "${MEDIA_DOWNLOADER_COOKIES_FILE:-}" ] && ! is_yes "$NON_INTERACTIVE"; then
            read -r -p "Pfad zu cookies.txt (leer = überspringen): " MEDIA_DOWNLOADER_COOKIES_FILE
            MEDIA_DOWNLOADER_COOKIES_FILE="${MEDIA_DOWNLOADER_COOKIES_FILE:-}"
        fi
    else
        print_manual_media_downloader_hint
    fi

    # .env Mode
    log_info ""
    log_info "=== .env-Konfiguration ==="
    if [ -z "$ENV_MODE" ]; then
        if is_yes "$NON_INTERACTIVE"; then
            ENV_MODE="auto"
        else
            echo "  1) auto   – Secrets generieren, sinnvolle Defaults"
            echo "  2) manual – kritische Werte interaktiv abfragen"
            echo "  3) file   – bestehende .env-Datei verwenden/mergen"
            read -r -p ".env-Modus (auto/manual/file) [auto]: " ENV_MODE
            ENV_MODE=${ENV_MODE:-auto}
        fi
    else
        log_info ".env-Modus (via Option): $ENV_MODE"
    fi
    case "$ENV_MODE" in
        auto|manual|file) ;;
        *)
            log_warning "Ungültiger .env-Modus '$ENV_MODE' – verwende auto"
            ENV_MODE="auto"
            ;;
    esac
    if [ "$ENV_MODE" = "file" ]; then
        prompt_or_default ENV_FILE "Pfad zur .env-Datei" ""
        if [ -z "$ENV_FILE" ] || [ ! -f "$ENV_FILE" ]; then
            error_exit ".env-Datei nicht gefunden: ${ENV_FILE:-<leer>}"
        fi
    fi

    prompt_or_default TIMEZONE "Zeitzone" "Europe/Berlin"
    prompt_or_default VAPID_CLAIM_EMAIL "VAPID Claim E-Mail" "admin@example.com"

    # E-Mail (optional, außer manual-Modus verlangt)
    MAIL_SERVER="${MAIL_SERVER:-}"
    MAIL_PORT="${MAIL_PORT:-587}"
    MAIL_USE_TLS="${MAIL_USE_TLS:-True}"
    MAIL_USE_SSL="${MAIL_USE_SSL:-False}"
    MAIL_USERNAME="${MAIL_USERNAME:-}"
    MAIL_PASSWORD="${MAIL_PASSWORD:-}"
    MAIL_DEFAULT_SENDER="${MAIL_DEFAULT_SENDER:-}"
    MAIL_SENDER_NAME="${MAIL_SENDER_NAME:-}"
    IMAP_SERVER="${IMAP_SERVER:-}"
    IMAP_PORT="${IMAP_PORT:-993}"
    IMAP_USE_SSL="${IMAP_USE_SSL:-True}"

    if [ "$ENV_MODE" = "manual" ] && ! is_yes "$NON_INTERACTIVE"; then
        log_info ""
        log_info "=== E-Mail-Konfiguration (optional) ==="
        read -r -p "SMTP-Server (leer = überspringen): " MAIL_SERVER
        if [ -n "$MAIL_SERVER" ]; then
            read -r -p "SMTP-Port [587]: " MAIL_PORT
            MAIL_PORT=${MAIL_PORT:-587}
            read -r -p "TLS verwenden? (j/n) [j]: " _tls
            _tls=${_tls:-j}
            if is_yes "$_tls"; then MAIL_USE_TLS="True"; else MAIL_USE_TLS="False"; fi
            read -r -p "SSL verwenden? (j/n) [n]: " _ssl
            _ssl=${_ssl:-n}
            if is_yes "$_ssl"; then MAIL_USE_SSL="True"; else MAIL_USE_SSL="False"; fi
            read -r -p "E-Mail-Benutzername: " MAIL_USERNAME
            read -r -sp "E-Mail-Passwort: " MAIL_PASSWORD
            echo
            read -r -p "Standard-Absender [${MAIL_USERNAME}]: " MAIL_DEFAULT_SENDER
            MAIL_DEFAULT_SENDER=${MAIL_DEFAULT_SENDER:-$MAIL_USERNAME}
            read -r -p "Absender-Name (optional): " MAIL_SENDER_NAME
            read -r -p "IMAP-Server (leer = überspringen): " IMAP_SERVER
            if [ -n "$IMAP_SERVER" ]; then
                read -r -p "IMAP-Port [993]: " IMAP_PORT
                IMAP_PORT=${IMAP_PORT:-993}
                read -r -p "IMAP SSL? (j/n) [j]: " _imaps
                _imaps=${_imaps:-j}
                if is_yes "$_imaps"; then IMAP_USE_SSL="True"; else IMAP_USE_SSL="False"; fi
            fi
        fi
    elif [ "$ENV_MODE" = "auto" ] && ! is_yes "$NON_INTERACTIVE"; then
        log_info ""
        log_info "=== E-Mail-Konfiguration (optional) ==="
        read -r -p "SMTP-Server (leer = überspringen): " MAIL_SERVER
        if [ -n "$MAIL_SERVER" ]; then
            read -r -p "SMTP-Port [587]: " MAIL_PORT
            MAIL_PORT=${MAIL_PORT:-587}
            read -r -p "TLS verwenden? (j/n) [j]: " _tls
            _tls=${_tls:-j}
            if is_yes "$_tls"; then MAIL_USE_TLS="True"; else MAIL_USE_TLS="False"; fi
            read -r -p "SSL verwenden? (j/n) [n]: " _ssl
            _ssl=${_ssl:-n}
            if is_yes "$_ssl"; then MAIL_USE_SSL="True"; else MAIL_USE_SSL="False"; fi
            read -r -p "E-Mail-Benutzername: " MAIL_USERNAME
            read -r -sp "E-Mail-Passwort: " MAIL_PASSWORD
            echo
            read -r -p "Standard-Absender [${MAIL_USERNAME}]: " MAIL_DEFAULT_SENDER
            MAIL_DEFAULT_SENDER=${MAIL_DEFAULT_SENDER:-$MAIL_USERNAME}
            read -r -p "Absender-Name (optional): " MAIL_SENDER_NAME
            read -r -p "IMAP-Server (leer = überspringen): " IMAP_SERVER
            if [ -n "$IMAP_SERVER" ]; then
                read -r -p "IMAP-Port [993]: " IMAP_PORT
                IMAP_PORT=${IMAP_PORT:-993}
                read -r -p "IMAP SSL? (j/n) [j]: " _imaps
                _imaps=${_imaps:-j}
                if is_yes "$_imaps"; then IMAP_USE_SSL="True"; else IMAP_USE_SSL="False"; fi
            fi
        fi
    fi

    confirm_plan
    log_success "Konfiguration gesammelt"
}

confirm_plan() {
    echo
    log_info "=== Geplante Installation ==="
    echo "  Pfad:           $INSTALL_DIR"
    echo "  Repo:           $REPO_URL"
    echo "  Branch:         ${GIT_BRANCH:-<default>}"
    echo "  Port:           $GUNICORN_PORT"
    echo "  Gunicorn:       $(is_yes "$SETUP_GUNICORN" && echo "ja ($GUNICORN_WORKERS Worker)" || echo "nein")"
    echo "  Webserver:      $(is_yes "$SETUP_WEBSERVER" && echo "$WEBSERVER_TYPE ($DOMAIN)" || echo "manuell")"
    echo "  SSL:            $(is_yes "$SETUP_SSL" && echo "ja" || echo "nein")"
    echo "  MySQL:          $(is_yes "$SETUP_MYSQL" && echo "ja ($DB_NAME / $DB_USER)" || echo "manuell")"
    echo "  Redis:          $(is_yes "$SETUP_REDIS" && echo "ja" || echo "manuell")"
    echo "  OnlyOffice:     $(is_yes "$INSTALL_ONLYOFFICE" && echo "ja" || echo "nein")"
    echo "  Excalidraw:     $(is_yes "$INSTALL_EXCALIDRAW" && echo "ja" || echo "nein")"
    echo "  FFmpeg:         $(is_yes "$INSTALL_MEDIA_DOWNLOADER" && echo "ja" || echo "nein")"
    echo "  .env-Modus:     $ENV_MODE"
    echo

    if is_yes "$NON_INTERACTIVE"; then
        return 0
    fi
    read -r -p "Mit dieser Konfiguration fortfahren? (j/n) [j]: " _ok
    _ok=${_ok:-j}
    if ! is_yes "$_ok"; then
        error_exit "Installation abgebrochen durch Benutzer"
    fi
}
