#!/usr/bin/env python3
"""
Prismateams - Betriebssystemunabhängiger Docker-Installer

Funktioniert auf jedem Betriebssystem mit Docker (Windows, macOS, Linux).
- Fragt Konfiguration ab (Standard: alle Dienste aktiviert / Opt-Out)
- Generiert alle Passwörter, Encryption-Keys und JWT-Tokens
- Schreibt die .env Datei
- Startet den Docker Compose Stack

Verwendung:
    python scripts/setup_docker.py [--defaults] [--skip-onlyoffice] [--skip-excalidraw] [--skip-mirotalk]
"""

import argparse
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.generate_docker_secrets import (
    generate_password,
    generate_hex_secret,
    generate_fernet_key,
    read_env_file,
    set_or_update_env_var,
    is_placeholder_or_empty,
)

try:
    from scripts.generate_vapid_keys import generate_vapid_keys
except ImportError:
    generate_vapid_keys = None


def ask_yn(question, default="j"):
    """Fragt Ja/Nein ab mit vorgegebenem Default."""
    hint = "J/n" if default.lower() == "j" else "j/N"
    try:
        reply = input(f"{question} [{hint}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAbgebrochen.")
        sys.exit(1)
    if not reply:
        return default.lower() == "j"
    return reply in ("j", "ja", "y", "yes", "1", "true")


def ask_text(prompt, default=""):
    """Fragt einen Text ab mit vorgegebenem Default."""
    try:
        hint = f" [{default}]" if default else ""
        reply = input(f"{prompt}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAbgebrochen.")
        sys.exit(1)
    return reply if reply else default


