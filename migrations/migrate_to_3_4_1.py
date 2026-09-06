"""
Portal 3.4.1: API-Tokens hashen (token_prefix + SHA-256 in token-Spalte).
"""

from __future__ import annotations

import hashlib
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _looks_like_hash(value: str) -> bool:
    if not value or len(value) != 64:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


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
        if 'api_tokens' not in set(inspector.get_table_names()):
            report.note_skip('Tabelle api_tokens fehlt')
            return

        cols = {c['name'] for c in inspector.get_columns('api_tokens')}
        dialect = db.engine.dialect.name

        if 'token_prefix' not in cols:
            if dialect == 'sqlite':
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE api_tokens ADD COLUMN token_prefix VARCHAR(16)'
                    ))
            elif dialect == 'mysql':
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE api_tokens ADD COLUMN token_prefix VARCHAR(16) NULL'
                    ))
                    try:
                        conn.execute(text(
                            'CREATE INDEX ix_api_tokens_token_prefix ON api_tokens (token_prefix)'
                        ))
                    except Exception:
                        pass
            else:
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE api_tokens ADD COLUMN token_prefix VARCHAR(16)'
                    ))
                    try:
                        conn.execute(text(
                            'CREATE INDEX IF NOT EXISTS ix_api_tokens_token_prefix '
                            'ON api_tokens (token_prefix)'
                        ))
                    except Exception:
                        pass
            report.note_ok('api_tokens.token_prefix angelegt')
        else:
            report.note_skip('api_tokens.token_prefix bereits vorhanden')

        from app.models.api_token import ApiToken

        migrated = 0
        skipped = 0
        for row in ApiToken.query.all():
            raw = row.token or ''
            if _looks_like_hash(raw):
                if not row.token_prefix:
                    # Prefix unbekannt bei bereits gehashten Zeilen ohne Prefix
                    skipped += 1
                else:
                    skipped += 1
                continue
            # Legacy-Klartext → Hash + Prefix
            row.token_prefix = raw[: ApiToken.PREFIX_LEN] if raw else None
            row.token = hashlib.sha256(raw.encode('utf-8')).hexdigest()
            migrated += 1

        if migrated:
            db.session.commit()
            report.note_ok(f'{migrated} API-Token(s) gehasht')
        else:
            report.note_skip('Keine Klartext-API-Tokens zu hashen')
        if skipped:
            report.note_ok(f'{skipped} bereits gehashte/übersprungene Token-Zeile(n)')

        report.note_ok('migrate_to_3_4_1 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_1 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
