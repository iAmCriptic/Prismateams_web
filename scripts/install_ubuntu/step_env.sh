#!/bin/bash
# Key-Generierung und .env-Konfiguration

generate_keys() {
    cd "$INSTALL_DIR" || return 1

    if [ ! -f "venv/bin/activate" ]; then
        log_error "Virtual Environment nicht gefunden in $INSTALL_DIR/venv"
        return 1
    fi
    # shellcheck disable=SC1091
    source venv/bin/activate || return 1

    FLASK_SECRET="${FLASK_SECRET:-$(generate_secret)}"

    log_info "Generiere VAPID Keys..."
    if [ ! -f "${INSTALL_DIR}/scripts/generate_vapid_keys.py" ]; then
        log_error "VAPID Key-Generator nicht gefunden"
        return 1
    fi

    VAPID_OUTPUT=$(cd "${INSTALL_DIR}" && python3 -c "
import sys, os
sys.path.insert(0, os.getcwd())
from scripts.generate_vapid_keys import generate_vapid_keys
keys = generate_vapid_keys()
print('VAPID_PRIVATE=' + keys['private_key_b64'])
print('VAPID_PUBLIC=' + keys['public_key_b64'])
" 2>&1) || {
        log_error "VAPID Key-Generierung fehlgeschlagen: $VAPID_OUTPUT"
        return 1
    }
    VAPID_PRIVATE=$(echo "$VAPID_OUTPUT" | grep "VAPID_PRIVATE=" | head -n1 | sed 's/^VAPID_PRIVATE=//' | tr -d '\r\n')
    VAPID_PUBLIC=$(echo "$VAPID_OUTPUT" | grep "VAPID_PUBLIC=" | head -n1 | sed 's/^VAPID_PUBLIC=//' | tr -d '\r\n')

    log_info "Generiere Encryption Keys..."
    if [ ! -f "${INSTALL_DIR}/scripts/generate_encryption_keys.py" ]; then
        log_error "Encryption Key-Generator nicht gefunden"
        return 1
    fi

    ENCRYPT_OUTPUT=$(cd "${INSTALL_DIR}" && python3 -c "
import sys, os
sys.path.insert(0, os.getcwd())
from scripts.generate_encryption_keys import generate_encryption_key
print('CREDENTIAL_KEY=' + generate_encryption_key())
print('MUSIC_KEY=' + generate_encryption_key())
print('TOTP_KEY=' + generate_encryption_key())
" 2>&1) || {
        log_error "Encryption Key-Generierung fehlgeschlagen: $ENCRYPT_OUTPUT"
        return 1
    }
    CREDENTIAL_KEY=$(echo "$ENCRYPT_OUTPUT" | grep "CREDENTIAL_KEY=" | head -n1 | sed 's/^CREDENTIAL_KEY=//' | tr -d '\r\n')
    MUSIC_KEY=$(echo "$ENCRYPT_OUTPUT" | grep "MUSIC_KEY=" | head -n1 | sed 's/^MUSIC_KEY=//' | tr -d '\r\n')
    TOTP_KEY=$(echo "$ENCRYPT_OUTPUT" | grep "TOTP_KEY=" | head -n1 | sed 's/^TOTP_KEY=//' | tr -d '\r\n')

    if [ -z "$VAPID_PRIVATE" ] || [ -z "$VAPID_PUBLIC" ] || [ ${#VAPID_PRIVATE} -lt 40 ]; then
        log_error "VAPID Keys ungültig"
        return 1
    fi
    if [ -z "$CREDENTIAL_KEY" ] || [ -z "$MUSIC_KEY" ] || [ -z "$TOTP_KEY" ]; then
        log_error "Encryption Keys ungültig"
        return 1
    fi

    if is_yes "$INSTALL_ONLYOFFICE" && [ -z "${ONLYOFFICE_SECRET:-}" ]; then
        ONLYOFFICE_SECRET=$(generate_secret)
    fi

    log_success "Alle Keys generiert"
    return 0
}

merge_env_file() {
    local src="$1"
    local dest="$2"
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// /}" ]] && continue
        if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
            set_env_var "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "$dest"
        fi
    done < "$src"
}

step_env() {
    cd "$INSTALL_DIR" || return 1

    if [ "$ENV_MODE" = "file" ] && [ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ]; then
        log_info "Übernehme .env aus $ENV_FILE"
        cp "$ENV_FILE" .env
    elif [ ! -f .env ]; then
        if [ -f docs/env.example ]; then
            cp docs/env.example .env
        else
            touch .env
        fi
    fi

    if [ "$ENV_MODE" != "file" ]; then
        generate_keys || return 1
    else
        # Bei file-Modus fehlende Secrets nur ergänzen wenn leer
        if ! grep -q '^SECRET_KEY=.\+' .env 2>/dev/null; then
            generate_keys || return 1
        fi
    fi

    # Secrets / Core
    [ -n "${FLASK_SECRET:-}" ] && set_env_var "SECRET_KEY" "$FLASK_SECRET" .env
    set_env_var "FLASK_ENV" "production" .env
    set_env_var "TIMEZONE" "${TIMEZONE:-Europe/Berlin}" .env
    # Secure-Cookies nur bei HTTPS; sonst speichert der Browser die Session nicht
    # und Setup/Login brechen nach Account-Erstellung ab.
    if is_yes "${SETUP_SSL:-n}"; then
        set_env_var "SESSION_COOKIE_SECURE" "True" .env
    else
        set_env_var "SESSION_COOKIE_SECURE" "False" .env
    fi

    if [ -n "${DB_USER:-}" ] && [ -n "${DB_PASS:-}" ] && [ -n "${DB_NAME:-}" ]; then
        DB_PASS_URI=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$DB_PASS")
        set_env_var "DATABASE_URI" "mysql+pymysql://${DB_USER}:${DB_PASS_URI}@localhost/${DB_NAME}" .env
    fi

    [ -n "${VAPID_PUBLIC:-}" ] && set_env_var "VAPID_PUBLIC_KEY" "$VAPID_PUBLIC" .env
    [ -n "${VAPID_PRIVATE:-}" ] && set_env_var "VAPID_PRIVATE_KEY" "$VAPID_PRIVATE" .env
    set_env_var "VAPID_CLAIM_EMAIL" "${VAPID_CLAIM_EMAIL:-admin@example.com}" .env

    [ -n "${CREDENTIAL_KEY:-}" ] && set_env_var "CREDENTIAL_ENCRYPTION_KEY" "$CREDENTIAL_KEY" .env
    [ -n "${MUSIC_KEY:-}" ] && set_env_var "MUSIC_ENCRYPTION_KEY" "$MUSIC_KEY" .env
    [ -n "${TOTP_KEY:-}" ] && set_env_var "TOTP_ENCRYPTION_KEY" "$TOTP_KEY" .env

    # OnlyOffice
    if is_yes "$INSTALL_ONLYOFFICE"; then
        set_env_var "ONLYOFFICE_ENABLED" "True" .env
        set_env_var "ONLYOFFICE_DOCUMENT_SERVER_URL" "/onlyoffice" .env
        [ -n "${ONLYOFFICE_SECRET:-}" ] && set_env_var "ONLYOFFICE_SECRET_KEY" "$ONLYOFFICE_SECRET" .env
        if [ -n "${DOMAIN:-}" ]; then
            if is_yes "$SETUP_SSL"; then
                set_env_var "ONLYOFFICE_PUBLIC_URL" "https://${DOMAIN}" .env
            else
                set_env_var "ONLYOFFICE_PUBLIC_URL" "http://${DOMAIN}" .env
            fi
        else
            set_env_var "ONLYOFFICE_PUBLIC_URL" "" .env
        fi
    else
        set_env_var "ONLYOFFICE_ENABLED" "False" .env
    fi

    # Redis
    if is_yes "$SETUP_REDIS"; then
        set_env_var "REDIS_ENABLED" "True" .env
        set_env_var "REDIS_URL" "redis://localhost:6379/0" .env
    else
        set_env_var "REDIS_ENABLED" "False" .env
    fi

    # FFmpeg / Media Downloader
    if is_yes "$INSTALL_MEDIA_DOWNLOADER"; then
        FFMPEG_PATH="${FFMPEG_PATH:-$(command -v ffmpeg 2>/dev/null || echo /usr/bin/ffmpeg)}"
        set_env_var "FFMPEG_PATH" "$FFMPEG_PATH" .env
        set_env_var "MEDIA_DOWNLOADER_PLAYER_CLIENT" "${MEDIA_DOWNLOADER_PLAYER_CLIENT:-ios,web_creator,mweb}" .env
        if [ -n "${MEDIA_DOWNLOADER_COOKIES_FILE:-}" ]; then
            set_env_var "MEDIA_DOWNLOADER_COOKIES_FILE" "$MEDIA_DOWNLOADER_COOKIES_FILE" .env
        fi
        log_info "Media Downloader: player_client=ios,web_creator,mweb (Cookie-Datei nur optional, siehe docs/INSTALLATION.md)"
    fi

    # Mail
    set_env_var "MAIL_SERVER" "${MAIL_SERVER:-}" .env
    set_env_var "MAIL_PORT" "${MAIL_PORT:-587}" .env
    set_env_var "MAIL_USE_TLS" "${MAIL_USE_TLS:-True}" .env
    set_env_var "MAIL_USE_SSL" "${MAIL_USE_SSL:-False}" .env
    set_env_var "MAIL_USERNAME" "${MAIL_USERNAME:-}" .env
    set_env_var "MAIL_PASSWORD" "${MAIL_PASSWORD:-}" .env
    set_env_var "MAIL_DEFAULT_SENDER" "${MAIL_DEFAULT_SENDER:-}" .env
    set_env_var "MAIL_SENDER_NAME" "${MAIL_SENDER_NAME:-}" .env
    set_env_var "IMAP_SERVER" "${IMAP_SERVER:-}" .env
    set_env_var "IMAP_PORT" "${IMAP_PORT:-993}" .env
    set_env_var "IMAP_USE_SSL" "${IMAP_USE_SSL:-True}" .env

    # Optional: zusätzliche Overrides aus ENV_FILE mergen (nach auto-Werten)
    if [ "$ENV_MODE" = "file" ] && [ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ]; then
        log_info "Mergen erneuter Overrides aus $ENV_FILE (Priorität Datei)"
        merge_env_file "$ENV_FILE" .env
    fi

    # Manual mode: allow overriding a few critical values if still placeholders
    if [ "$ENV_MODE" = "manual" ] && ! is_yes "$NON_INTERACTIVE"; then
        log_info "Manual .env: kritische Werte können überschrieben werden (Enter = behalten)"
        local _cur
        _cur=$(grep "^SECRET_KEY=" .env | cut -d= -f2-)
        read -r -p "SECRET_KEY [gesetzt]: " _v
        [ -n "$_v" ] && set_env_var "SECRET_KEY" "$_v" .env
        if is_yes "$INSTALL_ONLYOFFICE"; then
            read -r -p "ONLYOFFICE_SECRET_KEY [aktuell gesetzt]: " _v
            [ -n "$_v" ] && { ONLYOFFICE_SECRET="$_v"; set_env_var "ONLYOFFICE_SECRET_KEY" "$_v" .env; }
        fi
    fi

    chmod 600 .env
    chown www-data:www-data .env 2>/dev/null || true
    log_success ".env-Datei konfiguriert"
    return 0
}
