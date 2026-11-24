#!/usr/bin/env bash
# ==============================================================================
# Prismateams – Automatische HyCanvas ("Canvas") Migration (Natives Portal + Docker HyCanvas)
#
# Geht immer davon aus, dass Prismateams nativ auf dem Host läuft und
# HyCanvas + hycanvas-db als Docker-Container auf 127.0.0.1:8005 bereitgestellt werden.
#
# Führt alle Schritte idempotent aus, ohne bestehende Anpassungen zu überschreiben:
#   1. .env ergänzen (HYCANVAS_*, COMPOSE_PROFILES, sichere Secrets)
#   2. Host-Nginx (/etc/nginx/sites-available/*) & docker/nginx/default.conf prüfen/ergänzen
#   3. Nur Docker-Container hycanvas & hycanvas-db starten (ohne app/db anzufassen)
#   4. Tabelle canvas_documents & module_canvas_enabled über lokales .venv anlegen
#
# Verwendung:
#   sudo bash migrations/migrate_hycanvas.sh
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

ENV_FILE="${PROJECT_ROOT}/.env"
ENV_EXAMPLE="${PROJECT_ROOT}/docs/env.docker.example"
DOCKER_NGINX_CONF="${PROJECT_ROOT}/docker/nginx/default.conf"

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

# COMPOSE_PROFILES um hycanvas erweitern (bestehende Profile bleiben erhalten)
CURRENT_PROFILES="$(get_env COMPOSE_PROFILES)"
if [[ -z "${CURRENT_PROFILES}" ]]; then
    upsert_env "COMPOSE_PROFILES" "hycanvas"
elif [[ ",${CURRENT_PROFILES}," != *",hycanvas,"* ]]; then
    upsert_env "COMPOSE_PROFILES" "${CURRENT_PROFILES},hycanvas"
fi

# Natives Portal spricht HyCanvas immer über 127.0.0.1:8005 an
[[ -z "$(get_env HYCANVAS_ENABLED)" ]] && upsert_env "HYCANVAS_ENABLED" "True"
[[ -z "$(get_env HYCANVAS_URL)" ]] && upsert_env "HYCANVAS_URL" "/hycanvas"
upsert_env "HYCANVAS_API_URL" "http://127.0.0.1:8005"
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
echo "  -> .env aktualisiert (HYCANVAS_API_URL=http://127.0.0.1:8005)."

echo "[2/4] Prüfe Nginx-Konfiguration..."
patch_nginx_file() {
    local conf_file="$1"
    local upstream="$2"
    python3 - "${conf_file}" "${upstream}" << 'PYEOF'
import sys, pathlib, re
p = pathlib.Path(sys.argv[1])
upstream = sys.argv[2]
text = p.read_text(encoding='utf-8')
if 'location /hycanvas/' in text and 'sub_filter \'"/_next/' in text:
    sys.exit(0)

block = f"""    # HyCanvas (Canvas-Modul) – alles über /hycanvas/ per sub_filter
    location /hycanvas/ {{
        proxy_pass http://{upstream}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Accept-Encoding "";
        proxy_hide_header X-Frame-Options;
        proxy_buffering off;
        proxy_read_timeout 600;

        sub_filter_once off;
        sub_filter_types text/html application/javascript text/javascript text/css application/json;
        sub_filter '"/_next/' '"/hycanvas/_next/';
        sub_filter "'/_next/" "'/hycanvas/_next/";
        sub_filter '"/api/v1/' '"/hycanvas/api/v1/';
        sub_filter "'/api/v1/" "'/hycanvas/api/v1/";
        sub_filter '"/visitor-loader.svg"' '"/hycanvas/visitor-loader.svg"';
        sub_filter '"/manifest.webmanifest"' '"/hycanvas/manifest.webmanifest"';
        sub_filter '"/favicon.ico"' '"/hycanvas/favicon.ico"';
    }}

"""

# Falls ein alter /hycanvas/ Block ohne sub_filter existiert, diesen sauber ersetzen
old_hc = re.search(r'[ \t]*# HyCanvas[^\n]*\n[ \t]*location /hycanvas/ \{[^}]*\}\s*', text)
if old_hc:
    text = text[:old_hc.start()] + block + text[old_hc.end():]
    p.write_text(text, encoding='utf-8')
    print(f"  -> /hycanvas/ Block in {p} auf sub_filter aktualisiert.")
    sys.exit(0)

for anchor in ("    # WebSockets für Socket.IO", "    location /socket.io/"):
    if anchor in text:
        text = text.replace(anchor, block + anchor, 1)
        p.write_text(text, encoding='utf-8')
        print(f"  -> /hycanvas/ Proxy-Block in {p} eingefügt.")
        sys.exit(0)
m = re.search(r'^([ \t]*)location\s+/\s*\{', text, re.MULTILINE)
if m:
    indent = m.group(1)
    indented_block = "\n".join((indent + line.lstrip() if line.strip() else "") for line in block.splitlines()) + "\n"
    text = text[:m.start()] + indented_block + text[m.start():]
    p.write_text(text, encoding='utf-8')
    print(f"  -> /hycanvas/ Proxy-Block in {p} eingefügt.")
    sys.exit(0)
print(f"  -> Hinweis: Kein passender Anker in {p} gefunden, bitte manuell prüfen.")
PYEOF
}

