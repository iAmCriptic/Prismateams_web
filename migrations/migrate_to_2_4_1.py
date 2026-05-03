#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.4.1

Einheitliche Migration ohne weitere Skript-Abhängigkeiten.

Aufruf:
  python migrations/migrate_to_2_4_1.py
  python migrations/migrate_to_2_4_1.py --security-only
"""

import argparse
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


def add_column_if_missing(table_name, column_name, ddl):
    if not table_exists(table_name):
        print(f"[INFO] Tabelle {table_name} fehlt - ueberspringe {column_name}")
        return True
    if column_exists(table_name, column_name):
        print(f"[INFO] {table_name}.{column_name} existiert bereits")
        return True
    with db.engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
    print(f"[OK] {table_name}.{column_name} hinzugefuegt")
    return True


def migrate_security_features():
    print("\n[STEP] Sicherheitsfeatures")
    if not table_exists("users"):
        print("[WARNUNG] users-Tabelle fehlt")
        return False

    db_type = db.engine.dialect.name
    security_columns = [
        ("totp_secret", "VARCHAR(255)"),
        ("totp_enabled", "BOOLEAN DEFAULT 0"),
        ("password_changed_at", "DATETIME"),
        ("failed_login_attempts", "INTEGER DEFAULT 0"),
        ("failed_login_until", "DATETIME"),
    ]
    for name, ddl in security_columns:
        add_column_if_missing("users", name, ddl)

    if not table_exists("user_sessions"):
        with db.engine.begin() as conn:
            if db_type == "sqlite":
                conn.execute(
                    text(
                        """
                        CREATE TABLE user_sessions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            session_id VARCHAR(255) NOT NULL UNIQUE,
                            ip_address VARCHAR(45),
                            user_agent VARCHAR(500),
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            last_activity DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            is_active BOOLEAN NOT NULL DEFAULT 1,
                            FOREIGN KEY (user_id) REFERENCES users(id)
                        )
                        """
                    )
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id)")
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_user_sessions_session_id ON user_sessions(session_id)")
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_user_sessions_is_active ON user_sessions(is_active)")
                )
            else:
                conn.execute(
                    text(
                        """
                        CREATE TABLE user_sessions (
                            id INTEGER AUTO_INCREMENT PRIMARY KEY,
                            user_id INTEGER NOT NULL,
                            session_id VARCHAR(255) NOT NULL UNIQUE,
                            ip_address VARCHAR(45),
                            user_agent VARCHAR(500),
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            last_activity DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            is_active BOOLEAN NOT NULL DEFAULT 1,
                            FOREIGN KEY (user_id) REFERENCES users(id)
                        )
                        """
                    )
                )
        print("[OK] user_sessions erstellt")
    else:
        print("[INFO] user_sessions existiert bereits")

    return True


def migrate_share_modes():
    print("\n[STEP] Share-Modes")
    add_column_if_missing("files", "share_mode", "VARCHAR(16) NOT NULL DEFAULT 'edit'")
    add_column_if_missing("folders", "share_mode", "VARCHAR(16) NOT NULL DEFAULT 'edit'")
    return True


def migrate_shortlinks():
    print("\n[STEP] Shortlinks")
    if table_exists("short_links"):
        print("[INFO] short_links existiert bereits")
        return True

    db_type = db.engine.dialect.name
    with db.engine.begin() as conn:
        if db_type == "sqlite":
            conn.execute(
                text(
                    """
                    CREATE TABLE short_links (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_by INTEGER NOT NULL,
                        target_url VARCHAR(2048) NOT NULL,
                        slug VARCHAR(64) NOT NULL UNIQUE,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        password_hash VARCHAR(255) NULL,
                        expires_at DATETIME NULL,
                        max_clicks INTEGER NULL,
                        click_count INTEGER NOT NULL DEFAULT 0,
                        last_clicked_at DATETIME NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (created_by) REFERENCES users(id)
                    )
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE short_links (
                        id INTEGER PRIMARY KEY AUTO_INCREMENT,
                        created_by INTEGER NOT NULL,
                        target_url VARCHAR(2048) NOT NULL,
                        slug VARCHAR(64) NOT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        password_hash VARCHAR(255) NULL,
                        expires_at DATETIME NULL,
                        max_clicks INTEGER NULL,
                        click_count INTEGER NOT NULL DEFAULT 0,
                        last_clicked_at DATETIME NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        CONSTRAINT fk_short_links_user FOREIGN KEY (created_by) REFERENCES users(id),
                        CONSTRAINT uq_short_links_slug UNIQUE (slug)
                    )
                    """
                )
            )
    print("[OK] short_links erstellt")
    return True


def migrate_inventory_vnext():
    print("\n[STEP] Inventory V-Next")
    add_column_if_missing("products", "item_type", "VARCHAR(20) NOT NULL DEFAULT 'asset'")
    add_column_if_missing("products", "min_stock", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing("products", "reorder_note", "VARCHAR(255) NULL")
    add_column_if_missing("inventory_items", "version", "INTEGER NOT NULL DEFAULT 1")
    if table_exists("products"):
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE products SET item_type = 'asset' WHERE item_type IS NULL OR item_type = ''")
            )
            conn.execute(text("UPDATE products SET min_stock = 0 WHERE min_stock IS NULL"))
    print("[OK] Inventory V-Next Basisschritte abgeschlossen")
    return True


def migrate(security_only=False):
    print("=" * 60)
    print("Datenbank-Migration: Version 2.4.1 (einheitlich)")
    print("=" * 60)

    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        try:
            # Erst Modell-Tabellen sicherstellen, dann gezielte ALTERs
            db.create_all()
            if security_only:
                ok = migrate_security_features()
                if ok:
                    print("\n[OK] Sicherheitsmigration abgeschlossen")
                return ok

            steps = [
                migrate_security_features,
                migrate_share_modes,
                migrate_shortlinks,
                migrate_inventory_vnext,
            ]
            for step in steps:
                if not step():
                    return False

            print("\n" + "=" * 60)
            print("✅ Alle Migrationen erfolgreich abgeschlossen")
            print("=" * 60)
            return True
        except Exception as exc:
            print(f"[FEHLER] Migration fehlgeschlagen: {exc}")
            db.session.rollback()
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PrismaTeams DB-Migration 2.4.1 (einheitlich)")
    parser.add_argument(
        "--security-only",
        action="store_true",
        help="Nur Sicherheitsmigration ausführen (für Auto-Update beim Start)",
    )
    arguments = parser.parse_args()
    success = migrate(security_only=arguments.security_only)
    sys.exit(0 if success else 1)
