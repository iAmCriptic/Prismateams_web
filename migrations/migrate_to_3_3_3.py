"""
Portal 3.3.3: 2FA-Wiederherstellung per E-Mail (totp_recovery_code).
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
        report.note_ok('create_all for 2FA recovery 3.3.3')

        inspector = inspect(db.engine)
        dialect = db.engine.dialect
        table_name = User.__tablename__
        columns = (
            User.__table__.c.totp_recovery_code,
            User.__table__.c.totp_recovery_code_expires,
        )

        if table_name in inspector.get_table_names():
            existing = {c['name'] for c in inspector.get_columns(table_name)}
            for column in columns:
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
                    report.note_ok(f'{table_name}.{column.name} hinzugefügt')
                else:
                    report.note_skip(f'{table_name}.{column.name} existiert')

        report.note_ok('migrate_to_3_3_3 abgeschlossen')
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
