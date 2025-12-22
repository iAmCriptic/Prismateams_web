#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.2.1
Konsolidierte Migration für alle Versionen bis 2.2.1

Diese Migration fasst sämtliche bisherigen Einzelskripte zusammen:
- migrate_to_2.2.0.py (Basis-Migration)
- migrate_to_role_system.py
- migrate_to_music_module.py
- migrate_music_wish_count.py
- migrate_to_booking_module.py
- migrate_to_excalidraw.py

WICHTIG: Die Felder und Tabellen sind in den SQLAlchemy-Modellen bereits
definiert. Bei Neuinstallationen genügt weiterhin `db.create_all()`.
Dieses Skript richtet sich ausschließlich an bestehende Installationen.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.music import MusicProviderToken, MusicWish, MusicQueue, MusicSettings
from app.models.role import UserModuleRole
from sqlalchemy import text, inspect


def migrate_role_system():
    """Migration zum Rollensystem (aus migrate_to_role_system.py)."""
    print("\n" + "=" * 60)
    print("Migration: Rollensystem")
    print("=" * 60)
    
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    
    # Erstelle user_module_roles Tabelle
    if 'user_module_roles' not in tables:
        print("[INFO] Erstelle user_module_roles Tabelle...")
        UserModuleRole.__table__.create(db.engine, checkfirst=True)
        print("[OK] Tabelle user_module_roles erstellt")
    else:
        print("[INFO] Tabelle user_module_roles existiert bereits")
    
    # Füge has_full_access zu users hinzu
    if 'users' in tables:
        columns = {col['name'] for col in inspector.get_columns('users')}
        
        if 'has_full_access' not in columns:
            print("[INFO] Füge has_full_access Spalte zu users Tabelle hinzu...")
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN has_full_access BOOLEAN DEFAULT FALSE NOT NULL"))
            print("[OK] Spalte has_full_access hinzugefügt")
            db.session.expire_all()
        else:
            print("[INFO] Spalte has_full_access existiert bereits")
        
        # Setze has_full_access=True für alle bestehenden Benutzer
        print("[INFO] Setze has_full_access=True für alle bestehenden Benutzer...")
        with db.engine.begin() as conn:
            result = conn.execute(text("UPDATE users SET has_full_access = TRUE WHERE has_full_access = FALSE OR has_full_access IS NULL"))
            updated_count = result.rowcount
        print(f"[OK] {updated_count} Benutzer aktualisiert (has_full_access=True)")
    
    print("  ✓ Rollensystem Migration abgeschlossen")
    return True


def migrate_music_module():
    """Migration für Musikmodul (aus migrate_to_music_module.py)."""
    print("\n" + "=" * 60)
    print("Migration: Musikmodul")
    print("=" * 60)
    
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
    
    # Erstelle alle Musikmodul-Tabellen
    try:
        db.create_all()
        print("[OK] Musikmodul-Tabellen erfolgreich erstellt/aktualisiert")
    except Exception as e:
        print(f"[FEHLER] Fehler beim Erstellen der Tabellen: {e}")
        raise
    
    print("  ✓ Musikmodul Migration abgeschlossen")
    return True


def migrate_music_wish_count():
    """Migration: Fügt wish_count Spalte zu music_wishes hinzu (aus migrate_music_wish_count.py)."""
    print("\n" + "=" * 60)
    print("Migration: Musikmodul - wish_count")
    print("=" * 60)
    
    inspector = inspect(db.engine)
    if 'music_wishes' not in inspector.get_table_names():
        print("  ⚠ Tabelle 'music_wishes' existiert nicht (wird beim nächsten Start erstellt)")
        return True
    
    columns = [col['name'] for col in inspector.get_columns('music_wishes')]
    
    if 'wish_count' not in columns:
        print("Füge wish_count Spalte hinzu...")
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE music_wishes ADD COLUMN wish_count INTEGER DEFAULT 1 NOT NULL"))
        print("✓ Spalte hinzugefügt")
    else:
        print("✓ Spalte wish_count existiert bereits")
    
    # Setze alle bestehenden Einträge auf wish_count=1
    print("Setze bestehende Einträge auf wish_count=1...")
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE music_wishes SET wish_count = 1 WHERE wish_count IS NULL OR wish_count = 0"))
    print("✓ Migration abgeschlossen")
    return True


def table_exists(table_name):
    """Prüft ob eine Tabelle existiert."""
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def column_exists(table_name, column_name):
    """Prüft ob eine Spalte in einer Tabelle existiert."""
    inspector = inspect(db.engine)
    if not table_exists(table_name):
        return False
    columns = {col['name'] for col in inspector.get_columns(table_name)}
    return column_name in columns


