#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.9

Kontakte-Favoriten benutzerspezifisch:
- Tabelle contact_favorites (user_id, contact_id, unique)

Aufruf:
  python migrations/migrate_to_2_7_9_contact_favorites.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def ensure_contact_favorites_table():
    if table_exists("contact_favorites"):
        print("[OK] contact_favorites existiert bereits")
        return False

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text("""
                CREATE TABLE contact_favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    contact_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(contact_id) REFERENCES contacts(id),
                    UNIQUE(user_id, contact_id)
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE contact_favorites (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    contact_id INTEGER NOT NULL REFERENCES contacts(id),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT unique_user_contact_favorite UNIQUE (user_id, contact_id)
                )
            """))
    print("[OK] contact_favorites angelegt")
    return True


def main():
    app = create_app()
    with app.app_context():
        print("=== Migration 2.7.9: Kontakt-Favoriten ===")
        ensure_contact_favorites_table()
        print("Fertig.")


if __name__ == "__main__":
    main()
