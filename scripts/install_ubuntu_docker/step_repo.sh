#!/bin/bash
# Repository klonen / aktualisieren

step_repo() {
    REPO_URL="${REPO_URL:-$DEFAULT_REPO_URL}"
    mkdir -p "$(dirname "$INSTALL_DIR")"

    if [ -d "$INSTALL_DIR/.git" ]; then
        log_info "Repository vorhanden – aktualisiere..."
        cd "$INSTALL_DIR" || return 1
        git fetch origin --quiet || log_warning "git fetch fehlgeschlagen"
        if [ -n "$GIT_BRANCH" ]; then
            git checkout "$GIT_BRANCH" --quiet 2>/dev/null \
                || git checkout -b "$GIT_BRANCH" "origin/$GIT_BRANCH" --quiet \
                || { log_error "Branch nicht gefunden: $GIT_BRANCH"; return 1; }
            git pull origin "$GIT_BRANCH" --quiet || log_warning "git pull fehlgeschlagen"
        else
            git pull --quiet || log_warning "git pull fehlgeschlagen"
        fi
    elif [ -d "$INSTALL_DIR" ] && [ "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
        if [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
            log_info "Install-Dir enthält bereits docker-compose.yml – behalte Inhalt"
            cd "$INSTALL_DIR" || return 1
        else
            log_error "Verzeichnis $INSTALL_DIR existiert und ist kein Git-Repo"
            return 1
        fi
    else
        log_info "Klone $REPO_URL → $INSTALL_DIR"
        if [ -n "$GIT_BRANCH" ]; then
            git clone --branch "$GIT_BRANCH" --single-branch "$REPO_URL" "$INSTALL_DIR" || return 1
        else
            git clone "$REPO_URL" "$INSTALL_DIR" || return 1
        fi
        cd "$INSTALL_DIR" || return 1
    fi

    if [ ! -f "$INSTALL_DIR/docker-compose.yml" ] || [ ! -f "$INSTALL_DIR/Dockerfile" ]; then
        log_error "docker-compose.yml oder Dockerfile fehlt in $INSTALL_DIR"
        return 1
    fi

    log_success "Repository bereit: $INSTALL_DIR"
    return 0
}
