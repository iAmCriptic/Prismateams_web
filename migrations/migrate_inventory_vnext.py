#!/usr/bin/env python3
"""
Migration: Inventory V-Next

Führt die Datenbank auf das V-Next-Inventarmodell um:
- Product.item_type / min_stock / reorder_note
- InventoryItem.version
- Tabellen: product_lots, stock_movements, product_status_history, inventory_item_locks
- Backfill für bestehende Produkte (Statushistorie + Defaultwerte)
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from app import create_app, db
from app.models.inventory import Product, ProductStatusHistory


def table_exists(table_name):
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def column_exists(table_name, column_name):
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def index_exists(table_name, index_name):
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def add_column_if_missing(table_name, column_name, ddl):
    if column_exists(table_name, column_name):
        print(f"[INFO] {table_name}.{column_name} existiert bereits")
        return
    print(f"[INFO] Ergänze {table_name}.{column_name}")
    with db.engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
    print(f"[OK] {table_name}.{column_name} hinzugefügt")


def create_indexes():
    index_specs = [
        ("product_lots", "idx_product_lots_product_id", "CREATE INDEX idx_product_lots_product_id ON product_lots(product_id)"),
        ("stock_movements", "idx_stock_movements_product_id", "CREATE INDEX idx_stock_movements_product_id ON stock_movements(product_id)"),
        ("stock_movements", "idx_stock_movements_type", "CREATE INDEX idx_stock_movements_type ON stock_movements(movement_type)"),
        ("inventory_item_locks", "idx_inventory_item_locks_expires", "CREATE INDEX idx_inventory_item_locks_expires ON inventory_item_locks(expires_at)"),
        ("product_status_history", "idx_product_status_history_product_id", "CREATE INDEX idx_product_status_history_product_id ON product_status_history(product_id)"),
    ]
    for table_name, index_name, ddl in index_specs:
        if not table_exists(table_name):
            continue
        if index_exists(table_name, index_name):
            print(f"[INFO] Index {index_name} existiert bereits")
            continue
        with db.engine.begin() as conn:
            conn.execute(text(ddl))
        print(f"[OK] Index {index_name} erstellt")


def backfill_products():
    print("[INFO] Backfill für bestehende Produkte...")
    now = datetime.utcnow()

    updated = 0
    history_created = 0

    products = Product.query.all()
    for product in products:
        changed = False

        if not product.item_type:
            product.item_type = "asset"
            changed = True
        if product.min_stock is None:
            product.min_stock = 0
            changed = True
        if not product.status:
            product.status = "available"
            changed = True

        existing_history = ProductStatusHistory.query.filter_by(product_id=product.id).first()
        if not existing_history:
            db.session.add(
                ProductStatusHistory(
                    product_id=product.id,
                    old_status=None,
                    new_status=product.status,
                    reason="vnext_backfill",
                    note="Initiale Statushistorie aus V-Next-Migration",
                    changed_by=product.created_by,
                    changed_at=product.created_at or now,
                )
            )
            history_created += 1

        if changed:
            updated += 1

    db.session.commit()
    print(f"[OK] Produkte aktualisiert: {updated}")
    print(f"[OK] Historieneinträge erstellt: {history_created}")


def run():
    print("=" * 60)
    print("Inventory V-Next Migration")
    print("=" * 60)

    # Neue Spalten
    add_column_if_missing("products", "item_type", "VARCHAR(20) NOT NULL DEFAULT 'asset'")
    add_column_if_missing("products", "min_stock", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing("products", "reorder_note", "VARCHAR(255) NULL")
    add_column_if_missing("inventory_items", "version", "INTEGER NOT NULL DEFAULT 1")

    # Neue Tabellen entsprechend SQLAlchemy-Modellen
    db.create_all()
    print("[OK] V-Next-Tabellen geprüft/erstellt")

    create_indexes()
    backfill_products()

    print("=" * 60)
    print("Migration abgeschlossen")
    print("=" * 60)


if __name__ == "__main__":
    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        run()
