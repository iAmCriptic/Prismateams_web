"""
Portal 3.4.17: BookingPersonalEvent apply_token and apply_enabled columns.
"""

from __future__ import annotations

import os
import secrets
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
        tables = set(inspector.get_table_names())
        dialect = db.engine.dialect.name
        is_mysql = dialect in ('mysql', 'mariadb')
        is_pg = dialect == 'postgresql'

        table = 'booking_personal_events'
        if table in tables:
            cols = {c['name'] for c in inspector.get_columns(table)}

            # 1. apply_token
            if 'apply_token' in cols:
                report.note_skip(f'{table}.apply_token bereits vorhanden')
            else:
                with db.engine.begin() as conn:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN apply_token VARCHAR(64) NULL"
                    ))
                    try:
                        conn.execute(text(
                            f"CREATE UNIQUE INDEX ix_booking_personal_events_apply_token ON {table} (apply_token)"
                        ))
                    except Exception as idx_err:
                        report.note_warn(f"Index ix_booking_personal_events_apply_token: {idx_err}")
                report.note_ok(f'{table}.apply_token angelegt')

            # 2. apply_enabled
            if 'apply_enabled' in cols:
                report.note_skip(f'{table}.apply_enabled bereits vorhanden')
            else:
                bool_type = "TINYINT(1) NOT NULL DEFAULT 1" if is_mysql else ("BOOLEAN NOT NULL DEFAULT TRUE" if is_pg else "BOOLEAN NOT NULL DEFAULT 1")
                with db.engine.begin() as conn:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN apply_enabled {bool_type}"
                    ))
                report.note_ok(f'{table}.apply_enabled angelegt')

            # 3. Initialisiere Token für bestehende Events ohne apply_token
            with db.engine.connect() as conn:
                rows = conn.execute(text(
                    f"SELECT id FROM {table} WHERE apply_token IS NULL OR apply_token = ''"
                )).fetchall()

            if rows:
                with db.engine.begin() as conn:
                    for r in rows:
                        tok = secrets.token_urlsafe(32)
                        conn.execute(
                            text(f"UPDATE {table} SET apply_token = :token WHERE id = :id"),
                            {"token": tok, "id": r[0]}
                        )
                report.note_ok(f"{len(rows)} Event(s) mit neuem apply_token initialisiert.")
        else:
            report.note_warn(f'{table} Tabelle existiert noch nicht.')

        report.note_ok('migrate_to_3_4_17 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_17: {exc}')
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
