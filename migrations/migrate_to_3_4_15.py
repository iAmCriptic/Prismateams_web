"""
Portal 3.4.15: TeamInviteCode role column (team_only vs portal_user).
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

        table = 'team_invite_codes'
        if table in tables:
            cols = {c['name'] for c in inspector.get_columns(table)}

            if 'role' in cols:
                report.note_skip(f'{table}.role bereits vorhanden')
            else:
                with db.engine.begin() as conn:
                    if dialect == 'mysql':
                        conn.execute(text(
                            f"ALTER TABLE {table} ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'team_only'"
                        ))
                    elif dialect == 'postgresql':
                        conn.execute(text(
                            f"ALTER TABLE {table} ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'team_only'"
                        ))
                    else:
                        conn.execute(text(
                            f"ALTER TABLE {table} ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'team_only'"
                        ))
                report.note_ok(f'{table}.role angelegt')
        else:
            report.note_warn(f'{table} Tabelle fehlt noch')

        report.note_ok('migrate_to_3_4_15 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_15: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    class _CliReport:
        def note_ok(self, m): print(f'[OK] {m}')
        def note_warn(self, m): print(f'[WARN] {m}')
        def note_skip(self, m): print(f'[SKIP] {m}')
        def note_error(self, m): print(f'[ERR] {m}')

    run(report=_CliReport())
