#!/bin/bash
###############################################################################
# Modularer Ubuntu-Installer für Team Portal (Prismateams Web)
#
# Entry-Punkt – Logik liegt in scripts/install_ubuntu/*.sh
#
# Verwendung:
#   sudo bash scripts/install_ubuntu.sh [OPTIONEN]
#
# Siehe: sudo bash scripts/install_ubuntu.sh --help
# Doku:  docs/INSTALLATION_SCRIPT.md
###############################################################################

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/install_ubuntu"

if [ ! -d "$LIB_DIR" ]; then
    echo "Fehler: Modulverzeichnis nicht gefunden: $LIB_DIR" >&2
    exit 1
fi

# shellcheck source=/dev/null
. "${LIB_DIR}/common.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/args.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/prompts.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/steps.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_system.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_mysql.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_redis.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_docker.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_onlyoffice.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_ffmpeg.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_repo.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_venv.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_env.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_gunicorn.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_nginx.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_apache.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_firewall.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_ssl.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/summary.sh"

on_unexpected_error() {
    local line="${1:-?}"
    local cmd="${2:-?}"
    log_error "Unerwarteter Fehler in Zeile ${line}: ${cmd}"
    INSTALL_ABORTED=1
    if declare -f print_summary >/dev/null 2>&1; then
        print_summary || true
    fi
    exit 1
}

trap 'on_unexpected_error $LINENO "$BASH_COMMAND"' ERR

main() {
    init_defaults
    parse_arguments "$@"

    echo "=========================================="
    echo "Team Portal - Automatische Installation"
    echo "Ubuntu 24.04 / 26.04 LTS (modular)"
    echo "=========================================="
    echo

    check_root
    check_ubuntu
    gather_information

    run_step "system" "System-Pakete" step_system critical
    run_step "mysql" "MySQL" step_mysql critical
    run_step "redis" "Redis" step_redis optional
    run_step "docker" "Docker" step_docker optional
    run_step "onlyoffice" "OnlyOffice" step_onlyoffice optional
    run_step "ffmpeg" "FFmpeg" step_ffmpeg optional
    run_step "repo" "Repository" step_repo critical
    run_step "venv" "Python-venv" step_venv critical
    run_step "env" ".env / Keys" step_env critical
    run_step "uploads" "Upload-Verzeichnisse" step_uploads critical
    run_step "database" "Datenbank-Schema" step_database critical
    run_step "gunicorn" "Gunicorn" step_gunicorn critical
    run_step "nginx" "Nginx" step_nginx optional
    run_step "apache" "Apache" step_apache optional
    run_step "firewall" "Firewall" step_firewall optional
    run_step "ssl" "SSL" step_ssl optional
    run_step "permissions" "Berechtigungen" step_permissions critical

    print_summary
}

main "$@"