def check_docker():
    """Prüft, ob Docker und Docker Compose verfügbar sind."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        print("[FEHLER] 'docker' wurde im Pfad nicht gefunden. Bitte installieren Sie Docker zuerst.")
        return False

    try:
        res = subprocess.run(["docker", "compose", "version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            return "docker compose"
    except Exception:
        pass

    if shutil.which("docker-compose"):
        return "docker-compose"

    print("[WARNUNG] 'docker compose' Plugin nicht gefunden. Compose-Befehle müssen ggf. manuell ausgeführt werden.")
    return None


def main():
    parser = argparse.ArgumentParser(description="Prismateams OS-unabhängiger Docker Installer")
    parser.add_argument("--defaults", action="store_true", help="Alle Standardwerte ohne Abfragen übernehmen (Opt-Out per Flags)")
    parser.add_argument("--domain", default="", help="Domain oder Server-IP")
    parser.add_argument("--port", default="", help="HTTP-Port des Portals (Standard: 80)")
    parser.add_argument("--ssl", action="store_true", help="HTTPS / SSL ist aktiv")
    parser.add_argument("--skip-onlyoffice", action="store_true", help="Euro-Office Document Server abwählen")
    parser.add_argument("--skip-excalidraw", action="store_true", help="Excalidraw-Room abwählen")
    parser.add_argument("--skip-mirotalk", action="store_true", help="MiroTalk SFU abwählen")
    parser.add_argument("--no-start", action="store_true", help="Docker-Stack am Ende nicht automatisch starten")
    args = parser.parse_args()

    print("=" * 60)
    print("Prismateams – Universeller Docker-Installer")
    print("Plattformunabhängig (Windows, macOS, Linux)")
    print("=" * 60)
    print()

    compose_cmd = check_docker()

    env_path = os.path.join(PROJECT_ROOT, ".env")
    example_path = os.path.join(PROJECT_ROOT, "docs", "env.docker.example")

    existing_values, lines = read_env_file(env_path)
    if not lines and os.path.exists(example_path):
        _, lines = read_env_file(example_path)

    # 1. Konfiguration abfragen (sofern nicht --defaults)
    if args.defaults:
        domain = args.domain or "localhost"
        portal_port = args.port or "80"
        use_onlyoffice = not args.skip_onlyoffice
        use_excalidraw = not args.skip_excalidraw
        use_mirotalk = not args.skip_mirotalk
        use_container_proxy = True
    else:
        print("=== 1. Grundkonfiguration ===")
        domain = ask_text("Domain oder Hostname/IP für das Portal", default=args.domain or existing_values.get("DOMAIN", "localhost"))
        portal_port = ask_text("HTTP-Port für das Portal", default=args.port or existing_values.get("PORTAL_PORT", "80"))

        print("\n=== 2. Zusatzdienste / Sidecars (Standard: alle aktiv / Opt-Out) ===")
        use_onlyoffice = ask_yn("Euro-Office Document Server installieren? (Office-Bearbeitung)", default="j" if not args.skip_onlyoffice else "n")
        use_excalidraw = ask_yn("Excalidraw Live-Whiteboard installieren?", default="j" if not args.skip_excalidraw else "n")
        use_mirotalk = ask_yn("MiroTalk SFU Video-Meetings installieren?", default="j" if not args.skip_mirotalk else "n")
        use_container_proxy = ask_yn("Integrierter Container-Proxy aktivieren? (Empfohlen für Direktstart)", default="j")

    # 2. Profiles zusammenstellen
    active_profiles = []
    if use_container_proxy:
        active_profiles.append("proxy")
    if use_onlyoffice:
        active_profiles.append("onlyoffice")
    if use_excalidraw:
        active_profiles.append("excalidraw")
    if use_mirotalk:
        active_profiles.append("mirotalk")

    profiles_str = ",".join(active_profiles)
    set_or_update_env_var(lines, "COMPOSE_PROFILES", profiles_str)

    # 3. Ports & Bindings
    set_or_update_env_var(lines, "PORTAL_PORT", portal_port)
    set_or_update_env_var(lines, "PORTAL_HOST_BIND", "0.0.0.0")
    set_or_update_env_var(lines, "APP_HOST_BIND", "0.0.0.0" if not use_container_proxy else "127.0.0.1")
    set_or_update_env_var(lines, "APP_HOST_PORT", "5000")

    # 4. URLs
    scheme = "https" if args.ssl else "http"
    port_suffix = "" if portal_port in ("80", "443") else f":{portal_port}"
    base_url = f"{scheme}://{domain}{port_suffix}"
    set_or_update_env_var(lines, "PUBLIC_BASE_URL", base_url)

    # 5. Secrets generieren
    print("\nGeneriere sichere Schlüssel und Passwörter...")

    db_pass = existing_values.get("MYSQL_PASSWORD")
    if is_placeholder_or_empty(db_pass):
        db_pass = generate_password(32)
    set_or_update_env_var(lines, "MYSQL_PASSWORD", db_pass)

    root_pass = existing_values.get("MYSQL_ROOT_PASSWORD")
    if is_placeholder_or_empty(root_pass):
        root_pass = generate_password(32)
    set_or_update_env_var(lines, "MYSQL_ROOT_PASSWORD", root_pass)

    flask_secret = existing_values.get("SECRET_KEY")
    if is_placeholder_or_empty(flask_secret):
        flask_secret = generate_hex_secret(32)
    set_or_update_env_var(lines, "SECRET_KEY", flask_secret)

    for k in ["CREDENTIAL_ENCRYPTION_KEY", "MAILBOX_ENCRYPTION_KEY", "MUSIC_ENCRYPTION_KEY", "TOTP_ENCRYPTION_KEY"]:
        v = existing_values.get(k)
        if is_placeholder_or_empty(v):
            v = generate_fernet_key()
        set_or_update_env_var(lines, k, v)

    vapid_pub = existing_values.get("VAPID_PUBLIC_KEY")
    vapid_priv = existing_values.get("VAPID_PRIVATE_KEY")
    if is_placeholder_or_empty(vapid_pub) or is_placeholder_or_empty(vapid_priv):
        if generate_vapid_keys:
            try:
                keys = generate_vapid_keys()
                vapid_pub = keys["public_key_b64"]
                vapid_priv = keys["private_key_b64"]
            except Exception as e:
                print(f"[WARNUNG] VAPID-Generierung fehlgeschlagen: {e}")
        if vapid_pub and vapid_priv:
            set_or_update_env_var(lines, "VAPID_PUBLIC_KEY", vapid_pub)
            set_or_update_env_var(lines, "VAPID_PRIVATE_KEY", vapid_priv)

    # 6. Sidecar-Konfigurationen
    if use_onlyoffice:
        set_or_update_env_var(lines, "ONLYOFFICE_ENABLED", "True")
        set_or_update_env_var(lines, "ONLYOFFICE_DOCUMENT_SERVER_URL", "/eurooffice")
        oo_secret = existing_values.get("ONLYOFFICE_SECRET_KEY")
        if is_placeholder_or_empty(oo_secret):
            oo_secret = generate_hex_secret(32)
        set_or_update_env_var(lines, "ONLYOFFICE_SECRET_KEY", oo_secret)
        set_or_update_env_var(lines, "ONLYOFFICE_PUBLIC_URL", base_url)
    else:
        set_or_update_env_var(lines, "ONLYOFFICE_ENABLED", "False")

    if use_excalidraw:
        set_or_update_env_var(lines, "EXCALIDRAW_ENABLED", "True")
        set_or_update_env_var(lines, "EXCALIDRAW_URL", "/excalidraw")
        set_or_update_env_var(lines, "EXCALIDRAW_ROOM_URL", "/excalidraw-room")
    else:
        set_or_update_env_var(lines, "EXCALIDRAW_ENABLED", "False")

    if use_mirotalk:
        set_or_update_env_var(lines, "MIROTALK_ENABLED", "True")
        mt_api = existing_values.get("MIROTALK_API_KEY")
        if is_placeholder_or_empty(mt_api):
            mt_api = generate_hex_secret(32)
        set_or_update_env_var(lines, "MIROTALK_API_KEY", mt_api)

        mt_pass = existing_values.get("MIROTALK_HOST_PASSWORD")
        if is_placeholder_or_empty(mt_pass):
            mt_pass = generate_password(24)
        set_or_update_env_var(lines, "MIROTALK_HOST_PASSWORD", mt_pass)

        mt_jwt = existing_values.get("MIROTALK_JWT_SECRET")
        if is_placeholder_or_empty(mt_jwt):
            mt_jwt = generate_hex_secret(32)
        set_or_update_env_var(lines, "MIROTALK_JWT_SECRET", mt_jwt)

        meet_url = f"{scheme}://{domain}:3010" if domain != "localhost" else "http://localhost:3010"
        set_or_update_env_var(lines, "MIROTALK_URL", meet_url)
        set_or_update_env_var(lines, "MIROTALK_CORS_ORIGIN", f"{base_url},{meet_url}")
        set_or_update_env_var(lines, "MIROTALK_EMBED_ORIGINS", base_url)
    else:
        set_or_update_env_var(lines, "MIROTALK_ENABLED", "False")

    # .env schreiben
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    try:
        os.chmod(env_path, 0o600)
    except Exception:
        pass

    print(f"[OK] .env erfolgreich geschrieben ({env_path})")
    print(f"     Aktive Profile: {profiles_str}")
    print(f"     Portal-URL:     {base_url}")

    # 7. Stack starten
    if not args.no_start and compose_cmd:
        start_now = True if args.defaults else ask_yn("\nDocker Compose Stack jetzt starten?", default="j")
        if start_now:
            print("\nStarte Container mit Docker Compose...")
            cmd = compose_cmd.split() + ["up", "-d"]
            try:
                res = subprocess.run(cmd, cwd=PROJECT_ROOT)
                if res.returncode == 0:
                    print("\n[ERFOLG] Prismateams läuft!")
                    print(f"Öffnen Sie im Browser: {base_url}")
                else:
                    print("\n[HINWEIS] Docker Compose wurde mit Fehlercode beendet.")
            except Exception as e:
                print(f"[FEHLER] Beim Starten von Docker Compose: {e}")
    else:
        print("\nUm den Stack zu starten, führen Sie aus:")
        print("    docker compose up -d")


if __name__ == "__main__":
    main()

