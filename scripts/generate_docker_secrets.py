#!/usr/bin/env python3
"""
Prismateams - Docker Secrets & Environment Generator

Generiert alle benötigten Passwörter, Verschlüsselungsschlüssel (Fernet),
WebPush-Keys (VAPID) sowie Sidecar-Tokens (Euro-Office, MiroTalk) und schreibt
oder aktualisiert die .env-Datei.

Verwendung:
    python scripts/generate_docker_secrets.py [--env-file .env] [--domain DOMAIN] [--ssl]
"""

import argparse
import os
import secrets
import string
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

try:
    from scripts.generate_vapid_keys import generate_vapid_keys
except ImportError:
    generate_vapid_keys = None


def generate_password(length=32):
    """Generiert ein sicheres alphanumerisches Passwort."""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def generate_hex_secret(bytes_count=32):
    """Generiert ein kryptografisches Hex-Secret (z.B. 64 Hex-Zeichen)."""
    return secrets.token_hex(bytes_count)


def generate_fernet_key():
    """Generiert einen URL-safe Base64 Fernet Key."""
    if Fernet:
        return Fernet.generate_key().decode("utf-8")
    import base64
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8")


def read_env_file(filepath):
    """Liest eine .env Datei in ein Dictionary und merkt sich Zeilen."""
    if not os.path.exists(filepath):
        return {}, []
    values = {}
    lines = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            lines.append(line)
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, v = stripped.split("=", 1)
                values[k.strip()] = v.strip().strip("'\"")
    return values, lines


def set_or_update_env_var(lines, key, value):
    """Aktualisiert eine Variable in lines oder fügt sie am Ende hinzu."""
    key_prefix = f"{key}="
    updated = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(key_prefix) and not stripped.startswith("#"):
            lines[i] = f"{key}={value}\n"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}\n")


def is_placeholder_or_empty(val):
    """Prüft ob ein Wert leer ist oder ein Platzhalter wie change-me."""
    if not val:
        return True
    low = val.lower().strip()
    return "change-me" in low or "changeme" in low or low == "placeholder"