def migrate_booking_module():
    """Migration für Buchungsmodul (aus migrate_to_booking_module.py)."""
    print("\n" + "=" * 60)
    print("Migration: Buchungsmodul")
    print("=" * 60)
    
    # Erstelle alle Buchungsmodul-Tabellen über db.create_all()
    print("Erstelle alle Buchungsmodul-Tabellen...")
    try:
        db.create_all()
        print("  ✓ Buchungsmodul-Tabellen erstellt/aktualisiert")
    except Exception as e:
        print(f"  ⚠ Fehler beim Erstellen der Tabellen: {e}")
    
    # Füge zusätzliche Spalten hinzu, falls sie fehlen
    if table_exists('booking_forms'):
        if not column_exists('booking_forms', 'secondary_logo_path'):
            print("  - Füge Spalte secondary_logo_path zu booking_forms hinzu...")
            db.session.execute(text("ALTER TABLE booking_forms ADD COLUMN secondary_logo_path VARCHAR(500)"))
            db.session.commit()
            print("    ✓ Spalte secondary_logo_path hinzugefügt")
        
        if not column_exists('booking_forms', 'pdf_application_text'):
            print("  - Füge Spalte pdf_application_text zu booking_forms hinzu...")
            db.session.execute(text("ALTER TABLE booking_forms ADD COLUMN pdf_application_text TEXT"))
            db.session.commit()
            print("    ✓ Spalte pdf_application_text hinzugefügt")
        
        if not column_exists('booking_forms', 'pdf_footer_text'):
            print("  - Füge Spalte pdf_footer_text zu booking_forms hinzu...")
            db.session.execute(text("ALTER TABLE booking_forms ADD COLUMN pdf_footer_text TEXT"))
            db.session.commit()
            print("    ✓ Spalte pdf_footer_text hinzugefügt")
    
    print("  ✓ Buchungsmodul Migration abgeschlossen")
    return True


def migrate_excalidraw():
    """Migration für Excalidraw Integration (aus migrate_to_excalidraw.py)."""
    print("\n" + "=" * 60)
    print("Migration: Excalidraw Integration")
    print("=" * 60)
    
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()
    
    # 1. Lösche alte Tabellen
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
    
    # 2. Füge neue Spalten zur canvases-Tabelle hinzu
    if 'canvases' in existing_tables:
        try:
            print("📝 Aktualisiere canvases-Tabelle...")
            
            columns = [col['name'] for col in inspector.get_columns('canvases')]
            
            if 'excalidraw_data' not in columns:
                print("   + Füge Spalte 'excalidraw_data' hinzu...")
                db.session.execute(text("ALTER TABLE canvases ADD COLUMN excalidraw_data TEXT NULL"))
                db.session.commit()
                print("   ✓ Spalte 'excalidraw_data' hinzugefügt")
            
            if 'room_id' not in columns:
                print("   + Füge Spalte 'room_id' hinzu...")
                db.session.execute(text("ALTER TABLE canvases ADD COLUMN room_id VARCHAR(100) NULL"))
                db.session.commit()
                print("   ✓ Spalte 'room_id' hinzugefügt")
            
            print("🗑️  Lösche alle alten Canvas-Daten...")
            db.session.execute(text("DELETE FROM canvases"))
            db.session.commit()
            print("   ✓ Alle alten Canvas-Daten gelöscht")
            
        except Exception as e:
            print(f"   ⚠ Fehler beim Aktualisieren der Tabelle 'canvases': {e}")
            db.session.rollback()
            raise
    
    print("  ✓ Excalidraw Migration abgeschlossen")
    return True


def migrate():
    """Führt alle Migrationen aus."""
    print("=" * 60)
    print("Datenbank-Migration: Version 2.2.1")
    print("Konsolidierte Migration für alle Versionen bis 2.2.1")
    print("=" * 60)
    
    # Führe zuerst die Basis-Migration 2.2.0 aus
    print("\n[1/6] Führe Basis-Migration 2.2.0 aus...")
    # Importiere und führe migrate_to_2.2.0.py aus
    import importlib.util
    migrate_2_2_0_path = os.path.join(os.path.dirname(__file__), 'migrate_to_2.2.0.py')
    spec = importlib.util.spec_from_file_location("migrate_to_2_2_0", migrate_2_2_0_path)
    migrate_2_2_0_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migrate_2_2_0_module)
    if not migrate_2_2_0_module.migrate():
        print("❌ Basis-Migration 2.2.0 fehlgeschlagen!")
        return False
    
    # Jetzt die zusätzlichen Migrationen
    app = create_app()
    with app.app_context():
        try:
            print("\n[2/6] Führe Rollensystem-Migration aus...")
            if not migrate_role_system():
                print("❌ Rollensystem-Migration fehlgeschlagen!")
                return False
            
            print("\n[3/6] Führe Musikmodul-Migration aus...")
            if not migrate_music_module():
                print("❌ Musikmodul-Migration fehlgeschlagen!")
                return False
            
            print("\n[4/6] Führe Musikmodul wish_count-Migration aus...")
            if not migrate_music_wish_count():
                print("❌ Musikmodul wish_count-Migration fehlgeschlagen!")
                return False
            
            print("\n[5/6] Führe Buchungsmodul-Migration aus...")
            if not migrate_booking_module():
                print("❌ Buchungsmodul-Migration fehlgeschlagen!")
                return False
            
            print("\n[6/6] Führe Excalidraw-Migration aus...")
            if not migrate_excalidraw():
                print("❌ Excalidraw-Migration fehlgeschlagen!")
                return False
            
            print()
            print("=" * 60)
            print("✅ Alle Migrationen erfolgreich abgeschlossen!")
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
