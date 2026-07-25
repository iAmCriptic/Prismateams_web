#!/bin/bash
# Step-Registry: Status ok | skipped | failed | aborted

# Parallel arrays (bash 4+ / Ubuntu 24.04)
STEP_IDS=()
STEP_TITLES=()
STEP_STATUSES=()
STEP_NOTES=()

record_step() {
    local id="$1"
    local status="$2"
    local note="${3:-}"
    local title="${4:-}"
    local i
    for i in "${!STEP_IDS[@]}"; do
        if [ "${STEP_IDS[$i]}" = "$id" ]; then
            STEP_STATUSES[$i]="$status"
            STEP_NOTES[$i]="$note"
            [ -n "$title" ] && STEP_TITLES[$i]="$title"
            return 0
        fi
    done
    STEP_IDS+=("$id")
    STEP_TITLES+=("${title:-$id}")
    STEP_STATUSES+=("$status")
    STEP_NOTES+=("$note")
}

# run_step ID "Titel" function_name [critical|optional]
# function return: 0=ok, 2=skipped, sonst failed
run_step() {
    local id="$1"
    local title="$2"
    local fn="$3"
    local criticality="${4:-critical}"
    local rc note

    log_info ""
    log_info ">>> Schritt: $title"

    # Fehler des Schritts selbst fangen (kein globales set -e)
    set +e
    "$fn"
    rc=$?
    set +e

    if [ $rc -eq 0 ]; then
        record_step "$id" "ok" "" "$title"
        log_success "Schritt OK: $title"
        return 0
    fi
    if [ $rc -eq 2 ]; then
        note="übersprungen"
        record_step "$id" "skipped" "$note" "$title"
        log_info "Schritt übersprungen: $title"
        return 0
    fi

    note="Fehlercode $rc"
    record_step "$id" "failed" "$note" "$title"
    log_error "Schritt fehlgeschlagen: $title ($note)"

    if [ "$criticality" = "optional" ] || is_yes "$CONTINUE_ON_ERROR"; then
        log_warning "Fahre fort (--continue-on-error oder optionaler Schritt)"
        return 0
    fi

    INSTALL_ABORTED=1
    record_step "$id" "aborted" "Abbruch nach Fehler" "$title"
    if declare -f print_summary >/dev/null 2>&1; then
        print_summary || true
    fi
    exit 1
}

status_label() {
    case "$1" in
        ok) echo "ERFOLG" ;;
        skipped) echo "ÜBERSPRUNGEN" ;;
        failed) echo "FEHLGESCHLAGEN" ;;
        aborted) echo "ABGEBROCHEN" ;;
        *) echo "$1" ;;
    esac
}
