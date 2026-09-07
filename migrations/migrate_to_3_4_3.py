"""
Portal 3.4.3: AssessmentUser Login-Lockout-Spalten.
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
        if 'ass_users' not in set(inspector.get_table_names()):
            report.note_skip('Tabelle ass_users fehlt')
            return

        cols = {c['name'] for c in inspector.get_columns('ass_users')}
        dialect = db.engine.dialect.name
        added = []

        def _add_column(sql_mysql: str, sql_other: str, name: str):
            if name in cols:
                report.note_skip(f'ass_users.{name} bereits vorhanden')
                return
            with db.engine.begin() as conn:
                if dialect == 'mysql':
                    conn.execute(text(sql_mysql))
                else:
                    conn.execute(text(sql_other))
            added.append(name)
            report.note_ok(f'ass_users.{name} angelegt')

        _add_column(
            'ALTER TABLE ass_users ADD COLUMN failed_login_attempts INT NOT NULL DEFAULT 0',
            'ALTER TABLE ass_users ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0',
            'failed_login_attempts',
        )
        _add_column(
            'ALTER TABLE ass_users ADD COLUMN failed_login_until DATETIME NULL',
            'ALTER TABLE ass_users ADD COLUMN failed_login_until DATETIME',
            'failed_login_until',
        )

        if added:
            report.note_ok(f'migrate_to_3_4_3: {", ".join(added)}')
        else:
            report.note_skip('migrate_to_3_4_3: nichts zu tun')
        report.note_ok('migrate_to_3_4_3 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_3 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
