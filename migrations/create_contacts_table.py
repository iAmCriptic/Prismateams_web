#!/usr/bin/env python3
"""
Datenbank-Migration: Erstellt die contacts Tabelle

Diese Migration erstellt die contacts Tabelle für das Kontakte-Modul.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect


def table_exists(table_name):
    """Prüft ob eine Tabelle existiert."""
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def migrate():
    """Führt die Migration aus."""
    print("=" * 60)
    print("Datenbank-Migration: Erstelle contacts Tabelle")
    print("=" * 60)
    
    app = create_app()
    with app.app_context():
        try:
            # Prüfe ob Tabelle bereits existiert
            if table_exists('contacts'):
                print("✓ Tabelle 'contacts' existiert bereits. Migration übersprungen.")
                return True
            
            # Erstelle Tabelle
            print("Erstelle Tabelle 'contacts'...")
            
            with db.engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE contacts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(255) NOT NULL,
                        email VARCHAR(255) NOT NULL,
                        phone VARCHAR(50),
                        notes TEXT,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        created_by INTEGER NOT NULL,
                        FOREIGN KEY (created_by) REFERENCES users(id)
                    )
                """))
                
                # Erstelle Indizes
                print("Erstelle Indizes...")
                conn.execute(text("CREATE INDEX idx_contacts_email ON contacts(email)"))
                conn.execute(text("CREATE INDEX idx_contacts_name ON contacts(name)"))
            print("✓ Migration erfolgreich abgeschlossen!")
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ Fehler bei der Migration: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)
