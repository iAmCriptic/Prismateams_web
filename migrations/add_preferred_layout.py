#!/usr/bin/env python3
"""
Datenbank-Migration: preferred_layout Spalte hinzufügen
Fügt die preferred_layout Spalte zur users Tabelle hinzu.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect


def migrate():
    """Führt die Migration aus."""
    print("=" * 60)
    print("Datenbank-Migration: preferred_layout Spalte")
    print("=" * 60)
    
    app = create_app()
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            
            if 'users' not in inspector.get_table_names():
                print("[WARNUNG] Tabelle 'users' existiert nicht")
                return False
            
            columns = {col['name'] for col in inspector.get_columns('users')}
            
            if 'preferred_layout' not in columns:
                print("[INFO] Füge preferred_layout Spalte zu users Tabelle hinzu...")
                with db.engine.begin() as conn:
                    conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN preferred_layout VARCHAR(20) DEFAULT 'auto' NOT NULL
                    """))
                print("[OK] Spalte preferred_layout hinzugefügt")
                
                # Setze Standardwert für alle bestehenden Benutzer
                print("[INFO] Setze preferred_layout='auto' für alle bestehenden Benutzer...")
                with db.engine.begin() as conn:
                    result = conn.execute(text("""
                        UPDATE users 
                        SET preferred_layout = 'auto' 
                        WHERE preferred_layout IS NULL
                    """))
                    updated_count = result.rowcount
                print(f"[OK] {updated_count} Benutzer aktualisiert")
            else:
                print("[INFO] Spalte preferred_layout existiert bereits")
            
            print()
            print("=" * 60)
            print("✅ Migration erfolgreich abgeschlossen!")
            print("=" * 60)
            return True
            
        except Exception as e:
            print(f"\n❌ Fehler bei der Migration: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)
