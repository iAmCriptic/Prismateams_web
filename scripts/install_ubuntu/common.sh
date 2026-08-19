#!/bin/bash
# Gemeinsame Hilfsfunktionen für den Ubuntu-Installer

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

DEFAULT_REPO_URL="https://github.com/iAmCriptic/Prismateams_web.git"

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_manual() {
    echo -e "${YELLOW}[MANUELL]${NC} $1"
}

error_exit() {
    log_error "$1"
    INSTALL_ABORTED=1
    if declare -f print_summary >/dev/null 2>&1; then
        print_summary || true
    fi
    exit 1
}

is_yes() {
    [[ "$1" =~ ^[JjYy]$ ]] || [[ "$1" == "1" ]] || [[ "$1" == "true" ]] || [[ "$1" == "True" ]]
}

is_no() {
    [[ "$1" =~ ^[Nn]$ ]] || [[ "$1" == "0" ]] || [[ "$1" == "false" ]] || [[ "$1" == "False" ]]
}

generate_password() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-32
}

generate_secret() {
    openssl rand -hex 32
}

require_value() {
    local name="$1"
    local value="$2"
    if [ -z "$value" ]; then
        if is_yes "$NON_INTERACTIVE"; then
            error_exit "Pflichtwert fehlt (non-interactive): $name"
        fi
        return 1
    fi
    return 0
}

prompt_or_default() {
    # prompt_or_default VAR "Frage" "Default"
    local var_name="$1"
    local prompt_text="$2"
    local default_val="${3:-}"
    local current
    eval "current=\$$var_name"
    if [ -n "$current" ]; then
        log_info "${prompt_text%:*} (via Option/Vorgabe): $current"
        return 0
    fi
    if is_yes "$NON_INTERACTIVE"; then
        if [ -n "$default_val" ]; then
            eval "$var_name=\"\$default_val\""
            log_info "${prompt_text%:*} (Default, non-interactive): $default_val"
            return 0
        fi
        error_exit "Pflichtwert fehlt (non-interactive): $var_name"
    fi
    local answer
    if [ -n "$default_val" ]; then
        read -r -p "$prompt_text [$default_val]: " answer
        answer=${answer:-$default_val}
    else
        read -r -p "$prompt_text: " answer
    fi
    eval "$var_name=\"\$answer\""
}

prompt_yes_no() {
    # prompt_yes_no VAR "Frage" "Default j|n"
    local var_name="$1"
    local prompt_text="$2"
    local default_val="${3:-j}"
    local current
    eval "current=\$$var_name"
    if [ -n "$current" ]; then
        if is_yes "$current"; then
            log_info "$prompt_text: ja (via Option)"
            eval "$var_name=j"
        else
            log_info "$prompt_text: nein (via Option)"
            eval "$var_name=n"
        fi
        return 0
    fi
    if is_yes "$NON_INTERACTIVE"; then
        eval "$var_name=\"\$default_val\""
        log_info "$prompt_text: $default_val (Default, non-interactive)"
        return 0
    fi
    local answer
    read -r -p "$prompt_text (j/n) [$default_val]: " answer
    answer=${answer:-$default_val}
    if is_yes "$answer"; then
        eval "$var_name=j"
    else
        eval "$var_name=n"
    fi
}

prompt_secret() {
    local var_name="$1"
    local prompt_text="$2"
    local current
    eval "current=\$$var_name"
    if [ -n "$current" ]; then
        log_info "${prompt_text%:*}: (gesetzt via Option)"
        return 0
    fi
    if is_yes "$NON_INTERACTIVE"; then
        return 0
    fi
    local answer
    read -r -sp "$prompt_text: " answer
    echo
    eval "$var_name=\"\$answer\""
}

set_env_var() {
    # set_env_var KEY VALUE [file]
    local key="$1"
    local value="$2"
    local file="${3:-.env}"
    local tmp
    tmp=$(mktemp)
    if [ -f "$file" ] && grep -q "^${key}=" "$file" 2>/dev/null; then
        awk -v k="$key" -v v="$value" '
            BEGIN { done=0 }
            index($0, k "=") == 1 && !done { print k "=" v; done=1; next }
            { print }
            END { if (!done) print k "=" v }
        ' "$file" > "$tmp"
        mv "$tmp" "$file"
    else
        echo "${key}=${value}" >> "$file"
        rm -f "$tmp"
    fi
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "Dieses Skript muss als root ausgeführt werden!"
        log_info "Verwenden Sie: sudo $0"
        exit 1
    fi
}

