"""
Portal 3.5.0: Booking / Personal English email templates.
Adds accept_template_subject_en, accept_template_body_en,
reject_template_subject_en, reject_template_body_en,
invite_template_subject_en, invite_template_body_en to booking_personal_events.
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
        from app.models.booking_personal import BookingPersonalEvent  # noqa: F401

        db.create_all()
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        tbl = 'booking_personal_events'
        if tbl not in tables:
            report.note_warn(f'{tbl} existiert nicht.')
            return

        cols = {c['name'] for c in inspector.get_columns(tbl)}
        dialect = db.engine.dialect.name

        new_columns = [
            ('accept_template_subject_en', 'VARCHAR(255)'),
            ('accept_template_body_en', 'TEXT'),
            ('reject_template_subject_en', 'VARCHAR(255)'),
            ('reject_template_body_en', 'TEXT'),
            ('invite_template_subject_en', 'VARCHAR(255)'),
            ('invite_template_body_en', 'TEXT'),
        ]

        for col_name, col_type in new_columns:
            if col_name in cols:
                report.note_skip(f'{tbl}.{col_name} existiert bereits')
                continue
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type} NULL'))
                report.note_ok(f'Spalte {tbl}.{col_name} hinzugefügt')

    except Exception as exc:
        report.note_error(f'migrate_to_3_5_0 failed: {exc}')
        raise
    finally:
        if ctx:
            ctx.pop()


if __name__ == '__main__':
    run()
