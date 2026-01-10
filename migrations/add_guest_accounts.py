#!/usr/bin/env python3
"""
Datenbank-Migration: Gast-Accounts Feature
Fügt Gast-Account-Felder zum User-Modell und GuestShareAccess-Tabelle hinzu.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.guest import GuestShareAccess
from sqlalchemy import text, inspect


def column_exists(table_name, column_name):
    """Prüft ob eine Spalte in einer Tabelle existiert."""
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return False
    columns = {col['name'] for col in inspector.get_columns(table_name)}
    return column_name in columns


def table_exists(table_name):
    """Prüft ob eine Tabelle existiert."""
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def migrate_guest_account_fields():
    """Fügt Gast-Account-Felder zum User-Modell hinzu."""
    print("\n" + "=" * 60)
    print("Migration: Gast-Account-Felder zum User-Modell")
    print("=" * 60)
    
    inspector = inspect(db.engine)
    
    if 'users' not in inspector.get_table_names():
        print("[WARNUNG] Tabelle 'users' existiert nicht")
        return False
    
    columns = {col['name'] for col in inspector.get_columns('users')}
    
    # Füge is_guest Spalte hinzu
    if 'is_guest' not in columns:
        print("[INFO] Füge is_guest Spalte zu users Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_guest BOOLEAN DEFAULT FALSE NOT NULL"))
        print("[OK] Spalte is_guest hinzugefügt")
    else:
        print("[INFO] Spalte is_guest existiert bereits")
    
    # Füge guest_expires_at Spalte hinzu
    if 'guest_expires_at' not in columns:
        print("[INFO] Füge guest_expires_at Spalte zu users Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN guest_expires_at DATETIME NULL"))
        print("[OK] Spalte guest_expires_at hinzugefügt")
    else:
        print("[INFO] Spalte guest_expires_at existiert bereits")
    
    # Füge guest_username Spalte hinzu
    if 'guest_username' not in columns:
        print("[INFO] Füge guest_username Spalte zu users Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN guest_username VARCHAR(100) NULL"))
        print("[OK] Spalte guest_username hinzugefügt")
    else:
        print("[INFO] Spalte guest_username existiert bereits")
    
    # Setze is_guest=False für alle bestehenden Benutzer
    print("[INFO] Setze is_guest=False für alle bestehenden Benutzer...")
    with db.engine.begin() as conn:
        result = conn.execute(text("UPDATE users SET is_guest = FALSE WHERE is_guest IS NULL"))
        updated_count = result.rowcount
    print(f"[OK] {updated_count} Benutzer aktualisiert (is_guest=FALSE)")
    
    print("  ✓ Gast-Account-Felder Migration abgeschlossen")
    return True


def migrate_guest_share_access_table():
    """Erstellt die GuestShareAccess-Tabelle."""
    print("\n" + "=" * 60)
    print("Migration: GuestShareAccess Tabelle")
    print("=" * 60)
    
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    
    # Erstelle guest_share_access Tabelle
    if 'guest_share_access' not in tables:
        print("[INFO] Erstelle guest_share_access Tabelle...")
        GuestShareAccess.__table__.create(db.engine, checkfirst=True)
        print("[OK] Tabelle guest_share_access erstellt")
    else:
        print("[INFO] Tabelle guest_share_access existiert bereits")
    
    print("  ✓ GuestShareAccess Tabelle Migration abgeschlossen")
    return True


def migrate():
    """Führt alle Migrationen aus."""
    print("=" * 60)
    print("Datenbank-Migration: Gast-Accounts Feature")
    print("=" * 60)
    
    app = create_app()
    with app.app_context():
        try:
            print("\n[1/2] Führe Gast-Account-Felder-Migration aus...")
            if not migrate_guest_account_fields():
                print("❌ Gast-Account-Felder-Migration fehlgeschlagen!")
                return False
            
            print("\n[2/2] Führe GuestShareAccess-Tabelle-Migration aus...")
            if not migrate_guest_share_access_table():
                print("❌ GuestShareAccess-Tabelle-Migration fehlgeschlagen!")
                return False
            
            print()
            print("=" * 60)
            print("✅ Alle Migrationen erfolgreich abgeschlossen!")
            print("=" * 60)
            print()
            print("Die Datenbank wurde erfolgreich um Gast-Account-Features erweitert.")
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
