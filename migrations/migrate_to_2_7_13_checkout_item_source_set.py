#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.13

Checkout-Items: Herkunfts-Set (source_set_id)
- checkout_items.source_set_id → product_sets.id (nullable)

Aufruf:
  python migrations/migrate_to_2_7_13_checkout_item_source_set.py
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


def add_column_if_missing(table_name, column_name, ddl_sqlite, ddl_other):
    if column_exists(table_name, column_name):
        print(f"[OK] {table_name}.{column_name} existiert bereits")
        return
    dialect = db.engine.dialect.name
    ddl = ddl_sqlite if dialect == "sqlite" else ddl_other
    with db.engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))
    print(f"[OK] {table_name}.{column_name} hinzugefügt")


def main():
    app = create_app()
    with app.app_context():
        print("=== Migration 2.7.13: checkout_items.source_set_id ===")
        if not table_exists("checkout_items"):
            print("[WARN] Tabelle checkout_items fehlt")
            return
        add_column_if_missing(
            "checkout_items",
            "source_set_id",
            "source_set_id INTEGER",
            "source_set_id INTEGER NULL",
        )
        print("=== Migration 2.7.13 abgeschlossen ===")


if __name__ == "__main__":
    main()
