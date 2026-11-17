"""
Portal 3.5.1: Event hub module integration, multiday events, todo lists, booking & kanban links.
Adds columns to events and event_appointments, creates event_days, event_todo_lists,
event_todo_items, event_booking_personal_links, and backfills existing events.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def run(db=None, report=None):
    from sqlalchemy import inspect, text

    if db is None:
        from app import create_app, db as _db
        app = create_app()
        ctx = app.app_context()
        ctx.push()
        db = _db
    else:
        ctx = None

    class _Nop:
        def note_ok(self, *a, **k): pass
        def note_warn(self, *a, **k): pass
        def note_skip(self, *a, **k): pass
        def note_error(self, *a, **k): pass

    report = report or _Nop()

    try:
        from app.models.event import (
            Event,
            EventDay,
            EventAppointment,
            EventTodoList,
            EventTodoItem,
            EventBookingPersonalLink,
        )

        db.create_all()
        inspector = inspect(db.engine)
        dialect = db.engine.dialect.name

        # 1. Spalten in 'events' nachrüsten
        if 'events' in inspector.get_table_names():
            cols = {c['name'] for c in inspector.get_columns('events')}
            new_event_cols = [
                ('is_multiday', 'BOOLEAN DEFAULT 0 NOT NULL' if dialect == 'sqlite' else 'BOOLEAN DEFAULT FALSE NOT NULL'),
                ('start_date', 'DATE'),
                ('end_date', 'DATE'),
                ('kanban_board_id', 'INTEGER'),
                ('kanban_card_id', 'INTEGER'),
            ]
            for col_name, col_type in new_event_cols:
                if col_name not in cols:
                    try:
                        db.session.execute(text(f'ALTER TABLE events ADD COLUMN {col_name} {col_type}'))
                        db.session.commit()
                        report.note_ok(f'events.{col_name} hinzugefügt')
                    except Exception as e:
                        db.session.rollback()
                        report.note_warn(f'events.{col_name}: {e}')

        # 2. Spalte 'day_id' in 'event_appointments' nachrüsten
        if 'event_appointments' in inspector.get_table_names():
            appt_cols = {c['name'] for c in inspector.get_columns('event_appointments')}
            if 'day_id' not in appt_cols:
                try:
                    db.session.execute(text('ALTER TABLE event_appointments ADD COLUMN day_id INTEGER'))
                    db.session.commit()
                    report.note_ok('event_appointments.day_id hinzugefügt')
                except Exception as e:
                    db.session.rollback()
                    report.note_warn(f'event_appointments.day_id: {e}')

        # 3. Spalten in 'event_days' nachrüsten
        if 'event_days' in inspector.get_table_names():
            day_cols = {c['name'] for c in inspector.get_columns('event_days')}
            for c_name, c_type in [('start_time', 'TIME'), ('end_time', 'TIME'), ('location', 'VARCHAR(255)')]:
                if c_name not in day_cols:
                    try:
                        db.session.execute(text(f'ALTER TABLE event_days ADD COLUMN {c_name} {c_type}'))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

        # 4. Spalten in 'event_todo_items' nachrüsten
        if 'event_todo_items' in inspector.get_table_names():
            todo_cols = {c['name'] for c in inspector.get_columns('event_todo_items')}
            if 'due_time' not in todo_cols:
                try:
                    db.session.execute(text('ALTER TABLE event_todo_items ADD COLUMN due_time TIME'))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        # 5. Bestehende Events migrieren (Tage initialisieren)
        events = Event.query.all()
        for ev in events:
            if not ev.days and ev.appointments:
                # Sammle eindeutige Tage aus den Terminen
                dates_dict = {}
                for appt in ev.appointments:
                    d = appt.start_time.date()
                    if d not in dates_dict:
                        dates_dict[d] = []
                    dates_dict[d].append(appt)

                sorted_dates = sorted(dates_dict.keys())
                ev.is_multiday = len(sorted_dates) > 1
                ev.start_date = sorted_dates[0] if sorted_dates else None
                ev.end_date = sorted_dates[-1] if sorted_dates else None

                for idx, d in enumerate(sorted_dates, start=1):
                    day_label = f"Tag {idx}" if ev.is_multiday else "Haupttermin"
                    day_obj = EventDay(
                        event_id=ev.id,
                        day_number=idx,
                        date=d,
                        label=day_label,
                    )
                    db.session.add(day_obj)
                    db.session.flush()

                    for appt in dates_dict[d]:
                        appt.day_id = day_obj.id

        db.session.commit()
        report.note_ok('Events 3.5.1 Schema & Backfill abgeschlossen')

    except Exception as e:
        db.session.rollback()
        report.note_error(f'migrate_to_3_5_1: {e}')
        raise
    finally:
        if ctx:
            ctx.pop()


if __name__ == '__main__':
    run()
