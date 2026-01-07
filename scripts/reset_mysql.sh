#!/bin/bash

###############################################################################
# MySQL/MariaDB Komplette Deinstallation und Reset
#
# Dieses Skript entfernt MySQL/MariaDB komplett vom System und setzt alles
# auf Werkseinstellungen zurück, auch wenn das Root-Passwort nicht bekannt ist.
#
# WARNUNG: Dieses Script löscht ALLE MySQL-Datenbanken und -Daten dauerhaft!
#
# Verwendung:
#   sudo bash scripts/reset_mysql.sh
#
###############################################################################

set -e  # Beende bei Fehlern
set -o pipefail  # Beende bei Fehlern in Pipes

# Farben für Ausgabe
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging-Funktionen
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNUNG]${NC} $1"
}

log_error() {
    echo -e "${RED}[FEHLER]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[ERFOLG]${NC} $1"
}

# Error Handler
error_exit() {
    log_error "$1"
    exit 1
}

# Trap für Fehler
trap 'error_exit "Fehler in Zeile $LINENO. Befehl: $BASH_COMMAND"' ERR

# Prüfen ob als root/sudo ausgeführt
if [ "$EUID" -ne 0 ]; then
    log_error "Dieses Script muss als root oder mit sudo ausgeführt werden!"
    exit 1
fi

# Warnung anzeigen
echo ""
log_warning "=========================================="
log_warning "  MYSQL/MARIADB KOMPLETTE DEINSTALLATION"
log_warning "=========================================="
echo ""
log_error "WARNUNG: Dieses Script wird:"
log_error "  - Alle MySQL/MariaDB-Datenbanken LÖSCHEN"
log_error "  - Alle MySQL-Daten dauerhaft ENTFERNEN"
log_error "  - MySQL/MariaDB komplett deinstallieren"
log_error "  - Alle Konfigurationsdateien entfernen"
echo ""
log_warning "Diese Aktion kann NICHT rückgängig gemacht werden!"
echo ""

# Bestätigung einholen
read -p "Möchten Sie wirklich fortfahren? (JA zum Bestätigen): " confirmation
if [ "$confirmation" != "JA" ]; then
    log_info "Abgebrochen."
    exit 0
fi

echo ""
log_info "Starte MySQL/MariaDB Deinstallation..."
echo ""

# Schritt 1: MySQL/MariaDB Services stoppen
log_info "Schritt 1: Stoppe MySQL/MariaDB Services..."

# Prüfe welche MySQL-Variante läuft
if systemctl is-active --quiet mysql 2>/dev/null; then
    log_info "Stoppe MySQL Service..."
    systemctl stop mysql || true
    systemctl disable mysql || true
elif systemctl is-active --quiet mariadb 2>/dev/null; then
    log_info "Stoppe MariaDB Service..."
    systemctl stop mariadb || true
    systemctl disable mariadb || true
fi

# Zusätzlich alle mysql-Prozesse beenden (falls Service nicht gestoppt wurde)
log_info "Beende alle laufenden MySQL-Prozesse..."
pkill -9 mysql || true
pkill -9 mysqld || true
pkill -9 mysqld_safe || true
sleep 2

log_success "Services gestoppt."
echo ""

# Schritt 2: MySQL/MariaDB Pakete identifizieren
log_info "Schritt 2: Identifiziere installierte MySQL/MariaDB Pakete..."

# Liste aller installierten MySQL/MariaDB Pakete
MYSQL_PACKAGES=$(dpkg -l | grep -E "mysql|mariadb" | awk '{print $2}' || true)

if [ -z "$MYSQL_PACKAGES" ]; then
    log_warning "Keine MySQL/MariaDB Pakete gefunden."
else
    log_info "Gefundene Pakete:"
    echo "$MYSQL_PACKAGES"
    echo ""
fi

# Schritt 3: Pakete deinstallieren
log_info "Schritt 3: Deinstalliere MySQL/MariaDB Pakete..."

if [ -n "$MYSQL_PACKAGES" ]; then
    # Entferne Pakete ohne Konfigurationsdateien zu löschen (später manuell)
    apt-get remove --purge -y $MYSQL_PACKAGES 2>/dev/null || true
    
    # Entferne auch als Abhängigkeiten markierte Pakete
    apt-get autoremove -y 2>/dev/null || true
    apt-get autoclean -y 2>/dev/null || true
