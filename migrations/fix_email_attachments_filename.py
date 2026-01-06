#!/usr/bin/env python3
"""
Migration: Erweitert das filename-Feld in email_attachments von VARCHAR(255) auf VARCHAR(500)
um längere Dateinamen zu unterstützen.

Ausführen mit:
    python migrations/fix_email_attachments_filename.py
"""

import sys
import os

# Füge das Projektverzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text

def migrate():
    """Erweitert das filename-Feld in email_attachments."""
    app = create_app()
    
    with app.app_context():
        try:
            print("Starte Migration: Erweitere filename-Feld in email_attachments...")
            
            # Prüfe, ob die Tabelle existiert
            result = db.session.execute(text("SHOW TABLES LIKE 'email_attachments'"))
            if not result.fetchone():
                print("Tabelle 'email_attachments' existiert nicht. Migration übersprungen.")
                return
            
            # Prüfe die aktuelle Feldgröße
            result = db.session.execute(text(
                "SELECT CHARACTER_MAXIMUM_LENGTH "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'email_attachments' "
                "AND COLUMN_NAME = 'filename'"
            ))
            current_length = result.fetchone()
            
            if current_length:
                current_length = current_length[0]
                print(f"Aktuelle Feldgröße: {current_length} Zeichen")
                
                if current_length and current_length >= 500:
                    print("Feld ist bereits ausreichend groß (>= 500 Zeichen). Migration nicht erforderlich.")
                    return
            
            # Erweitere das Feld auf VARCHAR(500)
            print("Erweitere filename-Feld auf VARCHAR(500)...")
            db.session.execute(text(
                "ALTER TABLE email_attachments "
                "MODIFY filename VARCHAR(500) NOT NULL"
            ))
            db.session.commit()
            
            print("✓ Migration erfolgreich abgeschlossen!")
            print("  Das filename-Feld wurde auf VARCHAR(500) erweitert.")
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ Fehler bei der Migration: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    migrate()

