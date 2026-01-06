#!/bin/bash

###############################################################################
# Vollautomatisiertes Installationsskript für Ubuntu 24.04.3 LTS
# Team Portal - Prismateams Web
#
# Dieses Skript installiert und konfiguriert automatisch:
# - Python 3.12+ und Virtual Environment
# - MySQL/MariaDB mit automatischer Datenbank- und Benutzererstellung
# - Nginx mit vollständiger Konfiguration
# - Gunicorn als WSGI-Server
# - OnlyOffice Document Server (Docker)
# - Excalidraw (Docker)
# - Automatische Generierung aller Keys
# - Automatische .env-Konfiguration (inkl. E-Mail-Einstellungen)
# - Systemd Service für Gunicorn (mit 1 Worker für ersten Start)
# - Datenbank wird automatisch beim ersten Start durch Gunicorn initialisiert
# - Optional: SSL mit Let's Encrypt
#
# Verwendung:
#   sudo bash scripts/install_ubuntu.sh
#
# Das Skript fragt interaktiv nach allen benötigten Konfigurationen,
# einschließlich E-Mail-Einstellungen (SMTP/IMAP).
###############################################################################

set -e  # Beende bei Fehlern
set -o pipefail  # Beende bei Fehlern in Pipes

# Error Handler
error_exit() {
    log_error "$1"
    exit 1
}

# Trap für Fehler
trap 'error_exit "Fehler in Zeile $LINENO. Befehl: $BASH_COMMAND"' ERR

# Farben für Ausgabe
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging-Funktion
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Überprüfung auf Root-Rechte
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "Dieses Skript muss als root ausgeführt werden!"
        log_info "Verwenden Sie: sudo $0"
        exit 1
    fi
}

# Überprüfung auf Ubuntu 24.04
check_ubuntu() {
    if [ ! -f /etc/os-release ]; then
        log_error "Konnte /etc/os-release nicht finden. Nicht Ubuntu?"
        exit 1
    fi
    
    . /etc/os-release
    
    if [ "$ID" != "ubuntu" ]; then
        log_error "Dieses Skript ist nur für Ubuntu gedacht!"
        exit 1
    fi
    
    if [ "$VERSION_ID" != "24.04" ]; then
        log_warning "Dieses Skript wurde für Ubuntu 24.04 entwickelt. Aktuelle Version: $VERSION_ID"
        read -p "Fortfahren? (j/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[JjYy]$ ]]; then
            exit 1
        fi
    fi
}

# Sichere Passwort-Generierung
generate_password() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-32
}

# Zufälliger String für Secret Keys
generate_secret() {
    openssl rand -hex 32
}

# Interaktive Abfragen
gather_information() {
    log_info "=== Konfigurationsabfrage ==="
    
    # Installationspfad
    read -p "Installationspfad [/var/www/teamportal]: " INSTALL_DIR
    INSTALL_DIR=${INSTALL_DIR:-/var/www/teamportal}
    
    # Domain/IP
    read -p "Domain oder IP-Adresse für Nginx: " DOMAIN
    if [ -z "$DOMAIN" ]; then
        log_error "Domain/IP ist erforderlich!"
        exit 1
    fi
    
    # SSL
    read -p "SSL mit Let's Encrypt einrichten? (j/n) [n]: " SETUP_SSL
    SETUP_SSL=${SETUP_SSL:-n}
    
    if [[ $SETUP_SSL =~ ^[JjYy]$ ]]; then
        read -p "E-Mail-Adresse für Let's Encrypt: " LETSENCRYPT_EMAIL
        if [ -z "$LETSENCRYPT_EMAIL" ]; then
            log_warning "Keine E-Mail angegeben. Verwende webmaster@$DOMAIN"
            LETSENCRYPT_EMAIL="webmaster@$DOMAIN"
        fi
    fi
    
    # Datenbank-Root-Passwort
    read -p "MySQL Root-Passwort (leer lassen für automatische Generierung): " MYSQL_ROOT_PASS
    if [ -z "$MYSQL_ROOT_PASS" ]; then
        MYSQL_ROOT_PASS=$(generate_password)
        log_info "MySQL Root-Passwort wurde automatisch generiert"
    fi
    
    # Datenbank-Benutzer-Passwort
    DB_USER="teamportal"
    DB_PASS=$(generate_password)
    DB_NAME="teamportal"
    
    # E-Mail-Konfiguration
    log_info ""
    log_info "=== E-Mail-Konfiguration ==="
    read -p "SMTP-Server (z.B. smtp.example.com): " MAIL_SERVER
    if [ -n "$MAIL_SERVER" ]; then
        read -p "SMTP-Port [587]: " MAIL_PORT
        MAIL_PORT=${MAIL_PORT:-587}
        
        read -p "TLS verwenden? (j/n) [j]: " MAIL_USE_TLS
        MAIL_USE_TLS=${MAIL_USE_TLS:-j}
        if [[ $MAIL_USE_TLS =~ ^[JjYy]$ ]]; then
            MAIL_USE_TLS="True"
        else
            MAIL_USE_TLS="False"
        fi
        
        read -p "SSL verwenden? (j/n) [n]: " MAIL_USE_SSL
        MAIL_USE_SSL=${MAIL_USE_SSL:-n}
        if [[ $MAIL_USE_SSL =~ ^[JjYy]$ ]]; then
            MAIL_USE_SSL="True"
        else
            MAIL_USE_SSL="False"
        fi
        
        read -p "E-Mail-Benutzername: " MAIL_USERNAME
        read -sp "E-Mail-Passwort: " MAIL_PASSWORD
        echo
        read -p "Standard-Absender-E-Mail [${MAIL_USERNAME}]: " MAIL_DEFAULT_SENDER
        MAIL_DEFAULT_SENDER=${MAIL_DEFAULT_SENDER:-$MAIL_USERNAME}
        read -p "Absender-Name (optional, z.B. 'Teamportal'): " MAIL_SENDER_NAME
        
        # IMAP-Konfiguration
        log_info ""
        log_info "IMAP-Konfiguration (für E-Mail-Synchronisation):"
        read -p "IMAP-Server (z.B. imap.example.com): " IMAP_SERVER
        if [ -n "$IMAP_SERVER" ]; then
            read -p "IMAP-Port [993]: " IMAP_PORT
            IMAP_PORT=${IMAP_PORT:-993}
            
            read -p "IMAP SSL verwenden? (j/n) [j]: " IMAP_USE_SSL
            IMAP_USE_SSL=${IMAP_USE_SSL:-j}
            if [[ $IMAP_USE_SSL =~ ^[JjYy]$ ]]; then
                IMAP_USE_SSL="True"
            else
                IMAP_USE_SSL="False"
            fi
        fi
    else
        log_warning "Keine E-Mail-Konfiguration angegeben. E-Mail-Funktionen werden nicht verfügbar sein."
        MAIL_SERVER=""
        MAIL_PORT="587"
        MAIL_USE_TLS="True"
        MAIL_USE_SSL="False"
        MAIL_USERNAME=""
        MAIL_PASSWORD=""
        MAIL_DEFAULT_SENDER=""
        MAIL_SENDER_NAME=""
        IMAP_SERVER=""
        IMAP_PORT="993"
        IMAP_USE_SSL="True"
    fi
    
    log_success "Konfiguration gesammelt"
}