check_ubuntu() {
    if [ ! -f /etc/os-release ]; then
        log_error "Konnte /etc/os-release nicht finden. Nicht Ubuntu?"
        exit 1
    fi

    # shellcheck source=/dev/null
    . /etc/os-release

    if [ "$ID" != "ubuntu" ]; then
        log_error "Dieses Skript ist nur für Ubuntu gedacht!"
        exit 1
    fi

    # Unterstützte LTS-Batches: 24.04 (Noble) und 26.04 (Resolute)
    case "$VERSION_ID" in
        24.04|26.04)
            log_info "Ubuntu $VERSION_ID erkannt (unterstützt)"
            ;;
        *)
            log_warning "Dieses Skript ist für Ubuntu 24.04 / 26.04 LTS freigegeben. Aktuelle Version: $VERSION_ID"
            if is_yes "$NON_INTERACTIVE"; then
                log_warning "Non-interactive: fahre trotzdem fort"
            else
                read -r -p "Fortfahren? (j/n): " -n 1 REPLY
                echo
                if [[ ! $REPLY =~ ^[JjYy]$ ]]; then
                    exit 1
                fi
            fi
            ;;
    esac
}

validate_gunicorn_port() {
    if ! [[ "$GUNICORN_PORT" =~ ^[0-9]+$ ]]; then
        log_error "Ungültiger Port: $GUNICORN_PORT (nur Ziffern erlaubt)"
        return 1
    fi
    if [ "$GUNICORN_PORT" -lt 1024 ] || [ "$GUNICORN_PORT" -gt 65535 ]; then
        log_error "Port muss zwischen 1024 und 65535 liegen (angegeben: $GUNICORN_PORT)"
        return 1
    fi
    if command -v ss &>/dev/null; then
        if ss -tln | grep -q ":${GUNICORN_PORT} "; then
            log_warning "Port ${GUNICORN_PORT} ist bereits belegt. Gunicorn-Start könnte fehlschlagen."
        fi
    fi
    return 0
}

print_manual_webserver_hint() {
    echo
    log_manual "=== Webserver manuell einrichten (Standard-Konfiguration des Skripts) ==="
    log_manual "Gunicorn laeuft auf: http://127.0.0.1:${GUNICORN_PORT:-5000}"
    log_manual "Systemd-Service: /etc/systemd/system/teamportal.service"
    echo
    log_manual "Nginx (Standard):"
    log_manual "  1. apt install nginx"
    log_manual "  2. VHost: /etc/nginx/sites-available/teamportal"
    log_manual "  3. Upstream: server 127.0.0.1:${GUNICORN_PORT:-5000};"
    log_manual "  4. Proxy-Pfade: / -> Gunicorn, /onlyoffice -> :8080"
    log_manual "  5. ln -sf /etc/nginx/sites-available/teamportal /etc/nginx/sites-enabled/"
    log_manual "  6. nginx -t && systemctl enable nginx && systemctl restart nginx"
    log_manual "  7. Firewall: ufw allow 'Nginx Full'"
    log_manual "  8. SSL (optional): certbot --nginx -d IHRE-DOMAIN"
    echo
    log_manual "Details: docs/INSTALLATION.md (Schritt 11-13)"
    echo
}

