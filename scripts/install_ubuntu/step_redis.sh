#!/bin/bash
# Redis

step_redis() {
    if ! is_yes "$SETUP_REDIS"; then
        print_manual_redis_hint
        return 2
    fi

    if systemctl is-active --quiet redis-server; then
        log_info "Redis läuft bereits"
    else
        log_info "Starte Redis..."
        systemctl start redis-server || { log_error "Redis Start fehlgeschlagen"; return 1; }
        systemctl enable redis-server || { log_error "Redis Aktivierung fehlgeschlagen"; return 1; }
    fi

    log_info "Warte auf Redis-Service..."
    REDIS_READY=0
    for i in {1..10}; do
        if redis-cli ping > /dev/null 2>&1; then
            REDIS_READY=1
            break
        fi
        sleep 1
    done

    if [ $REDIS_READY -eq 0 ]; then
        log_warning "Redis antwortet nicht, fahre fort..."
    else
        log_success "Redis ist bereit"
    fi
    return 0
}
