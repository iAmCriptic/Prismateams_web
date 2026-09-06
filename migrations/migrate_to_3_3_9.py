"""
Portal 3.3.9: Meetings-Modul (MiroTalk SFU) — meetings + meeting_invites.
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
        from app.models.meetings import Meeting, MeetingInvite  # noqa: F401
        from app.models.settings import SystemSettings

        db.create_all()
        report.note_ok('create_all for meetings 3.3.9')

        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        for name in ('meetings', 'meeting_invites'):
            if name in tables:
                report.note_ok(f'Tabelle {name} vorhanden')
            else:
                report.note_warn(f'Tabelle {name} fehlt nach create_all')

        existing = SystemSettings.query.filter_by(key='module_meetings').first()
        if existing is None:
            db.session.add(SystemSettings(
                key='module_meetings',
                value='True',
                description='Modul Meetings aktiviert',
            ))
            db.session.commit()
            report.note_ok('module_meetings Flag angelegt')
        else:
            report.note_skip('module_meetings bereits vorhanden')

        report.note_ok('migrate_to_3_3_9 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_3_9 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()
