"""
Kanban 3.2.0: checklist item due/assignee, custom field categories,
card field enablement, card-local custom fields.
"""

from __future__ import annotations

import os
import sys

# Allow running standalone
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
        from app.models.kanban import (  # noqa: F401
            KanbanCardFieldEnabled,
            KanbanChecklistItem,
            KanbanCustomField,
            KanbanCustomFieldCategory,
        )

        # Ensure new tables exist
        db.create_all()
        report.note_ok('create_all for kanban 3.2.0')

        inspector = inspect(db.engine)
        dialect = db.engine.dialect

        def _add_col(table_name: str, column: Column):
            if table_name not in inspector.get_table_names():
                return
            existing = {c['name'] for c in inspector.get_columns(table_name)}
            if column.name in existing:
                report.note_skip(f'{table_name}.{column.name} existiert')
                return
            safe = Column(
                column.name,
                column.type,
                nullable=True if (not column.nullable and column.server_default is None and column.default is None) else column.nullable,
                server_default=column.server_default,
            )
            ddl = str(CreateColumn(safe).compile(dialect=dialect)).strip()
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {ddl}'))
            report.note_ok(f'{table_name}.{column.name} hinzugefügt')

        # Refresh inspector after create_all
        inspector = inspect(db.engine)

        item_table = KanbanChecklistItem.__table__
        _add_col('kanban_checklist_items', item_table.c.due_date)
        _add_col('kanban_checklist_items', item_table.c.assignee_id)

        cf_table = KanbanCustomField.__table__
        _add_col('kanban_custom_fields', cf_table.c.category_id)
        _add_col('kanban_custom_fields', cf_table.c.card_id)

        # Backfill: enable all existing board template fields on all existing cards
        with db.engine.begin() as conn:
            # Only if enabled table is empty (idempotent-ish)
            count = conn.execute(text('SELECT COUNT(*) FROM kanban_card_field_enabled')).scalar() or 0
            if count == 0:
                conn.execute(text("""
                    INSERT INTO kanban_card_field_enabled (card_id, field_id)
                    SELECT c.id, f.id
                    FROM kanban_cards c
                    JOIN kanban_lists l ON l.id = c.list_id
                    JOIN kanban_custom_fields f ON f.board_id = l.board_id
                    WHERE f.card_id IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM kanban_card_field_enabled e
                        WHERE e.card_id = c.id AND e.field_id = f.id
                    )
                """))
                report.note_ok('Bestehende Custom Fields auf allen Karten aktiviert')
            else:
                report.note_skip('kanban_card_field_enabled bereits befüllt')

        report.note_ok('migrate_to_3_2_0 abgeschlossen')
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
