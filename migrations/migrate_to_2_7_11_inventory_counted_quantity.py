#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.11

Inventur: gezählte Menge (z.B. gleiche Kabel)
- inventory_items.counted_quantity

Aufruf:
  python migrations/migrate_to_2_7_11_inventory_counted_quantity.py
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
        print("=== Migration 2.7.11: Inventur counted_quantity ===")
        if not table_exists("inventory_items"):
            print("[WARN] Tabelle inventory_items fehlt")
            return
        add_column_if_missing(
            "inventory_items",
            "counted_quantity",
            "counted_quantity INTEGER",
            "counted_quantity INTEGER NULL",
        )
        print("Fertig.")


if __name__ == "__main__":
    main()
