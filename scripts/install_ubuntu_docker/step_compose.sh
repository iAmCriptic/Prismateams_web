#!/bin/bash
# docker compose build + up

step_compose() {
    cd "$INSTALL_DIR" || return 1

    if [ ! -f .env ]; then
        log_error ".env fehlt"
        return 1
    fi

    # shellcheck disable=SC2207
    local profiles
    profiles=( $(compose_profile_args) )

    log_info "docker compose build..."
    if ! docker_compose "${profiles[@]}" build; then
        log_error "compose build fehlgeschlagen"
        return 1
    fi

    log_info "docker compose up -d ${profiles[*]}..."
    if ! docker_compose "${profiles[@]}" up -d; then
        log_error "compose up fehlgeschlagen"
        docker_compose "${profiles[@]}" ps || true
        docker_compose "${profiles[@]}" logs --tail 80 app || true
        return 1
    fi

    log_info "Warte auf App (bis 120s)..."
    local i ready=0
    for i in $(seq 1 60); do
        if curl -sf "http://127.0.0.1:${APP_HOST_PORT:-5000}/" >/dev/null 2>&1; then
            ready=1
            log_success "App antwortet (${i}×2s)"
            break
        fi
        sleep 2
    done
    if [ "$ready" -eq 0 ]; then
        log_warning "App antwortet noch nicht – Container-Logs prüfen"
        docker_compose "${profiles[@]}" ps || true
        docker_compose "${profiles[@]}" logs --tail 40 app || true
    fi

    if is_yes "${INSTALL_ONLYOFFICE:-n}"; then
        log_info "Warte auf Euro-Office healthcheck (bis 180s)..."
        ready=0
        for i in $(seq 1 90); do
            if curl -sf "http://127.0.0.1:${EUROOFFICE_HOST_PORT:-8080}/healthcheck" 2>/dev/null | grep -qi true; then
                ready=1
                log_success "Euro-Office bereit"
                break
            fi
            sleep 2
        done
        [ "$ready" -eq 0 ] && log_warning "Euro-Office noch nicht bereit (kann länger brauchen)"
    fi

    log_success "Compose-Stack gestartet"
    docker_compose "${profiles[@]}" ps || true
    return 0
}
