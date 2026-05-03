#!/usr/bin/env python3
"""
Migration: Share-Modi fuer Dateien und Ordner

Fuegt `share_mode` fuer `files` und `folders` hinzu.
Default fuer bestehende und neue Freigaben: `edit`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from app import create_app, db


def column_exists(table_name, column_name):
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def add_share_mode_column(table_name):
    if column_exists(table_name, "share_mode"):
        print(f"[INFO] {table_name}.share_mode existiert bereits")
        return
    print(f"[INFO] Ergaenze {table_name}.share_mode")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER TABLE {table_name} ADD COLUMN share_mode VARCHAR(16) NOT NULL DEFAULT 'edit'"
            )
        )
    print(f"[OK] {table_name}.share_mode hinzugefuegt")


def run():
    print("=" * 60)
    print("Migration Share-Modi")
    print("=" * 60)
    add_share_mode_column("files")
    add_share_mode_column("folders")
    print("=" * 60)
    print("Migration abgeschlossen")
    print("=" * 60)


if __name__ == "__main__":
    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        run()
