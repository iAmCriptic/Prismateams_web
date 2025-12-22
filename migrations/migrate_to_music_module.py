"""
Migration: Musikmodul Tabellen erstellen
Führt die Datenbank-Migration für das Musikmodul durch.
"""
import sys
import os

# Füge das Projektverzeichnis zum Python-Pfad hinzu
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app import create_app, db
from app.models.music import MusicProviderToken, MusicWish, MusicQueue, MusicSettings
from sqlalchemy import inspect, text


def create_music_tables():
    """Erstellt die Tabellen für das Musikmodul."""
    app = create_app()
    
    with app.app_context():
        try:
            # Prüfe ob Tabellen existieren
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            
            # Entferne public_token Spalte aus music_wishes, falls sie existiert
            if 'music_wishes' in tables:
                columns = {col['name'] for col in inspector.get_columns('music_wishes')}
                if 'public_token' in columns:
                    print("[INFO] Entferne public_token Spalte aus music_wishes...")
                    try:
                        with db.engine.begin() as conn:
                            conn.execute(text("ALTER TABLE music_wishes DROP COLUMN public_token"))
                        print("[OK] Spalte public_token entfernt")
                    except Exception as e:
                        print(f"[WARNUNG] Konnte Spalte public_token nicht entfernen: {e}")
            
            # Erstelle alle Tabellen
            db.create_all()
            
            print("[OK] Musikmodul-Tabellen erfolgreich erstellt/aktualisiert")
            return True
        except Exception as e:
            print(f"[FEHLER] Fehler beim Erstellen der Tabellen: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    success = create_music_tables()
    sys.exit(0 if success else 1)

