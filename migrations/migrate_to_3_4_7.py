"""
Portal 3.4.7: Serverseitige Auto-Antworten (Abwesenheit) pro Postfach.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def run(db=None, report=None):
    from sqlalchemy import inspect

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
        from app.models.email import MailboxAutoReply, MailboxAutoReplyLog  # noqa: F401

        db.create_all()
        report.note_ok('create_all for mailbox auto-reply 3.4.7')

        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        for name in ('mailbox_auto_replies', 'mailbox_auto_reply_logs'):
            if name in tables:
                report.note_ok(f'Tabelle {name} vorhanden')
            else:
                report.note_warn(f'Tabelle {name} fehlt nach create_all')

        report.note_ok('migrate_to_3_4_7 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_7 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()
