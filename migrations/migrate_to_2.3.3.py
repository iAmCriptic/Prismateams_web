#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.3.3
Konsolidierte Migration für alle Versionen bis 2.3.3

Diese Migration fasst sämtliche bisherigen Einzelskripte zusammen:
- migrate_to_2.3.0.py (Rollensystem, Musikmodul, preferred_layout, email_attachments, Excalidraw, etc.)
- add_guest_accounts.py (Gast-Account-Felder und GuestShareAccess-Tabelle)

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
from app.models.email import EmailMessage
from app.models.guest import GuestShareAccess
from sqlalchemy import text, inspect


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


def index_exists(inspector, table_name, index_name):
    """Prüft ob ein Index bereits existiert."""
    if table_name not in inspector.get_table_names():
        return False
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def migrate_role_system():
    """Migration zum Rollensystem (aus migrate_to_2.2.1.py)."""
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
    """Migration für Musikmodul (aus migrate_to_2.2.1.py)."""
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
    """Migration: Fügt wish_count Spalte zu music_wishes hinzu (aus migrate_to_2.2.1.py)."""
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


def migrate_music_indexes():
    """Migration: Fügt Performance-Indizes zu Music-Tabellen hinzu (aus add_music_indexes.py)."""
    print("\n" + "=" * 60)
    print("Migration: Music-Modul Performance-Indizes")
    print("=" * 60)
    
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
    
    print("  ✓ Music-Modul Indizes Migration abgeschlossen")
    return True


def migrate_preferred_layout():
    """Migration: Fügt preferred_layout Spalte zur users Tabelle hinzu (aus add_preferred_layout.py)."""
    print("\n" + "=" * 60)
    print("Migration: preferred_layout Spalte")
    print("=" * 60)
    
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
    
    print("  ✓ preferred_layout Migration abgeschlossen")
    return True


