#!/bin/bash
# CLI-Argumente und Hilfe

show_help() {
    cat <<'EOF'
Team Portal - Ubuntu Installationsskript (modular)

Verwendung:
  sudo bash scripts/install_ubuntu.sh [OPTIONEN]

Allgemein:
  --install-dir PATH         Installationsverzeichnis (Standard: /var/www/teamportal)
  --repo-url URL             Git-Repository (Fork/Dev möglich)
  --branch BRANCH            Git-Branch (sonst Default-Branch)
  --non-interactive          Keine Prompts; fehlende Pflichtwerte = Fehler
  --continue-on-error        Optionale Schritte bei Fehler fortsetzen
  --help, -h                 Diese Hilfe

Anwendung / Gunicorn:
  --port PORT                Gunicorn-Port (Standard: 5000)
  --workers N                Gunicorn-Worker (Standard: 1; bei N>1 One-Shot-DB-Init)
  --no-gunicorn              Keinen systemd-Service anlegen

Webserver:
  --no-webserver             Kein Nginx/Apache vHost
  --webserver TYPE           nginx oder apache
  --domain DOMAIN            Domain/IP für Webserver
  --ssl                      Let's Encrypt SSL (nur mit Webserver)
  --letsencrypt-email EMAIL  E-Mail für Let's Encrypt

Datenbank / Redis:
  --skip-mysql               MySQL-Setup überspringen
  --skip-redis               Redis-Setup überspringen
  --db-name NAME             Datenbankname (Standard: teamportal)
  --db-user USER             DB-Benutzer (Standard: teamportal)
  --db-pass PASS             DB-Passwort (sonst generiert)
  --mysql-root-pass PASS     MySQL-Root-Passwort (sonst generiert/abgefragt)

Optionale Dienste:
  --skip-docker              Docker + OnlyOffice überspringen
  --skip-onlyoffice          OnlyOffice überspringen
  --onlyoffice               OnlyOffice installieren
  --skip-media-downloader    FFmpeg/Media Downloader überspringen
  --ffmpeg                   FFmpeg installieren

.env:
  --env-mode MODE            auto | manual | file
  --env-file PATH            Bestehende .env mergen/übernehmen
  --timezone TZ              z.B. Europe/Berlin
  --vapid-claim-email EMAIL  VAPID Claim E-Mail

Beispiele:
  sudo bash scripts/install_ubuntu.sh
  sudo bash scripts/install_ubuntu.sh --port 8000 --workers 4 --webserver nginx
  sudo bash scripts/install_ubuntu.sh --repo-url https://github.com/ME/fork.git --branch Development
  sudo bash scripts/install_ubuntu.sh --no-webserver --skip-onlyoffice --ffmpeg
  sudo bash scripts/install_ubuntu.sh --non-interactive --install-dir /var/www/tp --domain example.com --webserver nginx

Ohne Optionen: interaktive Abfragen für alle leeren Werte.
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
            --port)
                [ -n "${2:-}" ] || error_exit "--port erfordert einen Wert"
                GUNICORN_PORT="$2"
                shift 2
                ;;
            --workers)
                [ -n "${2:-}" ] || error_exit "--workers erfordert eine Zahl"
                GUNICORN_WORKERS="$2"
                shift 2
                ;;
            --no-gunicorn)
                SETUP_GUNICORN="n"
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
            --skip-mysql)
                SETUP_MYSQL="n"
                shift
                ;;
            --skip-redis)
                SETUP_REDIS="n"
                shift
                ;;
            --db-name)
                [ -n "${2:-}" ] || error_exit "--db-name erfordert einen Namen"
                DB_NAME="$2"
                shift 2
                ;;
            --db-user)
                [ -n "${2:-}" ] || error_exit "--db-user erfordert einen Benutzer"
                DB_USER="$2"
                shift 2
                ;;
            --db-pass)
                [ -n "${2:-}" ] || error_exit "--db-pass erfordert ein Passwort"
                DB_PASS="$2"
                shift 2
                ;;
            --mysql-root-pass)
                [ -n "${2:-}" ] || error_exit "--mysql-root-pass erfordert ein Passwort"
                MYSQL_ROOT_PASS="$2"
                shift 2
                ;;
            --skip-docker)
                INSTALL_DOCKER="n"
                INSTALL_ONLYOFFICE="n"
                shift
                ;;
            --skip-onlyoffice)
                INSTALL_ONLYOFFICE="n"
                shift
                ;;
            --onlyoffice)
                INSTALL_ONLYOFFICE="j"
                INSTALL_DOCKER="j"
                INSTALL_DOCKER="j"
                shift
                ;;
            --skip-media-downloader)
                INSTALL_MEDIA_DOWNLOADER="n"
                shift
                ;;
            --ffmpeg)
                INSTALL_MEDIA_DOWNLOADER="j"
                shift
                ;;
            --env-mode)
                [ -n "${2:-}" ] || error_exit "--env-mode erfordert auto|manual|file"
                ENV_MODE="$2"
                shift 2
                ;;
            --env-file)
                [ -n "${2:-}" ] || error_exit "--env-file erfordert einen Pfad"
                ENV_FILE="$2"
                ENV_MODE="${ENV_MODE:-file}"
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
            --non-interactive)
                NON_INTERACTIVE="j"
                shift
                ;;
            --continue-on-error)
                CONTINUE_ON_ERROR="j"
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                error_exit "Unbekannte Option: $1 (verwenden Sie --help)"
                ;;
        esac
    done
}
