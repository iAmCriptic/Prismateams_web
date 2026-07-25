"""
Automatische DB-Migrationen beim App-Start.

Scannt den Ordner ``migrations/`` nach ``migrate_*.py`` und führt
noch nicht angewendete Skripte aus (Reihenfolge: natürliche Sortierung).
Bereits angewendete Skripte werden in der Tabelle ``schema_migrations``
gemerkt und übersprungen.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime

from sqlalchemy import text

# Verhindert Rekursion, wenn ein Migrationsskript selbst create_app() aufruft
RUNNING_ENV = "PRISMATEAMS_RUNNING_MIGRATIONS"
SKIP_JOBS_ENV = "PRISMATEAMS_SKIP_BACKGROUND_JOBS"


def _migrations_dir() -> str:
    # app/utils/auto_migrate.py -> Projektwurzel/migrations
    here = os.path.abspath(os.path.dirname(__file__))
    project_root = os.path.dirname(os.path.dirname(here))
    return os.path.join(project_root, "migrations")


def _natural_sort_key(name: str):
    """Sortiert migrate_to_2_7_2 vor migrate_to_2_7_10."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def discover_migration_scripts(migrations_dir: str | None = None) -> list[str]:
    """Alle migrate_*.py im Migrationsordner (ohne __pycache__ / Runner)."""
    folder = migrations_dir or _migrations_dir()
    if not os.path.isdir(folder):
        return []

    scripts = []
    for filename in os.listdir(folder):
        if not filename.startswith("migrate_"):
            continue
        if not filename.endswith(".py"):
            continue
        if filename.startswith("_"):
            continue
        # Runner selbst oder Hilfsmodule nicht ausführen
        if filename in ("run_all.py", "auto.py"):
            continue
        scripts.append(filename)

    scripts.sort(key=_natural_sort_key)
    return scripts


def _ensure_schema_migrations_table(db) -> None:
    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filename VARCHAR(255) NOT NULL UNIQUE,
                        applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        id INTEGER AUTO_INCREMENT PRIMARY KEY,
                        filename VARCHAR(255) NOT NULL,
                        applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_schema_migrations_filename (filename)
                    )
                    """
                )
            )


def _applied_filenames(db) -> set[str]:
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text("SELECT filename FROM schema_migrations")).fetchall()
        return {row[0] for row in rows}
    except Exception:
        return set()


def _mark_applied(db, filename: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO schema_migrations (filename, applied_at) "
                "VALUES (:filename, :applied_at)"
            ),
            {"filename": filename, "applied_at": datetime.utcnow()},
        )


def _run_script(script_path: str, timeout: int = 180) -> tuple[bool, str]:
    env = os.environ.copy()
    env[RUNNING_ENV] = "1"
    env.setdefault(SKIP_JOBS_ENV, "1")
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=os.path.dirname(os.path.dirname(script_path)),
        )
    except subprocess.TimeoutExpired:
        return False, f"Timeout nach {timeout}s"
    except Exception as exc:
        return False, str(exc)

    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        return False, output.strip() or f"Exit-Code {result.returncode}"
    return True, output.strip()


def run_pending_migrations(db=None, *, force_all: bool = False) -> bool:
    """
    Führt ausstehende Migrationen aus.

    Returns:
        True wenn alles ok (oder nichts zu tun), False bei Fehlern.
    """
    if os.getenv(RUNNING_ENV):
        return True

    if db is None:
        from app import db as _db

        db = _db

    migrations_dir = _migrations_dir()
    scripts = discover_migration_scripts(migrations_dir)
    if not scripts:
        print("[INFO] Keine Migrationsskripte in migrations/ gefunden")
        return True

    os.environ[RUNNING_ENV] = "1"
    try:
        _ensure_schema_migrations_table(db)
        applied = set() if force_all else _applied_filenames(db)

        pending = [name for name in scripts if name not in applied]
        if not pending:
            print(f"[OK] Alle {len(scripts)} Migration(en) bereits angewendet")
            return True

        print("=" * 60)
        print(f"Auto-Migration: {len(pending)} ausstehend, {len(applied)} bereits angewendet")
        print("=" * 60)

        all_ok = True
        for filename in pending:
            script_path = os.path.join(migrations_dir, filename)
            print(f"[INFO] Migration: {filename} ...")
            ok, detail = _run_script(script_path)
            if ok:
                try:
                    _mark_applied(db, filename)
                except Exception as mark_err:
                    # Doppelter Insert bei parallelem Start – ok wenn schon da
                    print(f"[WARNUNG] Konnte {filename} nicht als angewendet markieren: {mark_err}")
                print(f"[OK] {filename}")
            else:
                all_ok = False
                print(f"[FEHLER] {filename}: {detail[:2000]}")

        if all_ok:
            print("[OK] Auto-Migration abgeschlossen")
        else:
            print("[WARNUNG] Mindestens eine Migration ist fehlgeschlagen")
        return all_ok
    finally:
        os.environ.pop(RUNNING_ENV, None)
