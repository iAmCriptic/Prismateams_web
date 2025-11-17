#!/usr/bin/env python3
"""
Datenbank-Migration: Excalidraw Integration
Vereinfacht Canvas-Modell für Excalidraw-Integration

Diese Migration:
1. Löscht alte Tabellen: canvas_text_fields, canvas_elements
2. Fügt neue Spalten zur canvases-Tabelle hinzu: excalidraw_data, room_id

WICHTIG: Alle alten Canvas-Daten werden gelöscht (keine Migration der Daten).
"""

import os
import sys

# Projektverzeichnis zum Python-Pfad hinzufügen
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect


def migrate():
    """Führt die Migration aus."""
    app = create_app()
    
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        print("🔧 Excalidraw Integration Migration gestartet...")
        print("")
        
        # 1. Lösche alte Tabellen (wenn vorhanden)
        tables_to_drop = ['canvas_text_fields', 'canvas_elements']
        
        for table_name in tables_to_drop:
            if table_name in existing_tables:
                try:
                    print(f"🗑️  Lösche alte Tabelle: {table_name}")
                    db.session.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
                    db.session.commit()
                    print(f"   ✓ Tabelle '{table_name}' gelöscht")
                except Exception as e:
                    print(f"   ⚠ Fehler beim Löschen von '{table_name}': {e}")
                    db.session.rollback()
            else:
                print(f"   ℹ Tabelle '{table_name}' existiert nicht (übersprungen)")
        
        # 2. Füge neue Spalten zur canvases-Tabelle hinzu
        if 'canvases' in existing_tables:
            try:
                print("")
                print("📝 Aktualisiere canvases-Tabelle...")
                
                # Prüfe ob Spalten bereits existieren
                columns = [col['name'] for col in inspector.get_columns('canvases')]
                
                # Füge excalidraw_data hinzu
                if 'excalidraw_data' not in columns:
                    print("   + Füge Spalte 'excalidraw_data' hinzu...")
                    db.session.execute(text("""
                        ALTER TABLE canvases 
                        ADD COLUMN excalidraw_data TEXT NULL
                    """))
                    db.session.commit()
                    print("   ✓ Spalte 'excalidraw_data' hinzugefügt")
                else:
                    print("   ℹ Spalte 'excalidraw_data' existiert bereits")
                
                # Füge room_id hinzu
                if 'room_id' not in columns:
                    print("   + Füge Spalte 'room_id' hinzu...")
                    db.session.execute(text("""
                        ALTER TABLE canvases 
                        ADD COLUMN room_id VARCHAR(100) NULL
                    """))
                    db.session.commit()
                    print("   ✓ Spalte 'room_id' hinzugefügt")
                else:
                    print("   ℹ Spalte 'room_id' existiert bereits")
                
                # Lösche alte Canvas-Daten (keine Migration)
                print("")
                print("🗑️  Lösche alle alten Canvas-Daten...")
                db.session.execute(text("DELETE FROM canvases"))
                db.session.commit()
                print("   ✓ Alle alten Canvas-Daten gelöscht")
                
                print("")
                print("✅ Migration erfolgreich abgeschlossen!")
                
            except Exception as e:
                print(f"   ⚠ Fehler beim Aktualisieren der Tabelle 'canvases': {e}")
                db.session.rollback()
                raise
        else:
            print("   ℹ Tabelle 'canvases' existiert nicht (wird beim nächsten Start erstellt)")
            print("   ✅ Migration abgeschlossen (keine Aktion erforderlich)")
        
        print("")


if __name__ == '__main__':
    migrate()

