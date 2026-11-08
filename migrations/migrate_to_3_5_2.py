"""
Portal 3.5.2: Self-heal and ensure schema integrity for DGUV OTP column and missing modules.
Ensures users.dguv_signature_confirmed_until exists, verifies dguv_examinations,
mailbox_auto_replies, mailbox_auto_reply_logs, protocols, and meetings tables.
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
        os.environ.setdefault("PRISMATEAMS_RUNNING_MIGRATIONS", "1")
        os.environ.setdefault("PRISMATEAMS_SKIP_BACKGROUND_JOBS", "1")
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
        # 1. Models laden & Tabellen über create_all sicherstellen
        from app.models.inventory import DguvExamination  # noqa: F401
        from app.models.email import MailboxAutoReply, MailboxAutoReplyLog  # noqa: F401
        from app.models.protocol import Protocol, ProtocolAgendaItem  # noqa: F401
        from app.models.meetings import Meeting, MeetingInvite  # noqa: F401
        from app.models.user import User  # noqa: F401

        db.create_all()
        report.note_ok('db.create_all() ausgeführt')

        inspector = inspect(db.engine)
        dialect = db.engine.dialect.name
        is_mysql = dialect in ('mysql', 'mariadb')
        is_pg = dialect == 'postgresql'
        tables = set(inspector.get_table_names())

        # 2. users.dguv_signature_confirmed_until prüfen & nachrüsten
        users_table = 'users' if 'users' in tables else ('ass_users' if 'ass_users' in tables else None)
        if users_table:
            cols = {c['name'] for c in inspector.get_columns(users_table)}
            if 'dguv_signature_confirmed_until' in cols:
                report.note_skip(f'{users_table}.dguv_signature_confirmed_until bereits vorhanden')
            else:
                with db.engine.begin() as conn:
                    if is_mysql:
                        conn.execute(text(
                            f'ALTER TABLE {users_table} ADD COLUMN dguv_signature_confirmed_until DATETIME NULL'
                        ))
                    elif is_pg:
                        conn.execute(text(
                            f'ALTER TABLE {users_table} ADD COLUMN dguv_signature_confirmed_until TIMESTAMP NULL'
                        ))
                    else:
                        conn.execute(text(
                            f'ALTER TABLE {users_table} ADD COLUMN dguv_signature_confirmed_until DATETIME'
                        ))
                report.note_ok(f'{users_table}.dguv_signature_confirmed_until hinzugefügt')
        else:
            report.note_warn('users-Tabelle nicht gefunden')

        # 3. Tabellen-Existenz verifizieren
        critical_tables = (
            'dguv_examinations',
            'mailbox_auto_replies',
            'mailbox_auto_reply_logs',
            'protocols',
            'protocol_agenda_items',
            'meetings',
            'meeting_invites',
        )
        for t in critical_tables:
            if t in tables:
                report.note_ok(f'Tabelle {t} vorhanden')
            else:
                report.note_warn(f'Tabelle {t} fehlt')

        report.note_ok('migrate_to_3_5_2 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_5_2 fehlgeschlagen: {exc}')
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
