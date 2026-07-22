#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.7.4

Inventar Phase B/C:
- Tabellen checkouts + checkout_items
- Datenübernahme aus borrow_transactions
- Produktfelder: Gewicht, Abmessungen, Preise, DGUV, Barcode, Schadenfoto

Aufruf:
  python migrations/migrate_to_2_7_4_inventory_checkouts.py
"""

import os
import sys
from collections import OrderedDict
from datetime import datetime

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


def ensure_checkouts_tables():
    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        if not table_exists("checkouts"):
            if dialect == "sqlite":
                conn.execute(text("""
                    CREATE TABLE checkouts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        checkout_number VARCHAR(50) NOT NULL UNIQUE,
                        event_name VARCHAR(255) NOT NULL,
                        borrower_name VARCHAR(255) NOT NULL,
                        borrower_id INTEGER,
                        start_date DATETIME NOT NULL,
                        end_date DATETIME NOT NULL,
                        status VARCHAR(30) NOT NULL DEFAULT 'active',
                        created_by INTEGER NOT NULL,
                        qr_code_data VARCHAR(255),
                        legacy_borrow_group_id VARCHAR(50),
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME,
                        FOREIGN KEY(borrower_id) REFERENCES users(id),
                        FOREIGN KEY(created_by) REFERENCES users(id)
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE checkouts (
                        id SERIAL PRIMARY KEY,
                        checkout_number VARCHAR(50) NOT NULL UNIQUE,
                        event_name VARCHAR(255) NOT NULL,
                        borrower_name VARCHAR(255) NOT NULL,
                        borrower_id INTEGER REFERENCES users(id),
                        start_date TIMESTAMP NOT NULL,
                        end_date TIMESTAMP NOT NULL,
                        status VARCHAR(30) NOT NULL DEFAULT 'active',
                        created_by INTEGER NOT NULL REFERENCES users(id),
                        qr_code_data VARCHAR(255),
                        legacy_borrow_group_id VARCHAR(50),
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP
                    )
                """))
            print("[OK] checkouts erstellt")
        else:
            print("[OK] checkouts existiert bereits")

        if not table_exists("checkout_items"):
            if dialect == "sqlite":
                conn.execute(text("""
                    CREATE TABLE checkout_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        checkout_id INTEGER NOT NULL,
                        product_id INTEGER NOT NULL,
                        returned_at DATETIME,
                        legacy_transaction_id INTEGER,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(checkout_id) REFERENCES checkouts(id),
                        FOREIGN KEY(product_id) REFERENCES products(id)
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE checkout_items (
                        id SERIAL PRIMARY KEY,
                        checkout_id INTEGER NOT NULL REFERENCES checkouts(id),
                        product_id INTEGER NOT NULL REFERENCES products(id),
                        returned_at TIMESTAMP,
                        legacy_transaction_id INTEGER,
                        created_at TIMESTAMP NOT NULL
                    )
                """))
            print("[OK] checkout_items erstellt")
        else:
            print("[OK] checkout_items existiert bereits")


def ensure_product_phase_c_columns():
    specs = [
        ("weight_kg", "weight_kg FLOAT", "weight_kg DOUBLE PRECISION"),
        ("width_cm", "width_cm FLOAT", "width_cm DOUBLE PRECISION"),
        ("height_cm", "height_cm FLOAT", "height_cm DOUBLE PRECISION"),
        ("depth_cm", "depth_cm FLOAT", "depth_cm DOUBLE PRECISION"),
        ("purchase_price", "purchase_price NUMERIC(12,2)", "purchase_price NUMERIC(12,2)"),
        ("replacement_value", "replacement_value NUMERIC(12,2)", "replacement_value NUMERIC(12,2)"),
        ("dguv_last_check", "dguv_last_check DATE", "dguv_last_check DATE"),
        ("dguv_next_check", "dguv_next_check DATE", "dguv_next_check DATE"),
        ("dguv_interval_months", "dguv_interval_months INTEGER", "dguv_interval_months INTEGER"),
        ("external_barcode", "external_barcode VARCHAR(100)", "external_barcode VARCHAR(100)"),
        ("damage_image_path", "damage_image_path VARCHAR(500)", "damage_image_path VARCHAR(500)"),
    ]
    for name, sqlite_ddl, other_ddl in specs:
        add_column_if_missing("products", name, sqlite_ddl, other_ddl)


def migrate_borrow_transactions():
    if not table_exists("borrow_transactions"):
        print("[SKIP] borrow_transactions fehlt")
        return

    from app.models.inventory import BorrowTransaction, Checkout, CheckoutItem
    from app.models.user import User

    existing_legacy = {
        row[0]
        for row in db.session.query(CheckoutItem.legacy_transaction_id)
        .filter(CheckoutItem.legacy_transaction_id.isnot(None))
        .all()
    }

    txs = BorrowTransaction.query.order_by(BorrowTransaction.id.asc()).all()
    if not txs:
        print("[OK] keine BorrowTransactions zu migrieren")
        return

    groups = OrderedDict()
    for tx in txs:
        if tx.id in existing_legacy:
            continue
        key = tx.borrow_group_id if tx.borrow_group_id else f"_single_{tx.id}"
        groups.setdefault(key, []).append(tx)

    created = 0
    for key, group_txs in groups.items():
        first = group_txs[0]
        borrower = User.query.get(first.borrower_id)
        borrower_name = borrower.full_name if borrower else f"User #{first.borrower_id}"
        end_dt = datetime.combine(first.expected_return_date, datetime.min.time())
        all_returned = all(t.status == "returned" for t in group_txs)
        any_returned = any(t.status == "returned" for t in group_txs)
        if all_returned:
            status = "completed"
        elif any_returned:
            status = "partially_returned"
        else:
            status = "active"

        checkout_number = first.borrow_group_id or first.transaction_number
        # Ensure uniqueness if already used
        if Checkout.query.filter_by(checkout_number=checkout_number).first():
            checkout_number = f"{checkout_number}-M{first.id}"

        checkout = Checkout(
            checkout_number=checkout_number,
            event_name="Migriert",
            borrower_name=borrower_name,
            borrower_id=first.borrower_id,
            start_date=first.borrow_date or datetime.utcnow(),
            end_date=end_dt,
            status=status,
            created_by=first.borrowed_by_id or first.borrower_id,
            qr_code_data=first.qr_code_data or f"CHECKOUT-{checkout_number}",
            legacy_borrow_group_id=first.borrow_group_id,
            created_at=first.created_at or datetime.utcnow(),
        )
        db.session.add(checkout)
        db.session.flush()

        for tx in group_txs:
            returned_at = None
            if tx.status == "returned":
                if tx.actual_return_date:
                    returned_at = datetime.combine(tx.actual_return_date, datetime.min.time())
                else:
                    returned_at = tx.updated_at or datetime.utcnow()
            item = CheckoutItem(
                checkout_id=checkout.id,
                product_id=tx.product_id,
                returned_at=returned_at,
                legacy_transaction_id=tx.id,
                created_at=tx.created_at or datetime.utcnow(),
            )
            db.session.add(item)
        created += 1

    db.session.commit()
    print(f"[OK] {created} Checkouts aus BorrowTransactions migriert")


def main():
    app = create_app()
    with app.app_context():
        print("=== Migration 2.7.4 Inventar Checkouts ===")
        ensure_checkouts_tables()
        ensure_product_phase_c_columns()
        migrate_borrow_transactions()
        print("=== Fertig ===")


if __name__ == "__main__":
    main()