def main():
    parser = argparse.ArgumentParser(description="Prismateams Docker Secrets Generator")
    parser.add_argument("--env-file", default=os.path.join(PROJECT_ROOT, ".env"),
                        help="Pfad zur .env Datei (Standard: .env im Root)")
    parser.add_argument("--domain", default="", help="Öffentliche Domain oder IP")
    parser.add_argument("--ssl", action="store_true", help="HTTPS / SSL aktiviert")
    parser.add_argument("--print-only", action="store_true", help="Nur ausgeben, nicht in Datei schreiben")
    args = parser.parse_args()

    env_path = os.path.abspath(args.env_file)
    example_path = os.path.join(PROJECT_ROOT, "docs", "env.docker.example")

    existing_values, lines = read_env_file(env_path)
    if not lines and os.path.exists(example_path):
        _, lines = read_env_file(example_path)

    # 1. Datenbank-Passwörter
    db_pass = existing_values.get("MYSQL_PASSWORD")
    if is_placeholder_or_empty(db_pass):
        db_pass = generate_password(32)
    set_or_update_env_var(lines, "MYSQL_PASSWORD", db_pass)

    root_pass = existing_values.get("MYSQL_ROOT_PASSWORD")
    if is_placeholder_or_empty(root_pass):
        root_pass = generate_password(32)
    set_or_update_env_var(lines, "MYSQL_ROOT_PASSWORD", root_pass)

    # 2. Flask Secret
    secret_key = existing_values.get("SECRET_KEY")
    if is_placeholder_or_empty(secret_key):
        secret_key = generate_hex_secret(32)
    set_or_update_env_var(lines, "SECRET_KEY", secret_key)

    # 3. Verschlüsselungsschlüssel (Fernet)
    for key_name in [
        "CREDENTIAL_ENCRYPTION_KEY",
        "MAILBOX_ENCRYPTION_KEY",
        "MUSIC_ENCRYPTION_KEY",
        "TOTP_ENCRYPTION_KEY"
    ]:
        val = existing_values.get(key_name)
        if is_placeholder_or_empty(val):
            val = generate_fernet_key()
        set_or_update_env_var(lines, key_name, val)

    # 4. WebPush VAPID Keys
    vapid_pub = existing_values.get("VAPID_PUBLIC_KEY")
    vapid_priv = existing_values.get("VAPID_PRIVATE_KEY")
    if is_placeholder_or_empty(vapid_pub) or is_placeholder_or_empty(vapid_priv):
        if generate_vapid_keys:
            try:
                keys = generate_vapid_keys()
                vapid_pub = keys["public_key_b64"]
                vapid_priv = keys["private_key_b64"]
            except Exception as e:
                print(f"[WARNUNG] VAPID Key-Generierung fehlgeschlagen: {e}", file=sys.stderr)
        if vapid_pub and vapid_priv:
            set_or_update_env_var(lines, "VAPID_PUBLIC_KEY", vapid_pub)
            set_or_update_env_var(lines, "VAPID_PRIVATE_KEY", vapid_priv)

    # 5. Compose Profiles (Standardmäßig alle aktiv: Opt-Out)
    profiles = existing_values.get("COMPOSE_PROFILES")
    if not profiles:
        set_or_update_env_var(lines, "COMPOSE_PROFILES", "proxy,onlyoffice,excalidraw,mirotalk")

    # 6. Euro-Office
    oo_enabled = existing_values.get("ONLYOFFICE_ENABLED", "True")
    set_or_update_env_var(lines, "ONLYOFFICE_ENABLED", oo_enabled)
    set_or_update_env_var(lines, "ONLYOFFICE_DOCUMENT_SERVER_URL", "/eurooffice")

    oo_secret = existing_values.get("ONLYOFFICE_SECRET_KEY")
    if is_placeholder_or_empty(oo_secret):
        oo_secret = generate_hex_secret(32)
    set_or_update_env_var(lines, "ONLYOFFICE_SECRET_KEY", oo_secret)

    # 7. Excalidraw
    ex_enabled = existing_values.get("EXCALIDRAW_ENABLED", "True")
    set_or_update_env_var(lines, "EXCALIDRAW_ENABLED", ex_enabled)
    set_or_update_env_var(lines, "EXCALIDRAW_URL", "/excalidraw")
    set_or_update_env_var(lines, "EXCALIDRAW_ROOM_URL", "/excalidraw-room")

    # 8. MiroTalk SFU
    mt_enabled = existing_values.get("MIROTALK_ENABLED", "True")
    set_or_update_env_var(lines, "MIROTALK_ENABLED", mt_enabled)

    mt_api_key = existing_values.get("MIROTALK_API_KEY")
    if is_placeholder_or_empty(mt_api_key):
        mt_api_key = generate_hex_secret(32)
    set_or_update_env_var(lines, "MIROTALK_API_KEY", mt_api_key)

    mt_pass = existing_values.get("MIROTALK_HOST_PASSWORD")
    if is_placeholder_or_empty(mt_pass):
        mt_pass = generate_password(24)
    set_or_update_env_var(lines, "MIROTALK_HOST_PASSWORD", mt_pass)

    mt_jwt = existing_values.get("MIROTALK_JWT_SECRET")
    if is_placeholder_or_empty(mt_jwt):
        mt_jwt = generate_hex_secret(32)
    set_or_update_env_var(lines, "MIROTALK_JWT_SECRET", mt_jwt)

    # 9. Domain-URLs falls Domain angegeben
    domain = args.domain.strip() or existing_values.get("DOMAIN", "").strip()
    if domain:
        scheme = "https" if args.ssl else "http"
        base_url = f"{scheme}://{domain}"
        set_or_update_env_var(lines, "PUBLIC_BASE_URL", base_url)
        set_or_update_env_var(lines, "ONLYOFFICE_PUBLIC_URL", base_url)
        meet_url = f"{scheme}://meet.{domain}"
        set_or_update_env_var(lines, "MIROTALK_URL", meet_url)
        set_or_update_env_var(lines, "MIROTALK_CORS_ORIGIN", f"{base_url},{meet_url}")
        set_or_update_env_var(lines, "MIROTALK_EMBED_ORIGINS", base_url)

    if args.print_only:
        sys.stdout.write("".join(lines))
        return

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    try:
        os.chmod(env_path, 0o600)
    except Exception:
        pass

    print(f"[OK] .env erfolgreich aktualisiert/erzeugt: {env_path}")


if __name__ == "__main__":
    main()