# System-Vorbereitung
setup_system() {
    log_info "=== System-Vorbereitung ==="
    
    log_info "Aktualisiere Paketlisten..."
    export DEBIAN_FRONTEND=noninteractive
    if ! apt-get update -qq; then
        error_exit "Paketlisten-Update fehlgeschlagen"
    fi
    
    log_info "Installiere Basis-Pakete..."
    if ! apt-get install -y -qq \
        curl \
        wget \
        git \
        build-essential \
        software-properties-common \
        apt-transport-https \
        ca-certificates \
        gnupg \
        lsb-release \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        libmysqlclient-dev \
        pkg-config \
        ufw \
        nginx \
        supervisor \
        mysql-server \
        mysql-client \
        openssl \
        certbot \
        python3-certbot-nginx; then
        error_exit "Paket-Installation fehlgeschlagen"
    fi
    
    # Validierung
    if ! command -v python3 &> /dev/null; then
        error_exit "Python3 wurde nicht korrekt installiert"
    fi
    
    if ! command -v nginx &> /dev/null; then
        error_exit "Nginx wurde nicht korrekt installiert"
    fi
    
    log_info "Aktualisiere pip..."
    python3 -m pip install --upgrade pip --quiet || log_warning "pip Update fehlgeschlagen, fahre fort..."
    
    log_success "System-Vorbereitung abgeschlossen"
}

# MySQL Setup
setup_mysql() {
    log_info "=== MySQL/MariaDB Setup ==="
    
    # Prüfe ob MySQL bereits läuft
    if systemctl is-active --quiet mysql || systemctl is-active --quiet mariadb; then
        log_info "MySQL läuft bereits"
    else
        # MySQL sicher starten
        systemctl start mysql 2>/dev/null || systemctl start mariadb 2>/dev/null
        systemctl enable mysql 2>/dev/null || systemctl enable mariadb 2>/dev/null
    fi
    
    # Warte auf MySQL
    log_info "Warte auf MySQL-Service..."
    MYSQL_READY=0
    for i in {1..30}; do
        if mysqladmin ping -h localhost --silent 2>/dev/null; then
            MYSQL_READY=1
            break
        fi
        sleep 1
    done
    
    if [ $MYSQL_READY -eq 0 ]; then
        error_exit "MySQL konnte nicht gestartet werden"
    fi
    
    # MySQL Root-Passwort setzen (falls noch nicht gesetzt)
    log_info "Konfiguriere MySQL..."
    
    # Versuche zuerst ohne Passwort
    if mysql -u root -e "SELECT 1" 2>/dev/null; then
        # MySQL läuft ohne Passwort, setze es
        log_info "Setze MySQL Root-Passwort..."
        mysql -u root <<EOF
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '${MYSQL_ROOT_PASS}';
FLUSH PRIVILEGES;
EOF
    else
        # MySQL hat bereits ein Passwort
        log_warning "MySQL Root-Passwort ist bereits gesetzt."
        log_info "Versuche mit bereitgestelltem Passwort..."
        # Versuche mit dem bereitgestellten Passwort
        if ! mysql -u root -p"${MYSQL_ROOT_PASS}" -e "SELECT 1" 2>/dev/null; then
            log_error "MySQL Root-Passwort ist falsch oder MySQL ist nicht korrekt konfiguriert."
            log_info "Bitte setzen Sie das MySQL Root-Passwort manuell oder geben Sie das korrekte Passwort ein."
            exit 1
        fi
    fi
    
    # Erstelle Datenbank und Benutzer
    log_info "Erstelle Datenbank und Benutzer..."
    mysql -u root -p"${MYSQL_ROOT_PASS}" <<EOF 2>/dev/null
CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
EOF
    if [ $? -ne 0 ]; then
        log_error "Datenbank-Erstellung fehlgeschlagen"
        exit 1
    fi
    
    # Validierung
    if mysql -u "${DB_USER}" -p"${DB_PASS}" -e "USE ${DB_NAME}; SELECT 1;" 2>/dev/null; then
        log_success "Datenbank-Verbindungstest erfolgreich"
    else
        log_warning "Datenbank-Verbindungstest fehlgeschlagen. Möglicherweise müssen Sie die Berechtigungen prüfen."
    fi
    
    log_success "MySQL konfiguriert"
    log_info "Datenbank: ${DB_NAME}"
    log_info "Benutzer: ${DB_USER}"
}

