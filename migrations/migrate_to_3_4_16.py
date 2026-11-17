"""
Portal 3.4.16: Add Booking / Personal module tables and initial default template.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def run(db=None, report=None):
    from sqlalchemy import inspect

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
        from app.models.booking_personal import (
            BookingPersonalEvent,
            BookingPersonalField,
            BookingPersonalEntry,
            BookingPersonalFile,
            BookingPersonalTemplate,
        )
        from app.utils.booking_personal_presets import ensure_default_template

        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())

        # Erstelle Tabellen, falls nicht vorhanden
        for model in (
            BookingPersonalEvent,
            BookingPersonalField,
            BookingPersonalEntry,
            BookingPersonalFile,
            BookingPersonalTemplate,
        ):
            tbl = model.__tablename__
            if tbl not in existing_tables:
                model.__table__.create(db.engine, checkfirst=True)
                report.note_ok(f"Tabelle {tbl} erstellt.")
            else:
                report.note_skip(f"Tabelle {tbl} existiert bereits.")

        # Stelle Standard-Template 'Festival Standard' bereit
        ensure_default_template(db.session)
        report.note_ok("Standard-Vorlage 'Festival Standard' sichergestellt.")

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        report.note_error(f"Fehler bei Migration 3.4.16: {e}")
        raise
    finally:
        if ctx:
            ctx.pop()


if __name__ == '__main__':
    class _CliReport:
        def note_ok(self, m): print(f'[OK] {m}')
        def note_warn(self, m): print(f'[WARN] {m}')
        def note_skip(self, m): print(f'[SKIP] {m}')
        def note_error(self, m): print(f'[ERR] {m}')

    run(report=_CliReport())