def migrate_email_attachments_filename():
    """Migration: Erweitert filename-Feld in email_attachments (aus fix_email_attachments_filename.py)."""
    print("\n" + "=" * 60)
    print("Migration: email_attachments filename-Feld Erweiterung")
    print("=" * 60)
    
    inspector = inspect(db.engine)
    
    # Prüfe, ob die Tabelle existiert
    if 'email_attachments' not in inspector.get_table_names():
        print("Tabelle 'email_attachments' existiert nicht. Migration übersprungen.")
        return True
    
    # Prüfe die aktuelle Feldgröße
    result = db.session.execute(text("""
        SELECT CHARACTER_MAXIMUM_LENGTH 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_SCHEMA = DATABASE() 
        AND TABLE_NAME = 'email_attachments' 
        AND COLUMN_NAME = 'filename'
    """))
    current_length = result.fetchone()
    
    if current_length:
        current_length = current_length[0]
        print(f"Aktuelle Feldgröße: {current_length} Zeichen")
        
        if current_length and current_length >= 500:
            print("Feld ist bereits ausreichend groß (>= 500 Zeichen). Migration nicht erforderlich.")
            return True
    
    # Erweitere das Feld auf VARCHAR(500)
    print("Erweitere filename-Feld auf VARCHAR(500)...")
    with db.engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE email_attachments 
            MODIFY filename VARCHAR(500) NOT NULL
        """))
    print("✓ Feld erfolgreich auf VARCHAR(500) erweitert")
    
    print("  ✓ email_attachments filename Migration abgeschlossen")
    return True


def migrate_mark_sent_emails_as_read():
    """Migration: Markiert alle E-Mails im Sent-Ordner als gelesen (aus mark_sent_emails_as_read.py)."""
    print("\n" + "=" * 60)
    print("Migration: Markiere E-Mails im Sent-Ordner als gelesen")
    print("=" * 60)
    
    # Finde alle E-Mails im "Sent"-Ordner (auch "Sent Messages")
    sent_folders = ['Sent', 'Sent Messages']
    
    total_updated = 0
    for folder_name in sent_folders:
        emails = EmailMessage.query.filter_by(folder=folder_name).filter_by(is_read=False).all()
        
        count = len(emails)
        if count > 0:
            print(f"Markiere {count} E-Mails im Ordner '{folder_name}' als gelesen...")
            
            for email in emails:
                email.is_read = True
                email.is_sent = True  # Stelle auch sicher, dass is_sent korrekt ist
            
            db.session.commit()
            total_updated += count
            print(f"✅ {count} E-Mails im Ordner '{folder_name}' wurden als gelesen markiert.")
        else:
            print(f"Keine ungelesenen E-Mails im Ordner '{folder_name}' gefunden.")
    
    if total_updated > 0:
        print(f"✅ Migration erfolgreich: {total_updated} E-Mails wurden als gelesen markiert.")
    else:
        print("✅ Migration erfolgreich: Keine E-Mails zu aktualisieren.")
    
    print("  ✓ Sent-E-Mails Migration abgeschlossen")
    return True


def migrate_booking_module():
    """Migration für Buchungsmodul (aus migrate_to_2.2.1.py)."""
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
    """Migration für Excalidraw Integration (aus migrate_to_2.2.1.py)."""
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


def migrate_guest_account_fields():
    """Fügt Gast-Account-Felder zum User-Modell hinzu (aus add_guest_accounts.py)."""
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
    """Erstellt die GuestShareAccess-Tabelle (aus add_guest_accounts.py)."""
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
    print("Datenbank-Migration: Version 2.3.3")
    print("Konsolidierte Migration für alle Versionen bis 2.3.3")
    print("=" * 60)
    
    app = create_app()
    with app.app_context():
        try:
            print("\n[1/12] Führe Rollensystem-Migration aus...")
            if not migrate_role_system():
                print("❌ Rollensystem-Migration fehlgeschlagen!")
                return False
            
            print("\n[2/12] Führe Musikmodul-Migration aus...")
            if not migrate_music_module():
                print("❌ Musikmodul-Migration fehlgeschlagen!")
                return False
            
            print("\n[3/12] Führe Musikmodul wish_count-Migration aus...")
            if not migrate_music_wish_count():
                print("❌ Musikmodul wish_count-Migration fehlgeschlagen!")
                return False
            
            print("\n[4/12] Führe Music-Modul Indizes-Migration aus...")
            if not migrate_music_indexes():
                print("❌ Music-Modul Indizes-Migration fehlgeschlagen!")
                return False
            
            print("\n[5/12] Führe preferred_layout-Migration aus...")
            if not migrate_preferred_layout():
                print("❌ preferred_layout-Migration fehlgeschlagen!")
                return False
            
            print("\n[6/12] Führe email_attachments filename-Migration aus...")
            if not migrate_email_attachments_filename():
                print("❌ email_attachments filename-Migration fehlgeschlagen!")
                return False
            
            print("\n[7/12] Führe Sent-E-Mails-Migration aus...")
            if not migrate_mark_sent_emails_as_read():
                print("❌ Sent-E-Mails-Migration fehlgeschlagen!")
                return False
            
            print("\n[8/12] Führe Buchungsmodul-Migration aus...")
            if not migrate_booking_module():
                print("❌ Buchungsmodul-Migration fehlgeschlagen!")
                return False
            
            print("\n[9/12] Führe Excalidraw-Migration aus...")
            if not migrate_excalidraw():
                print("❌ Excalidraw-Migration fehlgeschlagen!")
                return False
            
            print("\n[10/12] Führe Gast-Account-Felder-Migration aus...")
            if not migrate_guest_account_fields():
                print("❌ Gast-Account-Felder-Migration fehlgeschlagen!")
                return False
            
            print("\n[11/12] Führe GuestShareAccess-Tabelle-Migration aus...")
            if not migrate_guest_share_access_table():
                print("❌ GuestShareAccess-Tabelle-Migration fehlgeschlagen!")
                return False
            
            print()
            print("=" * 60)
            print("✅ Alle Migrationen erfolgreich abgeschlossen!")
            print("=" * 60)
            print()
            print("Die Datenbank wurde erfolgreich auf Version 2.3.3 aktualisiert.")
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
