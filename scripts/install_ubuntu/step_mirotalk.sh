#!/bin/bash
# MiroTalk SFU (Meetings-Modul) via Docker
#
# Hostname: eigener Host meet.${DOMAIN} → 127.0.0.1:3010 (Nginx/Apache).
# IP/LAN:   http://IP:3010 öffentlich, kein meet.IP (ohne Hosts-Datei nutzlos).
# WebRTC-Medien: UDP/TCP 40000–40100 (host network).
# Docs: https://docs.mirotalk.com/mirotalk-sfu/self-hosting/
# Image: mirotalk/sfu:latest

MIROTALK_IMAGE="${MIROTALK_IMAGE:-mirotalk/sfu:latest}"
MIROTALK_CONTAINER="${MIROTALK_CONTAINER:-mirotalksfu}"
MIROTALK_DATA_ROOT="${MIROTALK_DATA_ROOT:-/var/lib/mirotalk-sfu}"
MIROTALK_HOST_PORT="${MIROTALK_HOST_PORT:-3010}"
MIROTALK_UDP_MIN="${MIROTALK_UDP_MIN:-40000}"
MIROTALK_UDP_MAX="${MIROTALK_UDP_MAX:-40100}"
MIROTALK_HOST_USER="${MIROTALK_HOST_USER:-portal}"

_mirotalk_container_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "${MIROTALK_CONTAINER}"
}

_mirotalk_container_exists() {
    docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "${MIROTALK_CONTAINER}"
}

