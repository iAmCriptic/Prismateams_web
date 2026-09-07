"""
Portal 3.4.4: totp_recovery_code Spalte erweitern (Hash statt 6-Ziffern-Klartext).
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
        if 'totp_recovery_code' not in cols:
            report.note_skip('users.totp_recovery_code fehlt')
            return

        col = cols['totp_recovery_code']
        col_type = str(col.get('type') or '').upper()
        dialect = db.engine.dialect.name

        # Schon lang genug (VARCHAR(128) / TEXT)
        if '128' in col_type or 'TEXT' in col_type or 'VARCHAR(255)' in col_type:
            report.note_skip('users.totp_recovery_code bereits ausreichend')
            report.note_ok('migrate_to_3_4_4 abgeschlossen')
            return

        with db.engine.begin() as conn:
            if dialect == 'mysql':
                conn.execute(text(
                    'ALTER TABLE users MODIFY COLUMN totp_recovery_code VARCHAR(128) NULL'
                ))
            elif dialect == 'postgresql':
                conn.execute(text(
                    'ALTER TABLE users ALTER COLUMN totp_recovery_code TYPE VARCHAR(128)'
                ))
            else:
                # SQLite: begrenzte ALTER-Unterstützung — skip wenn nicht nötig
                report.note_warn(
                    'SQLite: totp_recovery_code Typ-Änderung übersprungen '
                    '(neue Installationen nutzen Model String(128))'
                )
                report.note_ok('migrate_to_3_4_4 abgeschlossen')
                return

        report.note_ok('users.totp_recovery_code auf VARCHAR(128) erweitert')
        report.note_ok('migrate_to_3_4_4 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_4 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