# Docker Installation
install_docker() {
    log_info "=== Docker Installation ==="
    
    if command -v docker &> /dev/null; then
        log_info "Docker ist bereits installiert"
        return
    fi
    
    log_info "Installiere Docker..."
    
    # Docker Repository hinzufügen
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    # Docker Service starten
    systemctl start docker
    systemctl enable docker
    
    log_success "Docker installiert"
}

# OnlyOffice Installation
install_onlyoffice() {
    log_info "=== OnlyOffice Document Server Installation ==="
    
    # OnlyOffice Secret Key generieren
    ONLYOFFICE_SECRET=$(generate_secret)
    
    # Verzeichnisse erstellen
    mkdir -p /var/lib/onlyoffice/DocumentServer/data
    mkdir -p /var/lib/onlyoffice/DocumentServer/logs
    
    # OnlyOffice Container starten
    log_info "Starte OnlyOffice Container..."
    
    # Prüfe ob Container bereits existiert
    if docker ps -a --format '{{.Names}}' | grep -q "^onlyoffice-documentserver$"; then
        log_info "OnlyOffice Container existiert bereits. Entferne alten Container..."
        docker stop onlyoffice-documentserver 2>/dev/null || true
        docker rm onlyoffice-documentserver 2>/dev/null || true
    fi
    
    docker run -i -t -d -p 8080:80 --restart=always \
        --name onlyoffice-documentserver \
        -v /var/lib/onlyoffice/DocumentServer/data:/var/www/onlyoffice/Data \
        -v /var/lib/onlyoffice/DocumentServer/logs:/var/log/onlyoffice \
        -e JWT_SECRET="${ONLYOFFICE_SECRET}" \
        -e JWT_ENABLED=true \
        onlyoffice/documentserver:latest || {
        log_error "OnlyOffice Container konnte nicht gestartet werden"
        exit 1
    }
    
    # Warte auf OnlyOffice (länger warten, damit OnlyOffice vollständig startet)
    log_info "Warte auf OnlyOffice-Service (kann bis zu 60 Sekunden dauern)..."
    for i in {1..60}; do
        if curl -s http://127.0.0.1:8080/welcome/ > /dev/null 2>&1; then
            log_success "OnlyOffice ist bereit"
            break
        fi
        if [ $i -eq 60 ]; then
            log_warning "OnlyOffice antwortet noch nicht, aber fahre fort..."
        else
            sleep 1
        fi
    done
    
    log_success "OnlyOffice installiert"
    log_info "OnlyOffice Secret Key: ${ONLYOFFICE_SECRET}"
}

# Excalidraw Installation
install_excalidraw() {
    log_info "=== Excalidraw Installation ==="
    
    # Excalidraw Client
    log_info "Starte Excalidraw Client Container..."
    # Prüfe ob Container bereits existiert
    if docker ps -a --format '{{.Names}}' | grep -q "^excalidraw$"; then
        log_info "Excalidraw Client Container existiert bereits. Entferne alten Container..."
        docker stop excalidraw 2>/dev/null || true
        docker rm excalidraw 2>/dev/null || true
    fi
    
    docker run -i -t -d -p 8081:80 --restart=always \
        --name excalidraw \
        excalidraw/excalidraw:latest || {
        log_warning "Excalidraw Client Container konnte nicht gestartet werden."
    }
    
    # Excalidraw Room Server
    log_info "Starte Excalidraw Room Server Container..."
    # Prüfe ob Container bereits existiert
    if docker ps -a --format '{{.Names}}' | grep -q "^excalidraw-room$"; then
        log_info "Excalidraw Room Server Container existiert bereits. Entferne alten Container..."
        docker stop excalidraw-room 2>/dev/null || true
        docker rm excalidraw-room 2>/dev/null || true
    fi
    
    docker run -i -t -d -p 8082:80 --restart=always \
        --name excalidraw-room \
        -e PORT=80 \
        excalidraw/excalidraw-room:latest || {
        log_warning "Excalidraw Room Server Container konnte nicht gestartet werden."
    }
    
    sleep 5
    
    log_success "Excalidraw installiert"
}

