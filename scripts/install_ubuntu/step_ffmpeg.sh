#!/bin/bash
# Media Downloader / FFmpeg

step_ffmpeg() {
    if ! is_yes "$INSTALL_MEDIA_DOWNLOADER"; then
        print_manual_media_downloader_hint
        return 2
    fi

    export DEBIAN_FRONTEND=noninteractive
    if ! apt-get install -y ffmpeg; then
        log_error "FFmpeg konnte nicht installiert werden"
        return 1
    fi

    if command -v ffmpeg &>/dev/null; then
        FFMPEG_PATH="$(command -v ffmpeg)"
        log_success "FFmpeg installiert: $(ffmpeg -version | head -n 1)"
        log_info "FFMPEG_PATH=$FFMPEG_PATH"
        if [ -f "${INSTALL_DIR}/scripts/download_youtubei_vendor.py" ]; then
            log_info "Prüfe youtubei.js Browser-Bundle für Media Downloader..."
            python3 "${INSTALL_DIR}/scripts/download_youtubei_vendor.py" \
                || log_warning "youtubei.js Vendor-Download fehlgeschlagen (Browser nutzt CDN-Fallback)"
        fi
        return 0
    fi

    log_error "FFmpeg installiert, aber nicht im PATH"
    return 1
}
