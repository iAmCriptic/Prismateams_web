#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.8

Zugangsdaten-Favoriten benutzerspezifisch:
- Tabelle credential_favorites (user_id, credential_id, unique)
- Übernimmt bestehende credentials.is_favorite=True auf created_by

Aufruf:
  python migrations/migrate_to_2_7_8_credential_favorites.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def ensure_credential_favorites_table():
    if table_exists("credential_favorites"):
        print("[OK] credential_favorites existiert bereits")
        return False

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text("""
                CREATE TABLE credential_favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    credential_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(credential_id) REFERENCES credentials(id),
                    UNIQUE(user_id, credential_id)
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE credential_favorites (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    credential_id INTEGER NOT NULL REFERENCES credentials(id),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT unique_user_credential_favorite UNIQUE (user_id, credential_id)
                )
            """))
    print("[OK] credential_favorites angelegt")
    return True


def migrate_legacy_favorites():
    """Map global is_favorite flags onto the credential creator."""
    if not table_exists("credentials"):
        return

    columns = {col["name"] for col in inspect(db.engine).get_columns("credentials")}
    if "is_favorite" not in columns:
        return

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            result = conn.execute(text("""
                INSERT OR IGNORE INTO credential_favorites (user_id, credential_id, created_at)
                SELECT created_by, id, CURRENT_TIMESTAMP
                FROM credentials
                WHERE is_favorite = 1 AND created_by IS NOT NULL
            """))
        else:
            # MySQL / MariaDB
            result = conn.execute(text("""
                INSERT IGNORE INTO credential_favorites (user_id, credential_id, created_at)
                SELECT created_by, id, CURRENT_TIMESTAMP
                FROM credentials
                WHERE is_favorite = 1 AND created_by IS NOT NULL
            """))
        print(f"[OK] Legacy-Favoriten übernommen (rowcount={result.rowcount})")


def main():
    app = create_app()
    with app.app_context():
        print("=== Migration 2.7.8: Credential-Favoriten ===")
        ensure_credential_favorites_table()
        migrate_legacy_favorites()
        print("Fertig.")


if __name__ == "__main__":
    main()
