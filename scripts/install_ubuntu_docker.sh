#!/bin/bash
###############################################################################
# Ubuntu-Installer – reine Docker-Variante (Prismateams)
#
# Installiert Docker/Compose, klont das Repo, schreibt .env und startet
# docker compose. Optional: Host-Nginx/Apache + SSL + Firewall.
# Kein natives MySQL, Redis, venv oder systemd-Gunicorn.
#
# Verwendung:
#   sudo bash scripts/install_ubuntu_docker.sh [OPTIONEN]
#
# Doku: docs/INSTALLATION_DOCKER.md
###############################################################################

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/install_ubuntu_docker"
NATIVE_LIB_DIR="${SCRIPT_DIR}/install_ubuntu"

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
. "${NATIVE_LIB_DIR}/step_swap.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_system.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_docker.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_repo.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_env.sh"
# shellcheck source=/dev/null
. "${LIB_DIR}/step_compose.sh"
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
    echo "Prismateams – Docker-Installation (Ubuntu)"
    echo "Ubuntu 24.04 / 26.04 LTS"
    echo "=========================================="
    echo

    check_root
    check_ubuntu
    prepare_apt_environment
    run_step "swap" "Swap" step_swap critical
    gather_information

    run_step "system" "System-Pakete" step_system critical
    run_step "docker" "Docker Engine" step_docker critical
    run_step "repo" "Repository" step_repo critical
    run_step "env" ".env / Keys" step_env critical
    run_step "compose" "Docker Compose Stack" step_compose critical
    run_step "nginx" "Nginx" step_nginx optional
    run_step "apache" "Apache" step_apache optional
    run_step "firewall" "Firewall" step_firewall optional
    run_step "ssl" "SSL" step_ssl optional

    print_summary
}

main "$@"
