"""
Portal 3.4.8: User can_access_public/private + TeamInviteCode.
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
        from app.models.team import TeamInviteCode  # noqa: F401

        db.create_all()
        report.note_ok('create_all for team_invite_codes 3.4.8')

        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        dialect = db.engine.dialect.name

        # --- users columns ---
        users_table = 'users' if 'users' in tables else ('ass_users' if 'ass_users' in tables else None)
        if users_table:
            cols = {c['name'] for c in inspector.get_columns(users_table)}

            def _add_bool(name: str):
                if name in cols:
                    report.note_skip(f'{users_table}.{name} bereits vorhanden')
                    return
                with db.engine.begin() as conn:
                    if dialect == 'mysql':
                        conn.execute(text(
                            f'ALTER TABLE {users_table} ADD COLUMN {name} TINYINT(1) NOT NULL DEFAULT 1'
                        ))
                    elif dialect == 'postgresql':
                        conn.execute(text(
                            f'ALTER TABLE {users_table} ADD COLUMN {name} BOOLEAN NOT NULL DEFAULT TRUE'
                        ))
                    else:
                        conn.execute(text(
                            f'ALTER TABLE {users_table} ADD COLUMN {name} BOOLEAN NOT NULL DEFAULT 1'
                        ))
                report.note_ok(f'{users_table}.{name} angelegt')

            _add_bool('can_access_public')
            _add_bool('can_access_private')
        else:
            report.note_warn('users-Tabelle fehlt')

        if 'team_invite_codes' in tables:
            report.note_ok('Tabelle team_invite_codes vorhanden')
        else:
            report.note_warn('Tabelle team_invite_codes fehlt nach create_all')

        report.note_ok('migrate_to_3_4_8 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_8 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
