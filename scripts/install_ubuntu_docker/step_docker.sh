#!/bin/bash
# Docker Engine + Compose-Plugin (immer Pflicht)

_docker_write_repo() {
    local suite="$1"
    local key="$2"
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=${key}] https://download.docker.com/linux/ubuntu \
      ${suite} stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null
}

_docker_install_ubuntu_pkg() {
    log_warning "Fallback: Ubuntu-Paket docker.io"
    rm -f /etc/apt/sources.list.d/docker.list /etc/apt/sources.list.d/docker.sources
    apt_update -qq || true
    if apt_install docker.io docker-compose-v2; then
        return 0
    fi
    apt_install docker.io
}

_docker_start_daemon() {
    systemctl enable docker >/dev/null 2>&1 || true
    systemctl start docker >/dev/null 2>&1 || true
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if docker info >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

step_docker() {
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        local docker_ver
        docker_ver="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unbekannt)"
        log_info "Docker läuft bereits (Server ${docker_ver})"
        if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
            log_warning "Compose fehlt – versuche Plugin zu installieren..."
            apt_install docker-compose-plugin 2>/dev/null || apt_install docker-compose-v2 2>/dev/null || true
        fi
        return 0
    fi

    if command -v docker >/dev/null 2>&1; then
        log_info "Docker installiert, Daemon startet..."
        if _docker_start_daemon; then
            log_success "Docker-Daemon läuft"
            return 0
        fi
        log_error "Docker-Daemon nicht erreichbar"
        return 1
    fi

    log_info "Installiere Docker CE..."
    install -m 0755 -d /etc/apt/keyrings
    local docker_key="/etc/apt/keyrings/docker.asc"
    if [ ! -f /etc/apt/keyrings/docker.asc ] && [ ! -f /etc/apt/keyrings/docker.gpg ]; then
        if ! curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc; then
            log_error "Docker GPG-Key konnte nicht geladen werden"
            return 1
        fi
        chmod a+r /etc/apt/keyrings/docker.asc
    fi
    if [ ! -f "$docker_key" ] && [ -f /etc/apt/keyrings/docker.gpg ]; then
        docker_key="/etc/apt/keyrings/docker.gpg"
    fi

    local suite
    suite="$(ubuntu_codename)"
    _docker_write_repo "$suite" "$docker_key"

    local repo_ok=0
    if apt_update -qq; then
        repo_ok=1
    elif [ "$suite" != "noble" ]; then
        log_warning "Docker-Repo für '${suite}' nicht verfügbar – Fallback noble"
        _docker_write_repo "noble" "$docker_key"
        if apt_update -qq; then
            repo_ok=1
        fi
    fi

    if [ "$repo_ok" -eq 1 ] && apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; then
        log_info "Docker CE installiert"
    else
        if ! _docker_install_ubuntu_pkg; then
            log_error "Docker-Installation fehlgeschlagen"
            return 1
        fi
    fi

    if ! _docker_start_daemon; then
        log_error "Docker-Daemon startet nicht"
        return 1
    fi

    if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
        log_error "docker compose nicht verfügbar"
        return 1
    fi

    log_success "Docker bereit ($(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?'))"
    return 0
}
