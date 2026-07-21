#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.1

Ordner-Favoriten für schnellen Zugriff in der Dateien-Nav:
- Tabelle folder_favorites (user_id, folder_id, unique)

Aufruf:
  python migrations/migrate_to_2_7_1_folder_favorites.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def ensure_folder_favorites_table():
    if table_exists("folder_favorites"):
        print("[OK] folder_favorites existiert bereits")
        return

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text("""
                CREATE TABLE folder_favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    folder_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(folder_id) REFERENCES folders(id),
                    UNIQUE(user_id, folder_id)
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE folder_favorites (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    folder_id INTEGER NOT NULL REFERENCES folders(id),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT unique_user_folder_favorite UNIQUE (user_id, folder_id)
                )
            """))
    print("[OK] folder_favorites angelegt")


def main():
    app = create_app()
    with app.app_context():
        print("=== Migration 2.7.1: Ordner-Favoriten ===")
        ensure_folder_favorites_table()
        print("Fertig.")


if __name__ == "__main__":
    main()
