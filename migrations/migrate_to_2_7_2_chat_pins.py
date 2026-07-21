#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.2

Chat-Pins für die Chat-Nav (max. 6 pro User, enforced in API):
- Tabelle chat_pins (user_id, chat_id, unique)

Aufruf:
  python migrations/migrate_to_2_7_2_chat_pins.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def ensure_chat_pins_table():
    if table_exists("chat_pins"):
        print("[OK] chat_pins existiert bereits")
        return

    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text("""
                CREATE TABLE chat_pins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(chat_id) REFERENCES chats(id),
                    UNIQUE(user_id, chat_id)
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE chat_pins (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    chat_id INTEGER NOT NULL REFERENCES chats(id),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT unique_user_chat_pin UNIQUE (user_id, chat_id)
                )
            """))
    print("[OK] chat_pins angelegt")


def main():
    app = create_app()
    with app.app_context():
        print("=== Migration 2.7.2: Chat-Pins ===")
        ensure_chat_pins_table()
        print("Fertig.")


if __name__ == "__main__":
    main()
