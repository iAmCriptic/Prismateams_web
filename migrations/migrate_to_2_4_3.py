#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.4.3

Einheitliche Migration ohne weitere Skript-Abhängigkeiten.

Aufruf:
  python migrations/migrate_to_2_4_3.py
  python migrations/migrate_to_2_4_3.py --security-only
"""

import argparse
import os
import sys

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.booking import (
    BookingForm,
    BookingFormField,
    BookingFormImage,
    BookingFormRole,
    BookingFormRoleUser,
    BookingRequest,
    BookingRequestApproval,
    BookingRequestField,
    BookingRequestFile,
)

# Reihenfolge beachtet Fremdschluessel-Abhaengigkeiten
BOOKING_MODELS = [
    BookingForm,
    BookingFormField,
    BookingFormImage,
    BookingFormRole,
    BookingFormRoleUser,
    BookingRequest,
    BookingRequestField,
    BookingRequestFile,
    BookingRequestApproval,
]


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


def is_orphan_tablespace_error(exc):
    if isinstance(exc, OperationalError) and getattr(exc.orig, "args", None):
        if exc.orig.args and exc.orig.args[0] == 1813:
            return True
    message = str(exc)
    return "1813" in message or "Tablespace" in message


def remove_orphan_tablespace(table_name):
    with db.engine.connect() as conn:
        datadir = conn.execute(text("SHOW VARIABLES LIKE 'datadir'")).fetchone()[1]
        db_name = conn.execute(text("SELECT DATABASE()")).scalar()
    db_path = os.path.join(datadir, db_name)
    removed = False
    for ext in (".ibd", ".cfg"):
        path = os.path.join(db_path, f"{table_name}{ext}")
        if os.path.exists(path):
            os.remove(path)
            print(f"[OK] Verwaiste Tablespace-Datei entfernt: {path}")
            removed = True
    if not removed:
        print(f"[WARNUNG] Keine verwaiste Tablespace-Datei fuer {table_name} gefunden")
    return removed


def create_table(model):
    table_name = model.__tablename__
    try:
        model.__table__.create(db.engine, checkfirst=True)
        return True
    except OperationalError as exc:
        if not is_orphan_tablespace_error(exc):
            raise
        print(f"[WARNUNG] Verwaiste Tablespace fuer {table_name} - bereinige ...")
        remove_orphan_tablespace(table_name)
        model.__table__.create(db.engine, checkfirst=True)
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


def migrate_booking_tables():
    print("\n[STEP] Buchungs-Tabellen pruefen/erstellen")
    created = []
    for model in BOOKING_MODELS:
        table_name = model.__tablename__
        if table_exists(table_name):
            print(f"[INFO] {table_name} existiert bereits")
            continue
        create_table(model)
        print(f"[OK] {table_name} erstellt")
        created.append(table_name)

    if created:
        print(f"\n[OK] {len(created)} Tabelle(n) angelegt: {', '.join(created)}")
    else:
        print("\n[INFO] Alle Buchungs-Tabellen waren bereits vorhanden")
    return True


def migrate_public_shares_tables():
    print("\n[STEP] public_shares / share_access_logs")
    if table_exists("public_shares"):
        print("[INFO] public_shares existiert bereits")
        return True

    db_type = db.engine.dialect.name
    with db.engine.begin() as conn:
        if db_type == "sqlite":
            conn.execute(
                text(
                    """
                    CREATE TABLE public_shares (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        resource_type VARCHAR(16) NOT NULL,
                        resource_id INTEGER NOT NULL,
                        mode VARCHAR(16) NOT NULL,
                        token VARCHAR(255) NOT NULL UNIQUE,
                        enabled BOOLEAN NOT NULL DEFAULT 1,
                        password_hash VARCHAR(255),
                        expires_at DATETIME,
                        created_by INTEGER NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (created_by) REFERENCES users(id),
                        UNIQUE (resource_type, resource_id, mode)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE share_access_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        public_share_id INTEGER NOT NULL,
                        action VARCHAR(32) NOT NULL,
                        ip_address VARCHAR(45),
                        user_agent VARCHAR(500),
                        guest_name VARCHAR(255),
                        accessed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (public_share_id) REFERENCES public_shares(id)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_public_shares_token ON public_shares(token)"))
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_share_access_logs_share_id ON share_access_logs(public_share_id)"
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE public_shares (
                        id INTEGER AUTO_INCREMENT PRIMARY KEY,
                        resource_type VARCHAR(16) NOT NULL,
                        resource_id INTEGER NOT NULL,
                        mode VARCHAR(16) NOT NULL,
                        token VARCHAR(255) NOT NULL,
                        enabled BOOLEAN NOT NULL DEFAULT 1,
                        password_hash VARCHAR(255),
                        expires_at DATETIME,
                        created_by INTEGER NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        CONSTRAINT fk_public_shares_user FOREIGN KEY (created_by) REFERENCES users(id),
                        CONSTRAINT uq_public_share_resource_mode UNIQUE (resource_type, resource_id, mode),
                        CONSTRAINT uq_public_shares_token UNIQUE (token)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE share_access_logs (
                        id INTEGER AUTO_INCREMENT PRIMARY KEY,
                        public_share_id INTEGER NOT NULL,
                        action VARCHAR(32) NOT NULL,
                        ip_address VARCHAR(45),
                        user_agent VARCHAR(500),
                        guest_name VARCHAR(255),
                        accessed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT fk_share_access_logs_share FOREIGN KEY (public_share_id) REFERENCES public_shares(id)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX idx_public_shares_token ON public_shares(token)"))
            conn.execute(text("CREATE INDEX idx_share_access_logs_share_id ON share_access_logs(public_share_id)"))

    print("[OK] public_shares und share_access_logs erstellt")
    return True


def migrate_legacy_shares():
    print("\n[STEP] Legacy-Freigaben migrieren")
    from app.models.file import File, Folder
    from app.models.public_share import PublicShare

    migrated = 0
    for file_obj in File.query.filter_by(share_enabled=True).filter(File.share_token.isnot(None)).all():
        if PublicShare.query.filter_by(resource_type="file", resource_id=file_obj.id).first():
            continue
        mode = (file_obj.share_mode or "edit").strip().lower()
        if mode not in ("view", "edit"):
            mode = "edit"
        share = PublicShare(
            resource_type="file",
            resource_id=file_obj.id,
            mode=mode,
            token=file_obj.share_token,
            enabled=True,
            password_hash=file_obj.share_password_hash,
            expires_at=file_obj.share_expires_at,
            created_by=file_obj.uploaded_by,
        )
        db.session.add(share)
        migrated += 1

    for folder in Folder.query.filter_by(share_enabled=True).filter(Folder.share_token.isnot(None)).all():
        if PublicShare.query.filter_by(resource_type="folder", resource_id=folder.id).first():
            continue
        mode = (folder.share_mode or "edit").strip().lower()
        if mode not in ("view", "edit"):
            mode = "edit"
        share = PublicShare(
            resource_type="folder",
            resource_id=folder.id,
            mode=mode,
            token=folder.share_token,
            enabled=True,
            password_hash=folder.share_password_hash,
            expires_at=folder.share_expires_at,
            created_by=folder.created_by,
        )
        db.session.add(share)
        migrated += 1

    db.session.commit()
    print(f"[OK] {migrated} Legacy-Freigaben migriert")
    return True


def migrate_notification_logs():
    print("\n[STEP] notification_logs erweitern")
    add_column_if_missing("notification_logs", "notification_type", "VARCHAR(32)")
    add_column_if_missing("notification_logs", "dedup_key", "VARCHAR(255)")
    add_column_if_missing("notification_logs", "source_id", "INTEGER")
    return True


def migrate_push_delivery_logs():
    print("\n[STEP] push_delivery_logs")
    if table_exists("push_delivery_logs"):
        print("[INFO] push_delivery_logs existiert bereits")
        return True

    db_type = db.engine.dialect.name
    with db.engine.begin() as conn:
        if db_type == "sqlite":
            conn.execute(
                text(
                    """
                    CREATE TABLE push_delivery_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        subscription_id INTEGER NOT NULL,
                        dedup_key VARCHAR(255) NOT NULL,
                        sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        FOREIGN KEY (subscription_id) REFERENCES push_subscriptions(id),
                        UNIQUE (subscription_id, dedup_key)
                    )
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE push_delivery_logs (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        subscription_id INT NOT NULL,
                        dedup_key VARCHAR(255) NOT NULL,
                        sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        FOREIGN KEY (subscription_id) REFERENCES push_subscriptions(id),
                        UNIQUE KEY unique_push_delivery_per_subscription (subscription_id, dedup_key)
                    )
                    """
                )
            )
    print("[OK] push_delivery_logs erstellt")
    return True


def migrate(security_only=False):
    print("=" * 60)
    print("Datenbank-Migration: Version 2.4.3 (einheitlich)")
    print("=" * 60)

    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        try:
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
                migrate_booking_tables,
                migrate_public_shares_tables,
                migrate_legacy_shares,
                migrate_notification_logs,
                migrate_push_delivery_logs,
            ]
            for step in steps:
                if not step():
                    return False

            print("\n" + "=" * 60)
            print("Alle Migrationen erfolgreich abgeschlossen")
            print("=" * 60)
            return True
        except Exception as exc:
            print(f"[FEHLER] Migration fehlgeschlagen: {exc}")
            db.session.rollback()
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PrismaTeams DB-Migration 2.4.3 (einheitlich)")
    parser.add_argument(
        "--security-only",
        action="store_true",
        help="Nur Sicherheitsmigration ausfuehren (fuer Auto-Update beim Start)",
    )
    arguments = parser.parse_args()
    success = migrate(security_only=arguments.security_only)
    sys.exit(0 if success else 1)
