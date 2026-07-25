#!/usr/bin/env python3
"""
Migration 3.1.1: Veranstaltungen-Kalender (events).

- Singleton-Kalender calendar_type='events' anlegen
- Termine aus Events-/Booking-Modul von Public nach Events umhaengen

Aufruf:
  python migrations/migrate_to_3_1_1_events_calendar.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text


EVENTS_NAME = "Veranstaltungen"
EVENTS_COLOR = "#e85d04"


def table_exists(engine, table_name: str) -> bool:
    return table_name in inspect(engine).get_table_names()


def column_exists(engine, table_name: str, column_name: str) -> bool:
    if not table_exists(engine, table_name):
        return False
    return column_name in {col["name"] for col in inspect(engine).get_columns(table_name)}


def migrate() -> bool:
    print("=" * 60)
    print("Migration 3.1.1: Veranstaltungen-Kalender")
    print("=" * 60)

    from app import create_app, db

    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        engine = db.engine

        if not table_exists(engine, "calendars"):
            print("[INFO] calendars fehlt – Migration uebersprungen")
            return True

        if not column_exists(engine, "calendar_events", "calendar_id"):
            print("[INFO] calendar_events.calendar_id fehlt – Migration uebersprungen")
            return True

        with engine.begin() as connection:
            row = connection.execute(
                text("SELECT id FROM calendars WHERE calendar_type = 'events' LIMIT 1")
            ).fetchone()
            if row:
                events_id = row[0]
                print(f"[INFO] Veranstaltungen-Kalender existiert bereits (id={events_id})")
            else:
                connection.execute(
                    text(
                        "INSERT INTO calendars (name, calendar_type, owner_id, color, created_at) "
                        "VALUES (:name, 'events', NULL, :color, CURRENT_TIMESTAMP)"
                    ),
                    {"name": EVENTS_NAME, "color": EVENTS_COLOR},
                )
                row = connection.execute(
                    text("SELECT id FROM calendars WHERE calendar_type = 'events' LIMIT 1")
                ).fetchone()
                events_id = row[0]
                print(f"[OK] Veranstaltungen-Kalender angelegt (id={events_id})")

            public_row = connection.execute(
                text("SELECT id FROM calendars WHERE calendar_type = 'public' LIMIT 1")
            ).fetchone()
            if not public_row:
                print("[INFO] Kein Public-Kalender – nichts umzuhaengen")
                return True

            public_id = public_row[0]
            moved = 0

            # Booking-linked events
            if column_exists(engine, "calendar_events", "booking_request_id"):
                result = connection.execute(
                    text(
                        "UPDATE calendar_events SET calendar_id = :events_id "
                        "WHERE calendar_id = :public_id AND booking_request_id IS NOT NULL"
                    ),
                    {"events_id": events_id, "public_id": public_id},
                )
                moved += result.rowcount or 0

            # Events-module appointments
            if table_exists(engine, "event_appointments") and column_exists(
                engine, "event_appointments", "calendar_event_id"
            ):
                result = connection.execute(
                    text(
                        "UPDATE calendar_events SET calendar_id = :events_id "
                        "WHERE calendar_id = :public_id "
                        "AND id IN ("
                        "  SELECT calendar_event_id FROM event_appointments "
                        "  WHERE calendar_event_id IS NOT NULL"
                        ")"
                    ),
                    {"events_id": events_id, "public_id": public_id},
                )
                moved += result.rowcount or 0

            print(f"[OK] {moved} Termine nach Veranstaltungen umgehaengt")

        print("=" * 60)
        print("Migration 3.1.1 abgeschlossen")
        print("=" * 60)
        return True


if __name__ == "__main__":
    os.environ.setdefault("PRISMATEAMS_SKIP_BACKGROUND_JOBS", "1")
    os.environ["PRISMATEAMS_RUNNING_MIGRATIONS"] = "1"
    ok = migrate()
    sys.exit(0 if ok else 1)