if [[ -f "${DOCKER_NGINX_CONF}" ]]; then
    patch_nginx_file "${DOCKER_NGINX_CONF}" "hycanvas:8005"
fi

if [[ -d /etc/nginx/sites-available ]]; then
    for site_conf in /etc/nginx/sites-available/*; do
        [[ -f "${site_conf}" ]] || continue
        [[ "${site_conf}" == *.bak* ]] && continue
        if grep -qE "127\.0\.0\.1:5000|localhost:5000|teamportal" "${site_conf}"; then
            patch_nginx_file "${site_conf}" "127.0.0.1:8005"
        fi
    done
    if command -v nginx >/dev/null 2>&1 && nginx -t >/dev/null 2>&1; then
        systemctl reload nginx >/dev/null 2>&1 || true
        echo "  -> Host-Nginx neu geladen."
    fi
fi

echo "[3/4] Starte HyCanvas Docker-Container (hycanvas & hycanvas-db)..."
if command -v docker >/dev/null 2>&1; then
    docker compose pull hycanvas hycanvas-db || true
    docker compose --profile hycanvas up -d hycanvas hycanvas-db
else
    echo "  -> FEHLER: Docker nicht gefunden!" >&2
    exit 1
fi

echo "[4/4] Stelle Datenbank-Tabelle canvas_documents und Modul-Aktivierung sicher..."
PY_BIN=""
for candidate in \
    "${PROJECT_ROOT}/venv/bin/python" \
    "${PROJECT_ROOT}/.venv/bin/python" \
    "${PROJECT_ROOT}/venv/bin/python3" \
    "${PROJECT_ROOT}/.venv/bin/python3" \
    "$(command -v python3 || true)"; do
    if [[ -n "${candidate}" && -x "${candidate}" ]] && "${candidate}" -c "import flask" >/dev/null 2>&1; then
        PY_BIN="${candidate}"
        break
    fi
done

if [[ -z "${PY_BIN}" ]]; then
    echo "  -> FEHLER: Kein Python mit installiertem Flask gefunden (venv/.venv geprüft)." >&2
    exit 1
fi
echo "  -> Nutze Python: ${PY_BIN}"

"${PY_BIN}" -c "
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

for svc in teamportal prismateams; do
    if systemctl is-active --quiet "${svc}" 2>/dev/null; then
        systemctl restart "${svc}"
        echo "  -> Service ${svc} neu gestartet."
        break
    fi
done

echo "Fertig! HyCanvas läuft auf 127.0.0.1:8005 und das Canvas-Modul ist unter /canvas erreichbar."
