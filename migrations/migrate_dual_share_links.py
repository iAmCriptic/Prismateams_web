#!/usr/bin/env python3
"""
Datenbank-Migration: Dual-Link-Freigaben (public_shares)

Aufruf:
  python migrations/migrate_dual_share_links.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def migrate_public_shares_tables():
    print("\n[STEP] public_shares / share_access_logs")
    if table_exists('public_shares'):
        print("[INFO] public_shares existiert bereits")
        return True

    db_type = db.engine.dialect.name
    with db.engine.begin() as conn:
        if db_type == 'sqlite':
            conn.execute(
                text(
                    """
                    CREATE TABLE public_shares (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        resource_type VARCHAR(16) NOT NULL,
                        resource_id INTEGER NOT NULL,
                        mode VARCHAR(16) NOT NULL,
                        token VARCHAR(255) NOT NULL UNIQUE,
                        enabled BOOLEAN NOT NULL DEFAULT 1,
                        password_hash VARCHAR(255),
                        expires_at DATETIME,
                        created_by INTEGER NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (created_by) REFERENCES users(id),
                        UNIQUE (resource_type, resource_id, mode)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE share_access_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        public_share_id INTEGER NOT NULL,
                        action VARCHAR(32) NOT NULL,
                        ip_address VARCHAR(45),
                        user_agent VARCHAR(500),
                        guest_name VARCHAR(255),
                        accessed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (public_share_id) REFERENCES public_shares(id)
                    )
                    """
                )
            )
            conn.execute(text('CREATE INDEX IF NOT EXISTS idx_public_shares_token ON public_shares(token)'))
            conn.execute(
                text(
                    'CREATE INDEX IF NOT EXISTS idx_share_access_logs_share_id ON share_access_logs(public_share_id)'
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE public_shares (
                        id INTEGER AUTO_INCREMENT PRIMARY KEY,
                        resource_type VARCHAR(16) NOT NULL,
                        resource_id INTEGER NOT NULL,
                        mode VARCHAR(16) NOT NULL,
                        token VARCHAR(255) NOT NULL,
                        enabled BOOLEAN NOT NULL DEFAULT 1,
                        password_hash VARCHAR(255),
                        expires_at DATETIME,
                        created_by INTEGER NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        CONSTRAINT fk_public_shares_user FOREIGN KEY (created_by) REFERENCES users(id),
                        CONSTRAINT uq_public_share_resource_mode UNIQUE (resource_type, resource_id, mode),
                        CONSTRAINT uq_public_shares_token UNIQUE (token)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE share_access_logs (
                        id INTEGER AUTO_INCREMENT PRIMARY KEY,
                        public_share_id INTEGER NOT NULL,
                        action VARCHAR(32) NOT NULL,
                        ip_address VARCHAR(45),
                        user_agent VARCHAR(500),
                        guest_name VARCHAR(255),
                        accessed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT fk_share_access_logs_share FOREIGN KEY (public_share_id) REFERENCES public_shares(id)
                    )
                    """
                )
            )
            conn.execute(text('CREATE INDEX idx_public_shares_token ON public_shares(token)'))
            conn.execute(text('CREATE INDEX idx_share_access_logs_share_id ON share_access_logs(public_share_id)'))

    print("[OK] public_shares und share_access_logs erstellt")
    return True


def migrate_legacy_shares():
    print("\n[STEP] Legacy-Freigaben migrieren")
    from app.models.file import File, Folder
    from app.models.public_share import PublicShare

    migrated = 0
    for file_obj in File.query.filter_by(share_enabled=True).filter(File.share_token.isnot(None)).all():
        if PublicShare.query.filter_by(resource_type='file', resource_id=file_obj.id).first():
            continue
        mode = (file_obj.share_mode or 'edit').strip().lower()
        if mode not in ('view', 'edit'):
            mode = 'edit'
        share = PublicShare(
            resource_type='file',
            resource_id=file_obj.id,
            mode=mode,
            token=file_obj.share_token,
            enabled=True,
            password_hash=file_obj.share_password_hash,
            expires_at=file_obj.share_expires_at,
            created_by=file_obj.uploaded_by,
        )
        db.session.add(share)
        migrated += 1

    for folder in Folder.query.filter_by(share_enabled=True).filter(Folder.share_token.isnot(None)).all():
        if PublicShare.query.filter_by(resource_type='folder', resource_id=folder.id).first():
            continue
        mode = (folder.share_mode or 'edit').strip().lower()
        if mode not in ('view', 'edit'):
            mode = 'edit'
        share = PublicShare(
            resource_type='folder',
            resource_id=folder.id,
            mode=mode,
            token=folder.share_token,
            enabled=True,
            password_hash=folder.share_password_hash,
            expires_at=folder.share_expires_at,
            created_by=folder.created_by,
        )
        db.session.add(share)
        migrated += 1

    db.session.commit()
    print(f"[OK] {migrated} Legacy-Freigaben migriert")
    return True


def migrate():
    print("=" * 60)
    print("Datenbank-Migration: Dual-Link-Freigaben")
    print("=" * 60)

    app = create_app(os.getenv('FLASK_ENV', 'development'))
    with app.app_context():
        try:
            db.create_all()
            if not migrate_public_shares_tables():
                return False
            if not migrate_legacy_shares():
                return False
            print("\n" + "=" * 60)
            print("Migration erfolgreich abgeschlossen")
            print("=" * 60)
            return True
        except Exception as exc:
            print(f"[FEHLER] Migration fehlgeschlagen: {exc}")
            db.session.rollback()
            return False


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)