_mirotalk_detect_public_ip() {
    local ip
    # Bei Install mit LAN-IP als DOMAIN: ICE muss diese IP announcen, sonst
    # schlagen WebRTC-Verbindungen im lokalen Netz fehl (schwarzes iframe).
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

_mirotalk_write_env() {
    local env_file="${MIROTALK_DATA_ROOT}/.env"
    local announced="${MIROTALK_ANNOUNCED_IP:-}"
    local public_url portal_origin meet_host cors_origins embed_origins
    public_url=$(mirotalk_public_url)
    portal_origin=$(mirotalk_portal_origin)
    meet_host=$(mirotalk_meet_hostname)

    if [ -z "$announced" ]; then
        announced=$(_mirotalk_detect_public_ip)
    fi

    # CORS / Embed: Portal-Origin + öffentliche MiroTalk-URL (iframe-Parent = Portal)
    cors_origins="${public_url}"
    embed_origins=""
    if [ -n "$portal_origin" ]; then
        cors_origins="${portal_origin},${public_url}"
        embed_origins="${portal_origin}"
        # meet.-Host zusätzlich erlauben falls Browser den vHost direkt öffnet
        if [ -n "$meet_host" ]; then
            embed_origins="${portal_origin},$(mirotalk_public_scheme)://${meet_host}"
        fi
    else
        embed_origins="${public_url}"
    fi

    mkdir -p "${MIROTALK_DATA_ROOT}"

    cat > "${env_file}" <<EOF
NODE_ENV=production
SFU_ANNOUNCED_IP=${announced}
SFU_LISTEN_IP=0.0.0.0
SFU_MIN_PORT=${MIROTALK_UDP_MIN}
SFU_MAX_PORT=${MIROTALK_UDP_MAX}
SERVER_HOST_URL=${public_url}
SERVER_LISTEN_IP=${MIROTALK_LISTEN_IP:-127.0.0.1}
SERVER_LISTEN_PORT=${MIROTALK_HOST_PORT}
TRUST_PROXY=true
CORS_ORIGIN=${cors_origins}
ALLOWED_EMBED_ORIGINS=${embed_origins}
HOST_PROTECTED=true
HOST_USER_AUTH=false
HOST_USERS="${MIROTALK_HOST_USER}:${MIROTALK_HOST_PASSWORD}:Portal:*"
API_KEY_SECRET=${MIROTALK_API_KEY}
JWT_SECRET=${MIROTALK_JWT_SECRET}
JWT_EXPIRATION=8h
RECORDING_ENABLED=false
EOF

    chmod 640 "${env_file}"
    chown 1000:1000 "${env_file}" 2>/dev/null || true
    chown 1000:1000 "${MIROTALK_DATA_ROOT}" 2>/dev/null || true
    chmod 750 "${MIROTALK_DATA_ROOT}" 2>/dev/null || true

    log_info "MiroTalk .env geschrieben (${env_file})"
    log_info "SERVER_HOST_URL / MIROTALK_URL = ${public_url}"
    if [ -n "$announced" ]; then
        log_info "SFU_ANNOUNCED_IP=${announced}"
    else
        log_warning "Öffentliche IP nicht ermittelt – SFU_ANNOUNCED_IP in ${env_file} setzen"
    fi
    if [ -n "$meet_host" ]; then
        log_info "DNS: A/AAAA-Record ${meet_host} → Server-IP eintragen"
    else
        log_info "IP-/LAN-Modus: Browser nutzt ${public_url} (kein meet.-vHost nötig)"
    fi
}

step_mirotalk() {
    if ! is_yes "${INSTALL_MIROTALK:-n}"; then
        print_manual_mirotalk_hint
        return 2
    fi

    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker ist nicht installiert — MiroTalk SFU übersprungen"
        print_manual_mirotalk_hint
        return 1
    fi

    if ! docker info >/dev/null 2>&1; then
        log_info "Docker-Daemon nicht bereit – starte neu..."
        systemctl start docker >/dev/null 2>&1 || true
        sleep 3
        if ! docker info >/dev/null 2>&1; then
            log_error "Docker-Daemon nicht erreichbar (docker info fehlgeschlagen)"
            return 1
        fi
    fi

    log_info "=== MiroTalk SFU (Meetings) ==="

    if [ -z "${MIROTALK_API_KEY:-}" ]; then
        MIROTALK_API_KEY=$(generate_secret)
    fi
    if [ -z "${MIROTALK_HOST_PASSWORD:-}" ]; then
        MIROTALK_HOST_PASSWORD=$(generate_password)
    fi
    if [ -z "${MIROTALK_JWT_SECRET:-}" ]; then
        MIROTALK_JWT_SECRET=$(generate_secret)
    fi
    MIROTALK_HOST_USER="${MIROTALK_HOST_USER:-portal}"

    if ! domain_is_hostname "${DOMAIN:-}"; then
        MIROTALK_LISTEN_IP="0.0.0.0"
        log_warning "Keine Hostname-Domain – MiroTalk lauscht auf 0.0.0.0:${MIROTALK_HOST_PORT}"
        log_warning "Portal-.env bekommt MIROTALK_URL=http://IP:${MIROTALK_HOST_PORT} (kein meet.IP)"
        log_warning "Produktion: Hostname + DNS meet.DOMAIN + Nginx-Proxy empfehlen"
    else
        MIROTALK_LISTEN_IP="127.0.0.1"
        log_info "Hostname-Modus: MiroTalk nur Loopback, öffentlich über meet.${DOMAIN}"
    fi

    _mirotalk_write_env

    log_info "Lade MiroTalk SFU Image (${MIROTALK_IMAGE})..."
    if ! docker pull "${MIROTALK_IMAGE}"; then
        log_error "docker pull fehlgeschlagen: ${MIROTALK_IMAGE}"
        log_error "Quelle: https://hub.docker.com/r/mirotalk/sfu"
        return 1
    fi

    if _mirotalk_container_exists; then
        log_info "Entferne bestehenden Container ${MIROTALK_CONTAINER}..."
        docker stop "${MIROTALK_CONTAINER}" >/dev/null 2>&1 || true
        docker rm "${MIROTALK_CONTAINER}" >/dev/null 2>&1 || true
    fi

    log_info "Starte MiroTalk SFU (host network, HTTP ${MIROTALK_LISTEN_IP}:${MIROTALK_HOST_PORT})..."
    local run_err cid
    run_err="$(mktemp)"
    if ! docker run -d \
        --name "${MIROTALK_CONTAINER}" \
        --hostname "${MIROTALK_CONTAINER}" \
        --restart=always \
        --network host \
        --user 1000:1000 \
        -v "${MIROTALK_DATA_ROOT}/.env:/src/.env:ro" \
        "${MIROTALK_IMAGE}" >"${run_err}" 2>&1; then
        log_error "MiroTalk-Container konnte nicht gestartet werden"
        log_error "$(cat "${run_err}")"
        rm -f "${run_err}"
        return 1
    fi
    cid="$(tr -d '\r\n' <"${run_err}")"
    rm -f "${run_err}"
    log_info "Container gestartet: ${cid:0:12}"

    log_info "Warte auf MiroTalk SFU (bis 60s)..."
    local ready=0 i
    for i in $(seq 1 60); do
        if ! _mirotalk_container_running; then
            log_error "Container ${MIROTALK_CONTAINER} ist unerwartet gestoppt"
            docker logs --tail 60 "${MIROTALK_CONTAINER}" 2>&1 || true
            return 1
        fi
        if curl -sf "http://127.0.0.1:${MIROTALK_HOST_PORT}/" >/dev/null 2>&1; then
            ready=1
            log_success "MiroTalk SFU ist bereit (${i}s)"
            break
        fi
        sleep 1
    done

    if [ "$ready" -eq 0 ]; then
        log_warning "MiroTalk antwortet noch nicht nach 60s – Container läuft weiter"
        docker logs --tail 40 "${MIROTALK_CONTAINER}" 2>&1 || true
    fi

    log_info "UDP/TCP ${MIROTALK_UDP_MIN}-${MIROTALK_UDP_MAX} müssen in der Firewall offen sein"
    log_info "Portal-.env erhält dieselben Secrets: MIROTALK_API_KEY, MIROTALK_HOST_USER, MIROTALK_HOST_PASSWORD"
    if ! is_yes "${SETUP_SSL:-n}"; then
        log_warning "Ohne HTTPS: Browser Secure Context fehlt — Kamera/Mikrofon/WebRTC oft schwarz"
    fi
    log_success "MiroTalk SFU installiert (${MIROTALK_IMAGE})"
    log_success "Öffentliche Meet-URL: $(mirotalk_public_url)"
    return 0
}
