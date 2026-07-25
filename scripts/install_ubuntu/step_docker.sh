#!/bin/bash
# Docker

step_docker() {
    if ! is_yes "$INSTALL_ONLYOFFICE"; then
        log_info "Docker nicht benötigt"
        return 2
    fi

    if command -v docker &> /dev/null; then
        log_info "Docker ist bereits installiert"
        return 0
    fi

    log_info "Installiere Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    systemctl start docker
    systemctl enable docker

    log_success "Docker installiert"
    return 0
}
