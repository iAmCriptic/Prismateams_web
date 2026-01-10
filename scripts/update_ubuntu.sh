#!/bin/bash

###############################################################################
# Update-Skript für Ubuntu
# Team Portal - Prismateams Web
#
# Dieses Skript führt folgende Schritte aus:
# 1. Stoppt den teamportal-Service
# 2. Führt alle Migrationen im migrations/ Ordner aus
# 3. Startet den teamportal-Service wieder
#
# Verwendung:
#   sudo bash scripts/update_ubuntu.sh
#
###############################################################################

set -e  # Beende bei Fehlern
set -o pipefail  # Beende bei Fehlern in Pipes

# Error Handler
error_exit() {
    log_error "$1"
    log_error "Update fehlgeschlagen! Service wurde möglicherweise nicht neu gestartet."
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

# Finde Installationsverzeichnis
find_install_dir() {
    # Versuche mehrere mögliche Pfade
    POSSIBLE_DIRS=(
        "/var/www/teamportal"
        "$(dirname "$(dirname "$(readlink -f "$0")")")"
        "$(pwd)"
    )
    
    for dir in "${POSSIBLE_DIRS[@]}"; do
        if [ -f "$dir/app.py" ] && [ -d "$dir/migrations" ]; then
            INSTALL_DIR="$dir"
            log_info "Installationsverzeichnis gefunden: $INSTALL_DIR"
            return 0
        fi
    done
    
    log_error "Installationsverzeichnis nicht gefunden!"
    log_info "Bitte führen Sie das Skript aus dem Projektverzeichnis aus oder setzen Sie INSTALL_DIR manuell."
    exit 1
}

# Prüfe ob Service existiert
check_service() {
    if ! systemctl list-unit-files | grep -q "^teamportal.service"; then
        log_warning "Service 'teamportal.service' nicht gefunden."
        log_info "Möglicherweise wurde das System noch nicht mit install_ubuntu.sh installiert."
        read -p "Trotzdem fortfahren? (j/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[JjYy]$ ]]; then
            exit 1
        fi
        SERVICE_EXISTS=0
    else
        SERVICE_EXISTS=1
    fi
}

# Stoppe Service
stop_service() {
    if [ $SERVICE_EXISTS -eq 0 ]; then
        log_info "Service existiert nicht - überspringe Stopp."
        return 0
    fi
    
    log_info "Stoppe teamportal-Service..."
    
    if systemctl is-active --quiet teamportal; then
        systemctl stop teamportal || error_exit "Service konnte nicht gestoppt werden"
        log_success "Service gestoppt"
        
        # Warte kurz, damit der Service vollständig gestoppt ist
        sleep 2
    else
        log_info "Service läuft bereits nicht"
    fi
}

# Führe Migrationen aus
run_migrations() {
    log_info "=== Führe Migrationen aus ==="
    
    cd "$INSTALL_DIR" || error_exit "Konnte nicht nach $INSTALL_DIR wechseln"
    
    # Prüfe ob Virtual Environment existiert
    if [ ! -f "venv/bin/activate" ]; then
        error_exit "Virtual Environment nicht gefunden in $INSTALL_DIR/venv"
    fi
    
    # Aktiviere Virtual Environment
    source venv/bin/activate || error_exit "Konnte Virtual Environment nicht aktivieren"
    
    # Prüfe ob migrations Verzeichnis existiert
    if [ ! -d "migrations" ]; then
        log_warning "migrations Verzeichnis nicht gefunden. Keine Migrationen auszuführen."
        return 0
    fi
    
    # Finde alle Python-Migrationsdateien (außer __pycache__ und __init__.py)
    MIGRATION_FILES=$(find migrations -name "*.py" -type f ! -name "__init__.py" ! -path "*/__pycache__/*" | sort)
    
    if [ -z "$MIGRATION_FILES" ]; then
        log_info "Keine Migrationen gefunden."
        return 0
    fi
    
    log_info "Gefundene Migrationen:"
    while IFS= read -r file; do
        [ -z "$file" ] && continue
        log_info "  - $file"
    done <<< "$MIGRATION_FILES"
    
    # Führe jede Migration aus
    TOTAL_MIGRATIONS=$(echo "$MIGRATION_FILES" | wc -l)
    MIGRATION_COUNT=0
    FAILED_MIGRATIONS=()
    
    while IFS= read -r migration_file; do
        [ -z "$migration_file" ] && continue
        
        MIGRATION_COUNT=$((MIGRATION_COUNT + 1))
        log_info ""
        log_info "Führe Migration aus: $migration_file ($MIGRATION_COUNT/$TOTAL_MIGRATIONS)"
        
        # Führe Migration aus
        if python3 "$migration_file"; then
            log_success "Migration erfolgreich: $migration_file"
        else
            EXIT_CODE=$?
            log_error "Migration fehlgeschlagen: $migration_file (Exit Code: $EXIT_CODE)"
            FAILED_MIGRATIONS+=("$migration_file")
            
            # Bei Fehler: Stoppe weitere Migrationen
            log_error "Migration abgebrochen aufgrund von Fehlern."
            error_exit "Migration fehlgeschlagen: $migration_file"
        fi
    done <<< "$MIGRATION_FILES"
    
    # Prüfe ob Migrationen fehlgeschlagen sind
    if [ ${#FAILED_MIGRATIONS[@]} -gt 0 ]; then
        log_error "Folgende Migrationen sind fehlgeschlagen:"
        for failed in "${FAILED_MIGRATIONS[@]}"; do
            log_error "  - $failed"
        done
        error_exit "Mindestens eine Migration ist fehlgeschlagen!"
    fi
    
    log_success "Alle Migrationen erfolgreich abgeschlossen"
}

# Starte Service
start_service() {
    if [ $SERVICE_EXISTS -eq 0 ]; then
        log_info "Service existiert nicht - überspringe Start."
        return 0
    fi
    
    log_info "Starte teamportal-Service..."
    
    if systemctl start teamportal; then
        log_success "Service gestartet"
        
        # Warte kurz und prüfe Status
        sleep 3
        if systemctl is-active --quiet teamportal; then
            log_success "Service läuft erfolgreich"
        else
            log_warning "Service-Status unklar. Prüfe mit: systemctl status teamportal"
            log_info "Logs ansehen: journalctl -u teamportal -n 50"
        fi
    else
        log_error "Service konnte nicht gestartet werden!"
        log_info "Bitte manuell starten mit: systemctl start teamportal"
        log_info "Logs ansehen: journalctl -u teamportal -n 50"
        error_exit "Service-Start fehlgeschlagen"
    fi
}

# Hauptfunktion
main() {
    echo "=========================================="
    echo "Team Portal - Update-Skript"
    echo "Ubuntu"
    echo "=========================================="
    echo
    
    check_root
    find_install_dir
    check_service
    
    log_info "Installationsverzeichnis: $INSTALL_DIR"
    log_info "Service-Status: $([ $SERVICE_EXISTS -eq 1 ] && echo "vorhanden" || echo "nicht vorhanden")"
    echo
    
    # Bestätigung
    read -p "Update durchführen? (j/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[JjYy]$ ]]; then
        log_info "Update abgebrochen"
        exit 0
    fi
    
    # Führe Update-Schritte aus
    stop_service
    run_migrations
    start_service
    
    echo
    log_success "=== Update erfolgreich abgeschlossen! ==="
    echo
    echo "Nächste Schritte:"
    echo "==============="
    echo "1. Prüfe Service-Status: systemctl status teamportal"
    echo "2. Prüfe Logs: journalctl -u teamportal -n 50"
    echo "3. Teste die Anwendung im Browser"
    echo
}

# Skript ausführen
main "$@"
