#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.10

Exklusive Soft-Locks für Text-/Markdown-Editor im Dateienmodul:
- Tabelle file_edit_locks

Aufruf:
  python migrations/migrate_to_2_7_10_file_edit_locks.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def ensure_file_edit_locks_table():
    if table_exists("file_edit_locks"):
        print("[OK] file_edit_locks existiert bereits")
        return False

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text("""
                CREATE TABLE file_edit_locks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL UNIQUE,
                    locked_by INTEGER NOT NULL,
                    session_key VARCHAR(128) NOT NULL UNIQUE,
                    expires_at DATETIME NOT NULL,
                    last_heartbeat_at DATETIME NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(file_id) REFERENCES files(id),
                    FOREIGN KEY(locked_by) REFERENCES users(id)
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_file_edit_locks_file_id ON file_edit_locks(file_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_file_edit_locks_locked_by ON file_edit_locks(locked_by)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_file_edit_locks_expires_at ON file_edit_locks(expires_at)"
            ))
        else:
            conn.execute(text("""
                CREATE TABLE file_edit_locks (
                    id SERIAL PRIMARY KEY,
                    file_id INTEGER NOT NULL UNIQUE REFERENCES files(id),
                    locked_by INTEGER NOT NULL REFERENCES users(id),
                    session_key VARCHAR(128) NOT NULL UNIQUE,
                    expires_at TIMESTAMP NOT NULL,
                    last_heartbeat_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_file_edit_locks_file_id ON file_edit_locks(file_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_file_edit_locks_locked_by ON file_edit_locks(locked_by)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_file_edit_locks_expires_at ON file_edit_locks(expires_at)"
            ))
    print("[OK] file_edit_locks angelegt")
    return True


def main():
    app = create_app()
    with app.app_context():
        print("=== Migration 2.7.10: File Edit Locks ===")
        ensure_file_edit_locks_table()
        print("Fertig.")


if __name__ == "__main__":
    main()
