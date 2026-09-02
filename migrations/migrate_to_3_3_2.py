"""
Portal 3.3.2: user_passkeys Tabelle für WebAuthn/Passkeys.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def run(db=None, report=None):
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
        from app.models.passkey import UserPasskey

        db.create_all()
        report.note_ok('create_all for user_passkeys 3.3.2')

        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        if UserPasskey.__tablename__ in inspector.get_table_names():
            report.note_ok(f'{UserPasskey.__tablename__} vorhanden')
        else:
            report.note_warn(f'{UserPasskey.__tablename__} nicht gefunden nach create_all')

        report.note_ok('migrate_to_3_3_2 abgeschlossen')
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
