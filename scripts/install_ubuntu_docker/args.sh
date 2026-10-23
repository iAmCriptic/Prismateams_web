#!/bin/bash
# CLI-Argumente – Docker-Installer

show_help() {
    cat <<'EOF'
Prismateams – Ubuntu Docker-Installer (reine Compose-Variante)

Verwendung:
  sudo bash scripts/install_ubuntu_docker.sh [OPTIONEN]

Allgemein:
  --install-dir PATH         Installationsverzeichnis (Standard: /var/www/teamportal)
  --repo-url URL             Git-Repository
  --branch BRANCH            Git-Branch
  --non-interactive          Keine Prompts; fehlende Pflichtwerte = Fehler
  --continue-on-error        Optionale Schritte bei Fehler fortsetzen
  --help, -h                 Diese Hilfe

Webserver (Host-Proxy vor Containern):
  --no-webserver             Kein Nginx/Apache
  --webserver TYPE           nginx oder apache
  --domain DOMAIN            Domain/IP
  --ssl                      Let's Encrypt SSL
  --letsencrypt-email EMAIL  E-Mail für Let's Encrypt

Compose-Profiles / Sidecars:
  --onlyoffice               Euro-Office Document Server
  --skip-onlyoffice          Euro-Office überspringen
  --excalidraw               Excalidraw-Room
  --skip-excalidraw          Excalidraw überspringen
  --mirotalk                 MiroTalk SFU
  --skip-mirotalk            MiroTalk überspringen

Ports:
  --app-port PORT            Host-Port der App (Standard: 5000)

.env:
  --timezone TZ              z.B. Europe/Berlin
  --vapid-claim-email EMAIL  VAPID Claim E-Mail

Beispiele:
  sudo bash scripts/install_ubuntu_docker.sh
  sudo bash scripts/install_ubuntu_docker.sh --domain portal.example.com --webserver nginx --ssl
  sudo bash scripts/install_ubuntu_docker.sh --onlyoffice --excalidraw --mirotalk --domain example.com --webserver nginx

Kein natives MySQL/Redis/venv/Gunicorn – alles über docker compose.
Native Installation: scripts/install_ubuntu.sh
EOF
}

parse_arguments() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --install-dir)
                [ -n "${2:-}" ] || error_exit "--install-dir erfordert einen Pfad"
                INSTALL_DIR="$2"
                shift 2
                ;;
            --repo-url)
                [ -n "${2:-}" ] || error_exit "--repo-url erfordert eine URL"
                REPO_URL="$2"
                shift 2
                ;;
            --branch)
                [ -n "${2:-}" ] || error_exit "--branch erfordert einen Branch-Namen"
                GIT_BRANCH="$2"
                shift 2
                ;;
            --non-interactive)
                NON_INTERACTIVE="j"
                shift
                ;;
            --continue-on-error)
                CONTINUE_ON_ERROR="j"
                shift
                ;;
            --no-webserver)
                SETUP_WEBSERVER="n"
                shift
                ;;
            --webserver)
                [ -n "${2:-}" ] || error_exit "--webserver erfordert nginx oder apache"
                WEBSERVER_TYPE="$2"
                SETUP_WEBSERVER="j"
                shift 2
                ;;
            --domain)
                [ -n "${2:-}" ] || error_exit "--domain erfordert einen Wert"
                DOMAIN="$2"
                shift 2
                ;;
            --ssl)
                SETUP_SSL="j"
                shift
                ;;
            --letsencrypt-email)
                [ -n "${2:-}" ] || error_exit "--letsencrypt-email erfordert eine E-Mail"
                LETSENCRYPT_EMAIL="$2"
                shift 2
                ;;
            --onlyoffice)
                INSTALL_ONLYOFFICE="j"
                shift
                ;;
            --skip-onlyoffice)
                INSTALL_ONLYOFFICE="n"
                shift
                ;;
            --excalidraw)
                INSTALL_EXCALIDRAW="j"
                shift
                ;;
            --skip-excalidraw)
                INSTALL_EXCALIDRAW="n"
                shift
                ;;
            --mirotalk)
                INSTALL_MIROTALK="j"
                shift
                ;;
            --skip-mirotalk)
                INSTALL_MIROTALK="n"
                shift
                ;;
            --app-port)
                [ -n "${2:-}" ] || error_exit "--app-port erfordert einen Port"
                APP_HOST_PORT="$2"
                shift 2
                ;;
            --timezone)
                [ -n "${2:-}" ] || error_exit "--timezone erfordert einen Wert"
                TIMEZONE="$2"
                shift 2
                ;;
            --vapid-claim-email)
                [ -n "${2:-}" ] || error_exit "--vapid-claim-email erfordert eine E-Mail"
                VAPID_CLAIM_EMAIL="$2"
                shift 2
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                error_exit "Unbekannte Option: $1 (siehe --help)"
                ;;
        esac
    done
}
