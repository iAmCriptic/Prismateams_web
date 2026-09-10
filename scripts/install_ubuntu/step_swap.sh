#!/bin/bash
# Swap-Datei, bevor APT/MySQL/Docker RAM brauchen (26.04-VMs: apt-get sonst OOM-Killed)
#
# Ziel: mindestens 6 GiB Swap, angelegt werden 8 GiB.

SWAP_TARGET_GIB="${SWAP_TARGET_GIB:-8}"
SWAP_MIN_GIB="${SWAP_MIN_GIB:-6}"
SWAP_FILE="${SWAP_FILE:-/swapfile.prismateams}"

_swap_total_kib() {
    awk '/^SwapTotal:/ {print $2}' /proc/meminfo
}

_swap_kib_to_gib() {
    awk -v k="$1" 'BEGIN { printf "%.1f", k / 1024 / 1024 }'
}

_root_fstype() {
    findmnt -n -o FSTYPE / 2>/dev/null || stat -f -c %T / 2>/dev/null || echo unknown
}

_root_avail_kib() {
    df -Pk / | awk 'NR==2 {print $4}'
}

_swap_fstab_ensure() {
    local path="$1"
    if grep -qE "^${path}[[:space:]]" /etc/fstab 2>/dev/null; then
        return 0
    fi
    echo "${path} none swap sw 0 0" >> /etc/fstab
}

_swap_create_file() {
    local path="$1"
    local gib="$2"
    local mib=$((gib * 1024))

    rm -f "$path"
    if command -v fallocate >/dev/null 2>&1; then
        if fallocate -l "${gib}G" "$path" 2>/dev/null; then
            return 0
        fi
        log_warning "fallocate fehlgeschlagen – verwende dd"
    fi
    dd if=/dev/zero of="$path" bs=1M count="$mib" status=none
}

step_swap() {
    local have_kib need_kib target_kib avail_kib fstype
    have_kib=$(_swap_total_kib)
    have_kib=${have_kib:-0}
    need_kib=$((SWAP_MIN_GIB * 1024 * 1024))
    target_kib=$((SWAP_TARGET_GIB * 1024 * 1024))

    log_info "RAM: $(awk '/^MemTotal:/ {printf "%.1f GiB", $2/1024/1024}' /proc/meminfo)"
    log_info "Swap aktuell: $(_swap_kib_to_gib "$have_kib") GiB (Minimum ${SWAP_MIN_GIB} GiB)"

    if [ "$have_kib" -ge "$need_kib" ]; then
        log_success "Swap bereits ausreichend ($(_swap_kib_to_gib "$have_kib") GiB)"
        return 0
    fi

    fstype=$(_root_fstype)
    if [ "$fstype" = "zfs" ]; then
        log_warning "Root-Dateisystem ist ZFS – Swap-Datei kann fehlschlagen (Deadlock-Risiko)"
    fi

    avail_kib=$(_root_avail_kib)
    avail_kib=${avail_kib:-0}
    # Datei + etwas Puffer
    if [ "$avail_kib" -lt $((target_kib + 1024 * 1024)) ]; then
        log_error "Zu wenig freier Speicher auf / für ${SWAP_TARGET_GIB} GiB Swap (frei: $(_swap_kib_to_gib "$avail_kib") GiB)"
        return 1
    fi

    if [ -f "$SWAP_FILE" ]; then
        log_info "Entferne bestehende ${SWAP_FILE}..."
        swapoff "$SWAP_FILE" 2>/dev/null || true
        rm -f "$SWAP_FILE"
    fi

    log_info "Lege ${SWAP_FILE} mit ${SWAP_TARGET_GIB} GiB an..."
    if ! _swap_create_file "$SWAP_FILE" "$SWAP_TARGET_GIB"; then
        log_error "Swap-Datei konnte nicht erzeugt werden"
        return 1
    fi

    chmod 600 "$SWAP_FILE"
    if ! mkswap "$SWAP_FILE" >/dev/null; then
        log_error "mkswap fehlgeschlagen"
        rm -f "$SWAP_FILE"
        return 1
    fi

    if ! swapon "$SWAP_FILE"; then
        log_error "swapon ${SWAP_FILE} fehlgeschlagen (Dateisystem ${fstype})"
        rm -f "$SWAP_FILE"
        return 1
    fi

    _swap_fstab_ensure "$SWAP_FILE"

    have_kib=$(_swap_total_kib)
    if [ "$have_kib" -lt "$need_kib" ]; then
        log_error "Swap nach Aktivierung nur $(_swap_kib_to_gib "$have_kib") GiB (erwartet ≥ ${SWAP_MIN_GIB} GiB)"
        return 1
    fi

    log_success "Swap aktiv: $(_swap_kib_to_gib "$have_kib") GiB (${SWAP_FILE})"
    return 0
}
