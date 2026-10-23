#!/bin/bash
# Warte auf MySQL, initialisiere Schema einmalig, starte Gunicorn (oder CMD).
set -euo pipefail

log() { echo "[entrypoint] $*"; }

wait_for_db() {
    local uri="${DATABASE_URI:-}"
    if [ -z "$uri" ]; then
        log "DATABASE_URI nicht gesetzt – überspringe DB-Wait"
        return 0
    fi
    # Nur MySQL/MariaDB warten
    case "$uri" in
        mysql*|*pymysql*) ;;
        *)
            log "Kein MySQL-URI – überspringe DB-Wait"
            return 0
            ;;
    esac

    log "Warte auf Datenbank..."
    local i
    for i in $(seq 1 60); do
        if python - <<'PY'
import os, sys
from urllib.parse import urlparse, unquote

uri = os.environ.get("DATABASE_URI", "")
# mysql+pymysql://user:pass@host:port/db
u = uri.replace("mysql+pymysql://", "mysql://", 1)
p = urlparse(u)
host = p.hostname or "db"
port = p.port or 3306
user = unquote(p.username or "")
password = unquote(p.password or "")
db = (p.path or "/").lstrip("/") or None

try:
    import pymysql
    conn = pymysql.connect(
        host=host, port=port, user=user, password=password,
        database=db, connect_timeout=3,
    )
    conn.close()
    sys.exit(0)
except Exception as e:
    sys.stderr.write(str(e) + "\n")
    sys.exit(1)
PY
        then
            log "Datenbank erreichbar (${i}s)"
            return 0
        fi
        sleep 2
    done
    log "FEHLER: Datenbank nach 120s nicht erreichbar"
    return 1
}

init_schema() {
    if [ "${SKIP_DB_INIT:-0}" = "1" ] || [ "${SKIP_DB_INIT:-false}" = "true" ]; then
        log "SKIP_DB_INIT gesetzt – Schema-Init übersprungen"
        return 0
    fi
    log "Datenbank-Schema initialisieren..."
    export FLASK_ENV="${FLASK_ENV:-production}"
    export PRISMATEAMS_FORCE_SCHEMA_INIT=1
    export PRISMATEAMS_SKIP_BACKGROUND_JOBS=1
    python scripts/init_database.py || {
        log "WARNUNG: init_database.py fehlgeschlagen (erneuter Start kann ok sein)"
        return 0
    }
    log "Schema-Init abgeschlossen"
}

mkdir -p /app/uploads /app/instance 2>/dev/null || true

wait_for_db
init_schema

log "Starte: $*"
exec "$@"
