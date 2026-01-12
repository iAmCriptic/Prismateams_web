#!/usr/bin/env python3
"""
Datenbank-Migration: Fügt must_change_password Spalte zur users Tabelle hinzu

Diese Migration fügt die Spalte must_change_password hinzu, die verwendet wird,
um zu markieren, dass ein Benutzer sein Passwort beim ersten Login ändern muss.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect


def column_exists(table_name, column_name):
    """Prüft ob eine Spalte in einer Tabelle existiert."""
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return False
    columns = {col['name'] for col in inspector.get_columns(table_name)}
    return column_name in columns


def migrate():
    """Führt die Migration aus."""
    print("=" * 60)
    print("Datenbank-Migration: must_change_password Spalte")
    print("=" * 60)
    
    app = create_app()
    with app.app_context():
        try:
            if not column_exists('users', 'must_change_password'):
                print("[INFO] Füge must_change_password Spalte zu users Tabelle hinzu...")
                with db.engine.begin() as conn:
                    conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN must_change_password BOOLEAN DEFAULT FALSE NOT NULL
                    """))
                print("[OK] Spalte must_change_password hinzugefügt")
                
                # Setze Standardwert für alle bestehenden Benutzer
                print("[INFO] Setze must_change_password=FALSE für alle bestehenden Benutzer...")
                with db.engine.begin() as conn:
                    result = conn.execute(text("""
                        UPDATE users 
                        SET must_change_password = FALSE 
                        WHERE must_change_password IS NULL
                    """))
                    updated_count = result.rowcount
                print(f"[OK] {updated_count} Benutzer aktualisiert (must_change_password=FALSE)")
            else:
                print("[INFO] Spalte must_change_password existiert bereits")
            
            print()
            print("=" * 60)
            print("✅ Migration erfolgreich abgeschlossen!")
            print("=" * 60)
            return True
            
        except Exception as e:
            print(f"\n❌ Fehler bei der Migration: {e}")
            import traceback
            traceback.print_exc()
            db.session.rollback()
            return False


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)
