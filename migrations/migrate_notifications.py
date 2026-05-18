#!/usr/bin/env python3
"""
Datenbank-Migration: Benachrichtigungssystem

Erweitert notification_logs und legt push_delivery_logs an.

Aufruf:
  python migrations/migrate_notifications.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def column_exists(table_name, column_name):
    if not table_exists(table_name):
        return False
    columns = {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    return column_name in columns


def add_column_if_missing(table_name, column_name, ddl):
    if not table_exists(table_name):
        print(f"[INFO] Tabelle {table_name} fehlt - ueberspringe {column_name}")
        return True
    if column_exists(table_name, column_name):
        print(f"[INFO] {table_name}.{column_name} existiert bereits")
        return True
    with db.engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
    print(f"[OK] {table_name}.{column_name} hinzugefuegt")
    return True


def migrate_notification_logs():
    print("\n[STEP] notification_logs erweitern")
    add_column_if_missing("notification_logs", "notification_type", "VARCHAR(32)")
    add_column_if_missing("notification_logs", "dedup_key", "VARCHAR(255)")
    add_column_if_missing("notification_logs", "source_id", "INTEGER")
    return True


def migrate_push_delivery_logs():
    print("\n[STEP] push_delivery_logs")
    if table_exists("push_delivery_logs"):
        print("[INFO] push_delivery_logs existiert bereits")
        return True

    db_type = db.engine.dialect.name
    with db.engine.begin() as conn:
        if db_type == "sqlite":
            conn.execute(
                text(
                    """
                    CREATE TABLE push_delivery_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        subscription_id INTEGER NOT NULL,
                        dedup_key VARCHAR(255) NOT NULL,
                        sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        FOREIGN KEY (subscription_id) REFERENCES push_subscriptions(id),
                        UNIQUE (subscription_id, dedup_key)
                    )
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE push_delivery_logs (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        subscription_id INT NOT NULL,
                        dedup_key VARCHAR(255) NOT NULL,
                        sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        FOREIGN KEY (subscription_id) REFERENCES push_subscriptions(id),
                        UNIQUE KEY unique_push_delivery_per_subscription (subscription_id, dedup_key)
                    )
                    """
                )
            )
    print("[OK] push_delivery_logs erstellt")
    return True


def main():
    app = create_app()
    with app.app_context():
        migrate_notification_logs()
        migrate_push_delivery_logs()
        print("\n[FERTIG] Benachrichtigungs-Migration abgeschlossen.")


if __name__ == "__main__":
    main()
