#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.5.0 (Veranstaltungsmodul)

Aufruf:
  python migrations/migrate_to_2_5_0_events.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.event import (
    Event,
    EventAppointment,
    EventAssignment,
    EventInventoryNeed,
    EventContact,
    EventTimelineItem,
)

EVENT_MODELS = [
    Event,
    EventAppointment,
    EventAssignment,
    EventInventoryNeed,
    EventContact,
    EventTimelineItem,
]


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def migrate():
    print("=" * 60)
    print("Datenbank-Migration: Version 2.5.0 (Veranstaltungsmodul)")
    print("=" * 60)

    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        try:
            db.create_all()
            created_tables = []

            for model in EVENT_MODELS:
                table_name = model.__tablename__
                if table_exists(table_name):
                    print(f"[INFO] {table_name} existiert bereits")
                    continue
                model.__table__.create(db.engine, checkfirst=True)
                created_tables.append(table_name)
                print(f"[OK] {table_name} erstellt")

            # Nachruesten fuer bestehende Installationen
            inspector = inspect(db.engine)
            if 'events' in inspector.get_table_names():
                columns = {col['name'] for col in inspector.get_columns('events')}
                with db.engine.begin() as conn:
                    if 'is_archived' not in columns:
                        conn.execute(text("ALTER TABLE events ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0"))
                        print("[OK] events.is_archived hinzugefügt")
                    if 'archived_at' not in columns:
                        conn.execute(text("ALTER TABLE events ADD COLUMN archived_at DATETIME NULL"))
                        print("[OK] events.archived_at hinzugefügt")

            if 'event_timeline_items' in inspector.get_table_names():
                timeline_columns = {col['name'] for col in inspector.get_columns('event_timeline_items')}
                if 'appointment_id' not in timeline_columns:
                    with db.engine.begin() as conn:
                        conn.execute(text("ALTER TABLE event_timeline_items ADD COLUMN appointment_id INTEGER NULL"))
                    print("[OK] event_timeline_items.appointment_id hinzugefügt")

            if created_tables:
                print(f"[OK] {len(created_tables)} Tabelle(n) erstellt: {', '.join(created_tables)}")
            else:
                print("[INFO] Alle Veranstaltungs-Tabellen waren bereits vorhanden")

            return True
        except Exception as exc:
            print(f"[FEHLER] Migration fehlgeschlagen: {exc}")
            db.session.rollback()
            return False


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
