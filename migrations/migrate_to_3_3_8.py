"""
Portal 3.3.8: Composite/Hot-Column Indexes (Email, Chat, Files, ACL).
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


INDEXES = (
    # (name, table, columns)
    ('ix_email_messages_mailbox_folder_received', 'email_messages', ('mailbox_id', 'folder', 'received_at')),
    ('ix_email_messages_folder_is_read', 'email_messages', ('folder', 'is_read')),
    ('ix_email_messages_folder', 'email_messages', ('folder',)),
    ('ix_email_attachments_email_id', 'email_attachments', ('email_id',)),
    ('ix_chat_messages_chat_id', 'chat_messages', ('chat_id',)),
    ('ix_chat_messages_chat_created', 'chat_messages', ('chat_id', 'created_at')),
    ('ix_chat_members_chat_id', 'chat_members', ('chat_id',)),
    ('ix_chat_members_user_id', 'chat_members', ('user_id',)),
    ('ix_files_folder_id', 'files', ('folder_id',)),
    ('ix_files_is_current', 'files', ('is_current',)),
    ('ix_files_deleted_at', 'files', ('deleted_at',)),
    ('ix_files_folder_deleted', 'files', ('folder_id', 'deleted_at')),
    ('ix_folders_parent_id', 'folders', ('parent_id',)),
    ('ix_folders_deleted_at', 'folders', ('deleted_at',)),
    ('ix_resource_acl_type_id', 'resource_acl', ('resource_type', 'resource_id')),
    ('ix_resource_acl_grantee_user_id', 'resource_acl', ('grantee_user_id',)),
    ('ix_resource_acl_grantee_team_id', 'resource_acl', ('grantee_team_id',)),
)


def _already_exists_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            'already exists',
            'duplicate',
            'exists',
            '1061',  # MySQL duplicate key name
            '1060',
        )
    )


def _index_exists(inspector, table: str, name: str, columns: tuple[str, ...]) -> bool:
    try:
        for idx in inspector.get_indexes(table) or []:
            if idx.get('name') == name:
                return True
            cols = tuple(idx.get('column_names') or ())
            if cols == columns:
                return True
    except Exception:
        return False
    return False


def _create_index(db, report, name: str, table: str, columns: tuple[str, ...]) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    if table not in tables:
        report.note_skip(f'{table} fehlt – Index {name} übersprungen')
        return

    existing_cols = {c['name'] for c in inspector.get_columns(table)}
    missing = [c for c in columns if c not in existing_cols]
    if missing:
        report.note_skip(f'{name}: Spalten fehlen ({", ".join(missing)})')
        return

    if _index_exists(inspector, table, name, columns):
        report.note_skip(f'{name} bereits vorhanden')
        return

    dialect = db.engine.dialect.name
    cols_sql = ', '.join(f'`{c}`' if dialect != 'sqlite' else f'"{c}"' for c in columns)
    table_sql = f'`{table}`' if dialect != 'sqlite' else f'"{table}"'

    try:
        with db.engine.begin() as conn:
            if dialect == 'sqlite':
                conn.execute(
                    text(f'CREATE INDEX IF NOT EXISTS "{name}" ON {table_sql} ({cols_sql})')
                )
            else:
                conn.execute(
                    text(f'CREATE INDEX `{name}` ON {table_sql} ({cols_sql})')
                )
        report.note_ok(f'Index {name} angelegt')
    except Exception as exc:
        if _already_exists_error(exc):
            report.note_skip(f'{name} bereits vorhanden')
        else:
            report.note_warn(f'Index {name}: {exc}')


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
        # Modelle laden, damit Metadata/create_all Indizes kennt
        from app.models import chat, email, file as file_models  # noqa: F401

        try:
            db.create_all()
            report.note_ok('create_all (Indizes über Modelle wo möglich)')
        except Exception as exc:
            report.note_warn(f'create_all: {exc}')

        for name, table, columns in INDEXES:
            _create_index(db, report, name, table, columns)

        report.note_ok('migrate_to_3_3_8 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_3_8 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()
