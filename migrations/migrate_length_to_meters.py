#!/usr/bin/env python3
"""Normalisiert bestehende Produktlängen auf ein einheitliches Meter-Format."""
from __future__ import annotations

import os
import sys
from typing import List, Tuple

# Projektpfad für Flask-App verfügbar machen
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db  # type: ignore
from app.models.inventory import Product  # type: ignore
from app.utils.lengths import normalize_length_input  # type: ignore


def migrate() -> None:
    """Konvertiert alle gespeicherten Produktlängen in das "X,XX m"-Format."""
    app = create_app()

    with app.app_context():
        products: List[Product] = Product.query.all()  # type: ignore
        updated = 0
        skipped: List[Tuple[int, str]] = []

        for product in products:
            original = product.length
            if not original or not str(original).strip():
                continue

            normalized, meters = normalize_length_input(original)
            if normalized is None or meters is None:
                skipped.append((product.id, original))
                continue

            if normalized != original:
                product.length = normalized
                updated += 1
            else:
                # Stelle sicher, dass der Wert exakt dem formatierten String entspricht
                product.length = normalized

        db.session.commit()

        skipped_count = len(skipped)
        unchanged = len(products) - updated - skipped_count

        print("\n=== Migration: Produktlängen normalisieren ===")
        print(f"Gesamtprodukte geprüft : {len(products)}")
        print(f"Aktualisierte Einträge  : {updated}")
        print(f"Unveränderte Einträge   : {max(unchanged, 0)}")
        print(f"Nicht interpretierbar   : {skipped_count}")

        if skipped_count:
            print("\nNicht interpretierbare Längenangaben (max. 20 Beispiele):")
            for product_id, raw_value in skipped[:20]:
                print(f"  - Produkt #{product_id}: '{raw_value}'")
            if skipped_count > 20:
                print(f"  ... weitere {skipped_count - 20} Einträge")
        else:
            print("Alle vorhandenen Längen konnten erfolgreich normalisiert werden.")


if __name__ == '__main__':
    migrate()
