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

    FLASK_SECRET="${FLASK_SECRET:-$(generate_secret)}"
    MYSQL_PASSWORD="${MYSQL_PASSWORD:-$(generate_password)}"
    MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-$(generate_password)}"
    DB_PASS_GENERATED=1

    # Compose-Interpolation braucht MYSQL_* schon vor build/run
    set_env_var "MYSQL_DATABASE" "teamportal" .env
    set_env_var "MYSQL_USER" "teamportal" .env
    set_env_var "MYSQL_PASSWORD" "$MYSQL_PASSWORD" .env
    set_env_var "MYSQL_ROOT_PASSWORD" "$MYSQL_ROOT_PASSWORD" .env
    set_env_var "APP_HOST_BIND" "127.0.0.1" .env
    set_env_var "APP_HOST_PORT" "${APP_HOST_PORT:-5000}" .env
    set_env_var "EUROOFFICE_HOST_BIND" "127.0.0.1" .env
    set_env_var "EUROOFFICE_HOST_PORT" "${EUROOFFICE_HOST_PORT:-8080}" .env
    set_env_var "EXCALIDRAW_HOST_BIND" "127.0.0.1" .env
    set_env_var "EXCALIDRAW_HOST_PORT" "${EXCALIDRAW_HOST_PORT:-8082}" .env
    set_env_var "MIROTALK_HOST_PORT" "${MIROTALK_HOST_PORT:-3010}" .env
    set_env_var "MIROTALK_UDP_MIN" "${MIROTALK_UDP_MIN:-40000}" .env
    set_env_var "MIROTALK_UDP_MAX" "${MIROTALK_UDP_MAX:-40100}" .env

    _generate_keys_via_compose || {
        log_error "Keys konnten nicht erzeugt werden"
        return 1
    }

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

    if is_yes "${INSTALL_ONLYOFFICE:-n}"; then
        ONLYOFFICE_SECRET="${ONLYOFFICE_SECRET:-$(generate_secret)}"
        set_env_var "ONLYOFFICE_ENABLED" "True" .env
        set_env_var "ONLYOFFICE_DOCUMENT_SERVER_URL" "/eurooffice" .env
        set_env_var "ONLYOFFICE_SECRET_KEY" "$ONLYOFFICE_SECRET" .env
        if [ -n "${DOMAIN:-}" ]; then
            if is_yes "${SETUP_SSL:-n}"; then
                set_env_var "ONLYOFFICE_PUBLIC_URL" "https://${DOMAIN}" .env
            else
                set_env_var "ONLYOFFICE_PUBLIC_URL" "http://${DOMAIN}" .env
            fi
        fi
    else
        set_env_var "ONLYOFFICE_ENABLED" "False" .env
    fi

    if is_yes "${INSTALL_EXCALIDRAW:-n}"; then
        set_env_var "EXCALIDRAW_ENABLED" "True" .env
        set_env_var "EXCALIDRAW_ROOM_URL" "/excalidraw-room" .env
    else
        set_env_var "EXCALIDRAW_ENABLED" "False" .env
    fi

    if is_yes "${INSTALL_MIROTALK:-n}"; then
        MIROTALK_API_KEY="${MIROTALK_API_KEY:-$(generate_secret)}"
        MIROTALK_HOST_PASSWORD="${MIROTALK_HOST_PASSWORD:-$(generate_password)}"
        MIROTALK_JWT_SECRET="${MIROTALK_JWT_SECRET:-$(generate_secret)}"
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
