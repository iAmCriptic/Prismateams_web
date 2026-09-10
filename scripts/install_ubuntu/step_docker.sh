#!/bin/bash
# Docker (für Euro-Office Document Server)
# 26.04: Docker-CE-Repo „resolute“, Fallback noble, danach Ubuntu docker.io

_docker_write_repo() {
    local suite="$1"
    local key="$2"
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=${key}] https://download.docker.com/linux/ubuntu \
      ${suite} stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null
}

_docker_install_ubuntu_pkg() {
    log_warning "Fallback: Ubuntu-Paket docker.io (ohne Docker-CE-Repo)"
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
    if ! is_yes "$INSTALL_ONLYOFFICE" && ! is_yes "$INSTALL_EXCALIDRAW" && ! is_yes "$INSTALL_MIROTALK" && ! is_yes "$INSTALL_DOCKER"; then
        log_info "Docker nicht benötigt"
        return 2
    fi

    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        local docker_ver
        docker_ver="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unbekannt)"
        log_info "Docker ist bereits installiert und läuft (Server ${docker_ver})"
        return 0
    fi

    if command -v docker >/dev/null 2>&1; then
        log_info "Docker installiert, Daemon startet..."
        if _docker_start_daemon; then
            log_success "Docker-Daemon läuft"
            return 0
        fi
        log_error "Docker installiert, aber Daemon nicht erreichbar"
        systemctl status docker --no-pager 2>&1 | tail -20 || true
        return 1
    fi

    log_info "Installiere Docker (offizielles Docker CE Repo)..."
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
        log_warning "Docker-Repo für '${suite}' nicht verfügbar – versuche noble (24.04-kompatibel)"
        _docker_write_repo "noble" "$docker_key"
        if apt_update -qq; then
            repo_ok=1
        fi
    fi

    if [ "$repo_ok" -eq 1 ] && apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; then
        log_info "Docker CE installiert"
    else
        log_warning "Docker-CE-Pakete nicht installierbar"
        if ! _docker_install_ubuntu_pkg; then
            log_error "Weder Docker CE noch docker.io konnten installiert werden"
            return 1
        fi
    fi

    if ! _docker_start_daemon; then
        log_error "Docker installiert, aber Daemon startet nicht"
        systemctl status docker --no-pager 2>&1 | tail -20 || true
        journalctl -u docker -n 30 --no-pager 2>&1 || true
        return 1
    fi

    local docker_ver
    docker_ver="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?')"
    log_success "Docker installiert (Server ${docker_ver})"
    return 0
}
