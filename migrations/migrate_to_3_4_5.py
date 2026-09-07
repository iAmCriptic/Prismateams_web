"""
Portal 3.4.5: Product owner fields (owner_user_id, owner_label).
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
        if 'products' not in set(inspector.get_table_names()):
            report.note_skip('Tabelle products fehlt')
            return

        cols = {c['name'] for c in inspector.get_columns('products')}
        dialect = db.engine.dialect.name
        added = []

        def _add_column(sql_mysql: str, sql_other: str, name: str):
            if name in cols:
                report.note_skip(f'products.{name} bereits vorhanden')
                return
            with db.engine.begin() as conn:
                if dialect == 'mysql':
                    conn.execute(text(sql_mysql))
                else:
                    conn.execute(text(sql_other))
            added.append(name)
            report.note_ok(f'products.{name} angelegt')

        _add_column(
            'ALTER TABLE products ADD COLUMN owner_user_id INT NULL',
            'ALTER TABLE products ADD COLUMN owner_user_id INTEGER',
            'owner_user_id',
        )
        _add_column(
            'ALTER TABLE products ADD COLUMN owner_label VARCHAR(255) NULL',
            'ALTER TABLE products ADD COLUMN owner_label VARCHAR(255)',
            'owner_label',
        )

        # Index / FK best-effort (MySQL/Postgres); SQLite ohne FK-Constraint ok
        if 'owner_user_id' in added or 'owner_user_id' in cols:
            try:
                with db.engine.begin() as conn:
                    if dialect == 'mysql':
                        conn.execute(text(
                            'CREATE INDEX IF NOT EXISTS ix_products_owner_user_id ON products (owner_user_id)'
                        ))
                    elif dialect == 'postgresql':
                        conn.execute(text(
                            'CREATE INDEX IF NOT EXISTS ix_products_owner_user_id ON products (owner_user_id)'
                        ))
            except Exception as idx_exc:
                report.note_warn(f'Index owner_user_id: {idx_exc}')

        if added:
            report.note_ok(f'migrate_to_3_4_5: {", ".join(added)}')
        else:
            report.note_skip('migrate_to_3_4_5: nichts zu tun')
        report.note_ok('migrate_to_3_4_5 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_5 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
