#!/usr/bin/env python3
"""
Datenbank-Migration: Music-Modul Indizes hinzufügen
Fügt Performance-Indizes zu den Music-Tabellen hinzu für optimale Performance.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect


def index_exists(inspector, table_name, index_name):
    """Prüft ob ein Index bereits existiert."""
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def migrate():
    """Führt die Migration aus."""
    print("=" * 60)
    print("Datenbank-Migration: Music-Modul Performance-Indizes")
    print("=" * 60)
    
    app = create_app()
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            
            # Prüfe ob Tabellen existieren
            if 'music_wishes' not in inspector.get_table_names():
                print("[WARNUNG] Tabelle 'music_wishes' existiert nicht - überspringe Indizes")
            else:
                print("[INFO] Füge Indizes zu music_wishes Tabelle hinzu...")
                
                # Index auf status
                if not index_exists(inspector, 'music_wishes', 'idx_wish_status'):
                    with db.engine.begin() as conn:
                        conn.execute(text("""
                            CREATE INDEX idx_wish_status ON music_wishes(status)
                        """))
                    print("  ✓ Index idx_wish_status erstellt")
                else:
                    print("  - Index idx_wish_status existiert bereits")
                
                # Index auf provider und track_id (zusammengesetzt)
                if not index_exists(inspector, 'music_wishes', 'idx_wish_provider_track'):
                    with db.engine.begin() as conn:
                        conn.execute(text("""
                            CREATE INDEX idx_wish_provider_track ON music_wishes(provider, track_id)
                        """))
                    print("  ✓ Index idx_wish_provider_track erstellt")
                else:
                    print("  - Index idx_wish_provider_track existiert bereits")
                
                # Index auf created_at
                if not index_exists(inspector, 'music_wishes', 'idx_wish_created'):
                    with db.engine.begin() as conn:
                        conn.execute(text("""
                            CREATE INDEX idx_wish_created ON music_wishes(created_at)
                        """))
                    print("  ✓ Index idx_wish_created erstellt")
                else:
                    print("  - Index idx_wish_created existiert bereits")
                
                # Index auf updated_at
                if not index_exists(inspector, 'music_wishes', 'idx_wish_updated'):
                    with db.engine.begin() as conn:
                        conn.execute(text("""
                            CREATE INDEX idx_wish_updated ON music_wishes(updated_at)
                        """))
                    print("  ✓ Index idx_wish_updated erstellt")
                else:
                    print("  - Index idx_wish_updated existiert bereits")
            
            print()
            
            # Prüfe ob Tabellen existieren
            if 'music_queue' not in inspector.get_table_names():
                print("[WARNUNG] Tabelle 'music_queue' existiert nicht - überspringe Indizes")
            else:
                print("[INFO] Füge Indizes zu music_queue Tabelle hinzu...")
                
                # Index auf status
                if not index_exists(inspector, 'music_queue', 'idx_queue_status'):
                    with db.engine.begin() as conn:
                        conn.execute(text("""
                            CREATE INDEX idx_queue_status ON music_queue(status)
                        """))
                    print("  ✓ Index idx_queue_status erstellt")
                else:
                    print("  - Index idx_queue_status existiert bereits")
                
                # Index auf status und position (zusammengesetzt)
                if not index_exists(inspector, 'music_queue', 'idx_queue_status_position'):
                    with db.engine.begin() as conn:
                        conn.execute(text("""
                            CREATE INDEX idx_queue_status_position ON music_queue(status, position)
                        """))
                    print("  ✓ Index idx_queue_status_position erstellt")
                else:
                    print("  - Index idx_queue_status_position existiert bereits")
                
                # Index auf wish_id (für Foreign Key Lookups)
                if not index_exists(inspector, 'music_queue', 'idx_queue_wish_id'):
                    with db.engine.begin() as conn:
                        conn.execute(text("""
                            CREATE INDEX idx_queue_wish_id ON music_queue(wish_id)
                        """))
                    print("  ✓ Index idx_queue_wish_id erstellt")
                else:
                    print("  - Index idx_queue_wish_id existiert bereits")
            
            print()
            print("=" * 60)
            print("✅ Migration erfolgreich abgeschlossen!")
            print("=" * 60)
            print()
            print("Die Indizes wurden erfolgreich hinzugefügt und verbessern")
            print("die Performance des Musik-Moduls erheblich.")
            return True
            
        except Exception as e:
            print(f"\n❌ Fehler bei der Migration: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)
