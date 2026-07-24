#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.12

Booking: E-Mail-Nachrichten-Thread pro Anfrage
- booking_request_messages

Aufruf:
  python migrations/migrate_to_2_7_12_booking_messages.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def main():
    app = create_app()
    with app.app_context():
        print("=== Migration 2.7.12: booking_request_messages ===")
        if table_exists("booking_request_messages"):
            print("[OK] Tabelle booking_request_messages existiert bereits")
            print("Fertig.")
            return

        if not table_exists("booking_requests"):
            print("[WARN] Tabelle booking_requests fehlt")
            return

        dialect = db.engine.dialect.name
        if dialect == "sqlite":
            ddl = """
            CREATE TABLE booking_request_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                direction VARCHAR(20) NOT NULL,
                subject VARCHAR(500),
                body_text TEXT,
                body_html TEXT,
                from_email VARCHAR(255),
                to_email VARCHAR(255),
                message_id VARCHAR(500),
                in_reply_to VARCHAR(500),
                is_read BOOLEAN NOT NULL DEFAULT 1,
                created_by INTEGER,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(request_id) REFERENCES booking_requests(id),
                FOREIGN KEY(created_by) REFERENCES users(id)
            )
            """
        else:
            ddl = """
            CREATE TABLE booking_request_messages (
                id INT AUTO_INCREMENT PRIMARY KEY,
                request_id INT NOT NULL,
                direction VARCHAR(20) NOT NULL,
                subject VARCHAR(500) NULL,
                body_text TEXT NULL,
                body_html TEXT NULL,
                from_email VARCHAR(255) NULL,
                to_email VARCHAR(255) NULL,
                message_id VARCHAR(500) NULL,
                in_reply_to VARCHAR(500) NULL,
                is_read TINYINT(1) NOT NULL DEFAULT 1,
                created_by INT NULL,
                created_at DATETIME NOT NULL,
                CONSTRAINT fk_brm_request FOREIGN KEY (request_id) REFERENCES booking_requests(id),
                CONSTRAINT fk_brm_user FOREIGN KEY (created_by) REFERENCES users(id),
                UNIQUE KEY uq_brm_message_id (message_id),
                KEY ix_brm_request_id (request_id),
                KEY ix_brm_message_id (message_id)
            )
            """

        with db.engine.begin() as conn:
            conn.execute(text(ddl))
            if dialect == "sqlite":
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_brm_message_id "
                    "ON booking_request_messages(message_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_brm_request_id "
                    "ON booking_request_messages(request_id)"
                ))

        print("[OK] Tabelle booking_request_messages erstellt")
        print("Fertig.")


if __name__ == "__main__":
    main()
