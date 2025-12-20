#!/usr/bin/env python3
"""
Migration: Fügt wish_count Spalte zu music_wishes Tabelle hinzu
"""
import sys
import os

# Füge Projekt-Root zum Python-Pfad hinzu
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app import create_app, db
from app.models.music import MusicWish

def migrate():
    """Führt die Migration aus."""
    app = create_app()
    
    with app.app_context():
        try:
            # Prüfe ob Spalte bereits existiert
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('music_wishes')]
            
            if 'wish_count' not in columns:
                print("Füge wish_count Spalte hinzu...")
                with db.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE music_wishes ADD COLUMN wish_count INTEGER DEFAULT 1 NOT NULL"))
                print("✓ Spalte hinzugefügt")
            else:
                print("✓ Spalte wish_count existiert bereits")
            
            # Setze alle bestehenden Einträge auf wish_count=1 (falls NULL oder 0)
            print("Setze bestehende Einträge auf wish_count=1...")
            with db.engine.begin() as conn:
                conn.execute(text("UPDATE music_wishes SET wish_count = 1 WHERE wish_count IS NULL OR wish_count = 0"))
            print("✓ Migration abgeschlossen")
            
        except Exception as e:
            print(f"✗ Fehler bei Migration: {e}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    migrate()

