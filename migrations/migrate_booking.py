#!/usr/bin/env python3
"""
Datenbank-Migration: Buchungsmodul

Erstellt fehlende Tabellen für Buchungsanfragen und zugehörige Daten.

Aufruf:
  python migrations/migrate_booking.py
"""

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

# Reihenfolge beachtet Fremdschlüssel-Abhängigkeiten
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


def is_orphan_tablespace_error(exc):
    if isinstance(exc, OperationalError) and getattr(exc.orig, "args", None):
        if exc.orig.args and exc.orig.args[0] == 1813:
            return True
    message = str(exc)
    return "1813" in message or "Tablespace" in message


def remove_orphan_tablespace(table_name):
    """Entfernt verwaiste .ibd/.cfg-Dateien (MySQL-Fehler 1813)."""
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
        print(f"[WARNUNG] Keine verwaiste Tablespace-Datei für {table_name} gefunden")
    return removed


def create_table(model):
    table_name = model.__tablename__
    try:
        model.__table__.create(db.engine, checkfirst=True)
        return True
    except OperationalError as exc:
        if not is_orphan_tablespace_error(exc):
            raise
        print(f"[WARNUNG] Verwaiste Tablespace für {table_name} – bereinige …")
        remove_orphan_tablespace(table_name)
        model.__table__.create(db.engine, checkfirst=True)
        return True


def migrate_booking_tables():
    print("\n[STEP] Buchungs-Tabellen prüfen/erstellen")
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


def main():
    app = create_app()
    with app.app_context():
        migrate_booking_tables()
        print("\n[FERTIG] Buchungs-Migration abgeschlossen.")


if __name__ == "__main__":
    main()
