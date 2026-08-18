#!/bin/bash
# Excalidraw Integration (Prismateams Web)
#
# ARCHITEKTUR-HINWEIS:
# - Der Excalidraw Zeichnungs-Editor ist nativ im Flask-Portal integriert.
#   Alle Frontend-Bibliotheken (React, ReactDOM, Excalidraw, Socket.IO) liegen lokal unter app/static/vendor/.
# - Das Docker-Image excalidraw/excalidraw-room:latest dient als optionaler WebSocket-Backend-Server für Live-Kollaboration.
# - Port: 127.0.0.1:8082 — Nginx/Apache leiten /excalidraw-room per WebSocket weiter.

EXCALIDRAW_ROOM_IMAGE="${EXCALIDRAW_ROOM_IMAGE:-excalidraw/excalidraw-room:latest}"
EXCALIDRAW_ROOM_HOST_PORT="${EXCALIDRAW_ROOM_HOST_PORT:-8082}"
EXCALIDRAW_ROOM_CONTAINER="${EXCALIDRAW_ROOM_CONTAINER:-excalidraw-room}"

_excalidraw_room_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "${EXCALIDRAW_ROOM_CONTAINER}"
}

_excalidraw_room_exists() {
    docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "${EXCALIDRAW_ROOM_CONTAINER}"
}

_excalidraw_port_in_use() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | grep -qE ":${port}\\s"
        return $?
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
        return $?
    fi
    return 1
}

step_excalidraw() {
    if ! is_yes "${INSTALL_EXCALIDRAW:-n}"; then
        print_manual_excalidraw_hint
        return 2
    fi

    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker ist nicht installiert — Excalidraw-Room übersprungen"
        print_manual_excalidraw_hint
        return 1
    fi

    log_info "=== Excalidraw Integration ==="
    if [ -f "${INSTALL_DIR}/scripts/download_excalidraw_vendor.py" ]; then
        log_info "Prüfe lokale Excalidraw UMD Vendor-Bibliotheken..."
        python3 "${INSTALL_DIR}/scripts/download_excalidraw_vendor.py" 2>/dev/null || log_warning "Vendor-Download Skript fehlgeschlagen (nutze CDN-Fallback)"
    fi
    docker pull "${EXCALIDRAW_ROOM_IMAGE}" || log_warning "Image-Pull fehlgeschlagen, versuche vorhandenen Cache"

    if _excalidraw_port_in_use "${EXCALIDRAW_ROOM_HOST_PORT}"; then
        if ! _excalidraw_room_running; then
            log_warning "Port ${EXCALIDRAW_ROOM_HOST_PORT} ist belegt, aber Container ${EXCALIDRAW_ROOM_CONTAINER} läuft nicht"
        fi
    fi

    if _excalidraw_room_exists; then
        if _excalidraw_room_running; then
            log_info "Container ${EXCALIDRAW_ROOM_CONTAINER} läuft bereits"
            return 0
        fi
        log_info "Starte vorhandenen Container ${EXCALIDRAW_ROOM_CONTAINER}"
        docker start "${EXCALIDRAW_ROOM_CONTAINER}" || return 1
        return 0
    fi

    docker run -d --restart=always \
        --name "${EXCALIDRAW_ROOM_CONTAINER}" \
        -p "127.0.0.1:${EXCALIDRAW_ROOM_HOST_PORT}:80" \
        -e PORT=80 \
        "${EXCALIDRAW_ROOM_IMAGE}" || return 1

    log_success "Excalidraw-Room auf 127.0.0.1:${EXCALIDRAW_ROOM_HOST_PORT}"
}
