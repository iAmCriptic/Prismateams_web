#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.6.0

Einheitliches Freigabe-Management + OnlyOffice Presence:
- UniqueConstraint (resource_type, resource_id, mode) entfernen
- public_shares.label hinzufuegen
- mode darf 'dropbox' sein
- bestehende Briefkaesten in public_shares migrieren
- onlyoffice_sessions Tabelle anlegen

Aufruf:
  python migrations/migrate_to_2_6_0_shares.py
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


def index_exists(table_name, index_name):
    if not table_exists(table_name):
        return False
    indexes = inspect(db.engine).get_indexes(table_name)
    return any(idx.get("name") == index_name for idx in indexes)


def unique_constraint_exists(table_name, constraint_name):
    if not table_exists(table_name):
        return False
    try:
        uniques = inspect(db.engine).get_unique_constraints(table_name)
        return any(u.get("name") == constraint_name for u in uniques)
    except Exception:
        return False


def drop_unique_constraint():
    constraint_name = "uq_public_share_resource_mode"
    if not table_exists("public_shares"):
        print("[INFO] public_shares fehlt - UniqueConstraint uebersprungen")
        return

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            cols = {c["name"] for c in inspect(db.engine).get_columns("public_shares")}
            has_label = "label" in cols
            label_col = ", label VARCHAR(255)" if has_label else ""
            label_sel = ", label" if has_label else ""
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text(
                f"""
                CREATE TABLE public_shares_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_type VARCHAR(16) NOT NULL,
                    resource_id INTEGER NOT NULL,
                    mode VARCHAR(16) NOT NULL,
                    token VARCHAR(255) NOT NULL UNIQUE,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    password_hash VARCHAR(255),
                    expires_at DATETIME,
                    created_by INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME
                    {label_col},
                    FOREIGN KEY(created_by) REFERENCES users(id)
                )
                """
            ))
            conn.execute(text(
                f"""
                INSERT INTO public_shares_new (
                    id, resource_type, resource_id, mode, token, enabled,
                    password_hash, expires_at, created_by, created_at, updated_at
                    {label_sel}
                )
                SELECT
                    id, resource_type, resource_id, mode, token, enabled,
                    password_hash, expires_at, created_by, created_at, updated_at
                    {label_sel}
                FROM public_shares
                """
            ))
            conn.execute(text("DROP TABLE public_shares"))
            conn.execute(text("ALTER TABLE public_shares_new RENAME TO public_shares"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            print("[OK] SQLite UniqueConstraint entfernt")
            return

        if unique_constraint_exists("public_shares", constraint_name) or index_exists("public_shares", constraint_name):
            try:
                conn.execute(text(f"ALTER TABLE public_shares DROP INDEX `{constraint_name}`"))
                print(f"[OK] Index/Constraint {constraint_name} entfernt")
            except Exception as exc:
                try:
                    conn.execute(text(f"ALTER TABLE public_shares DROP CONSTRAINT `{constraint_name}`"))
                    print(f"[OK] Constraint {constraint_name} entfernt")
                except Exception as exc2:
                    print(f"[WARNUNG] UniqueConstraint nicht entfernt: {exc} / {exc2}")
        else:
            print(f"[INFO] {constraint_name} nicht gefunden")


def add_label_column():
    if not table_exists("public_shares"):
        print("[INFO] public_shares fehlt - label uebersprungen")
        return
    if column_exists("public_shares", "label"):
        print("[INFO] public_shares.label existiert bereits")
        return
    with db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE public_shares ADD COLUMN label VARCHAR(255) NULL"))
    print("[OK] public_shares.label hinzugefuegt")


def migrate_dropboxes_to_shares():
    if not table_exists("folders") or not table_exists("public_shares"):
        print("[INFO] folders/public_shares fehlen - Dropbox-Migration uebersprungen")
        return

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        rows = conn.execute(text(
            """
            SELECT id, dropbox_token, dropbox_password_hash, created_by
            FROM folders
            WHERE is_dropbox = 1 AND dropbox_token IS NOT NULL AND dropbox_token != ''
            """
        )).fetchall()

        migrated = 0
        for row in rows:
            folder_id, token, password_hash, created_by = row[0], row[1], row[2], row[3]
            exists = conn.execute(
                text("SELECT id FROM public_shares WHERE token = :token LIMIT 1"),
                {"token": token},
            ).fetchone()
            if exists:
                continue

            now_expr = "CURRENT_TIMESTAMP" if dialect == "sqlite" else "UTC_TIMESTAMP()"
            conn.execute(
                text(
                    f"""
                    INSERT INTO public_shares (
                        resource_type, resource_id, mode, token, enabled,
                        password_hash, expires_at, created_by, created_at, updated_at, label
                    ) VALUES (
                        'folder', :rid, 'dropbox', :token, 1,
                        :pw, NULL, :uid, {now_expr}, {now_expr}, :label
                    )
                    """
                ),
                {
                    "rid": folder_id,
                    "token": token,
                    "pw": password_hash,
                    "uid": created_by or 1,
                    "label": "Briefkasten",
                },
            )
            migrated += 1

    print(f"[OK] {migrated} Briefkasten nach public_shares migriert")


def create_onlyoffice_sessions_table():
    if table_exists("onlyoffice_sessions"):
        print("[INFO] onlyoffice_sessions existiert bereits")
        return

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text(
                """
                CREATE TABLE onlyoffice_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    user_id INTEGER,
                    guest_key VARCHAR(128),
                    display_name VARCHAR(255) NOT NULL,
                    avatar_filename VARCHAR(255),
                    session_key VARCHAR(128) NOT NULL UNIQUE,
                    last_seen DATETIME NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(file_id) REFERENCES files(id),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_oo_sessions_file_id ON onlyoffice_sessions(file_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_oo_sessions_last_seen ON onlyoffice_sessions(last_seen)"
            ))
        else:
            conn.execute(text(
                """
                CREATE TABLE onlyoffice_sessions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    file_id INT NOT NULL,
                    user_id INT NULL,
                    guest_key VARCHAR(128) NULL,
                    display_name VARCHAR(255) NOT NULL,
                    avatar_filename VARCHAR(255) NULL,
                    session_key VARCHAR(128) NOT NULL,
                    last_seen DATETIME NOT NULL,
                    created_at DATETIME NOT NULL,
                    UNIQUE KEY uq_oo_session_key (session_key),
                    KEY idx_oo_sessions_file_id (file_id),
                    KEY idx_oo_sessions_last_seen (last_seen),
                    CONSTRAINT fk_oo_sessions_file FOREIGN KEY (file_id) REFERENCES files(id),
                    CONSTRAINT fk_oo_sessions_user FOREIGN KEY (user_id) REFERENCES users(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            ))
    print("[OK] onlyoffice_sessions erstellt")


def migrate():
    print("=" * 60)
    print("Datenbank-Migration: Version 2.6.0 (Freigaben + Presence)")
    print("=" * 60)

    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        try:
            add_label_column()
            drop_unique_constraint()
            add_label_column()
            migrate_dropboxes_to_shares()
            create_onlyoffice_sessions_table()
            print("\n[OK] Migration 2.6.0 abgeschlossen")
            return True
        except Exception as exc:
            print(f"[FEHLER] Migration fehlgeschlagen: {exc}")
            db.session.rollback()
            return False


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
