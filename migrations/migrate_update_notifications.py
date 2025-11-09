#!/usr/bin/env python3
"""
Datenbank-Migration: Update-Benachrichtigungen
Fügt das Feld show_update_notifications zur users-Tabelle hinzu.

Dieses Feld ermöglicht es Administratoren, Update-Benachrichtigungen zu deaktivieren.
"""

import os
import sys

# Füge das Projektverzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect


def migrate():
    """Führt die Migration aus."""
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        inspector = inspect(db.engine)
        
        # Prüfe ob die Tabelle existiert
        if 'users' not in inspector.get_table_names():
            print("❌ Tabelle 'users' existiert nicht. Migration übersprungen.")
            return
        
        # Prüfe ob das Feld bereits existiert
        columns = [col['name'] for col in inspector.get_columns('users')]
        
        if 'show_update_notifications' in columns:
            print("✅ Feld 'show_update_notifications' existiert bereits in 'users'.")
            return
        
        print("\n🔄 Füge Feld 'show_update_notifications' zu 'users' hinzu...")
        
        try:
            # Prüfe Datenbanktyp für SQLite-Kompatibilität
            db_type = db.engine.dialect.name
            
            if db_type == 'sqlite':
                # SQLite unterstützt keine NOT NULL mit DEFAULT in ALTER TABLE
                db.session.execute(text("""
                    ALTER TABLE users 
                    ADD COLUMN show_update_notifications BOOLEAN DEFAULT 1
                """))
                db.session.commit()
                print("✅ Feld 'show_update_notifications' erfolgreich hinzugefügt (SQLite).")
            else:
                # MySQL/PostgreSQL
                db.session.execute(text("""
                    ALTER TABLE users 
                    ADD COLUMN show_update_notifications BOOLEAN DEFAULT TRUE NOT NULL
                """))
                db.session.commit()
                print("✅ Feld 'show_update_notifications' erfolgreich hinzugefügt.")
            
            # Setze Standardwert für alle bestehenden Benutzer (falls NULL)
            if db_type == 'sqlite':
                db.session.execute(text("""
                    UPDATE users 
                    SET show_update_notifications = 1 
                    WHERE show_update_notifications IS NULL
                """))
            else:
                db.session.execute(text("""
                    UPDATE users 
                    SET show_update_notifications = TRUE 
                    WHERE show_update_notifications IS NULL
                """))
            db.session.commit()
            print("✅ Standardwerte für bestehende Benutzer gesetzt.")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Fehler beim Hinzufügen des Feldes: {e}")
            raise


if __name__ == '__main__':
    print("Migration: Update-Benachrichtigungen")
    print("=" * 50)
    migrate()
    print("\n✅ Migration abgeschlossen!")

