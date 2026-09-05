"""
Portal 3.3.5: ProductDocument — file_path/file_name nullable (reine Manual-Links).
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
        from app.models.inventory import ProductDocument

        db.create_all()
        report.note_ok('create_all for product documents 3.3.5')

        inspector = inspect(db.engine)
        table_name = ProductDocument.__tablename__
        if table_name not in inspector.get_table_names():
            report.note_skip(f'{table_name} fehlt – create_all sollte sie angelegt haben')
            report.note_ok('migrate_to_3_3_5 abgeschlossen')
            return

        cols = {c['name']: c for c in inspector.get_columns(table_name)}
        to_nullable = []
        for name in ('file_path', 'file_name'):
            info = cols.get(name)
            if info is None:
                report.note_warn(f'{table_name}.{name} fehlt')
                continue
            if info.get('nullable'):
                report.note_skip(f'{table_name}.{name} bereits nullable')
            else:
                to_nullable.append(name)

        if not to_nullable:
            report.note_ok('migrate_to_3_3_5 abgeschlossen')
            return

        dialect = db.engine.dialect.name

        if dialect == 'sqlite':
            from alembic.migration import MigrationContext
            from alembic.operations import Operations

            with db.engine.begin() as conn:
                ctx_mig = MigrationContext.configure(conn)
                op = Operations(ctx_mig)
                with op.batch_alter_table(table_name) as batch_op:
                    for name in to_nullable:
                        batch_op.alter_column(name, nullable=True)
                        report.note_ok(f'{table_name}.{name} → nullable (sqlite batch)')
        elif dialect == 'mysql':
            type_map = {
                'file_path': 'VARCHAR(500)',
                'file_name': 'VARCHAR(255)',
            }
            with db.engine.begin() as conn:
                for name in to_nullable:
                    conn.execute(text(
                        f'ALTER TABLE {table_name} MODIFY COLUMN {name} {type_map[name]} NULL'
                    ))
                    report.note_ok(f'{table_name}.{name} → nullable (mysql)')
        else:
            with db.engine.begin() as conn:
                for name in to_nullable:
                    conn.execute(text(
                        f'ALTER TABLE {table_name} ALTER COLUMN {name} DROP NOT NULL'
                    ))
                    report.note_ok(f'{table_name}.{name} → nullable ({dialect})')

        report.note_ok('migrate_to_3_3_5 abgeschlossen')
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
