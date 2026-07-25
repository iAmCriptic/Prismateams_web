#!/usr/bin/env python3
"""
Migration 3.1.0: Datei-Speicherlimits und Nutzer-Kontingente.

- files.file_size / file_versions.file_size -> BIGINT
- Tabelle file_storage_exceptions
- SystemSettings-Seeds fuer globale Limits/Kontingente

Aufruf:
  python migrations/migrate_to_3_1_0_file_storage_quotas.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text


DEFAULT_MAX_FILE_SIZE = "104857600"  # 100 MB
DEFAULT_QUOTA_ENABLED = "false"
DEFAULT_QUOTA_BYTES = "16106127360"  # 15 GB


def table_exists(engine, table_name: str) -> bool:
    return table_name in inspect(engine).get_table_names()


def column_exists(engine, table_name: str, column_name: str) -> bool:
    if not table_exists(engine, table_name):
        return False
    return column_name in {col["name"] for col in inspect(engine).get_columns(table_name)}


def _column_type_name(engine, table_name: str, column_name: str) -> str:
    for col in inspect(engine).get_columns(table_name):
        if col["name"] == column_name:
            return str(col["type"]).upper()
    return ""


def _ensure_bigint(connection, engine, table_name: str, column_name: str) -> None:
    if not column_exists(engine, table_name, column_name):
        print(f"[INFO] {table_name}.{column_name} fehlt – uebersprungen")
        return

    type_name = _column_type_name(engine, table_name, column_name)
    if "BIGINT" in type_name or type_name in ("INTEGER", "INT"):
        # SQLite meldet oft INTEGER auch fuer BIGINT-Affinitaet; bei MySQL BIGINT pruefen
        dialect = engine.dialect.name
        if dialect == "sqlite":
            # SQLite speichert Integer dynamisch – kein ALTER noetig
            print(f"[INFO] {table_name}.{column_name}: SQLite Integer (dynamisch) – OK")
            return
        if "BIGINT" in type_name:
            print(f"[INFO] {table_name}.{column_name} ist bereits BIGINT")
            return

    dialect = engine.dialect.name
    if dialect == "mysql":
        connection.execute(
            text(
                f"ALTER TABLE {table_name} "
                f"MODIFY COLUMN {column_name} BIGINT NOT NULL"
            )
        )
        print(f"[OK] {table_name}.{column_name} -> BIGINT")
    elif dialect == "postgresql":
        connection.execute(
            text(
                f"ALTER TABLE {table_name} "
                f"ALTER COLUMN {column_name} TYPE BIGINT"
            )
        )
        print(f"[OK] {table_name}.{column_name} -> BIGINT")
    else:
        print(f"[INFO] {table_name}.{column_name}: Dialekt {dialect} – kein ALTER")


def _seed_setting(connection, engine, key: str, value: str, description: str) -> None:
    if not table_exists(engine, "system_settings"):
        print("[WARNUNG] system_settings fehlt – Seeds uebersprungen")
        return

    row = connection.execute(
        text("SELECT id FROM system_settings WHERE `key` = :key"),
        {"key": key},
    ).fetchone()
    if row:
        print(f"[INFO] system_settings.{key} existiert bereits")
        return

    # SQLite uses "key" without backticks differently; use quoted identifier via SQLAlchemy binds
    dialect = engine.dialect.name
    if dialect == "sqlite":
        connection.execute(
            text(
                "INSERT INTO system_settings (key, value, description) "
                "VALUES (:key, :value, :description)"
            ),
            {"key": key, "value": value, "description": description},
        )
    else:
        connection.execute(
            text(
                "INSERT INTO system_settings (`key`, value, description) "
                "VALUES (:key, :value, :description)"
            ),
            {"key": key, "value": value, "description": description},
        )
    print(f"[OK] system_settings.{key} = {value}")


def migrate() -> bool:
    print("=" * 60)
    print("Migration 3.1.0: Datei-Speicherlimits / Kontingente")
    print("=" * 60)

    os.environ.setdefault("PRISMATEAMS_SKIP_BACKGROUND_JOBS", "1")
    os.environ["PRISMATEAMS_RUNNING_MIGRATIONS"] = "1"

    try:
        from app import create_app, db

        app = create_app(os.getenv("FLASK_ENV", "development"))
        with app.app_context():
            engine = db.engine
            dialect = engine.dialect.name

            with engine.begin() as connection:
                # BIGINT fuer Dateigroessen
                _ensure_bigint(connection, engine, "files", "file_size")
                _ensure_bigint(connection, engine, "file_versions", "file_size")

                # Ausnahme-Tabelle
                if table_exists(engine, "file_storage_exceptions"):
                    print("[INFO] file_storage_exceptions existiert bereits")
                else:
                    if dialect == "sqlite":
                        connection.execute(
                            text(
                                """
                                CREATE TABLE file_storage_exceptions (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    user_id INTEGER NOT NULL UNIQUE,
                                    max_file_size_bytes BIGINT,
                                    quota_bytes BIGINT,
                                    created_at DATETIME NOT NULL,
                                    updated_at DATETIME,
                                    FOREIGN KEY(user_id) REFERENCES users(id)
                                )
                                """
                            )
                        )
                    else:
                        connection.execute(
                            text(
                                """
                                CREATE TABLE file_storage_exceptions (
                                    id INT AUTO_INCREMENT PRIMARY KEY,
                                    user_id INT NOT NULL,
                                    max_file_size_bytes BIGINT NULL,
                                    quota_bytes BIGINT NULL,
                                    created_at DATETIME NOT NULL,
                                    updated_at DATETIME NULL,
                                    UNIQUE KEY uq_file_storage_exceptions_user (user_id),
                                    CONSTRAINT fk_file_storage_exceptions_user
                                        FOREIGN KEY (user_id) REFERENCES users(id)
                                        ON DELETE CASCADE
                                )
                                """
                            )
                        )
                    print("[OK] file_storage_exceptions erstellt")

                _seed_setting(
                    connection,
                    engine,
                    "files_max_file_size_bytes",
                    DEFAULT_MAX_FILE_SIZE,
                    "Maximale Dateigroesse in Bytes (global)",
                )
                _seed_setting(
                    connection,
                    engine,
                    "files_storage_quota_enabled",
                    DEFAULT_QUOTA_ENABLED,
                    "Speicherkontingente aktiv (true/false)",
                )
                _seed_setting(
                    connection,
                    engine,
                    "files_storage_quota_bytes",
                    DEFAULT_QUOTA_BYTES,
                    "Standard-Speicherkontingent pro Nutzer in Bytes",
                )

            print("=" * 60)
            print("[OK] Migration 3.1.0 abgeschlossen")
            print("=" * 60)
            return True
    except Exception as exc:
        print(f"[FEHLER] Migration 3.1.0: {exc}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        os.environ.pop("PRISMATEAMS_RUNNING_MIGRATIONS", None)


if __name__ == "__main__":
    ok = migrate()
    sys.exit(0 if ok else 1)
