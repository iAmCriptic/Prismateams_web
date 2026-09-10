#!/bin/bash
# MySQL 8.0 (24.04) / MySQL 8.4 (26.04) / MariaDB-Fallback
#
# 26.04 liefert MySQL 8.4: mysql_native_password ist deaktiviert.
# PyMySQL spricht caching_sha2_password – Plugin nicht erzwingen.

_mysql_cli() {
    if command -v mysql >/dev/null 2>&1; then
        echo mysql
    elif command -v mariadb >/dev/null 2>&1; then
        echo mariadb
    else
        echo mysql
    fi
}

_mysql_admin() {
    if command -v mysqladmin >/dev/null 2>&1; then
        echo mysqladmin
    elif command -v mariadb-admin >/dev/null 2>&1; then
        echo mariadb-admin
    else
        echo mysqladmin
    fi
}

step_mysql() {
    if ! is_yes "$SETUP_MYSQL"; then
        print_manual_mysql_hint
        return 2
    fi

    local MYSQL
    local MYSQLADMIN
    MYSQL="$(_mysql_cli)"
    MYSQLADMIN="$(_mysql_admin)"

    if systemctl is-active --quiet mysql || systemctl is-active --quiet mariadb; then
        log_info "MySQL/MariaDB läuft bereits"
    else
        systemctl start mysql 2>/dev/null || systemctl start mariadb 2>/dev/null
        systemctl enable mysql 2>/dev/null || systemctl enable mariadb 2>/dev/null
    fi

    log_info "Warte auf MySQL-Service..."
    MYSQL_READY=0
    local i
    for i in {1..60}; do
        if "$MYSQLADMIN" ping -h localhost --silent 2>/dev/null \
            || "$MYSQL" --protocol=socket -u root -e "SELECT 1" >/dev/null 2>&1; then
            MYSQL_READY=1
            break
        fi
        sleep 1
    done
    if [ $MYSQL_READY -eq 0 ]; then
        log_error "MySQL konnte nicht gestartet werden"
        systemctl status mysql --no-pager 2>&1 | tail -20 || true
        systemctl status mariadb --no-pager 2>&1 | tail -20 || true
        return 1
    fi

    local mysql_ver
    mysql_ver=$("$MYSQL" --version 2>/dev/null | head -n1 || echo unbekannt)
    log_info "Datenbank-Server: ${mysql_ver}"

    log_info "Konfiguriere MySQL (Standard-Auth, kein mysql_native_password)..."
    local mysql_err
    mysql_err=$(mktemp)

    if "$MYSQL" --protocol=socket -u root -e "SELECT 1" >/dev/null 2>&1; then
        log_info "Setze MySQL Root-Passwort (caching_sha2 / Server-Default)..."
        # IDENTIFIED BY ohne WITH → Default-Plugin (8.0/8.4: caching_sha2_password)
        if ! "$MYSQL" --protocol=socket -u root >"$mysql_err" 2>&1 <<EOF
ALTER USER 'root'@'localhost' IDENTIFIED BY '${MYSQL_ROOT_PASS}';
FLUSH PRIVILEGES;
EOF
        then
            log_error "Root-Passwort konnte nicht gesetzt werden"
            log_error "$(cat "$mysql_err")"
            rm -f "$mysql_err"
            return 1
        fi
    else
        log_warning "MySQL Root-Passwort ist bereits gesetzt – prüfe bereitgestelltes Passwort..."
        if ! "$MYSQL" -u root -p"${MYSQL_ROOT_PASS}" -e "SELECT 1" >/dev/null 2>&1; then
            log_error "MySQL Root-Passwort falsch oder MySQL nicht korrekt konfiguriert"
            rm -f "$mysql_err"
            return 1
        fi
    fi

    log_info "Erstelle Datenbank und Benutzer..."
    if ! "$MYSQL" -u root -p"${MYSQL_ROOT_PASS}" >"$mysql_err" 2>&1 <<EOF
CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
ALTER USER '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
EOF
    then
        log_error "Datenbank-Erstellung fehlgeschlagen"
        log_error "$(cat "$mysql_err")"
        rm -f "$mysql_err"
        return 1
    fi
    rm -f "$mysql_err"

    if "$MYSQL" -u "${DB_USER}" -p"${DB_PASS}" -e "USE ${DB_NAME}; SELECT 1;" >/dev/null 2>&1; then
        log_success "Datenbank-Verbindungstest erfolgreich"
    else
        log_warning "Datenbank-Verbindungstest fehlgeschlagen"
    fi

    log_success "MySQL konfiguriert (${DB_NAME} / ${DB_USER})"
    return 0
}
