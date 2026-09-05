"""
Portal 3.3.6: Contact.email nullable (Kontakte ohne E-Mail-Adresse).
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
        from app.models.contact import Contact

        db.create_all()
        report.note_ok('create_all for contacts 3.3.6')

        inspector = inspect(db.engine)
        table_name = Contact.__tablename__
        if table_name not in inspector.get_table_names():
            report.note_skip(f'{table_name} fehlt – create_all sollte sie angelegt haben')
            report.note_ok('migrate_to_3_3_6 abgeschlossen')
            return

        cols = {c['name']: c for c in inspector.get_columns(table_name)}
        info = cols.get('email')
        if info is None:
            report.note_warn(f'{table_name}.email fehlt')
            report.note_ok('migrate_to_3_3_6 abgeschlossen')
            return
        if info.get('nullable'):
            report.note_skip(f'{table_name}.email bereits nullable')
            report.note_ok('migrate_to_3_3_6 abgeschlossen')
            return

        dialect = db.engine.dialect.name

        if dialect == 'sqlite':
            from alembic.migration import MigrationContext
            from alembic.operations import Operations

            with db.engine.begin() as conn:
                ctx_mig = MigrationContext.configure(conn)
                op = Operations(ctx_mig)
                with op.batch_alter_table(table_name) as batch_op:
                    batch_op.alter_column('email', nullable=True)
                    report.note_ok(f'{table_name}.email → nullable (sqlite batch)')
        elif dialect == 'mysql':
            with db.engine.begin() as conn:
                conn.execute(text(
                    f'ALTER TABLE {table_name} MODIFY COLUMN email VARCHAR(255) NULL'
                ))
                report.note_ok(f'{table_name}.email → nullable (mysql)')
        else:
            with db.engine.begin() as conn:
                conn.execute(text(
                    f'ALTER TABLE {table_name} ALTER COLUMN email DROP NOT NULL'
                ))
                report.note_ok(f'{table_name}.email → nullable ({dialect})')

        report.note_ok('migrate_to_3_3_6 abgeschlossen')
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