# Projekt-Verzeichnis erstellen
setup_project_directory() {
    log_info "=== Projekt-Verzeichnis Setup ==="
    
    # Verzeichnis erstellen
    mkdir -p "$INSTALL_DIR"
    
    # Prüfe ob bereits Code vorhanden ist
    if [ -d "$INSTALL_DIR/.git" ] || [ -f "$INSTALL_DIR/app.py" ]; then
        log_warning "Projekt-Verzeichnis enthält bereits Code. Überspringe Klonen."
        return
    fi
    
    # Versuche das aktuelle Verzeichnis zu verwenden, wenn es das Projekt ist
    CURRENT_DIR=$(pwd)
    if [ -f "$CURRENT_DIR/app.py" ] && [ -f "$CURRENT_DIR/requirements.txt" ]; then
        log_info "Kopiere Projekt von $CURRENT_DIR nach $INSTALL_DIR..."
        cp -r "$CURRENT_DIR"/* "$INSTALL_DIR"/ 2>/dev/null || {
            log_warning "Kopieren fehlgeschlagen. Bitte manuell kopieren."
        }
    else
        # Wenn kein Code vorhanden, muss der Benutzer das Repository klonen
        log_info "Bitte klonen Sie das Repository manuell nach $INSTALL_DIR"
        log_info "Oder kopieren Sie die Dateien dorthin"
        read -p "Drücken Sie Enter, wenn das Repository in $INSTALL_DIR vorhanden ist..."
    fi
    
    if [ ! -f "$INSTALL_DIR/app.py" ]; then
        log_error "app.py nicht gefunden in $INSTALL_DIR"
        log_error "Bitte stellen Sie sicher, dass das Projekt in $INSTALL_DIR vorhanden ist"
        exit 1
    fi
    
    log_success "Projekt-Verzeichnis eingerichtet"
}

# Python Virtual Environment
setup_venv() {
    log_info "=== Python Virtual Environment Setup ==="
    
    cd "$INSTALL_DIR"
    
    if [ -d "venv" ]; then
        log_warning "venv existiert bereits. Überspringe Erstellung."
    else
        log_info "Erstelle Virtual Environment..."
        python3 -m venv venv
    fi
    
    log_info "Installiere Python-Dependencies..."
    source venv/bin/activate
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    
    log_success "Virtual Environment eingerichtet"
}

# Key-Generierung
generate_keys() {
    log_info "=== Key-Generierung ==="
    
    cd "$INSTALL_DIR" || {
        log_error "Konnte nicht nach $INSTALL_DIR wechseln"
        exit 1
    }
    
    if [ ! -f "venv/bin/activate" ]; then
        log_error "Virtual Environment nicht gefunden in $INSTALL_DIR/venv"
        exit 1
    fi
    
    source venv/bin/activate || {
        log_error "Konnte Virtual Environment nicht aktivieren"
        exit 1
    }
    
    # Flask Secret Key
    FLASK_SECRET=$(generate_secret)
    
    # VAPID Keys - Rufe Python-Skript direkt auf
    log_info "Generiere VAPID Keys..."
    if [ ! -f "${INSTALL_DIR}/scripts/generate_vapid_keys.py" ]; then
        log_error "VAPID Key-Generator nicht gefunden: ${INSTALL_DIR}/scripts/generate_vapid_keys.py"
        exit 1
    fi
    
    VAPID_OUTPUT=$(cd "${INSTALL_DIR}" && python3 -c "
import sys
import os
sys.path.insert(0, os.getcwd())
from scripts.generate_vapid_keys import generate_vapid_keys
keys = generate_vapid_keys()
print('VAPID_PRIVATE=' + keys['private_key_b64'])
print('VAPID_PUBLIC=' + keys['public_key_b64'])
" 2>&1)
    VAPID_EXIT_CODE=$?
    if [ $VAPID_EXIT_CODE -ne 0 ]; then
        log_error "VAPID Key-Generierung fehlgeschlagen (Exit Code: $VAPID_EXIT_CODE)"
        log_error "Python Output: $VAPID_OUTPUT"
        exit 1
    fi
    VAPID_PRIVATE=$(echo "$VAPID_OUTPUT" | grep "VAPID_PRIVATE=" | cut -d'=' -f2)
    VAPID_PUBLIC=$(echo "$VAPID_OUTPUT" | grep "VAPID_PUBLIC=" | cut -d'=' -f2)
    
    # Encryption Keys - Rufe Python-Skript direkt auf
    log_info "Generiere Encryption Keys..."
    if [ ! -f "${INSTALL_DIR}/scripts/generate_encryption_keys.py" ]; then
        log_error "Encryption Key-Generator nicht gefunden: ${INSTALL_DIR}/scripts/generate_encryption_keys.py"
        exit 1
    fi
    
    ENCRYPT_OUTPUT=$(cd "${INSTALL_DIR}" && python3 -c "
import sys
import os
sys.path.insert(0, os.getcwd())
from scripts.generate_encryption_keys import generate_encryption_key
credential_key = generate_encryption_key()
music_key = generate_encryption_key()
print('CREDENTIAL_KEY=' + credential_key)
print('MUSIC_KEY=' + music_key)
" 2>&1)
    ENCRYPT_EXIT_CODE=$?
    if [ $ENCRYPT_EXIT_CODE -ne 0 ]; then
        log_error "Encryption Key-Generierung fehlgeschlagen (Exit Code: $ENCRYPT_EXIT_CODE)"
        log_error "Python Output: $ENCRYPT_OUTPUT"
        exit 1
    fi
    CREDENTIAL_KEY=$(echo "$ENCRYPT_OUTPUT" | grep "CREDENTIAL_KEY=" | cut -d'=' -f2)
    MUSIC_KEY=$(echo "$ENCRYPT_OUTPUT" | grep "MUSIC_KEY=" | cut -d'=' -f2)
    
    # OnlyOffice Secret (bereits generiert)
    # ONLYOFFICE_SECRET ist bereits in install_onlyoffice() gesetzt
    
    # Validierung
    if [ -z "$VAPID_PRIVATE" ] || [ -z "$VAPID_PUBLIC" ]; then
        log_error "VAPID Key-Generierung fehlgeschlagen!"
        log_error "VAPID_OUTPUT war: $VAPID_OUTPUT"
        exit 1
    fi
    
    if [ -z "$CREDENTIAL_KEY" ] || [ -z "$MUSIC_KEY" ]; then
        log_error "Encryption Key-Generierung fehlgeschlagen!"
        log_error "ENCRYPT_OUTPUT war: $ENCRYPT_OUTPUT"
        exit 1
    fi
    
    log_success "Alle Keys generiert"
}

# .env-Konfiguration
configure_env() {
    log_info "=== .env-Konfiguration ==="
    
    cd "$INSTALL_DIR"
    
    # Kopiere env.example
    if [ ! -f .env ]; then
        cp docs/env.example .env
    fi
    
    # Aktualisiere .env mit generierten Werten
    log_info "Aktualisiere .env-Datei..."
    
    # SECRET_KEY
    sed -i "s|SECRET_KEY=.*|SECRET_KEY=${FLASK_SECRET}|" .env
    
    # DATABASE_URI (URL-encode password for database URI)
    # Python urllib.parse.quote wird verwendet, um Sonderzeichen im Passwort zu encodieren
    DB_PASS_URI=$(python3 -c "import urllib.parse; import sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$DB_PASS")
    DATABASE_URI="mysql+pymysql://${DB_USER}:${DB_PASS_URI}@localhost/${DB_NAME}"
    # Escape für sed (nur Pipe-Zeichen, da wir | als Trennzeichen verwenden)
    DATABASE_URI_ESC=$(echo "$DATABASE_URI" | sed 's/|/\\|/g')
    sed -i "s|DATABASE_URI=.*|DATABASE_URI=${DATABASE_URI_ESC}|" .env
    
    # VAPID Keys
    sed -i "s|VAPID_PUBLIC_KEY=.*|VAPID_PUBLIC_KEY=${VAPID_PUBLIC}|" .env
    sed -i "s|VAPID_PRIVATE_KEY=.*|VAPID_PRIVATE_KEY=${VAPID_PRIVATE}|" .env
    
    # Encryption Keys
    sed -i "s|CREDENTIAL_ENCRYPTION_KEY=.*|CREDENTIAL_ENCRYPTION_KEY=${CREDENTIAL_KEY}|" .env
    sed -i "s|MUSIC_ENCRYPTION_KEY=.*|MUSIC_ENCRYPTION_KEY=${MUSIC_KEY}|" .env
    
    # OnlyOffice - Entferne Kommentare (#) am Zeilenanfang und setze Werte
    # Entferne # am Anfang und Kommentare am Ende, dann setze Werte
    sed -i "s|^#.*ONLYOFFICE_ENABLED=.*|ONLYOFFICE_ENABLED=True|" .env
    sed -i "s|^ONLYOFFICE_ENABLED=.*|ONLYOFFICE_ENABLED=True|" .env
    # Entferne Kommentare am Ende der Zeile für ONLYOFFICE_DOCUMENT_SERVER_URL
    sed -i "s|^#.*ONLYOFFICE_DOCUMENT_SERVER_URL=\([^#]*\).*|ONLYOFFICE_DOCUMENT_SERVER_URL=\1|" .env
    sed -i "s|^ONLYOFFICE_DOCUMENT_SERVER_URL=\([^#]*\).*|ONLYOFFICE_DOCUMENT_SERVER_URL=\1|" .env
    sed -i "s|^ONLYOFFICE_DOCUMENT_SERVER_URL=.*|ONLYOFFICE_DOCUMENT_SERVER_URL=/onlyoffice|" .env
    if [ -n "$ONLYOFFICE_SECRET" ]; then
        # Entferne Kommentare am Ende der Zeile für ONLYOFFICE_SECRET_KEY
        sed -i "s|^#.*ONLYOFFICE_SECRET_KEY=\([^#]*\).*|ONLYOFFICE_SECRET_KEY=\1|" .env
        sed -i "s|^ONLYOFFICE_SECRET_KEY=\([^#]*\).*|ONLYOFFICE_SECRET_KEY=\1|" .env
        sed -i "s|^ONLYOFFICE_SECRET_KEY=.*|ONLYOFFICE_SECRET_KEY=${ONLYOFFICE_SECRET}|" .env
    fi
    # Stelle sicher, dass ONLYOFFICE-Einstellungen gesetzt sind (falls nicht in env.example vorhanden)
    if ! grep -q "^ONLYOFFICE_ENABLED=" .env; then
        echo "ONLYOFFICE_ENABLED=True" >> .env
    fi
    if ! grep -q "^ONLYOFFICE_DOCUMENT_SERVER_URL=" .env; then
        echo "ONLYOFFICE_DOCUMENT_SERVER_URL=/onlyoffice" >> .env
    fi
    if [ -n "$ONLYOFFICE_SECRET" ] && ! grep -q "^ONLYOFFICE_SECRET_KEY=" .env; then
        echo "ONLYOFFICE_SECRET_KEY=${ONLYOFFICE_SECRET}" >> .env
    fi
    
    # Excalidraw - Entferne Kommentare (#) am Zeilenanfang und setze Werte
    sed -i "s|^#.*EXCALIDRAW_ENABLED=.*|EXCALIDRAW_ENABLED=True|" .env
    sed -i "s|^EXCALIDRAW_ENABLED=.*|EXCALIDRAW_ENABLED=True|" .env
    # Entferne Kommentare am Ende der Zeile für EXCALIDRAW_URL
    sed -i "s|^#.*EXCALIDRAW_URL=\([^#]*\).*|EXCALIDRAW_URL=\1|" .env
    sed -i "s|^EXCALIDRAW_URL=\([^#]*\).*|EXCALIDRAW_URL=\1|" .env
    sed -i "s|^EXCALIDRAW_URL=.*|EXCALIDRAW_URL=/excalidraw|" .env
    # Entferne Kommentare am Ende der Zeile für EXCALIDRAW_ROOM_URL
    sed -i "s|^#.*EXCALIDRAW_ROOM_URL=\([^#]*\).*|EXCALIDRAW_ROOM_URL=\1|" .env
    sed -i "s|^EXCALIDRAW_ROOM_URL=\([^#]*\).*|EXCALIDRAW_ROOM_URL=\1|" .env
    sed -i "s|^EXCALIDRAW_ROOM_URL=.*|EXCALIDRAW_ROOM_URL=/excalidraw-room|" .env
    # EXCALIDRAW_PUBLIC_URL (optional, leer lassen wenn nicht benötigt)
    sed -i "s|^#.*EXCALIDRAW_PUBLIC_URL=.*|EXCALIDRAW_PUBLIC_URL=|" .env
    sed -i "s|^EXCALIDRAW_PUBLIC_URL=.*|EXCALIDRAW_PUBLIC_URL=|" .env
    # Stelle sicher, dass Excalidraw-Einstellungen gesetzt sind (falls nicht in env.example vorhanden)
    if ! grep -q "^EXCALIDRAW_ENABLED=" .env; then
        echo "EXCALIDRAW_ENABLED=True" >> .env
    fi
    if ! grep -q "^EXCALIDRAW_URL=" .env; then
        echo "EXCALIDRAW_URL=/excalidraw" >> .env
    fi
    if ! grep -q "^EXCALIDRAW_ROOM_URL=" .env; then
        echo "EXCALIDRAW_ROOM_URL=/excalidraw-room" >> .env
    fi
    if ! grep -q "^EXCALIDRAW_PUBLIC_URL=" .env; then
        echo "EXCALIDRAW_PUBLIC_URL=" >> .env
    fi
    
    # Production Settings
    sed -i "s|FLASK_ENV=.*|FLASK_ENV=production|" .env
    
    # E-Mail-Konfiguration
    if [ -n "$MAIL_SERVER" ]; then
        log_info "Konfiguriere E-Mail-Einstellungen..."
        sed -i "s|^MAIL_SERVER=.*|MAIL_SERVER=${MAIL_SERVER}|" .env
        sed -i "s|^MAIL_PORT=.*|MAIL_PORT=${MAIL_PORT}|" .env
        sed -i "s|^MAIL_USE_TLS=.*|MAIL_USE_TLS=${MAIL_USE_TLS}|" .env
        sed -i "s|^MAIL_USE_SSL=.*|MAIL_USE_SSL=${MAIL_USE_SSL}|" .env
        if [ -n "$MAIL_USERNAME" ]; then
            sed -i "s|^MAIL_USERNAME=.*|MAIL_USERNAME=${MAIL_USERNAME}|" .env
        else
            sed -i "s|^MAIL_USERNAME=.*|MAIL_USERNAME=|" .env
        fi
        if [ -n "$MAIL_PASSWORD" ]; then
            # Escape special characters in password for sed
            MAIL_PASSWORD_ESC=$(echo "$MAIL_PASSWORD" | sed 's/[[\.*^$()+?{|]/\\&/g')
            sed -i "s|^MAIL_PASSWORD=.*|MAIL_PASSWORD=${MAIL_PASSWORD_ESC}|" .env
        else
            sed -i "s|^MAIL_PASSWORD=.*|MAIL_PASSWORD=|" .env
        fi
        if [ -n "$MAIL_DEFAULT_SENDER" ]; then
            sed -i "s|^MAIL_DEFAULT_SENDER=.*|MAIL_DEFAULT_SENDER=${MAIL_DEFAULT_SENDER}|" .env
        else
            sed -i "s|^MAIL_DEFAULT_SENDER=.*|MAIL_DEFAULT_SENDER=|" .env
        fi
        if [ -n "$MAIL_SENDER_NAME" ]; then
            sed -i "s|^MAIL_SENDER_NAME=.*|MAIL_SENDER_NAME=${MAIL_SENDER_NAME}|" .env
        else
            sed -i "s|^MAIL_SENDER_NAME=.*|MAIL_SENDER_NAME=|" .env
        fi
        
        # IMAP-Konfiguration
        if [ -n "$IMAP_SERVER" ]; then
            sed -i "s|^IMAP_SERVER=.*|IMAP_SERVER=${IMAP_SERVER}|" .env
            sed -i "s|^IMAP_PORT=.*|IMAP_PORT=${IMAP_PORT}|" .env
            sed -i "s|^IMAP_USE_SSL=.*|IMAP_USE_SSL=${IMAP_USE_SSL}|" .env
        else
            sed -i "s|^IMAP_SERVER=.*|IMAP_SERVER=|" .env
            sed -i "s|^IMAP_PORT=.*|IMAP_PORT=993|" .env
            sed -i "s|^IMAP_USE_SSL=.*|IMAP_USE_SSL=True|" .env
        fi
    else
        log_info "E-Mail-Konfiguration übersprungen (nicht angegeben)"
        # Setze leere Werte, damit Platzhalter ersetzt werden
        sed -i "s|^MAIL_SERVER=.*|MAIL_SERVER=|" .env
        sed -i "s|^MAIL_PORT=.*|MAIL_PORT=587|" .env
        sed -i "s|^MAIL_USE_TLS=.*|MAIL_USE_TLS=True|" .env
        sed -i "s|^MAIL_USE_SSL=.*|MAIL_USE_SSL=False|" .env
        sed -i "s|^MAIL_USERNAME=.*|MAIL_USERNAME=|" .env
        sed -i "s|^MAIL_PASSWORD=.*|MAIL_PASSWORD=|" .env
        sed -i "s|^MAIL_DEFAULT_SENDER=.*|MAIL_DEFAULT_SENDER=|" .env
        sed -i "s|^MAIL_SENDER_NAME=.*|MAIL_SENDER_NAME=|" .env
        sed -i "s|^IMAP_SERVER=.*|IMAP_SERVER=|" .env
        sed -i "s|^IMAP_PORT=.*|IMAP_PORT=993|" .env
        sed -i "s|^IMAP_USE_SSL=.*|IMAP_USE_SSL=True|" .env
    fi
    
    # Sichere Berechtigungen
    chmod 600 .env
    chown www-data:www-data .env
    
    log_success ".env-Datei konfiguriert"
}

# Upload-Verzeichnisse erstellen
setup_upload_directories() {
    log_info "=== Upload-Verzeichnisse Setup ==="
    
    cd "$INSTALL_DIR"
    
    # Erstelle instance-Verzeichnis (für Flask)
    mkdir -p instance
    
    # Erstelle alle Upload-Verzeichnisse
    mkdir -p uploads/{files,chat,manuals,profile_pics,inventory/product_images,inventory/product_documents,system,attachments,booking_forms,bookings,email_attachments,veranstaltungen,wiki}
    mkdir -p uploads/chat/avatars
    
    chown -R www-data:www-data instance uploads
    chmod -R 755 instance
    chmod -R 775 uploads
    
    log_success "Upload-Verzeichnisse erstellt"
}

# Datenbank-Initialisierung wird NICHT durch das Skript durchgeführt
# Die Datenbank wird automatisch beim ersten Start von Gunicorn initialisiert
# (siehe INSTALLATION.md - Schritt 9: Supervisor konfigurieren)
# WICHTIG: Verwenden Sie -w 1 (1 Worker) für den ersten Start!

# Gunicorn Systemd Service
setup_gunicorn_service() {
    log_info "=== Gunicorn Systemd Service Setup ==="
    
    # Prüfe ob Gunicorn installiert ist
    if [ ! -f "${INSTALL_DIR}/venv/bin/gunicorn" ]; then
        log_info "Installiere Gunicorn..."
        cd "$INSTALL_DIR"
        source venv/bin/activate
        pip install gunicorn --quiet || error_exit "Gunicorn Installation fehlgeschlagen"
    fi
    
    # Service-Datei erstellen
    # WICHTIG: Verwenden Sie -w 1 (1 Worker) für den ersten Start!
    # Die Datenbank wird automatisch beim ersten Start initialisiert.
    # Nach erfolgreichem Start können Sie auf mehrere Worker umstellen (z.B. -w 4)
    cat > /etc/systemd/system/teamportal.service <<EOF
[Unit]
Description=Team Portal Gunicorn Application Server
After=network.target mysql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/venv/bin"
Environment="FLASK_ENV=production"
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn \\
    --workers 1 \\
    --bind 127.0.0.1:5000 \\
    --timeout 600 \\
    --access-logfile - \\
    --error-logfile - \\
    wsgi:app

Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
    
    # Service aktivieren und starten
    systemctl daemon-reload || error_exit "systemd daemon-reload fehlgeschlagen"
    systemctl enable teamportal || error_exit "Service-Aktivierung fehlgeschlagen"
    
    # Warte kurz bevor Start
    sleep 2
    
    systemctl start teamportal || {
        log_error "Service-Start fehlgeschlagen. Prüfe Logs mit: journalctl -u teamportal -n 50"
        log_warning "Service wird trotzdem aktiviert. Bitte manuell prüfen."
    }
    
    # Prüfe Status
    sleep 3
    if systemctl is-active --quiet teamportal; then
        log_success "Gunicorn Service läuft"
    else
        log_warning "Service-Status unklar. Prüfe mit: systemctl status teamportal"
    fi
    
    log_success "Gunicorn Service eingerichtet"
}

# Nginx Konfiguration
setup_nginx() {
    log_info "=== Nginx Konfiguration ==="
    
    # Nginx Site-Konfiguration erstellen
    cat > /etc/nginx/sites-available/teamportal <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # File upload limit
    client_max_body_size 100M;

    # OnlyOffice Document Server (OPTIONAL - nur wenn installiert)
    # WICHTIG: Kein trailing slash bei proxy_pass, damit der Pfad korrekt weitergegeben wird
    location /onlyoffice {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # OnlyOffice spezifische Header
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # WICHTIG: Content-Type Header vom Backend übernehmen
        # Standardmäßig sollte Nginx den Content-Type vom Backend übernehmen,
        # aber wir stellen sicher, dass er nicht überschrieben wird
        
        # CORS headers for OnlyOffice (wichtig für API-Zugriff)
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
        add_header Access-Control-Allow-Credentials true always;
        
        # Handle preflight requests
        if (\$request_method = 'OPTIONS') {
            add_header Access-Control-Allow-Origin * always;
            add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
            add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
            add_header Access-Control-Allow-Credentials true always;
            add_header Content-Length 0;
            add_header Content-Type text/plain;
            return 204;
        }
        
        # Timeouts für große Dokumente
        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
        send_timeout 600;
        
        # Disable buffering for OnlyOffice (wichtig für Streaming)
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # Excalidraw Room Server (OPTIONAL - nur wenn installiert)
    # WICHTIG: Muss VOR /excalidraw kommen!
    location /excalidraw-room {
        proxy_pass http://127.0.0.1:8082;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # WebSocket support (wichtig für Echtzeit-Kollaboration)
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts für WebSocket-Verbindungen
        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
        send_timeout 600;
    }

    # Excalidraw Client (OPTIONAL - nur wenn installiert)
    location /excalidraw {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts
        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
        send_timeout 600;
    }

    # Statische Dateien (MUSS VOR / kommen!)
    location /static {
        alias ${INSTALL_DIR}/app/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Uploads (MUSS VOR / kommen!)
    location /uploads {
        alias ${INSTALL_DIR}/uploads;
        expires 7d;
    }

    # Hauptanwendung (MUSS ZULETZT kommen!)
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
    
    # Site aktivieren
    ln -sf /etc/nginx/sites-available/teamportal /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
    # Nginx testen
    if ! nginx -t; then
        error_exit "Nginx-Konfigurationstest fehlgeschlagen"
    fi
    
    # Nginx neu laden
    systemctl enable nginx || error_exit "Nginx-Aktivierung fehlgeschlagen"
    systemctl restart nginx || error_exit "Nginx-Neustart fehlgeschlagen"
    
    # Prüfe Status
    sleep 2
    if systemctl is-active --quiet nginx; then
        log_success "Nginx läuft"
    else
        error_exit "Nginx läuft nicht. Prüfe Logs: journalctl -u nginx -n 50"
    fi
    
    log_success "Nginx konfiguriert"
}

# Firewall Setup
setup_firewall() {
    log_info "=== Firewall Setup ==="
    
    # UFW konfigurieren
    ufw --force enable
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    
    log_success "Firewall konfiguriert"
}

# SSL Setup
setup_ssl() {
    if [[ ! $SETUP_SSL =~ ^[JjYy]$ ]]; then
        return
    fi
    
    log_info "=== SSL Setup mit Let's Encrypt ==="
    
    # Prüfe ob Certbot verfügbar ist
    if ! command -v certbot &> /dev/null; then
        log_warning "Certbot nicht gefunden. Installiere..."
        apt-get install -y -qq certbot python3-certbot-nginx || {
            log_warning "Certbot Installation fehlgeschlagen. SSL wird übersprungen."
            return
        }
    fi
    
    # Prüfe ob Domain erreichbar ist (Port 80 muss offen sein)
    log_info "Prüfe Domain-Erreichbarkeit..."
    if ! curl -s -o /dev/null -w "%{http_code}" "http://${DOMAIN}" | grep -q "200\|301\|302\|403"; then
        log_warning "Domain $DOMAIN scheint nicht erreichbar zu sein. SSL-Setup könnte fehlschlagen."
        log_info "Stelle sicher, dass Port 80 von außen erreichbar ist und auf diesen Server zeigt."
        read -p "Trotzdem fortfahren? (j/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[JjYy]$ ]]; then
            log_info "SSL-Setup übersprungen"
            return
        fi
    fi
    
    if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$LETSENCRYPT_EMAIL" --redirect; then
        log_success "SSL konfiguriert"
        systemctl reload nginx
    else
        log_warning "SSL-Setup fehlgeschlagen. Bitte manuell einrichten mit:"
        log_info "  certbot --nginx -d $DOMAIN"
    fi
}

# Berechtigungen setzen
set_permissions() {
    log_info "=== Berechtigungen setzen ==="
    
    chown -R www-data:www-data "$INSTALL_DIR"
    chmod -R 755 "$INSTALL_DIR"
    chmod -R 775 "$INSTALL_DIR/uploads"
    
    log_success "Berechtigungen gesetzt"
}

# Zusammenfassung ausgeben
print_summary() {
    log_success "=== Installation abgeschlossen! ==="
    echo
    echo "Zusammenfassung:"
    echo "==============="
    echo "Installationspfad: $INSTALL_DIR"
    echo "Domain: $DOMAIN"
    echo "Datenbank: $DB_NAME"
    echo "Datenbank-Benutzer: $DB_USER"
    echo "Datenbank-Passwort: $DB_PASS"
    echo "MySQL Root-Passwort: $MYSQL_ROOT_PASS"
    echo
    if [ -n "$ONLYOFFICE_SECRET" ]; then
        echo "OnlyOffice Secret Key: $ONLYOFFICE_SECRET"
    fi
    echo
    if [ -n "$MAIL_SERVER" ]; then
        echo "E-Mail-Konfiguration:"
        echo "  SMTP-Server: $MAIL_SERVER"
        echo "  SMTP-Port: $MAIL_PORT"
        echo "  E-Mail-Benutzer: $MAIL_USERNAME"
        if [ -n "$IMAP_SERVER" ]; then
            echo "  IMAP-Server: $IMAP_SERVER"
            echo "  IMAP-Port: $IMAP_PORT"
        fi
        echo
    fi
    echo "WICHTIG: Speichern Sie diese Informationen sicher!"
    echo "         Besonders die Passwörter und Secret Keys!"
    echo
    echo "Nächste Schritte:"
    if [ -z "$MAIL_SERVER" ]; then
        echo "1. Konfigurieren Sie die E-Mail-Einstellungen in $INSTALL_DIR/.env (falls benötigt)"
    else
        echo "1. E-Mail-Einstellungen wurden bereits konfiguriert"
    fi
    echo "2. Warten Sie etwa 1 Minute, damit die Datenbank beim ersten Start initialisiert wird"
    echo "3. Prüfen Sie die Logs: journalctl -u teamportal -n 50"
    echo "4. Öffnen Sie http://$DOMAIN (oder https://$DOMAIN wenn SSL eingerichtet)"
    echo "5. Erstellen Sie einen Admin-Benutzer über den Setup-Assistenten"
    echo
    echo "WICHTIG: Nach erfolgreichem ersten Start können Sie auf mehrere Worker umstellen:"
    echo "  sudo nano /etc/systemd/system/teamportal.service"
    echo "  Ändern Sie '--workers 1' zu '--workers 4' (oder mehr)"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl restart teamportal"
    echo
    echo "Service-Status prüfen:"
    echo "  systemctl status teamportal"
    echo "  systemctl status nginx"
    echo "  docker ps"
    echo
    echo "Logs ansehen:"
    echo "  journalctl -u teamportal -f"
    echo "  journalctl -u nginx -f"
    echo "  docker logs onlyoffice-documentserver"
    echo "  docker logs excalidraw"
    echo "  docker logs excalidraw-room"
    echo
    echo "Bei Problemen:"
    echo "  - Prüfe Logs: journalctl -u teamportal -n 100"
    echo "  - Prüfe Nginx: nginx -t && systemctl status nginx"
    echo "  - Prüfe Datenbank: mysql -u $DB_USER -p$DB_PASS $DB_NAME -e 'SHOW TABLES;'"
    echo
}

# Hauptfunktion
main() {
    echo "=========================================="
    echo "Team Portal - Automatische Installation"
    echo "Ubuntu 24.04.3 LTS"
    echo "=========================================="
    echo
    
    check_root
    check_ubuntu
    gather_information
    
    setup_system
    setup_mysql
    install_docker
    install_onlyoffice
    install_excalidraw
    setup_project_directory
    setup_venv
    generate_keys
    configure_env
    setup_upload_directories
    # init_database wird NICHT aufgerufen - DB wird durch Gunicorn beim ersten Start initialisiert
    setup_gunicorn_service
    setup_nginx
    setup_firewall
    setup_ssl
    set_permissions
    
    print_summary
}

# Skript ausführen
main "$@"
