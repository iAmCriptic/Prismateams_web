#!/usr/bin/env python3
"""
Datenbank-Migration: Benachrichtigungszentrale mit Kategorien
Fügt Kategorien zu Benachrichtigungen hinzu und erweitert das Benachrichtigungssystem

Diese Migration fügt folgende Änderungen hinzu:
- category Spalte zu notification_logs (Chat, Dateien, E-Mails, Kalender, System)
- Index auf category und is_read für bessere Performance
- Setzt Standard-Kategorien für bestehende Benachrichtigungen basierend auf URL/Inhalt

WICHTIG: Die Felder sind in den SQLAlchemy-Modellen bereits definiert.
Bei Neuinstallationen genügt weiterhin `db.create_all()`.
Dieses Skript richtet sich ausschließlich an bestehende Installationen.
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


def migrate_notification_logs_category():
    """Migration: Fügt category Spalte zu notification_logs hinzu."""
    print("\n" + "=" * 60)
    print("Migration: notification_logs - category Spalte")
    print("=" * 60)
    
    inspector = inspect(db.engine)
    
    if 'notification_logs' not in inspector.get_table_names():
        print("[WARNUNG] Tabelle 'notification_logs' existiert nicht")
        print("  ⚠ Tabelle wird beim nächsten Start erstellt")
        return True
    
    columns = {col['name'] for col in inspector.get_columns('notification_logs')}
    
    if 'category' not in columns:
        print("[INFO] Füge category Spalte zu notification_logs Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(text("""
                ALTER TABLE notification_logs 
                ADD COLUMN category VARCHAR(50) DEFAULT 'System' NOT NULL
            """))
        print("[OK] Spalte category hinzugefügt")
        
        # Setze Kategorien für bestehende Benachrichtigungen basierend auf URL
        print("[INFO] Setze Kategorien für bestehende Benachrichtigungen...")
        with db.engine.begin() as conn:
            # Chat-Benachrichtigungen
            conn.execute(text("""
                UPDATE notification_logs 
                SET category = 'Chat' 
                WHERE url LIKE '/chat/%' OR url LIKE '%chat%'
            """))
            
            # Dateien-Benachrichtigungen
            conn.execute(text("""
                UPDATE notification_logs 
                SET category = 'Dateien' 
                WHERE url LIKE '/files/%' OR url LIKE '%file%' OR title LIKE '%Datei%'
            """))
            
            # E-Mail-Benachrichtigungen
            conn.execute(text("""
                UPDATE notification_logs 
                SET category = 'E-Mails' 
                WHERE url LIKE '/email/%' OR url = '/email/' OR title LIKE '%E-Mail%' OR title = 'E-Mail'
            """))
            
            # Kalender-Benachrichtigungen
            conn.execute(text("""
                UPDATE notification_logs 
                SET category = 'Kalender' 
                WHERE url LIKE '/calendar/%' OR title LIKE '%Termin%' OR title LIKE '%Event%'
            """))
            
            # System-Benachrichtigungen (Standard, bleibt für alle anderen)
            conn.execute(text("""
                UPDATE notification_logs 
                SET category = 'System' 
                WHERE category IS NULL OR category = ''
            """))
        
        print("[OK] Kategorien für bestehende Benachrichtigungen gesetzt")
    else:
        print("[INFO] Spalte category existiert bereits")
    
    print("  ✓ notification_logs category Migration abgeschlossen")
    return True


def migrate_notification_logs_indexes():
    """Migration: Fügt Performance-Indizes zu notification_logs hinzu."""
    print("\n" + "=" * 60)
    print("Migration: notification_logs Performance-Indizes")
    print("=" * 60)
    
    inspector = inspect(db.engine)
    
    if 'notification_logs' not in inspector.get_table_names():
        print("[WARNUNG] Tabelle 'notification_logs' existiert nicht - überspringe Indizes")
        return True
    
    # Index auf category
    if not index_exists(inspector, 'notification_logs', 'idx_notification_category'):
        print("[INFO] Erstelle Index idx_notification_category...")
        with db.engine.begin() as conn:
            conn.execute(text("""
                CREATE INDEX idx_notification_category ON notification_logs(category)
            """))
        print("  ✓ Index idx_notification_category erstellt")
    else:
        print("  - Index idx_notification_category existiert bereits")
    
    # Index auf is_read
    if not index_exists(inspector, 'notification_logs', 'idx_notification_is_read'):
        print("[INFO] Erstelle Index idx_notification_is_read...")
        with db.engine.begin() as conn:
            conn.execute(text("""
                CREATE INDEX idx_notification_is_read ON notification_logs(is_read)
            """))
        print("  ✓ Index idx_notification_is_read erstellt")
    else:
        print("  - Index idx_notification_is_read existiert bereits")
    
    # Zusammengesetzter Index auf user_id, category und is_read (für häufige Abfragen)
    if not index_exists(inspector, 'notification_logs', 'idx_notification_user_category_read'):
        print("[INFO] Erstelle Index idx_notification_user_category_read...")
        with db.engine.begin() as conn:
            conn.execute(text("""
                CREATE INDEX idx_notification_user_category_read 
                ON notification_logs(user_id, category, is_read)
            """))
        print("  ✓ Index idx_notification_user_category_read erstellt")
    else:
        print("  - Index idx_notification_user_category_read existiert bereits")
    
    # Index auf sent_at für Sortierung
    if not index_exists(inspector, 'notification_logs', 'idx_notification_sent_at'):
        print("[INFO] Erstelle Index idx_notification_sent_at...")
        with db.engine.begin() as conn:
            conn.execute(text("""
                CREATE INDEX idx_notification_sent_at ON notification_logs(sent_at DESC)
            """))
        print("  ✓ Index idx_notification_sent_at erstellt")
    else:
        print("  - Index idx_notification_sent_at existiert bereits")
    
    print("  ✓ notification_logs Indizes Migration abgeschlossen")
    return True


def migrate_push_subscriptions_device_id():
    """Migration: Fügt device_id Spalte zu push_subscriptions hinzu (optional, für bessere Geräteverfolgung)."""
    print("\n" + "=" * 60)
    print("Migration: push_subscriptions - device_id Spalte (optional)")
    print("=" * 60)
    
    inspector = inspect(db.engine)
    
    if 'push_subscriptions' not in inspector.get_table_names():
        print("[WARNUNG] Tabelle 'push_subscriptions' existiert nicht")
        print("  ⚠ Tabelle wird beim nächsten Start erstellt")
        return True
    
    columns = {col['name'] for col in inspector.get_columns('push_subscriptions')}
    
    if 'device_id' not in columns:
        print("[INFO] Füge device_id Spalte zu push_subscriptions Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(text("""
                ALTER TABLE push_subscriptions 
                ADD COLUMN device_id VARCHAR(255) NULL
            """))
        print("[OK] Spalte device_id hinzugefügt")
        
        # Generiere device_id aus endpoint (erste 50 Zeichen des Endpoints als Hash)
        print("[INFO] Generiere device_id aus endpoint für bestehende Subscriptions...")
        with db.engine.begin() as conn:
            # Verwende einen Hash des Endpoints als device_id
            # Für SQLite verwenden wir SUBSTR, für andere DBs könnte man MD5/SHA verwenden
            conn.execute(text("""
                UPDATE push_subscriptions 
                SET device_id = SUBSTR(endpoint, 1, 50)
                WHERE device_id IS NULL
            """))
        print("[OK] device_id für bestehende Subscriptions generiert")
    else:
        print("[INFO] Spalte device_id existiert bereits")
    
    print("  ✓ push_subscriptions device_id Migration abgeschlossen")
    return True


def migrate():
    """Führt alle Migrationen aus."""
    print("=" * 60)
    print("Datenbank-Migration: Benachrichtigungszentrale mit Kategorien")
    print("=" * 60)
    
    app = create_app()
    with app.app_context():
        try:
            print("\n[1/3] Führe notification_logs category-Migration aus...")
            if not migrate_notification_logs_category():
                print("❌ notification_logs category-Migration fehlgeschlagen!")
                return False
            
            print("\n[2/3] Führe notification_logs Indizes-Migration aus...")
            if not migrate_notification_logs_indexes():
                print("❌ notification_logs Indizes-Migration fehlgeschlagen!")
                return False
            
            print("\n[3/3] Führe push_subscriptions device_id-Migration aus...")
            if not migrate_push_subscriptions_device_id():
                print("❌ push_subscriptions device_id-Migration fehlgeschlagen!")
                return False
            
            print()
            print("=" * 60)
            print("✅ Alle Migrationen erfolgreich abgeschlossen!")
            print("=" * 60)
            print()
            print("Die Datenbank wurde erfolgreich für die Benachrichtigungszentrale aktualisiert.")
            print()
            print("Neue Features:")
            print("  - Kategorien für Benachrichtigungen (Chat, Dateien, E-Mails, Kalender, System)")
            print("  - Performance-Indizes für schnellere Abfragen")
            print("  - Device-ID für bessere Geräteverfolgung")
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
