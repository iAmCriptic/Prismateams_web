#!/bin/sh
# Prismateams - OS-unabhängiger Docker Setup Wrapper (Linux, macOS, BSD, WSL)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/setup_docker.py" "$@"
elif command -v python >/dev/null 2>&1; then
    exec python "$SCRIPT_DIR/setup_docker.py" "$@"
else
    echo "Python nicht gefunden. Bitte Python 3 installieren oder 'docker compose up -d' direkt ausführen." >&2
    exit 1
fi

