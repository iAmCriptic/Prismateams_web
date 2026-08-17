#!/bin/bash
# OnlyOffice Document Server (Docs) via Docker
#
# WICHTIG: Prismateams braucht ONLYOFFICE Docs (Document Server),
# nicht Community Server / Workspace (Docker-CommunityServer).
# Community Server ist ein eigenes Portal und belegt Port 80/443.
#
# Offiziell: https://github.com/ONLYOFFICE/Docker-DocumentServer
# Image:     onlyoffice/documentserver:latest

ONLYOFFICE_IMAGE="${ONLYOFFICE_IMAGE:-onlyoffice/documentserver:latest}"
ONLYOFFICE_HOST_PORT="${ONLYOFFICE_HOST_PORT:-8080}"
ONLYOFFICE_CONTAINER="${ONLYOFFICE_CONTAINER:-onlyoffice-documentserver}"
ONLYOFFICE_DATA_ROOT="${ONLYOFFICE_DATA_ROOT:-/var/lib/onlyoffice/DocumentServer}"

_onlyoffice_container_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "${ONLYOFFICE_CONTAINER}"
}

_onlyoffice_container_exists() {
    docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "${ONLYOFFICE_CONTAINER}"
}

_onlyoffice_port_in_use() {
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

_onlyoffice_dump_logs() {
    log_info "Letzte OnlyOffice-Container-Logs:"
    docker logs --tail 60 "${ONLYOFFICE_CONTAINER}" 2>&1 || true
}

# Host-Fonts für PDF/Druck im Document Server (Volume …/fonts).
# Ohne diese Dateien listet der Browser-Editor Schriften, Rendering schlägt aber fehl.
_onlyoffice_ensure_font_repos() {
    if command -v add-apt-repository >/dev/null 2>&1; then
        add-apt-repository -y universe >/dev/null 2>&1 || true
        add-apt-repository -y multiverse >/dev/null 2>&1 || true
    fi
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq || log_warning "apt-get update für Schriftarten fehlgeschlagen"
}

_onlyoffice_install_host_fonts() {
    log_info "Installiere Schriftarten für OnlyOffice (Microsoft Core Fonts, Carlito/Caladea)..."
    _onlyoffice_ensure_font_repos

    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections
    echo "ttf-mscorefonts-installer msttcorefonts/present-mscorefonts-eula note" | debconf-set-selections

    local extra_ok=1
    if ! apt-get install -y -qq \
        fonts-crosextra-carlito fonts-crosextra-caladea \
        fonts-liberation fonts-liberation2 fonts-dejavu-core cabextract; then
        extra_ok=0
        log_warning "Libre-/Ersatz-Schriftarten konnten nicht vollständig installiert werden"
    fi

    # mscorefonts lädt TTFs von SourceForge – kann fehlschlagen, Rest bleibt nutzbar
    if ! apt-get install -y -qq ttf-mscorefonts-installer; then
        log_warning "ttf-mscorefonts-installer fehlgeschlagen (EULA/Download) – Arial/Times ggf. unvollständig"
    fi

    if [ "$extra_ok" -eq 1 ]; then
        log_success "Host-Schriftarten installiert (Carlito = Calibri-kompatibel)"
    fi
}

_onlyoffice_copy_fonts_to_volume() {
    local dest="${ONLYOFFICE_DATA_ROOT}/fonts"
    mkdir -p "$dest"
    log_info "Kopiere Schriftarten nach ${dest}..."

    local copied=0
    local dir
    for dir in \
        /usr/share/fonts/truetype/msttcorefonts \
        /usr/share/fonts/truetype/liberation \
        /usr/share/fonts/truetype/liberation2 \
        /usr/share/fonts/truetype/crosextra \
        /usr/share/fonts/truetype/carlito \
        /usr/share/fonts/truetype/caladea \
        /usr/share/fonts/truetype/dejavu; do
        if [ -d "$dir" ]; then
            while IFS= read -r -d '' fontfile; do
                if cp -n "$fontfile" "$dest/" 2>/dev/null; then
                    copied=$((copied + 1))
                fi
            done < <(find "$dir" -type f \( -iname '*.ttf' -o -iname '*.otf' -o -iname '*.ttc' \) -print0 2>/dev/null)
        fi
    done

    if [ "$copied" -gt 0 ]; then
        log_success "${copied} Schriftdateien im OnlyOffice-Fonts-Volume"
    else
        log_warning "Keine Schriftdateien zum Kopieren gefunden – PDF-Rendering kann Schrift-Substitution nutzen"
    fi
}

_onlyoffice_generate_allfonts() {
    if ! _onlyoffice_container_running; then
        log_warning "Font-Index nicht erzeugt – Container läuft nicht"
        return 0
    fi
    log_info "Erzeuge OnlyOffice-Font-Index (documentserver-generate-allfonts.sh, kann 1–2 Min. dauern)..."
    if docker exec "${ONLYOFFICE_CONTAINER}" /usr/bin/documentserver-generate-allfonts.sh; then
        log_success "OnlyOffice-Font-Index aktualisiert"
    else
        log_warning "documentserver-generate-allfonts.sh fehlgeschlagen – später manuell ausführen"
        log_warning "  docker exec ${ONLYOFFICE_CONTAINER} /usr/bin/documentserver-generate-allfonts.sh"
    fi
}

step_onlyoffice() {
    if ! is_yes "$INSTALL_ONLYOFFICE"; then
        print_manual_onlyoffice_hint
        return 2
    fi

    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker nicht gefunden – OnlyOffice Docs braucht Docker"
        log_error "Schritt 'Docker' muss vorher erfolgreich sein"
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

    local mem_kb mem_gb
    mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
    mem_gb=$((mem_kb / 1024 / 1024))
    if [ "$mem_gb" -gt 0 ] && [ "$mem_gb" -lt 4 ]; then
        log_warning "OnlyOffice Docs empfiehlt ≥4 GB RAM (aktuell ca. ${mem_gb} GB) – Start kann scheitern/OOM"
    fi

    local free_kb=0
    free_kb=$(df -Pk /var/lib/docker 2>/dev/null | awk 'NR==2 {print $4}')
    if [ -z "$free_kb" ] || [ "$free_kb" = "0" ]; then
        free_kb=$(df -Pk / 2>/dev/null | awk 'NR==2 {print $4}')
    fi
    if [ -n "$free_kb" ] && [ "$free_kb" -lt 5000000 ]; then
        log_warning "Wenig freier Speicher (~$((free_kb / 1024)) MB) – Docs-Image braucht mehrere GB"
    fi

    local arch
    arch=$(uname -m)
    if [ "$arch" != "x86_64" ] && [ "$arch" != "amd64" ]; then
        log_error "OnlyOffice Docs Docker-Image ist nur für amd64/x86_64 (diese Maschine: ${arch})"
        return 1
    fi

    if [ -z "${ONLYOFFICE_SECRET:-}" ]; then
        ONLYOFFICE_SECRET=$(generate_secret)
    fi

    # Offizielle Volume-Layout (Docker-DocumentServer Community Edition)
    mkdir -p "${ONLYOFFICE_DATA_ROOT}/data"
    mkdir -p "${ONLYOFFICE_DATA_ROOT}/logs"
    mkdir -p "${ONLYOFFICE_DATA_ROOT}/lib"
    mkdir -p "${ONLYOFFICE_DATA_ROOT}/fonts"

    _onlyoffice_install_host_fonts
    _onlyoffice_copy_fonts_to_volume

    if _onlyoffice_port_in_use "${ONLYOFFICE_HOST_PORT}"; then
        if ! _onlyoffice_container_running; then
            log_error "Port ${ONLYOFFICE_HOST_PORT} ist belegt (nicht durch ${ONLYOFFICE_CONTAINER})"
            log_error "Port freigeben oder ONLYOFFICE_HOST_PORT setzen"
            return 1
        fi
    fi

    if _onlyoffice_container_exists; then
        log_info "Entferne bestehenden Container ${ONLYOFFICE_CONTAINER}..."
        docker stop "${ONLYOFFICE_CONTAINER}" >/dev/null 2>&1 || true
        docker rm "${ONLYOFFICE_CONTAINER}" >/dev/null 2>&1 || true
    fi

    log_info "Lade OnlyOffice Docs Image (${ONLYOFFICE_IMAGE})..."
    if ! docker pull "${ONLYOFFICE_IMAGE}"; then
        log_error "docker pull fehlgeschlagen: ${ONLYOFFICE_IMAGE}"
        log_error "Netzwerk, Registry-Zugang und Speicherplatz prüfen"
        log_error "Quelle: https://github.com/ONLYOFFICE/Docker-DocumentServer"
        return 1
    fi

    log_info "Starte OnlyOffice Document Server (JWT aktiv, Port ${ONLYOFFICE_HOST_PORT})..."
    local run_err cid
    run_err="$(mktemp)"

    if ! docker run -d \
        --name "${ONLYOFFICE_CONTAINER}" \
        --restart=always \
        -p "127.0.0.1:${ONLYOFFICE_HOST_PORT}:80" \
        -v "${ONLYOFFICE_DATA_ROOT}/logs:/var/log/onlyoffice" \
        -v "${ONLYOFFICE_DATA_ROOT}/data:/var/www/onlyoffice/Data" \
        -v "${ONLYOFFICE_DATA_ROOT}/lib:/var/lib/onlyoffice" \
        -v "${ONLYOFFICE_DATA_ROOT}/fonts:/usr/share/fonts/truetype/custom" \
        -e JWT_ENABLED=true \
        -e JWT_SECRET="${ONLYOFFICE_SECRET}" \
        -e JWT_HEADER=Authorization \
        -e ALLOW_PRIVATE_IP_ADDRESS=true \
        "${ONLYOFFICE_IMAGE}" >"${run_err}" 2>&1; then
        log_error "OnlyOffice Container konnte nicht gestartet werden"
        log_error "$(cat "${run_err}")"
        rm -f "${run_err}"
        return 1
    fi
    cid="$(tr -d '\r\n' <"${run_err}")"
    rm -f "${run_err}"
    log_info "Container gestartet: ${cid:0:12}"

    # Erststart (DB/Fonts) kann 2–3 Minuten dauern
    log_info "Warte auf OnlyOffice Docs (bis 180s)..."
    local OO_READY=0
    local i
    for i in $(seq 1 180); do
        if ! _onlyoffice_container_running; then
            log_error "Container ${ONLYOFFICE_CONTAINER} ist unerwartet gestoppt"
            _onlyoffice_dump_logs
            return 1
        fi
        if curl -sf "http://127.0.0.1:${ONLYOFFICE_HOST_PORT}/healthcheck" >/dev/null 2>&1 \
            || curl -sf "http://127.0.0.1:${ONLYOFFICE_HOST_PORT}/welcome/" >/dev/null 2>&1; then
            OO_READY=1
            log_success "OnlyOffice Docs ist bereit (${i}s)"
            break
        fi
        if [ $((i % 30)) -eq 0 ]; then
            log_info "Noch kein Ready-Signal (${i}/180s)..."
        fi
        sleep 1
    done

    if [ "$OO_READY" -eq 0 ]; then
        if _onlyoffice_container_running; then
            log_warning "OnlyOffice antwortet noch nicht nach 180s – Container läuft weiter"
            log_warning "Später prüfen: curl -s http://127.0.0.1:${ONLYOFFICE_HOST_PORT}/healthcheck"
            _onlyoffice_dump_logs
        else
            log_error "OnlyOffice Container nicht mehr aktiv"
            _onlyoffice_dump_logs
            return 1
        fi
    fi

    if [ "$OO_READY" -eq 1 ]; then
        _onlyoffice_generate_allfonts
    else
        log_warning "Font-Index übersprungen (Docs noch nicht bereit) – später:"
        log_warning "  docker exec ${ONLYOFFICE_CONTAINER} /usr/bin/documentserver-generate-allfonts.sh"
    fi

    log_info "OnlyOffice JWT_SECRET = ONLYOFFICE_SECRET_KEY (für .env)"
    log_success "OnlyOffice Document Server installiert (${ONLYOFFICE_IMAGE})"
    return 0
}
