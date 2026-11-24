"""
Portal 3.5.3: Mehrfachauswahl für Räume bei Veranstaltungen (event_rooms).
Legt die Verknüpfungstabelle event_rooms über db.create_all() an und
überträgt bestehende events.room_id-Zuordnungen idempotent in event_rooms.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def run(db=None, report=None):
    from sqlalchemy import inspect, text

    if db is None:
        os.environ.setdefault("PRISMATEAMS_RUNNING_MIGRATIONS", "1")
        os.environ.setdefault("PRISMATEAMS_SKIP_BACKGROUND_JOBS", "1")
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
        from app.models.event import Event, event_rooms  # noqa: F401
        from app.models.booking import BookingRoom  # noqa: F401

        db.create_all()
        report.note_ok('db.create_all() ausgeführt (event_rooms sichergestellt)')

        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        if 'events' in tables and 'event_rooms' in tables:
            with db.engine.begin() as conn:
                rows = conn.execute(
                    text('SELECT id, room_id FROM events WHERE room_id IS NOT NULL')
                ).fetchall()
                inserted = 0
                for ev_id, room_id in rows:
                    exists = conn.execute(
                        text('SELECT 1 FROM event_rooms WHERE event_id = :eid AND room_id = :rid'),
                        {'eid': ev_id, 'rid': room_id},
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            text('INSERT INTO event_rooms (event_id, room_id) VALUES (:eid, :rid)'),
                            {'eid': ev_id, 'rid': room_id},
                        )
                        inserted += 1
            if inserted:
                report.note_ok(f'{inserted} bestehende Raum-Zuordnung(en) nach event_rooms übertragen')
            else:
                report.note_skip('Keine offenen Raum-Zuordnungen für event_rooms')
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
