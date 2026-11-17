"""
Portal 3.4.12: app_passwords.username (z. B. enricomatzke.12) for WebDAV login.
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
        from app.models.app_password import AppPassword, build_app_username
        from app.models.user import User

        db.create_all()
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        if 'app_passwords' not in tables:
            report.note_warn('app_passwords table missing after create_all')
            return

        cols = {c['name'] for c in inspector.get_columns('app_passwords')}
        dialect = db.engine.dialect.name
        if 'username' not in cols:
            with db.engine.begin() as conn:
                if dialect == 'mysql':
                    conn.execute(text(
                        'ALTER TABLE app_passwords ADD COLUMN username VARCHAR(120) NULL'
                    ))
                elif dialect == 'postgresql':
                    conn.execute(text(
                        'ALTER TABLE app_passwords ADD COLUMN username VARCHAR(120) NULL'
                    ))
                else:
                    conn.execute(text(
                        'ALTER TABLE app_passwords ADD COLUMN username VARCHAR(120)'
                    ))
            report.note_ok('app_passwords.username hinzugefügt')
        else:
            report.note_skip('app_passwords.username bereits vorhanden')

        # Unique index (best-effort)
        try:
            indexes = {idx['name'] for idx in inspector.get_indexes('app_passwords')}
            if 'ix_app_passwords_username' not in indexes and 'username' in (
                {c['name'] for c in inspect(db.engine).get_columns('app_passwords')}
            ):
                with db.engine.begin() as conn:
                    if dialect == 'sqlite':
                        conn.execute(text(
                            'CREATE UNIQUE INDEX IF NOT EXISTS ix_app_passwords_username '
                            'ON app_passwords (username)'
                        ))
                    else:
                        conn.execute(text(
                            'CREATE UNIQUE INDEX ix_app_passwords_username ON app_passwords (username)'
                        ))
                report.note_ok('ix_app_passwords_username angelegt')
        except Exception as idx_exc:
            report.note_warn(f'username index: {idx_exc}')

        # Backfill usernames for existing rows
        rows = AppPassword.query.filter(
            (AppPassword.username.is_(None)) | (AppPassword.username == '')
        ).all()
        filled = 0
        for row in rows:
            user = User.query.get(row.user_id)
            first = getattr(user, 'first_name', None) if user else None
            last = getattr(user, 'last_name', None) if user else None
            candidate = build_app_username(first, last, row.id)
            # Collision guard (unlikely)
            clash = AppPassword.query.filter(
                AppPassword.username == candidate,
                AppPassword.id != row.id,
            ).first()
            if clash:
                candidate = f'{candidate}u{row.user_id}'
            row.username = candidate
            filled += 1
        if filled:
            db.session.commit()
            report.note_ok(f'{filled} App-Passwort-Username(s) nachgetragen')
        else:
            report.note_skip('keine Username-Backfills nötig')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_12 failed: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
