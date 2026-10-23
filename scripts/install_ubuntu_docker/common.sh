#!/bin/bash
# Hilfsfunktionen – Docker-Installer (an install_ubuntu/common.sh angelehnt)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

DEFAULT_REPO_URL="https://github.com/iAmCriptic/Prismateams_web.git"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_manual() { echo -e "${YELLOW}[MANUELL]${NC} $1"; }

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

prompt_or_default() {
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
    local var_name="$1"
    local prompt_text="$2"
    local default_yn="${3:-j}"
    local current
    eval "current=\$$var_name"
    if [ -n "$current" ]; then
        log_info "${prompt_text%:*} (via Option): $current"
        return 0
    fi
    if is_yes "$NON_INTERACTIVE"; then
        eval "$var_name=\"\$default_yn\""
        log_info "${prompt_text%:*} (Default, non-interactive): $default_yn"
        return 0
    fi
    local hint="j/n"
    [ "$default_yn" = "j" ] && hint="J/n"
    [ "$default_yn" = "n" ] && hint="j/N"
    local answer
    read -r -p "$prompt_text [$hint]: " answer
    answer=${answer:-$default_yn}
    if is_yes "$answer"; then
        eval "$var_name=\"j\""
    else
        eval "$var_name=\"n\""
    fi
}

set_env_var() {
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

APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-180}"
UBUNTU_VERSION_ID=""
UBUNTU_CODENAME=""

prepare_apt_environment() {
    export DEBIAN_FRONTEND=noninteractive
    export NEEDRESTART_MODE=a
    export NEEDRESTART_SUSPEND=1
    mkdir -p /etc/needrestart/conf.d
    cat > /etc/needrestart/conf.d/99-prismateams-auto.conf <<'EOF'
$nrconf{restart} = 'a';
EOF
    if command -v cloud-init >/dev/null 2>&1; then
        log_info "Warte auf cloud-init..."
        if command -v timeout >/dev/null 2>&1; then
            timeout 300 cloud-init status --wait >/dev/null 2>&1 || true
        else
            cloud-init status --wait >/dev/null 2>&1 || true
        fi
    fi
    systemctl stop unattended-upgrades.service >/dev/null 2>&1 || true
    systemctl stop apt-daily.service apt-daily-upgrade.service >/dev/null 2>&1 || true
}

apt_update() {
    DEBIAN_FRONTEND=noninteractive apt-get \
        -o DPkg::Lock::Timeout="${APT_LOCK_TIMEOUT}" \
        update "$@"
}

apt_install() {
    DEBIAN_FRONTEND=noninteractive apt-get \
        -o DPkg::Lock::Timeout="${APT_LOCK_TIMEOUT}" \
        install -y "$@"
}

ubuntu_codename() {
    if [ -n "${UBUNTU_CODENAME:-}" ]; then
        echo "$UBUNTU_CODENAME"
        return 0
    fi
    # shellcheck source=/dev/null
    . /etc/os-release
    echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}"
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
        log_error "Konnte /etc/os-release nicht finden."
        exit 1
    fi
    # shellcheck source=/dev/null
    . /etc/os-release
    if [ "$ID" != "ubuntu" ]; then
        log_error "Dieses Skript ist nur für Ubuntu gedacht!"
        exit 1
    fi
    UBUNTU_VERSION_ID="${VERSION_ID}"
    UBUNTU_CODENAME="${UBUNTU_CODENAME:-$VERSION_CODENAME}"
    case "$VERSION_ID" in
        24.04|24.04.*|26.04|26.04.*)
            log_info "Ubuntu ${VERSION_ID} (${UBUNTU_CODENAME}) erkannt"
            ;;
        *)
            log_warning "Empfohlen: Ubuntu 24.04 / 26.04 LTS (aktuell: $VERSION_ID)"
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

domain_is_hostname() {
    local d="${1:-}"
    [ -n "$d" ] || return 1
    if [[ "$d" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        return 1
    fi
    if [[ "$d" == *:* ]]; then
        return 1
    fi
    return 0
}

mirotalk_meet_hostname() {
    if domain_is_hostname "${DOMAIN:-}"; then
        echo "meet.${DOMAIN}"
    fi
}

mirotalk_public_scheme() {
    if is_yes "${SETUP_SSL:-n}"; then
        echo "https"
    else
        echo "http"
    fi
}

mirotalk_public_url() {
    local host
    host=$(mirotalk_meet_hostname)
    if [ -n "$host" ]; then
        echo "$(mirotalk_public_scheme)://${host}"
        return 0
    fi
    if [ -n "${DOMAIN:-}" ]; then
        echo "http://${DOMAIN}:${MIROTALK_HOST_PORT:-3010}"
        return 0
    fi
    local lan
    lan=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [ -n "$lan" ]; then
        echo "http://${lan}:${MIROTALK_HOST_PORT:-3010}"
        return 0
    fi
    echo "http://127.0.0.1:${MIROTALK_HOST_PORT:-3010}"
}

mirotalk_portal_origin() {
    local scheme
    scheme=$(mirotalk_public_scheme)
    if [ -z "${DOMAIN:-}" ]; then
        return 0
    fi
    if domain_is_hostname "${DOMAIN}"; then
        echo "${scheme}://${DOMAIN}"
    else
        echo "http://${DOMAIN}"
    fi
}

detect_public_ip() {
    local ip
    if [[ "${DOMAIN:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "${DOMAIN}"
        return 0
    fi
    ip=$(curl -4 -fsS --max-time 5 https://ifconfig.me 2>/dev/null || true)
    if [ -z "$ip" ]; then
        ip=$(curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)
    fi
    if [ -z "$ip" ]; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    echo "${ip}"
}

compose_profile_args() {
    local args=()
    if is_yes "${INSTALL_ONLYOFFICE:-n}"; then
        args+=(--profile onlyoffice)
    fi
    if is_yes "${INSTALL_EXCALIDRAW:-n}"; then
        args+=(--profile excalidraw)
    fi
    if is_yes "${INSTALL_MIROTALK:-n}"; then
        args+=(--profile mirotalk)
    fi
    echo "${args[@]}"
}

docker_compose() {
    # docker compose (Plugin) bevorzugen
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose "$@"
    else
        log_error "docker compose nicht gefunden"
        return 1
    fi
}

init_defaults() {
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
    INSTALL_MIROTALK="${INSTALL_MIROTALK:-}"
    APP_HOST_PORT="${APP_HOST_PORT:-5000}"
    EUROOFFICE_HOST_PORT="${EUROOFFICE_HOST_PORT:-8080}"
    EXCALIDRAW_HOST_PORT="${EXCALIDRAW_HOST_PORT:-8082}"
    MIROTALK_HOST_PORT="${MIROTALK_HOST_PORT:-3010}"
    MIROTALK_UDP_MIN="${MIROTALK_UDP_MIN:-40000}"
    MIROTALK_UDP_MAX="${MIROTALK_UDP_MAX:-40100}"
    TIMEZONE="${TIMEZONE:-Europe/Berlin}"
    VAPID_CLAIM_EMAIL="${VAPID_CLAIM_EMAIL:-}"
    NON_INTERACTIVE="${NON_INTERACTIVE:-n}"
    CONTINUE_ON_ERROR="${CONTINUE_ON_ERROR:-n}"
    INSTALL_ABORTED="${INSTALL_ABORTED:-0}"
    DB_PASS_GENERATED="${DB_PASS_GENERATED:-0}"
}
