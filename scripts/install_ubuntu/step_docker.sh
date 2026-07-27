#!/bin/bash
# Docker (für OnlyOffice Document Server)

step_docker() {
    if ! is_yes "$INSTALL_ONLYOFFICE" && ! is_yes "$INSTALL_DOCKER"; then
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
        systemctl enable docker >/dev/null 2>&1 || true
        systemctl start docker >/dev/null 2>&1 || true
        sleep 3
        if docker info >/dev/null 2>&1; then
            log_success "Docker-Daemon läuft"
            return 0
        fi
        log_error "Docker installiert, aber Daemon nicht erreichbar"
        systemctl status docker --no-pager 2>&1 | tail -20 || true
        return 1
    fi

    log_info "Installiere Docker (offizielles Docker CE Repo)..."
    install -m 0755 -d /etc/apt/keyrings
    if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
        if ! curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg; then
            log_error "Docker GPG-Key konnte nicht geladen werden"
            return 1
        fi
        chmod a+r /etc/apt/keyrings/docker.gpg
    fi

    local codename
    codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      ${codename} stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    if ! apt-get update -qq; then
        log_error "apt-get update für Docker-Repo fehlgeschlagen"
        return 1
    fi

    if ! apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; then
        log_error "Docker-Pakete konnten nicht installiert werden"
        return 1
    fi

    systemctl enable docker >/dev/null 2>&1 || true
    systemctl start docker >/dev/null 2>&1 || true

    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if docker info >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done

    if ! docker info >/dev/null 2>&1; then
        log_error "Docker installiert, aber Daemon startet nicht"
        systemctl status docker --no-pager 2>&1 | tail -20 || true
        return 1
    fi

    # OnlyOffice Docs Image basiert auf ubuntu:24.04 – braucht aktuelle Docker-Engine
    local docker_ver
    docker_ver="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?')"
    log_success "Docker installiert (Server ${docker_ver})"
    return 0
}
