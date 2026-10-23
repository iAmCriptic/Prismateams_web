"""
Portal 3.4.10: User.dguv_signature_confirmed_until for monthly DGUV OTP window.
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
        tables = set(inspector.get_table_names())
        dialect = db.engine.dialect.name
        users_table = 'users' if 'users' in tables else None
        if not users_table:
            report.note_warn('users table missing')
            return

        cols = {c['name'] for c in inspector.get_columns(users_table)}
        if 'dguv_signature_confirmed_until' in cols:
            report.note_skip('users.dguv_signature_confirmed_until bereits vorhanden')
        else:
            with db.engine.begin() as conn:
                if dialect == 'mysql':
                    conn.execute(text(
                        f'ALTER TABLE {users_table} ADD COLUMN dguv_signature_confirmed_until DATETIME NULL'
                    ))
                elif dialect == 'postgresql':
                    conn.execute(text(
                        f'ALTER TABLE {users_table} ADD COLUMN dguv_signature_confirmed_until TIMESTAMP NULL'
                    ))
                else:
                    conn.execute(text(
                        f'ALTER TABLE {users_table} ADD COLUMN dguv_signature_confirmed_until DATETIME'
                    ))
            report.note_ok('users.dguv_signature_confirmed_until hinzugefügt')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_10 failed: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()
