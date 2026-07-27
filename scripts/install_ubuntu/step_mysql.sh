#!/bin/bash
# MySQL/MariaDB

step_mysql() {
    if ! is_yes "$SETUP_MYSQL"; then
        print_manual_mysql_hint
        return 2
    fi

    if systemctl is-active --quiet mysql || systemctl is-active --quiet mariadb; then
        log_info "MySQL läuft bereits"
    else
        systemctl start mysql 2>/dev/null || systemctl start mariadb 2>/dev/null
        systemctl enable mysql 2>/dev/null || systemctl enable mariadb 2>/dev/null
    fi

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
        log_error "MySQL konnte nicht gestartet werden"
        return 1
    fi

    log_info "Konfiguriere MySQL..."
    if mysql -u root -e "SELECT 1" 2>/dev/null; then
        log_info "Setze MySQL Root-Passwort..."
        mysql -u root <<EOF
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '${MYSQL_ROOT_PASS}';
FLUSH PRIVILEGES;
EOF
    else
        log_warning "MySQL Root-Passwort ist bereits gesetzt – prüfe bereitgestelltes Passwort..."
        if ! mysql -u root -p"${MYSQL_ROOT_PASS}" -e "SELECT 1" 2>/dev/null; then
            log_error "MySQL Root-Passwort falsch oder MySQL nicht korrekt konfiguriert"
            return 1
        fi
    fi

    log_info "Erstelle Datenbank und Benutzer..."
    if ! mysql -u root -p"${MYSQL_ROOT_PASS}" <<EOF 2>/dev/null
CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
EOF
    then
        log_error "Datenbank-Erstellung fehlgeschlagen"
        return 1
    fi

    if mysql -u "${DB_USER}" -p"${DB_PASS}" -e "USE ${DB_NAME}; SELECT 1;" 2>/dev/null; then
        log_success "Datenbank-Verbindungstest erfolgreich"
    else
        log_warning "Datenbank-Verbindungstest fehlgeschlagen"
    fi

    log_success "MySQL konfiguriert (${DB_NAME} / ${DB_USER})"
    return 0
}