print_manual_onlyoffice_hint() {
    echo
    log_manual "=== OnlyOffice Docs (Document Server) manuell einrichten ==="
    log_manual "  Hinweis: Portal braucht Document Server, NICHT Community Server/Workspace."
    log_manual "  Offiziell: https://github.com/ONLYOFFICE/Docker-DocumentServer"
    log_manual "  1. Docker installieren (docs/INSTALLATION.md Schritt 2)"
    log_manual "  2. Volumes: mkdir -p /var/lib/onlyoffice/DocumentServer/{data,logs,lib,fonts}"
    log_manual "  3. Schriftarten (PDF/Druck): nur ttf-mscorefonts-installer (Arial/Times/…)"
    log_manual "     TTFs nach /var/lib/onlyoffice/DocumentServer/fonts kopieren."
    log_manual "     Carlito/Liberation NICHT kopieren (liegen im Image; Duplikate zerlegen Calibri)"
    log_manual "  4. Container:"
    log_manual "       docker pull onlyoffice/documentserver:latest"
    log_manual "       docker run -d --name onlyoffice-documentserver --restart=always \\"
    log_manual "         -p 127.0.0.1:8080:80 \\"
    log_manual "         -v /var/lib/onlyoffice/DocumentServer/logs:/var/log/onlyoffice \\"
    log_manual "         -v /var/lib/onlyoffice/DocumentServer/data:/var/www/onlyoffice/Data \\"
    log_manual "         -v /var/lib/onlyoffice/DocumentServer/lib:/var/lib/onlyoffice \\"
    log_manual "         -v /var/lib/onlyoffice/DocumentServer/fonts:/usr/share/fonts/truetype/custom \\"
    log_manual "         -e JWT_ENABLED=true -e JWT_SECRET=IHR-SECRET \\"
    log_manual "         -e ALLOW_PRIVATE_IP_ADDRESS=true \\"
    log_manual "         onlyoffice/documentserver:latest"
    log_manual "  5. Font-Index: Container startet den Index selbst. Spaeter neue TTFs:"
    log_manual "     docker restart onlyoffice-documentserver (kein Live-generate-allfonts)"
    log_manual "  6. In .env: ONLYOFFICE_ENABLED=True, ONLYOFFICE_DOCUMENT_SERVER_URL=/onlyoffice,"
    log_manual "     ONLYOFFICE_SECRET_KEY=<gleicher JWT_SECRET>"
    log_manual "  7. Webserver-Proxy fuer /onlyoffice und /cache auf 127.0.0.1:8080"
    echo
    log_manual "Details: docs/INSTALLATION.md (Schritt 5, Schriftarten)"
    echo
}

print_manual_media_downloader_hint() {
    echo
    log_manual "=== Media Downloader manuell einrichten ==="
    log_manual "  1. FFmpeg installieren: apt install -y ffmpeg"
    log_manual "  2. In .env: FFMPEG_PATH=$(command -v ffmpeg 2>/dev/null || echo /usr/bin/ffmpeg)"
    log_manual "  3. Modul aktivieren: Einstellungen -> Administration -> Module -> Media Downloader"
    log_manual "  4. Standard: MEDIA_DOWNLOADER_PLAYER_CLIENT=ios,web_creator,mweb (Bot-Check-Workaround)"
    log_manual "  5. Optional bei Altersfreigabe/hartnaeckigen Blocks:"
    log_manual "       MEDIA_DOWNLOADER_COOKIES_FILE=/etc/prismateams/yt-cookies.txt"
    log_manual "       (Netscape cookies.txt, chmod 600, Owner www-data — siehe docs/INSTALLATION.md)"
    echo
}

print_manual_mysql_hint() {
    echo
    log_manual "=== MySQL manuell einrichten ==="
    log_manual "  1. apt install mysql-server"
    log_manual "  2. CREATE DATABASE ${DB_NAME:-teamportal} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    log_manual "  3. CREATE USER '${DB_USER:-teamportal}'@'localhost' IDENTIFIED BY 'PASSWORT';"
    log_manual "  4. GRANT ALL PRIVILEGES ON ${DB_NAME:-teamportal}.* TO '${DB_USER:-teamportal}'@'localhost';"
    log_manual "  5. DATABASE_URI in .env setzen"
    echo
}

print_manual_redis_hint() {
    echo
    log_manual "=== Redis manuell einrichten ==="
    log_manual "  1. apt install redis-server && systemctl enable --now redis-server"
    log_manual "  2. In .env: REDIS_ENABLED=True, REDIS_URL=redis://localhost:6379/0"
    log_manual "  3. Empfohlen bei mehreren Gunicorn-Workern"
    echo
}

