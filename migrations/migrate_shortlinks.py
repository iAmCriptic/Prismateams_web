#!/usr/bin/env python3
"""
Migration: Shortlinks Tabelle

Erstellt `short_links` fuer das URL-Shortener-Modul.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from app import create_app, db


def table_exists(table_name):
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def create_short_links_table():
    if table_exists("short_links"):
        print("[INFO] short_links existiert bereits")
        return

    print("[INFO] Erstelle Tabelle short_links")
    with db.engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE short_links (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                created_by INTEGER NOT NULL,
                target_url VARCHAR(2048) NOT NULL,
                slug VARCHAR(64) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                password_hash VARCHAR(255) NULL,
                expires_at DATETIME NULL,
                max_clicks INTEGER NULL,
                click_count INTEGER NOT NULL DEFAULT 0,
                last_clicked_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                CONSTRAINT fk_short_links_user FOREIGN KEY (created_by) REFERENCES users(id),
                CONSTRAINT uq_short_links_slug UNIQUE (slug)
            )
        """))
    print("[OK] short_links erstellt")


def run():
    print("=" * 60)
    print("Migration Shortlinks")
    print("=" * 60)
    create_short_links_table()
    print("=" * 60)
    print("Migration abgeschlossen")
    print("=" * 60)


if __name__ == "__main__":
    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        run()
