#!/bin/bash
# Repository klonen / aktualisieren

clone_repository() {
    local target_dir="$1"
    if [ -n "$GIT_BRANCH" ]; then
        log_info "Klone Repository (Branch: $GIT_BRANCH) nach $target_dir..."
        git clone --branch "$GIT_BRANCH" --single-branch "$REPO_URL" "$target_dir" || {
            log_error "Repository konnte nicht geklont werden (Branch: $GIT_BRANCH)"
            return 1
        }
    else
        log_info "Klone Repository nach $target_dir..."
        git clone "$REPO_URL" "$target_dir" || {
            log_error "Repository konnte nicht geklont werden"
            return 1
        }
    fi
    return 0
}

update_repository() {
    git fetch origin --quiet || log_warning "Git fetch fehlgeschlagen"

    if [ -n "$GIT_BRANCH" ]; then
        log_info "Wechsle auf Branch: $GIT_BRANCH"
        if ! git checkout "$GIT_BRANCH" --quiet 2>/dev/null; then
            if ! git checkout -b "$GIT_BRANCH" "origin/$GIT_BRANCH" --quiet; then
                log_error "Branch nicht gefunden: $GIT_BRANCH"
                return 1
            fi
        fi
        git pull origin "$GIT_BRANCH" --quiet || log_warning "Git pull fehlgeschlagen (Branch: $GIT_BRANCH)"
        log_success "Repository aktualisiert (Branch: $GIT_BRANCH)"
    else
        git pull origin main --quiet || git pull origin master --quiet || log_warning "Git pull fehlgeschlagen"
        log_success "Repository aktualisiert"
    fi
    return 0
}

step_repo() {
    REPO_URL="${REPO_URL:-$DEFAULT_REPO_URL}"

    if [ -n "$GIT_BRANCH" ]; then
        log_info "Gewählter Git-Branch: $GIT_BRANCH"
    else
        log_info "Git-Branch: Default (main/master)"
    fi
    log_info "Repository: $REPO_URL"

    mkdir -p "$INSTALL_DIR"

    if [ -d "$INSTALL_DIR/.git" ]; then
        log_info "Git-Repository bereits vorhanden in $INSTALL_DIR"
        cd "$INSTALL_DIR" || return 1

        CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
        local expected_a="$REPO_URL"
        local expected_b="${REPO_URL%.git}"
        if [ "$CURRENT_REMOTE" = "$expected_a" ] || [ "$CURRENT_REMOTE" = "$expected_b" ] \
           || [ "$CURRENT_REMOTE" = "${expected_a}.git" ]; then
            log_info "Korrektes Repository gefunden. Aktualisiere..."
            update_repository || return 1
        else
            if [ -n "$CURRENT_REMOTE" ]; then
                log_warning "Anderes Repository gefunden: $CURRENT_REMOTE"
                log_warning "Erwartet: $REPO_URL"
                if is_yes "$NON_INTERACTIVE"; then
                    log_error "Repository-Konflikt im non-interactive Modus"
                    return 1
                fi
                read -r -p "Trotzdem fortfahren? (j/n): " -n 1 REPLY
                echo
                if [[ ! $REPLY =~ ^[JjYy]$ ]]; then
                    log_error "Installation abgebrochen"
                    return 1
                fi
            else
                log_warning "Git-Repository ohne Remote-URL gefunden"
            fi
        fi
    else
        if [ -z "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ] || [ "$(ls -A "$INSTALL_DIR" 2>/dev/null | grep -v '^\.')" = "" ]; then
            clone_repository "$INSTALL_DIR" || return 1
            log_success "Repository geklont"
        else
            log_warning "Verzeichnis $INSTALL_DIR ist nicht leer und enthält kein Git-Repository"
            if is_yes "$NON_INTERACTIVE"; then
                log_error "Zielverzeichnis nicht leer (non-interactive)"
                return 1
            fi
            read -r -p "Verzeichnis löschen und neu klonen? (j/n) [n]: " -n 1 REPLY
            echo
            if [[ $REPLY =~ ^[JjYy]$ ]]; then
                rm -rf "${INSTALL_DIR:?}/"*
                rm -rf "${INSTALL_DIR}"/.[!.]* "${INSTALL_DIR}"/..?* 2>/dev/null || true
                clone_repository "$INSTALL_DIR" || return 1
                log_success "Repository geklont"
            else
                log_error "Installation abgebrochen"
                return 1
            fi
        fi
    fi

    if [ ! -f "$INSTALL_DIR/app.py" ]; then
        log_error "app.py nicht gefunden in $INSTALL_DIR"
        return 1
    fi

    cd "$INSTALL_DIR" || return 1
    log_success "Projekt-Verzeichnis eingerichtet"
    return 0
}
