#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.0

Private Ordner / Bereiche / Papierkorb:
- folders/files: space, deleted_at, deleted_by
- folders: is_personal_root
- Tabelle resource_acl
- SystemSettings files_private_folders_enabled (default False)
- Bestehende Dateien/Ordner → space=public

Aufruf:
  python migrations/migrate_to_2_7_0_private_files.py
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


def add_column(table, column_sql):
    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_sql}"))
        else:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_sql}"))


def ensure_folder_columns():
    if not table_exists("folders"):
        print("[INFO] folders fehlt")
        return
    specs = [
        ("space", "space VARCHAR(16) NOT NULL DEFAULT 'public'"),
        ("deleted_at", "deleted_at DATETIME"),
        ("deleted_by", "deleted_by INTEGER"),
        ("is_personal_root", "is_personal_root BOOLEAN NOT NULL DEFAULT 0"),
    ]
    for name, sql in specs:
        if column_exists("folders", name):
            print(f"[INFO] folders.{name} existiert")
        else:
            add_column("folders", sql)
            print(f"[OK] folders.{name} hinzugefuegt")


def ensure_file_columns():
    if not table_exists("files"):
        print("[INFO] files fehlt")
        return
    specs = [
        ("space", "space VARCHAR(16) NOT NULL DEFAULT 'public'"),
        ("deleted_at", "deleted_at DATETIME"),
        ("deleted_by", "deleted_by INTEGER"),
    ]
    for name, sql in specs:
        if column_exists("files", name):
            print(f"[INFO] files.{name} existiert")
        else:
            add_column("files", sql)
            print(f"[OK] files.{name} hinzugefuegt")


def backfill_space_public():
    with db.engine.begin() as conn:
        if table_exists("folders") and column_exists("folders", "space"):
            conn.execute(text("UPDATE folders SET space='public' WHERE space IS NULL OR space=''"))
            print("[OK] folders.space -> public (Backfill)")
        if table_exists("files") and column_exists("files", "space"):
            conn.execute(text("UPDATE files SET space='public' WHERE space IS NULL OR space=''"))
            print("[OK] files.space -> public (Backfill)")


def ensure_resource_acl():
    if table_exists("resource_acl"):
        print("[INFO] resource_acl existiert")
        return
    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text(
                """
                CREATE TABLE resource_acl (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_type VARCHAR(16) NOT NULL,
                    resource_id INTEGER NOT NULL,
                    grantee_user_id INTEGER,
                    permission VARCHAR(16) NOT NULL DEFAULT 'view',
                    created_by INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(grantee_user_id) REFERENCES users(id),
                    FOREIGN KEY(created_by) REFERENCES users(id)
                )
                """
            ))
            conn.execute(text(
                "CREATE INDEX ix_resource_acl_resource ON resource_acl (resource_type, resource_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_resource_acl_grantee ON resource_acl (grantee_user_id)"
            ))
        else:
            conn.execute(text(
                """
                CREATE TABLE resource_acl (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    resource_type VARCHAR(16) NOT NULL,
                    resource_id INT NOT NULL,
                    grantee_user_id INT NULL,
                    permission VARCHAR(16) NOT NULL DEFAULT 'view',
                    created_by INT NOT NULL,
                    created_at DATETIME NOT NULL,
                    INDEX ix_resource_acl_resource (resource_type, resource_id),
                    INDEX ix_resource_acl_grantee (grantee_user_id),
                    CONSTRAINT fk_resource_acl_grantee FOREIGN KEY (grantee_user_id) REFERENCES users(id),
                    CONSTRAINT fk_resource_acl_creator FOREIGN KEY (created_by) REFERENCES users(id)
                )
                """
            ))
    print("[OK] resource_acl angelegt")


def ensure_setting():
    from app.models.settings import SystemSettings
    existing = SystemSettings.query.filter_by(key="files_private_folders_enabled").first()
    if existing:
        print("[INFO] Setting files_private_folders_enabled existiert")
        return
    db.session.add(SystemSettings(key="files_private_folders_enabled", value="False"))
    db.session.commit()
    print("[OK] Setting files_private_folders_enabled=False")


def main():
    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        print("=== Migration 2.7.0 Private Files ===")
        ensure_folder_columns()
        ensure_file_columns()
        backfill_space_public()
        ensure_resource_acl()
        ensure_setting()
        print("=== Fertig ===")


if __name__ == "__main__":
    main()
