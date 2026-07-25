#!/usr/bin/env python3
"""
Migration 3.1.1: Orphaned email_attachments reparieren (MySQL Error 1932).

Symptom: Tabelle steht in INFORMATION_SCHEMA, ENGINE ist NULL,
Zugriff liefert OperationalError 1932 ("doesn't exist in engine").

Loesung: DROP + CREATE aus dem SQLAlchemy-Modell EmailAttachment.
Bereits vorhandene, gesunde Tabellen bleiben unangetastet.

Aufruf:
  python migrations/migrate_to_3_1_1_fix_email_attachments.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text


def _is_orphaned_mysql(connection, table_name: str) -> bool:
    row = connection.execute(
        text(
            "SELECT ENGINE FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :name"
        ),
        {"name": table_name},
    ).fetchone()
    if row is None:
        return False
    engine_name = row[0]
    return engine_name is None or str(engine_name).strip() == ""


def _table_usable(connection, table_name: str) -> bool:
    try:
        connection.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1"))
        return True
    except Exception:
        return False


def migrate() -> bool:
    print("=" * 60)
    print("Migration 3.1.1: email_attachments reparieren")
    print("=" * 60)

    os.environ.setdefault("PRISMATEAMS_SKIP_BACKGROUND_JOBS", "1")
    os.environ["PRISMATEAMS_RUNNING_MIGRATIONS"] = "1"

    try:
        from app import create_app, db
        from app.models.email import EmailAttachment

        app = create_app(os.getenv("FLASK_ENV", "development"))
        with app.app_context():
            engine = db.engine
            dialect = engine.dialect.name
            table_name = EmailAttachment.__tablename__
            insp = inspect(engine)
            listed = table_name in insp.get_table_names()

            if dialect == "mysql":
                with engine.connect() as connection:
                    orphaned = listed and _is_orphaned_mysql(connection, table_name)
                    usable = listed and not orphaned and _table_usable(connection, table_name)

                if usable:
                    print(f"[INFO] {table_name} ist gesund – nichts zu tun")
                    print("=" * 60)
                    print("[OK] Migration 3.1.1 abgeschlossen")
                    print("=" * 60)
                    return True

                if orphaned or (listed and not usable):
                    print(f"[WARNUNG] {table_name} orphaned/kaputt – DROP + CREATE")
                    with engine.begin() as connection:
                        connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
                    EmailAttachment.__table__.create(engine, checkfirst=True)
                    print(f"[OK] {table_name} neu erstellt")
                elif not listed:
                    print(f"[INFO] {table_name} fehlt – CREATE")
                    EmailAttachment.__table__.create(engine, checkfirst=True)
                    print(f"[OK] {table_name} erstellt")
            else:
                # SQLite / andere: nur anlegen wenn fehlend
                with engine.connect() as connection:
                    usable = listed and _table_usable(connection, table_name)
                if usable:
                    print(f"[INFO] {table_name} vorhanden – OK")
                else:
                    EmailAttachment.__table__.create(engine, checkfirst=True)
                    print(f"[OK] {table_name} sichergestellt")

            with engine.connect() as connection:
                if not _table_usable(connection, table_name):
                    raise RuntimeError(f"{table_name} nach Repair weiterhin nicht nutzbar")

            print("=" * 60)
            print("[OK] Migration 3.1.1 abgeschlossen")
            print("=" * 60)
            return True
    except Exception as exc:
        print(f"[FEHLER] Migration 3.1.1: {exc}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        os.environ.pop("PRISMATEAMS_RUNNING_MIGRATIONS", None)


if __name__ == "__main__":
    ok = migrate()
    sys.exit(0 if ok else 1)
