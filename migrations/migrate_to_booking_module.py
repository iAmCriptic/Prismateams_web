#!/usr/bin/env python3
"""
Datenbank-Migration: Buchungsmodul
Erstellt alle Tabellen für das neue Buchungsmodul.

Diese Migration erstellt folgende Tabellen:
1. booking_forms - Buchungsformulare
2. booking_form_fields - Zusätzliche Felder für Formulare
3. booking_form_images - Bilder für Buchungsseiten
4. booking_requests - Buchungsanfragen
5. booking_request_fields - Werte der zusätzlichen Felder
6. booking_request_files - Hochgeladene Dateien zu Buchungen

Zusätzlich wird das Feld booking_request_id zu calendar_events hinzugefügt.

WICHTIG: Führen Sie dieses Skript VOR dem Starten der App aus.
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
    columns = {col['name']: col for col in inspector.get_columns(table_name)}
    return column_name in columns


def create_booking_tables():
    """Erstellt alle Tabellen für das Buchungsmodul."""
    db_url = str(db.engine.url)
    is_sqlite = 'sqlite' in db_url.lower()
    is_mysql = 'mysql' in db_url.lower() or 'mariadb' in db_url.lower()
    is_postgres = 'postgresql' in db_url.lower() or 'postgres' in db_url.lower()
    
    print("=" * 60)
    print("Migration: Buchungsmodul")
    print("=" * 60)
    print(f"Datenbank-Typ: {'SQLite' if is_sqlite else 'MySQL/MariaDB' if is_mysql else 'PostgreSQL' if is_postgres else 'Unbekannt'}")
    print()
    
    with db.engine.connect() as conn:
        # 1. booking_forms Tabelle
        if not table_exists('booking_forms'):
            print("Erstelle Tabelle: booking_forms")
            if is_sqlite:
                conn.execute(text("""
                    CREATE TABLE booking_forms (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title VARCHAR(200) NOT NULL,
                        description TEXT,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        created_by INTEGER NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        archive_days INTEGER NOT NULL DEFAULT 30,
                        enable_mailbox BOOLEAN NOT NULL DEFAULT 0,
                        enable_shared_folder BOOLEAN NOT NULL DEFAULT 0,
                        FOREIGN KEY (created_by) REFERENCES users(id)
                    )
                """))
            elif is_mysql:
                conn.execute(text("""
                    CREATE TABLE booking_forms (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        title VARCHAR(200) NOT NULL,
                        description TEXT,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_by INT NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        archive_days INT NOT NULL DEFAULT 30,
                        enable_mailbox BOOLEAN NOT NULL DEFAULT FALSE,
                        enable_shared_folder BOOLEAN NOT NULL DEFAULT FALSE,
                        FOREIGN KEY (created_by) REFERENCES users(id)
                    )
                """))
            else:  # PostgreSQL
                conn.execute(text("""
                    CREATE TABLE booking_forms (
                        id SERIAL PRIMARY KEY,
                        title VARCHAR(200) NOT NULL,
                        description TEXT,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_by INTEGER NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        archive_days INTEGER NOT NULL DEFAULT 30,
                        enable_mailbox BOOLEAN NOT NULL DEFAULT FALSE,
                        enable_shared_folder BOOLEAN NOT NULL DEFAULT FALSE,
                        FOREIGN KEY (created_by) REFERENCES users(id)
                    )
                """))
            conn.commit()
            print("  ✓ Tabelle booking_forms erstellt")
        else:
            print("  ✓ Tabelle booking_forms existiert bereits")
        
        # 2. booking_form_fields Tabelle
        if not table_exists('booking_form_fields'):
            print("Erstelle Tabelle: booking_form_fields")
            if is_sqlite:
                conn.execute(text("""
                    CREATE TABLE booking_form_fields (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        form_id INTEGER NOT NULL,
                        field_type VARCHAR(20) NOT NULL,
                        field_name VARCHAR(100) NOT NULL,
                        field_label VARCHAR(200) NOT NULL,
                        is_required BOOLEAN NOT NULL DEFAULT 0,
                        field_order INTEGER NOT NULL DEFAULT 0,
                        field_options TEXT,
                        placeholder VARCHAR(255),
                        FOREIGN KEY (form_id) REFERENCES booking_forms(id) ON DELETE CASCADE
                    )
                """))
            elif is_mysql:
                conn.execute(text("""
                    CREATE TABLE booking_form_fields (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        form_id INT NOT NULL,
                        field_type VARCHAR(20) NOT NULL,
                        field_name VARCHAR(100) NOT NULL,
                        field_label VARCHAR(200) NOT NULL,
                        is_required BOOLEAN NOT NULL DEFAULT FALSE,
                        field_order INT NOT NULL DEFAULT 0,
                        field_options TEXT,
                        placeholder VARCHAR(255),
                        FOREIGN KEY (form_id) REFERENCES booking_forms(id) ON DELETE CASCADE
                    )
                """))
            else:  # PostgreSQL
                conn.execute(text("""
                    CREATE TABLE booking_form_fields (
                        id SERIAL PRIMARY KEY,
                        form_id INTEGER NOT NULL,
                        field_type VARCHAR(20) NOT NULL,
                        field_name VARCHAR(100) NOT NULL,
                        field_label VARCHAR(200) NOT NULL,
                        is_required BOOLEAN NOT NULL DEFAULT FALSE,
                        field_order INTEGER NOT NULL DEFAULT 0,
                        field_options TEXT,
                        placeholder VARCHAR(255),
                        FOREIGN KEY (form_id) REFERENCES booking_forms(id) ON DELETE CASCADE
                    )
                """))
            conn.commit()
            print("  ✓ Tabelle booking_form_fields erstellt")
        else:
            print("  ✓ Tabelle booking_form_fields existiert bereits")
        
        # 3. booking_form_images Tabelle
        if not table_exists('booking_form_images'):
            print("Erstelle Tabelle: booking_form_images")
            if is_sqlite:
                conn.execute(text("""
                    CREATE TABLE booking_form_images (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        form_id INTEGER NOT NULL,
                        image_path VARCHAR(500) NOT NULL,
                        display_order INTEGER NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (form_id) REFERENCES booking_forms(id) ON DELETE CASCADE
                    )
                """))
            elif is_mysql:
                conn.execute(text("""
                    CREATE TABLE booking_form_images (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        form_id INT NOT NULL,
                        image_path VARCHAR(500) NOT NULL,
                        display_order INT NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (form_id) REFERENCES booking_forms(id) ON DELETE CASCADE
                    )
                """))
            else:  # PostgreSQL
                conn.execute(text("""
                    CREATE TABLE booking_form_images (
                        id SERIAL PRIMARY KEY,
                        form_id INTEGER NOT NULL,
                        image_path VARCHAR(500) NOT NULL,
                        display_order INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (form_id) REFERENCES booking_forms(id) ON DELETE CASCADE
                    )
                """))
            conn.commit()
            print("  ✓ Tabelle booking_form_images erstellt")
        else:
            print("  ✓ Tabelle booking_form_images existiert bereits")
        
        # 4. booking_requests Tabelle
        if not table_exists('booking_requests'):
            print("Erstelle Tabelle: booking_requests")
            if is_sqlite:
                conn.execute(text("""
                    CREATE TABLE booking_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        form_id INTEGER NOT NULL,
                        event_name VARCHAR(200) NOT NULL,
                        email VARCHAR(120) NOT NULL,
                        token VARCHAR(64) UNIQUE,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        event_date DATE,
                        event_start_time TIME,
                        event_end_time TIME,
                        calendar_event_id INTEGER,
                        folder_id INTEGER,
                        rejection_reason TEXT,
                        rejected_by INTEGER,
                        rejected_at DATETIME,
                        accepted_by INTEGER,
                        accepted_at DATETIME,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (form_id) REFERENCES booking_forms(id) ON DELETE CASCADE,
                        FOREIGN KEY (calendar_event_id) REFERENCES calendar_events(id),
                        FOREIGN KEY (folder_id) REFERENCES folders(id),
                        FOREIGN KEY (rejected_by) REFERENCES users(id),
                        FOREIGN KEY (accepted_by) REFERENCES users(id)
                    )
                """))
                # Index für Token
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_booking_requests_token ON booking_requests(token)"))
            elif is_mysql:
                conn.execute(text("""
                    CREATE TABLE booking_requests (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        form_id INT NOT NULL,
                        event_name VARCHAR(200) NOT NULL,
                        email VARCHAR(120) NOT NULL,
                        token VARCHAR(64) UNIQUE,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        event_date DATE,
                        event_start_time TIME,
                        event_end_time TIME,
                        calendar_event_id INT,
                        folder_id INT,
                        rejection_reason TEXT,
                        rejected_by INT,
                        rejected_at DATETIME,
                        accepted_by INT,
                        accepted_at DATETIME,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        FOREIGN KEY (form_id) REFERENCES booking_forms(id) ON DELETE CASCADE,
                        FOREIGN KEY (calendar_event_id) REFERENCES calendar_events(id),
                        FOREIGN KEY (folder_id) REFERENCES folders(id),
                        FOREIGN KEY (rejected_by) REFERENCES users(id),
                        FOREIGN KEY (accepted_by) REFERENCES users(id),
                        INDEX idx_booking_requests_token (token)
                    )
                """))
            else:  # PostgreSQL
                conn.execute(text("""
                    CREATE TABLE booking_requests (
                        id SERIAL PRIMARY KEY,
                        form_id INTEGER NOT NULL,
                        event_name VARCHAR(200) NOT NULL,
                        email VARCHAR(120) NOT NULL,
                        token VARCHAR(64) UNIQUE,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        event_date DATE,
                        event_start_time TIME,
                        event_end_time TIME,
                        calendar_event_id INTEGER,
                        folder_id INTEGER,
                        rejection_reason TEXT,
                        rejected_by INTEGER,
                        rejected_at TIMESTAMP,
                        accepted_by INTEGER,
                        accepted_at TIMESTAMP,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (form_id) REFERENCES booking_forms(id) ON DELETE CASCADE,
                        FOREIGN KEY (calendar_event_id) REFERENCES calendar_events(id),
                        FOREIGN KEY (folder_id) REFERENCES folders(id),
                        FOREIGN KEY (rejected_by) REFERENCES users(id),
                        FOREIGN KEY (accepted_by) REFERENCES users(id)
                    )
                """))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_booking_requests_token ON booking_requests(token)"))
            conn.commit()
            print("  ✓ Tabelle booking_requests erstellt")
        else:
            print("  ✓ Tabelle booking_requests existiert bereits")
        
        # 5. booking_request_fields Tabelle
        if not table_exists('booking_request_fields'):
            print("Erstelle Tabelle: booking_request_fields")
            if is_sqlite:
                conn.execute(text("""
                    CREATE TABLE booking_request_fields (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        request_id INTEGER NOT NULL,
                        field_id INTEGER NOT NULL,
                        field_value TEXT,
                        file_path VARCHAR(500),
                        FOREIGN KEY (request_id) REFERENCES booking_requests(id) ON DELETE CASCADE,
                        FOREIGN KEY (field_id) REFERENCES booking_form_fields(id) ON DELETE CASCADE
                    )
                """))
            elif is_mysql:
                conn.execute(text("""
                    CREATE TABLE booking_request_fields (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        request_id INT NOT NULL,
                        field_id INT NOT NULL,
                        field_value TEXT,
                        file_path VARCHAR(500),
                        FOREIGN KEY (request_id) REFERENCES booking_requests(id) ON DELETE CASCADE,
                        FOREIGN KEY (field_id) REFERENCES booking_form_fields(id) ON DELETE CASCADE
                    )
                """))
            else:  # PostgreSQL
                conn.execute(text("""
                    CREATE TABLE booking_request_fields (
                        id SERIAL PRIMARY KEY,
                        request_id INTEGER NOT NULL,
                        field_id INTEGER NOT NULL,
                        field_value TEXT,
                        file_path VARCHAR(500),
                        FOREIGN KEY (request_id) REFERENCES booking_requests(id) ON DELETE CASCADE,
                        FOREIGN KEY (field_id) REFERENCES booking_form_fields(id) ON DELETE CASCADE
                    )
                """))
            conn.commit()
            print("  ✓ Tabelle booking_request_fields erstellt")
        else:
            print("  ✓ Tabelle booking_request_fields existiert bereits")
        
        # 6. booking_request_files Tabelle
        if not table_exists('booking_request_files'):
            print("Erstelle Tabelle: booking_request_files")
            if is_sqlite:
                conn.execute(text("""
                    CREATE TABLE booking_request_files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        request_id INTEGER NOT NULL,
                        file_path VARCHAR(500) NOT NULL,
                        original_filename VARCHAR(255) NOT NULL,
                        uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (request_id) REFERENCES booking_requests(id) ON DELETE CASCADE
                    )
                """))
            elif is_mysql:
                conn.execute(text("""
                    CREATE TABLE booking_request_files (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        request_id INT NOT NULL,
                        file_path VARCHAR(500) NOT NULL,
                        original_filename VARCHAR(255) NOT NULL,
                        uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (request_id) REFERENCES booking_requests(id) ON DELETE CASCADE
                    )
                """))
            else:  # PostgreSQL
                conn.execute(text("""
                    CREATE TABLE booking_request_files (
                        id SERIAL PRIMARY KEY,
                        request_id INTEGER NOT NULL,
                        file_path VARCHAR(500) NOT NULL,
                        original_filename VARCHAR(255) NOT NULL,
                        uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (request_id) REFERENCES booking_requests(id) ON DELETE CASCADE
                    )
                """))
            conn.commit()
            print("  ✓ Tabelle booking_request_files erstellt")
        else:
            print("  ✓ Tabelle booking_request_files existiert bereits")
        
        # 7. booking_request_id zu calendar_events hinzufügen
        if table_exists('calendar_events'):
            if not column_exists('calendar_events', 'booking_request_id'):
                print("Füge booking_request_id zu calendar_events hinzu")
                if is_sqlite:
                    conn.execute(text("""
                        ALTER TABLE calendar_events 
                        ADD COLUMN booking_request_id INTEGER,
                        FOREIGN KEY (booking_request_id) REFERENCES booking_requests(id)
                    """))
                elif is_mysql:
                    conn.execute(text("""
                        ALTER TABLE calendar_events 
                        ADD COLUMN booking_request_id INT,
                        ADD FOREIGN KEY (booking_request_id) REFERENCES booking_requests(id)
                    """))
                else:  # PostgreSQL
                    conn.execute(text("""
                        ALTER TABLE calendar_events 
                        ADD COLUMN booking_request_id INTEGER,
                        ADD FOREIGN KEY (booking_request_id) REFERENCES booking_requests(id)
                    """))
                conn.commit()
                print("  ✓ Spalte booking_request_id zu calendar_events hinzugefügt")
            else:
                print("  ✓ Spalte booking_request_id in calendar_events existiert bereits")
        else:
            print("  ⚠ Tabelle calendar_events existiert nicht - booking_request_id wird beim nächsten Start hinzugefügt")
    
    print()
    print("=" * 60)
    print("Migration erfolgreich abgeschlossen!")
    print("=" * 60)


def main():
    """Hauptfunktion für die Migration."""
    try:
        app = create_app()
        with app.app_context():
            create_booking_tables()
    except Exception as e:
        print(f"\n❌ Fehler bei der Migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

