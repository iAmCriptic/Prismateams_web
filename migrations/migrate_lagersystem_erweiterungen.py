#!/usr/bin/env python3
"""
Datenbank-Migration: Lagersystem Erweiterungen
Erstellt die neuen Tabellen für:
- product_sets
- product_set_items
- product_documents
- saved_filters
- product_favorites
- api_tokens

WICHTIG: Die Felder sind bereits in den Modellen definiert.
Diese Migration ist nur für bestehende Datenbanken erforderlich.
Bei neuen Installationen werden die Tabellen automatisch durch db.create_all() erstellt.
"""

import os
import sys

# Füge das Projektverzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import inspect, text


def table_exists(table_name):
    """Prüft ob eine Tabelle existiert."""
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def migrate():
    """Führt die Migration aus."""
    app = create_app()
    
    with app.app_context():
        print("=" * 60)
        print("Migration: Lagersystem Erweiterungen")
        print("=" * 60)
        
        # Die Tabellen werden automatisch durch db.create_all() erstellt
        # Diese Migration dient nur zur Dokumentation und als Backup
        try:
            db.create_all()
            print("[OK] Alle Tabellen erfolgreich erstellt/aktualisiert")
            
            # Prüfe ob die Tabellen existieren
            tables_to_check = [
                'product_sets',
                'product_set_items',
                'product_documents',
                'saved_filters',
                'product_favorites',
                'api_tokens'
            ]
            
            for table in tables_to_check:
                if table_exists(table):
                    print(f"[OK] Tabelle {table} existiert")
                else:
                    print(f"[WARNUNG] Tabelle {table} wurde nicht erstellt")
            
            print("\nMigration erfolgreich abgeschlossen!")
            return True
            
        except Exception as e:
            print(f"[FEHLER] Migration fehlgeschlagen: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)

