#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.3

Flache Ordner für Handbücher/Anleitungen:
- Tabelle manual_folders
- Spalte manuals.folder_id (nullable FK)

Aufruf:
  python migrations/migrate_to_2_7_3_manual_folders.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def column_exists(table_name, column_name):
    if not table_exists(table_name):
        return False
    columns = {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    return column_name in columns


def ensure_manual_folders_table():
    if table_exists("manual_folders"):
        print("[OK] manual_folders existiert bereits")
        return

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text("""
                CREATE TABLE manual_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(120) NOT NULL,
                    color VARCHAR(16) NOT NULL DEFAULT '#0d6efd',
                    position INTEGER NOT NULL DEFAULT 0,
                    created_by INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME,
                    FOREIGN KEY(created_by) REFERENCES users(id)
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE manual_folders (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    color VARCHAR(16) NOT NULL DEFAULT '#0d6efd',
                    position INTEGER NOT NULL DEFAULT 0,
                    created_by INTEGER NOT NULL REFERENCES users(id),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NULL
                )
            """))
    print("[OK] manual_folders angelegt")


def ensure_manuals_folder_id():
    if not table_exists("manuals"):
        print("[SKIP] manuals Tabelle fehlt")
        return

    if column_exists("manuals", "folder_id"):
        print("[OK] manuals.folder_id existiert bereits")
        return

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text(
                "ALTER TABLE manuals ADD COLUMN folder_id INTEGER "
                "REFERENCES manual_folders(id)"
            ))
        else:
            conn.execute(text(
                "ALTER TABLE manuals ADD COLUMN folder_id INTEGER NULL "
                "REFERENCES manual_folders(id)"
            ))
    print("[OK] manuals.folder_id angelegt")


def main():
    app = create_app()
    with app.app_context():
        print("=== Migration 2.7.3: Manual-Ordner ===")
        ensure_manual_folders_table()
        ensure_manuals_folder_id()
        print("Fertig.")


if __name__ == "__main__":
    main()
