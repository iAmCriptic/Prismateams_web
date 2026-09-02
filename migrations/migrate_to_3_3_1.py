"""
Portal 3.3.1: portal_onboarding_completed für Dashboard-Onboarding-Tour.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def run(db=None, report=None):
    from sqlalchemy import inspect, text
    from sqlalchemy.schema import CreateColumn, Column

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
        from app.models.user import User

        db.create_all()
        report.note_ok('create_all for portal onboarding 3.3.1')

        inspector = inspect(db.engine)
        dialect = db.engine.dialect
        table_name = User.__tablename__
        column = User.__table__.c.portal_onboarding_completed

        if table_name in inspector.get_table_names():
            existing = {c['name'] for c in inspector.get_columns(table_name)}
            column_added = False
            if column.name not in existing:
                safe = Column(
                    column.name,
                    column.type,
                    nullable=column.nullable,
                    server_default=column.server_default,
                )
                ddl = str(CreateColumn(safe).compile(dialect=dialect)).strip()
                with db.engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {ddl}'))
                column_added = True
                report.note_ok(f'{table_name}.{column.name} hinzugefügt')
            else:
                report.note_skip(f'{table_name}.{column.name} existiert')

            if column_added:
                with db.engine.begin() as conn:
                    conn.execute(text(f'UPDATE {table_name} SET {column.name} = 1'))
                report.note_ok('Bestehende Nutzer als onboarding-abgeschlossen markiert')
        else:
            report.note_warn(f'Tabelle {table_name} nicht gefunden')

        report.note_ok('migrate_to_3_3_1 abgeschlossen')
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
