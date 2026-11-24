#!/usr/bin/env bash
# ==============================================================================
# Prismateams – Automatische HyCanvas ("Canvas") Integration & Migration
#
# Führt alle notwendigen Schritte idempotent aus:
#   1. .env anlegen/aktualisieren (COMPOSE_PROFILES, HYCANVAS_*, sichere Secrets)
#   2. Nginx-Config (docker/nginx/default.conf) prüfen & /hycanvas/-Block ergänzen
#   3. Datenbank-Tabelle canvas_documents anlegen
#   4. Docker-Container (hycanvas-db, hycanvas, app, proxy) starten/neuladen
#
# Verwendung:
#   bash migrations/migrate_hycanvas.sh
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

ENV_FILE="${PROJECT_ROOT}/.env"
ENV_EXAMPLE="${PROJECT_ROOT}/docs/env.docker.example"
NGINX_CONF="${PROJECT_ROOT}/docker/nginx/default.conf"

echo "[1/4] Prüfe und aktualisiere .env..."
if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ -f "${ENV_EXAMPLE}" ]]; then
        cp "${ENV_EXAMPLE}" "${ENV_FILE}"
        echo "  -> .env aus docs/env.docker.example erstellt."
    else
        touch "${ENV_FILE}"
        echo "  -> Leere .env erstellt."
    fi
fi

gen_hex() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import secrets; print(secrets.token_hex(32))"
    else
        head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
    fi
}

upsert_env() {
    local key="$1"
    local value="$2"
    if grep -qE "^${key}=" "${ENV_FILE}"; then
        sed -i.bak -E "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}" && rm -f "${ENV_FILE}.bak"
    else
        printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
    fi
}

get_env() {
    local key="$1"
    grep -E "^${key}=" "${ENV_FILE}" | head -n1 | cut -d'=' -f2- | tr -d '\r' || true
}

# COMPOSE_PROFILES um hycanvas erweitern
CURRENT_PROFILES="$(get_env COMPOSE_PROFILES)"
if [[ -z "${CURRENT_PROFILES}" ]]; then
    upsert_env "COMPOSE_PROFILES" "proxy,onlyoffice,excalidraw,mirotalk,hycanvas"
elif [[ ",${CURRENT_PROFILES}," != *",hycanvas,"* ]]; then
    upsert_env "COMPOSE_PROFILES" "${CURRENT_PROFILES},hycanvas"
fi

# Standardwerte setzen, falls fehlend
[[ -z "$(get_env HYCANVAS_ENABLED)" ]] && upsert_env "HYCANVAS_ENABLED" "True"
[[ -z "$(get_env HYCANVAS_URL)" ]] && upsert_env "HYCANVAS_URL" "/hycanvas"
[[ -z "$(get_env HYCANVAS_API_URL)" ]] && upsert_env "HYCANVAS_API_URL" "http://hycanvas:8005"
[[ -z "$(get_env HYCANVAS_HOST_BIND)" ]] && upsert_env "HYCANVAS_HOST_BIND" "127.0.0.1"
[[ -z "$(get_env HYCANVAS_HOST_PORT)" ]] && upsert_env "HYCANVAS_HOST_PORT" "8005"
[[ -z "$(get_env HYCANVAS_DB_USER)" ]] && upsert_env "HYCANVAS_DB_USER" "hycanvas"
[[ -z "$(get_env HYCANVAS_DB_NAME)" ]] && upsert_env "HYCANVAS_DB_NAME" "hycanvas"
[[ -z "$(get_env HYCANVAS_COOKIE_SECURE)" ]] && upsert_env "HYCANVAS_COOKIE_SECURE" "False"

CUR_DB_PASS="$(get_env HYCANVAS_DB_PASSWORD)"
if [[ -z "${CUR_DB_PASS}" || "${CUR_DB_PASS}" == *"change-me"* || "${CUR_DB_PASS}" == *"changeme"* ]]; then
    upsert_env "HYCANVAS_DB_PASSWORD" "$(gen_hex)"
fi

CUR_JWT="$(get_env HYCANVAS_JWT_SECRET)"
if [[ -z "${CUR_JWT}" || "${CUR_JWT}" == *"change-me"* || "${CUR_JWT}" == *"changeme"* ]]; then
    upsert_env "HYCANVAS_JWT_SECRET" "$(gen_hex)"
fi
echo "  -> .env aktualisiert."

echo "[2/4] Prüfe Nginx-Konfiguration (${NGINX_CONF})..."
if [[ -f "${NGINX_CONF}" ]] && ! grep -q "location /hycanvas/" "${NGINX_CONF}"; then
    python3 - "${NGINX_CONF}" << 'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
text = p.read_text(encoding='utf-8')
block = """    # HyCanvas (Canvas-Modul)
    location /hycanvas/ {
        proxy_pass http://hycanvas:8005/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_hide_header X-Frame-Options;
        proxy_buffering off;
        proxy_read_timeout 600;
    }

"""
anchor = "    # WebSockets für Socket.IO"
if anchor in text:
    text = text.replace(anchor, block + anchor, 1)
else:
    text = text.replace("    location / {", block + "    location / {", 1)
p.write_text(text, encoding='utf-8')
print("  -> /hycanvas/ Proxy-Block eingefügt.")
PYEOF
else
    echo "  -> /hycanvas/ Proxy-Block bereits vorhanden."
fi

echo "[3/4] Starte/Aktualisiere Docker-Container (inkl. hycanvas)..."
if command -v docker >/dev/null 2>&1; then
    docker compose pull hycanvas hycanvas-db || true
    docker compose up -d --build app
    docker compose up -d

    echo "[4/4] Stelle Datenbank-Tabelle canvas_documents und Modul-Aktivierung sicher..."
    docker compose exec -T app python3 -c "
import os
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
from app import create_app, db
from app.models.canvas import CanvasDocument
from app.models.settings import SystemSettings
app = create_app()
with app.app_context():
    db.create_all()
    if not SystemSettings.query.filter_by(key='module_canvas_enabled').first():
        db.session.add(SystemSettings(key='module_canvas_enabled', value='true', description='Canvas (HyCanvas) Modul'))
        db.session.commit()
print('  -> canvas_documents & module_canvas_enabled bereit.')
"
    docker compose exec -T proxy nginx -s reload >/dev/null 2>&1 || true
else
    echo "  -> Docker nicht gefunden. Überspringe Container-Start und DB-Exec."
fi

echo "Fertig! Das Canvas-Modul (HyCanvas) ist eingerichtet und unter /canvas erreichbar."
