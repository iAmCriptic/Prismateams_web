#!/usr/bin/env python3
"""
Führt alle migrate_*.py im Ordner migrations/ aus.

Aufruf:
  python migrations/run_all.py
  python migrations/run_all.py --force   # erneut alle Skripte (idempotent)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.utils.auto_migrate import run_pending_migrations


def main():
    parser = argparse.ArgumentParser(description="Alle DB-Migrationen ausführen")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Alle Skripte erneut ausführen (Tracking ignorieren)",
    )
    args = parser.parse_args()

    # create_app überspringt Auto-Migration wegen RUNNING_ENV in run_pending;
    # hier setzen wir SKIP, damit keine Background-Jobs starten.
    os.environ.setdefault("PRISMATEAMS_SKIP_BACKGROUND_JOBS", "1")
    # Verhindert, dass create_app parallel schon auto_migrate startet
    os.environ["PRISMATEAMS_RUNNING_MIGRATIONS"] = "1"

    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        # Flag für den eigentlichen Lauf zurücksetzen
        os.environ.pop("PRISMATEAMS_RUNNING_MIGRATIONS", None)
        ok = run_pending_migrations(force_all=args.force)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
