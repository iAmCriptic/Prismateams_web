"""
Portal 3.4.6: ChatMessage.sender_id nullable (Kontolöschung / Art. 17 Anonymisierung).
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
        inspector = inspect(db.engine)
        table_name = 'chat_messages'
        if table_name not in inspector.get_table_names():
            report.note_skip(f'{table_name} fehlt')
            report.note_ok('migrate_to_3_4_6 abgeschlossen')
            return

        cols = {c['name']: c for c in inspector.get_columns(table_name)}
        info = cols.get('sender_id')
        if info is None:
            report.note_warn(f'{table_name}.sender_id fehlt')
            report.note_ok('migrate_to_3_4_6 abgeschlossen')
            return
        if info.get('nullable'):
            report.note_skip(f'{table_name}.sender_id bereits nullable')
            report.note_ok('migrate_to_3_4_6 abgeschlossen')
            return

        dialect = db.engine.dialect.name

        if dialect == 'sqlite':
            from alembic.migration import MigrationContext
            from alembic.operations import Operations

            with db.engine.begin() as conn:
                ctx_mig = MigrationContext.configure(conn)
                op = Operations(ctx_mig)
                with op.batch_alter_table(table_name) as batch_op:
                    batch_op.alter_column('sender_id', nullable=True)
                    report.note_ok(f'{table_name}.sender_id → nullable (sqlite batch)')
        elif dialect == 'mysql':
            with db.engine.begin() as conn:
                conn.execute(text(
                    f'ALTER TABLE {table_name} MODIFY COLUMN sender_id INT NULL'
                ))
                report.note_ok(f'{table_name}.sender_id → nullable (mysql)')
        else:
            with db.engine.begin() as conn:
                conn.execute(text(
                    f'ALTER TABLE {table_name} ALTER COLUMN sender_id DROP NOT NULL'
                ))
                report.note_ok(f'{table_name}.sender_id → nullable ({dialect})')

        report.note_ok('migrate_to_3_4_6 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_6 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
