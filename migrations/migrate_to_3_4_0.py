"""
Portal 3.4.0: password_reset_code auf VARCHAR(128) erweitern (SHA-256-Hex).
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
        if 'users' not in set(inspector.get_table_names()):
            report.note_skip('Tabelle users fehlt')
            return

        cols = {c['name']: c for c in inspector.get_columns('users')}
        col = cols.get('password_reset_code')
        if col is None:
            report.note_skip('users.password_reset_code fehlt')
            return

        dialect = db.engine.dialect.name
        # SQLite ignoriert VARCHAR-Längen weitgehend — trotzdem batch für Konsistenz
        if dialect == 'sqlite':
            from alembic.migration import MigrationContext
            from alembic.operations import Operations
            from sqlalchemy import String

            with db.engine.begin() as conn:
                ctx_mig = MigrationContext.configure(conn)
                op = Operations(ctx_mig)
                with op.batch_alter_table('users') as batch_op:
                    batch_op.alter_column(
                        'password_reset_code',
                        existing_type=String(64),
                        type_=String(128),
                        existing_nullable=True,
                        nullable=True,
                    )
            report.note_ok('users.password_reset_code → VARCHAR(128) (sqlite batch)')
        elif dialect == 'mysql':
            with db.engine.begin() as conn:
                conn.execute(text(
                    'ALTER TABLE users MODIFY COLUMN password_reset_code VARCHAR(128) NULL'
                ))
            report.note_ok('users.password_reset_code → VARCHAR(128) (mysql)')
        else:
            with db.engine.begin() as conn:
                conn.execute(text(
                    'ALTER TABLE users ALTER COLUMN password_reset_code TYPE VARCHAR(128)'
                ))
            report.note_ok(f'users.password_reset_code → VARCHAR(128) ({dialect})')

        report.note_ok('migrate_to_3_4_0 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_0 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
