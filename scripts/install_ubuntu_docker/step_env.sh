#!/bin/bash
# .env für Docker Compose erzeugen / ergänzen

_generate_keys_via_compose() {
    cd "$INSTALL_DIR" || return 1
    log_info "Baue App-Image für Key-Generierung..."
    docker_compose build app || return 1

    log_info "Generiere Encryption Keys..."
    local enc_out
    enc_out=$(docker_compose run --rm --no-deps app python -c "
from scripts.generate_encryption_keys import generate_encryption_key
print('CREDENTIAL_KEY=' + generate_encryption_key())
print('MAILBOX_KEY=' + generate_encryption_key())
print('MUSIC_KEY=' + generate_encryption_key())
print('TOTP_KEY=' + generate_encryption_key())
" 2>/dev/null) || return 1

    CREDENTIAL_KEY=$(echo "$enc_out" | grep '^CREDENTIAL_KEY=' | head -n1 | cut -d= -f2- | tr -d '\r')
    MAILBOX_KEY=$(echo "$enc_out" | grep '^MAILBOX_KEY=' | head -n1 | cut -d= -f2- | tr -d '\r')
    MUSIC_KEY=$(echo "$enc_out" | grep '^MUSIC_KEY=' | head -n1 | cut -d= -f2- | tr -d '\r')
    TOTP_KEY=$(echo "$enc_out" | grep '^TOTP_KEY=' | head -n1 | cut -d= -f2- | tr -d '\r')

    log_info "Generiere VAPID Keys..."
    local vapid_out
    vapid_out=$(docker_compose run --rm --no-deps app python -c "
from scripts.generate_vapid_keys import generate_vapid_keys
keys = generate_vapid_keys()
print('VAPID_PRIVATE=' + keys['private_key_b64'])
print('VAPID_PUBLIC=' + keys['public_key_b64'])
" 2>/dev/null) || return 1

    VAPID_PRIVATE=$(echo "$vapid_out" | grep '^VAPID_PRIVATE=' | head -n1 | cut -d= -f2- | tr -d '\r')
    VAPID_PUBLIC=$(echo "$vapid_out" | grep '^VAPID_PUBLIC=' | head -n1 | cut -d= -f2- | tr -d '\r')

    if [ -z "$CREDENTIAL_KEY" ] || [ -z "$VAPID_PRIVATE" ]; then
        log_error "Key-Generierung unvollständig"
        return 1
    fi
    return 0
}

step_env() {
    cd "$INSTALL_DIR" || return 1

    if [ ! -f .env ]; then
        if [ -f docs/env.docker.example ]; then
            cp docs/env.docker.example .env
        elif [ -f docs/env.example ]; then
            cp docs/env.example .env
        else
            touch .env
        fi
        log_info ".env aus Vorlage angelegt"
    else
        log_info "Bestehende .env wird ergänzt"
    fi

    # Bestehende Passwörter/Secrets weiterverwenden, falls vorhanden und kein Platzhalter
    local existing_db_pass existing_root_pass existing_secret
    existing_db_pass="$(get_env_val MYSQL_PASSWORD .env)"
    if [ -n "$existing_db_pass" ] && [[ "$existing_db_pass" != *"change-me"* ]]; then
        MYSQL_PASSWORD="$existing_db_pass"
    else
        MYSQL_PASSWORD="${MYSQL_PASSWORD:-$(generate_password)}"
    fi

    existing_root_pass="$(get_env_val MYSQL_ROOT_PASSWORD .env)"
    if [ -n "$existing_root_pass" ] && [[ "$existing_root_pass" != *"change-me"* ]]; then
        MYSQL_ROOT_PASSWORD="$existing_root_pass"
    else
        MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-$(generate_password)}"
    fi

    existing_secret="$(get_env_val SECRET_KEY .env)"
    if [ -n "$existing_secret" ] && [[ "$existing_secret" != *"change-me"* ]]; then
        FLASK_SECRET="$existing_secret"
    else
        FLASK_SECRET="${FLASK_SECRET:-$(generate_secret)}"
    fi
    DB_PASS_GENERATED=1

    # Compose-Interpolation braucht MYSQL_* schon vor build/run
    set_env_var "MYSQL_DATABASE" "teamportal" .env
    set_env_var "MYSQL_USER" "teamportal" .env
    set_env_var "MYSQL_PASSWORD" "$MYSQL_PASSWORD" .env
    set_env_var "MYSQL_ROOT_PASSWORD" "$MYSQL_ROOT_PASSWORD" .env

    # Bindings: bei Proxy (Nginx/Apache) Loopback 127.0.0.1; ohne Webserver 0.0.0.0
    local host_bind="127.0.0.1"
    if ! is_yes "${SETUP_WEBSERVER:-j}"; then
        host_bind="0.0.0.0"
    fi
    set_env_var "APP_HOST_BIND" "$host_bind" .env
    set_env_var "APP_HOST_PORT" "${APP_HOST_PORT:-5000}" .env
    set_env_var "EUROOFFICE_HOST_BIND" "$host_bind" .env
    set_env_var "EUROOFFICE_HOST_PORT" "${EUROOFFICE_HOST_PORT:-8080}" .env
    set_env_var "EXCALIDRAW_HOST_BIND" "$host_bind" .env
    set_env_var "EXCALIDRAW_HOST_PORT" "${EXCALIDRAW_HOST_PORT:-8082}" .env
    set_env_var "MIROTALK_HOST_PORT" "${MIROTALK_HOST_PORT:-3010}" .env
    set_env_var "MIROTALK_UDP_MIN" "${MIROTALK_UDP_MIN:-40000}" .env
    set_env_var "MIROTALK_UDP_MAX" "${MIROTALK_UDP_MAX:-40100}" .env

    # Aktive Profiles sammeln und COMPOSE_PROFILES setzen (Standard: Opt-Out)
    local active_profiles=()
    if is_yes "${INSTALL_ONLYOFFICE:-j}"; then
        active_profiles+=("onlyoffice")
    fi
    if is_yes "${INSTALL_EXCALIDRAW:-j}"; then
        active_profiles+=("excalidraw")
    fi
    if is_yes "${INSTALL_MIROTALK:-j}"; then
        active_profiles+=("mirotalk")
    fi
    if [ ${#active_profiles[@]} -gt 0 ]; then
        local profiles_csv
        profiles_csv=$(IFS=,; echo "${active_profiles[*]}")
        set_env_var "COMPOSE_PROFILES" "$profiles_csv" .env
        log_info "Aktive Compose-Profiles in .env: $profiles_csv"
    else
        set_env_var "COMPOSE_PROFILES" "" .env
    fi

    # Verschlüsselungs- und VAPID-Keys prüfen oder generieren
    local cur_cred cur_mail cur_music cur_totp cur_vpub cur_vpriv
    cur_cred="$(get_env_val CREDENTIAL_ENCRYPTION_KEY .env)"
    cur_mail="$(get_env_val MAILBOX_ENCRYPTION_KEY .env)"
    cur_music="$(get_env_val MUSIC_ENCRYPTION_KEY .env)"
    cur_totp="$(get_env_val TOTP_ENCRYPTION_KEY .env)"
    cur_vpub="$(get_env_val VAPID_PUBLIC_KEY .env)"
    cur_vpriv="$(get_env_val VAPID_PRIVATE_KEY .env)"

    if [ -n "$cur_cred" ] && [[ "$cur_cred" != *"change-me"* ]] && \
       [ -n "$cur_mail" ] && [[ "$cur_mail" != *"change-me"* ]] && \
       [ -n "$cur_music" ] && [[ "$cur_music" != *"change-me"* ]] && \
       [ -n "$cur_totp" ] && [[ "$cur_totp" != *"change-me"* ]] && \
       [ -n "$cur_vpub" ] && [ -n "$cur_vpriv" ]; then
        log_info "Bestehende Verschlüsselungs- und VAPID-Keys übernommen"
        CREDENTIAL_KEY="$cur_cred"
        MAILBOX_KEY="$cur_mail"
        MUSIC_KEY="$cur_music"
        TOTP_KEY="$cur_totp"
        VAPID_PUBLIC="$cur_vpub"
        VAPID_PRIVATE="$cur_vpriv"
    else
        _generate_keys_via_compose || {
            log_error "Keys konnten nicht erzeugt werden"
            return 1
        }
    fi

    set_env_var "SECRET_KEY" "$FLASK_SECRET" .env
    set_env_var "FLASK_ENV" "production" .env
    set_env_var "TIMEZONE" "${TIMEZONE:-Europe/Berlin}" .env
    if is_yes "${SETUP_SSL:-n}"; then
        set_env_var "SESSION_COOKIE_SECURE" "True" .env
    else
        set_env_var "SESSION_COOKIE_SECURE" "False" .env
    fi

    set_env_var "CREDENTIAL_ENCRYPTION_KEY" "$CREDENTIAL_KEY" .env
    set_env_var "MAILBOX_ENCRYPTION_KEY" "$MAILBOX_KEY" .env
    set_env_var "MUSIC_ENCRYPTION_KEY" "$MUSIC_KEY" .env
    set_env_var "TOTP_ENCRYPTION_KEY" "$TOTP_KEY" .env
    set_env_var "VAPID_PUBLIC_KEY" "$VAPID_PUBLIC" .env
    set_env_var "VAPID_PRIVATE_KEY" "$VAPID_PRIVATE" .env
    set_env_var "VAPID_CLAIM_EMAIL" "${VAPID_CLAIM_EMAIL:-admin@example.com}" .env
    set_env_var "UPLOAD_FOLDER" "uploads" .env

    if [ -n "${DOMAIN:-}" ]; then
        if is_yes "${SETUP_SSL:-n}"; then
            set_env_var "PUBLIC_BASE_URL" "https://${DOMAIN}" .env
        else
            set_env_var "PUBLIC_BASE_URL" "http://${DOMAIN}" .env
        fi
    fi

    # Euro-Office Document Server
    if is_yes "${INSTALL_ONLYOFFICE:-j}"; then
        local existing_oo_secret
        existing_oo_secret="$(get_env_val ONLYOFFICE_SECRET_KEY .env)"
        if [ -n "$existing_oo_secret" ] && [[ "$existing_oo_secret" != *"change-me"* ]]; then
            ONLYOFFICE_SECRET="$existing_oo_secret"
        else
            ONLYOFFICE_SECRET="${ONLYOFFICE_SECRET:-$(generate_secret)}"
        fi

        set_env_var "ONLYOFFICE_ENABLED" "True" .env
        set_env_var "ONLYOFFICE_DOCUMENT_SERVER_URL" "/eurooffice" .env
        set_env_var "ONLYOFFICE_SECRET_KEY" "$ONLYOFFICE_SECRET" .env
        if [ -n "${DOMAIN:-}" ]; then
            if is_yes "${SETUP_SSL:-n}"; then
                set_env_var "ONLYOFFICE_PUBLIC_URL" "https://${DOMAIN}" .env
            else
                set_env_var "ONLYOFFICE_PUBLIC_URL" "http://${DOMAIN}" .env
            fi
        else
            local auto_ip
            auto_ip="$(detect_public_ip)"
            if [ -n "$auto_ip" ]; then
                set_env_var "ONLYOFFICE_PUBLIC_URL" "http://${auto_ip}:${APP_HOST_PORT:-5000}" .env
            fi
        fi
    else
        set_env_var "ONLYOFFICE_ENABLED" "False" .env
    fi

    # Excalidraw Live-Kollaboration
    if is_yes "${INSTALL_EXCALIDRAW:-j}"; then
        set_env_var "EXCALIDRAW_ENABLED" "True" .env
        set_env_var "EXCALIDRAW_URL" "/excalidraw" .env
        set_env_var "EXCALIDRAW_ROOM_URL" "/excalidraw-room" .env
    else
        set_env_var "EXCALIDRAW_ENABLED" "False" .env
    fi

    # MiroTalk SFU Meetings
    if is_yes "${INSTALL_MIROTALK:-j}"; then
        local existing_mt_api existing_mt_pass existing_mt_jwt
        existing_mt_api="$(get_env_val MIROTALK_API_KEY .env)"
        if [ -n "$existing_mt_api" ] && [[ "$existing_mt_api" != *"change-me"* ]]; then
            MIROTALK_API_KEY="$existing_mt_api"
        else
            MIROTALK_API_KEY="${MIROTALK_API_KEY:-$(generate_secret)}"
        fi

        existing_mt_pass="$(get_env_val MIROTALK_HOST_PASSWORD .env)"
        if [ -n "$existing_mt_pass" ] && [[ "$existing_mt_pass" != *"change-me"* ]]; then
            MIROTALK_HOST_PASSWORD="$existing_mt_pass"
        else
            MIROTALK_HOST_PASSWORD="${MIROTALK_HOST_PASSWORD:-$(generate_password)}"
        fi

        existing_mt_jwt="$(get_env_val MIROTALK_JWT_SECRET .env)"
        if [ -n "$existing_mt_jwt" ] && [[ "$existing_mt_jwt" != *"change-me"* ]]; then
            MIROTALK_JWT_SECRET="$existing_mt_jwt"
        else
            MIROTALK_JWT_SECRET="${MIROTALK_JWT_SECRET:-$(generate_secret)}"
        fi

        MIROTALK_HOST_USER="${MIROTALK_HOST_USER:-portal}"
        SFU_ANNOUNCED_IP="${SFU_ANNOUNCED_IP:-$(detect_public_ip)}"

        local portal_origin meet_url
        meet_url=$(mirotalk_public_url)
        portal_origin=$(mirotalk_portal_origin)

        set_env_var "MIROTALK_ENABLED" "True" .env
        set_env_var "MIROTALK_URL" "$meet_url" .env
        set_env_var "MIROTALK_API_URL" "http://mirotalk:3010" .env
        set_env_var "MIROTALK_API_KEY" "$MIROTALK_API_KEY" .env
        set_env_var "MIROTALK_HOST_USER" "$MIROTALK_HOST_USER" .env
        set_env_var "MIROTALK_HOST_PASSWORD" "$MIROTALK_HOST_PASSWORD" .env
        set_env_var "MIROTALK_JWT_SECRET" "$MIROTALK_JWT_SECRET" .env
        set_env_var "SFU_ANNOUNCED_IP" "$SFU_ANNOUNCED_IP" .env
        if [ -n "$portal_origin" ]; then
            set_env_var "MIROTALK_CORS_ORIGIN" "${portal_origin},${meet_url}" .env
            set_env_var "MIROTALK_EMBED_ORIGINS" "${portal_origin}" .env
        else
            set_env_var "MIROTALK_CORS_ORIGIN" "${meet_url}" .env
            set_env_var "MIROTALK_EMBED_ORIGINS" "${meet_url}" .env
        fi
        if ! is_yes "${SETUP_SSL:-n}"; then
            log_warning "Ohne HTTPS: WebRTC/Kamera oft blockiert (Secure Context)"
        fi
    else
        set_env_var "MIROTALK_ENABLED" "False" .env
    fi

    chmod 600 .env 2>/dev/null || true
    log_success ".env geschrieben (${INSTALL_DIR}/.env)"
    return 0
}