print_manual_gunicorn_hint() {
    echo
    log_manual "=== Gunicorn manuell einrichten ==="
    log_manual "  1. cd $INSTALL_DIR && source venv/bin/activate && pip install gunicorn"
    log_manual "  2. FLASK_ENV=production python scripts/init_database.py"
    log_manual "  3. Systemd-Unit /etc/systemd/system/teamportal.service anlegen"
    log_manual "  4. gunicorn --workers ${GUNICORN_WORKERS:-1} --bind 127.0.0.1:${GUNICORN_PORT:-5000} wsgi:app"
    log_manual "  5. systemctl enable --now teamportal"
    echo
}

print_manual_custom_port_hint() {
    if [ -n "${GUNICORN_PORT:-}" ] && [ "$GUNICORN_PORT" != "5000" ]; then
        echo
        log_manual "=== Abweichender Gunicorn-Port: ${GUNICORN_PORT} ==="
        log_manual "Der Webserver muss auf http://127.0.0.1:${GUNICORN_PORT} weiterleiten."
        echo
    fi
}

print_manual_excalidraw_hint() {
    echo
    log_manual "=== Excalidraw Room (Kollaboration) manuell einrichten ==="
    log_manual "  1. Docker installieren (docs/INSTALLATION.md Schritt 2)"
    log_manual "  2. Container (nur Loopback):"
    log_manual "       docker pull excalidraw/excalidraw-room:latest"
    log_manual "       docker run -d --name excalidraw-room --restart=always \\"
    log_manual "         -p 127.0.0.1:8082:80 -e PORT=80 \\"
    log_manual "         excalidraw/excalidraw-room:latest"
    log_manual "  3. In .env: EXCALIDRAW_ENABLED=True, EXCALIDRAW_ROOM_URL=/excalidraw-room"
    log_manual "  4. Nginx: Location /excalidraw-room/ -> 127.0.0.1:8082/ mit WebSocket-Upgrade"
    echo
}

init_defaults() {
    GUNICORN_PORT="${GUNICORN_PORT:-}"
    GUNICORN_WORKERS="${GUNICORN_WORKERS:-}"
    SETUP_GUNICORN="${SETUP_GUNICORN:-}"
    GIT_BRANCH="${GIT_BRANCH:-}"
    REPO_URL="${REPO_URL:-}"
    INSTALL_DIR="${INSTALL_DIR:-}"
    SETUP_WEBSERVER="${SETUP_WEBSERVER:-}"
    WEBSERVER_TYPE="${WEBSERVER_TYPE:-}"
    DOMAIN="${DOMAIN:-}"
    SETUP_SSL="${SETUP_SSL:-}"
    LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"
    INSTALL_ONLYOFFICE="${INSTALL_ONLYOFFICE:-}"
    INSTALL_EXCALIDRAW="${INSTALL_EXCALIDRAW:-}"
    INSTALL_MEDIA_DOWNLOADER="${INSTALL_MEDIA_DOWNLOADER:-}"
    MEDIA_DOWNLOADER_COOKIES_FILE="${MEDIA_DOWNLOADER_COOKIES_FILE:-}"
    MEDIA_DOWNLOADER_PLAYER_CLIENT="${MEDIA_DOWNLOADER_PLAYER_CLIENT:-}"
    INSTALL_DOCKER="${INSTALL_DOCKER:-}"
    SETUP_MYSQL="${SETUP_MYSQL:-}"
    SETUP_REDIS="${SETUP_REDIS:-}"
    DB_NAME="${DB_NAME:-}"
    DB_USER="${DB_USER:-}"
    DB_PASS="${DB_PASS:-}"
    MYSQL_ROOT_PASS="${MYSQL_ROOT_PASS:-}"
    ENV_MODE="${ENV_MODE:-}"
    ENV_FILE="${ENV_FILE:-}"
    TIMEZONE="${TIMEZONE:-}"
    VAPID_CLAIM_EMAIL="${VAPID_CLAIM_EMAIL:-}"
    NON_INTERACTIVE="${NON_INTERACTIVE:-n}"
    CONTINUE_ON_ERROR="${CONTINUE_ON_ERROR:-n}"
    INSTALL_ABORTED="${INSTALL_ABORTED:-0}"
    MYSQL_ROOT_PASS_GENERATED="${MYSQL_ROOT_PASS_GENERATED:-0}"
    DB_PASS_GENERATED="${DB_PASS_GENERATED:-0}"
}
