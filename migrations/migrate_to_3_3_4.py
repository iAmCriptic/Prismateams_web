"""
Portal 3.3.4: Kanban-Benachrichtigungseinstellungen in notification_settings.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def run(db=None, report=None):
    from sqlalchemy import inspect, text
    from sqlalchemy.schema import CreateColumn, Column

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
        from app.models.notification import NotificationSettings

        db.create_all()
        report.note_ok('create_all for kanban notifications 3.3.4')

        inspector = inspect(db.engine)
        dialect = db.engine.dialect
        table_name = NotificationSettings.__tablename__
        columns = (
            NotificationSettings.__table__.c.kanban_notifications_enabled,
            NotificationSettings.__table__.c.kanban_upload_notifications,
            NotificationSettings.__table__.c.kanban_change_notifications,
            NotificationSettings.__table__.c.kanban_checklist_notifications,
        )

        if table_name in inspector.get_table_names():
            existing = {c['name'] for c in inspector.get_columns(table_name)}
            for column in columns:
                if column.name not in existing:
                    safe = Column(
                        column.name,
                        column.type,
                        nullable=column.nullable,
                        server_default=column.server_default,
                    )
                    ddl = str(CreateColumn(safe).compile(dialect=dialect)).strip()
                    with db.engine.begin() as conn:
                        conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {ddl}'))
                    report.note_ok(f'{table_name}.{column.name} hinzugefügt')
                else:
                    report.note_skip(f'{table_name}.{column.name} existiert')

        report.note_ok('migrate_to_3_3_4 abgeschlossen')
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