fi

log_success "Pakete deinstalliert."
echo ""

# Schritt 4: Datenverzeichnisse und Konfigurationsdateien löschen
log_info "Schritt 4: Lösche Datenverzeichnisse und Konfigurationsdateien..."

# MySQL/MariaDB Datenverzeichnisse
DATA_DIRS=(
    "/var/lib/mysql"
    "/var/lib/mysql-files"
    "/var/lib/mysql-keyring"
    "/var/lib/mysql-upgrade"
)

# Konfigurationsdateien
CONFIG_FILES=(
    "/etc/mysql"
    "/etc/my.cnf"
    "/root/.my.cnf"
    "/root/.mysql_history"
    "/etc/apparmor.d/usr.sbin.mysqld"
    "/var/log/mysql"
    "/var/log/mysqld.log"
)

# Lösche Datenverzeichnisse
for dir in "${DATA_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        log_info "Lösche: $dir"
        rm -rf "$dir"
    fi
done

# Lösche Konfigurationsdateien
for file in "${CONFIG_FILES[@]}"; do
    if [ -e "$file" ]; then
        log_info "Lösche: $file"
        rm -rf "$file"
    fi
done

log_success "Dateien und Verzeichnisse gelöscht."
echo ""

# Schritt 5: MySQL-Benutzer und -Gruppen entfernen (optional)
log_info "Schritt 5: Prüfe MySQL-Benutzer und -Gruppen..."

# Prüfe ob mysql/mariadb Benutzer existiert
if id "mysql" &>/dev/null; then
    log_info "Entferne mysql Benutzer..."
    userdel -r mysql 2>/dev/null || true
    log_success "mysql Benutzer entfernt."
fi

if id "mariadb" &>/dev/null; then
    log_info "Entferne mariadb Benutzer..."
    userdel -r mariadb 2>/dev/null || true
    log_success "mariadb Benutzer entfernt."
fi

# Prüfe ob mysql/mariadb Gruppen existieren
if getent group mysql &>/dev/null; then
    log_info "Entferne mysql Gruppe..."
    groupdel mysql 2>/dev/null || true
    log_success "mysql Gruppe entfernt."
fi

if getent group mariadb &>/dev/null; then
    log_info "Entferne mariadb Gruppe..."
    groupdel mariadb 2>/dev/null || true
    log_success "mariadb Gruppe entfernt."
fi

echo ""

# Schritt 6: Apt-Cache aufräumen
log_info "Schritt 6: Räume Apt-Cache auf..."
apt-get update 2>/dev/null || true
log_success "Apt-Cache aktualisiert."
echo ""

# Schritt 7: Finale Prüfung
log_info "Schritt 7: Führe finale Prüfung durch..."

# Prüfe ob noch MySQL-Prozesse laufen
if pgrep mysql > /dev/null 2>&1; then
    log_warning "Warnung: Es laufen noch MySQL-Prozesse!"
else
    log_success "Keine MySQL-Prozesse mehr aktiv."
fi

# Prüfe ob noch MySQL-Verzeichnisse existieren
REMAINING_DIRS=$(find /var/lib -name "*mysql*" -type d 2>/dev/null || true)
if [ -n "$REMAINING_DIRS" ]; then
    log_warning "Warnung: Folgende MySQL-Verzeichnisse existieren noch:"
    echo "$REMAINING_DIRS"
else
    log_success "Keine MySQL-Verzeichnisse mehr vorhanden."
fi

echo ""

# Zusammenfassung
log_success "=========================================="
log_success "  DEINSTALLATION ABGESCHLOSSEN"
log_success "=========================================="
echo ""
log_info "MySQL/MariaDB wurde vollständig vom System entfernt."
log_info "Alle Datenbanken, Daten und Konfigurationen wurden gelöscht."
echo ""
log_info "Um MySQL/MariaDB neu zu installieren, können Sie verwenden:"
log_info "  sudo apt-get update"
log_info "  sudo apt-get install mysql-server"
log_info "  oder"
log_info "  sudo apt-get install mariadb-server"
echo ""
log_warning "Hinweis: Nach der Neuinstallation müssen Sie MySQL neu konfigurieren."
echo ""

