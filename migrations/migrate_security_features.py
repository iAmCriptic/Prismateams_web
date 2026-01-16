#!/usr/bin/env python3
"""
Datenbank-Migration: Sicherheitsfeatures (2FA, Rate Limiting, Session-Management)
Fügt die neuen Spalten für Sicherheitsfeatures zur users-Tabelle hinzu und erstellt die user_sessions-Tabelle.

Diese Migration fügt hinzu:
- users.totp_secret (String, nullable)
- users.totp_enabled (Boolean, default=False)
- users.password_changed_at (DateTime, nullable)
- users.failed_login_attempts (Integer, default=0)
- users.failed_login_until (DateTime, nullable)
- user_sessions Tabelle (neu)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect, Column, Integer, String, Boolean, DateTime, ForeignKey, VARCHAR
from sqlalchemy.exc import OperationalError


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


def migrate():
    """Führt die Migration aus."""
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        print("=" * 60)
        print("Datenbank-Migration: Sicherheitsfeatures")
        print("=" * 60)
        
        inspector = inspect(db.engine)
        db_type = db.engine.dialect.name
        print(f"   [INFO] Datenbanktyp: {db_type}")
        
        # Neue Spalten für users-Tabelle
        # Format: (column_name, type_class, default_value)
        new_columns = [
            ('totp_secret', 'VARCHAR', None),
            ('totp_enabled', 'BOOLEAN', False),
            ('password_changed_at', 'DATETIME', None),
            ('failed_login_attempts', 'INTEGER', 0),
            ('failed_login_until', 'DATETIME', None)
        ]
        
        print("\n1. Prüfe users-Tabelle...")
        if not table_exists('users'):
            print("   FEHLER: users-Tabelle existiert nicht!")
            return False
        
        print("   [OK] users-Tabelle gefunden")
        
        # Füge fehlende Spalten hinzu
        print("\n2. Füge neue Spalten zur users-Tabelle hinzu...")
        added_columns = []
        
        for column_name, column_type, default_value in new_columns:
            if column_exists('users', column_name):
                print(f"   - {column_name}: bereits vorhanden")
            else:
                try:
                    alter_sql = None
                    if db_type == 'mysql':
                        # MySQL/MariaDB
                        if default_value is None:
                            if column_type == 'VARCHAR':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} VARCHAR(255) NULL"
                            elif column_type == 'DATETIME':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} DATETIME NULL"
                            elif column_type == 'BOOLEAN':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN NOT NULL DEFAULT 0"
                            elif column_type == 'INTEGER':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} INTEGER NOT NULL DEFAULT 0"
                        else:
                            if column_type == 'BOOLEAN':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN NOT NULL DEFAULT {1 if default_value else 0}"
                            elif column_type == 'INTEGER':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} INTEGER NOT NULL DEFAULT {default_value}"
                            else:
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} {column_type} NOT NULL DEFAULT '{default_value}'"
                    elif db_type == 'sqlite':
                        # SQLite
                        if default_value is None:
                            if column_type == 'VARCHAR':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} VARCHAR(255)"
                            elif column_type == 'DATETIME':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} DATETIME"
                            elif column_type == 'BOOLEAN':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN DEFAULT 0"
                            elif column_type == 'INTEGER':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} INTEGER DEFAULT 0"
                        else:
                            if column_type == 'BOOLEAN':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN DEFAULT {1 if default_value else 0}"
                            elif column_type == 'INTEGER':
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} INTEGER DEFAULT {default_value}"
                            else:
                                alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} {column_type} DEFAULT '{default_value}'"
                    
                    if alter_sql is None:
                        print(f"   - {column_name}: Unbekannter Datenbanktyp {db_type} oder Spaltentyp {column_type}, ueberspringe")
                        continue
                    
                    db.session.execute(text(alter_sql))
                    db.session.commit()
                    print(f"   [OK] {column_name}: hinzugefuegt")
                    added_columns.append(column_name)
                except Exception as e:
                    print(f"   [FEHLER] {column_name}: Fehler - {e}")
                    db.session.rollback()
        
        # Erstelle user_sessions-Tabelle
        print("\n3. Prüfe user_sessions-Tabelle...")
        if table_exists('user_sessions'):
            print("   [OK] user_sessions-Tabelle bereits vorhanden")
        else:
            print("   - Erstelle user_sessions-Tabelle...")
            try:
                if db_type == 'mysql':
                    create_table_sql = """
                    CREATE TABLE user_sessions (
                        id INTEGER AUTO_INCREMENT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        session_id VARCHAR(255) NOT NULL UNIQUE,
                        ip_address VARCHAR(45),
                        user_agent VARCHAR(500),
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_activity DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        INDEX idx_user_id (user_id),
                        INDEX idx_session_id (session_id),
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """
                elif db_type == 'sqlite':
                    create_table_sql = """
                    CREATE TABLE user_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        session_id VARCHAR(255) NOT NULL UNIQUE,
                        ip_address VARCHAR(45),
                        user_agent VARCHAR(500),
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_activity DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                    """
                    # SQLite unterstützt keine separaten CREATE INDEX Statements in einer Transaktion
                    # Indizes werden später erstellt
                else:
                    print(f"   ✗ Unbekannter Datenbanktyp {db_type}, überspringe Tabellenerstellung")
                    return False
                
                db.session.execute(text(create_table_sql))
                db.session.commit()
                
                # Erstelle Indizes für SQLite separat
                if db_type == 'sqlite':
                    indexes = [
                        "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id)",
                        "CREATE INDEX IF NOT EXISTS idx_user_sessions_session_id ON user_sessions(session_id)",
                        "CREATE INDEX IF NOT EXISTS idx_user_sessions_is_active ON user_sessions(is_active)"
                    ]
                    for index_sql in indexes:
                        try:
                            db.session.execute(text(index_sql))
                        except:
                            pass
                    db.session.commit()
                
                print("   [OK] user_sessions-Tabelle erstellt")
            except Exception as e:
                print(f"   [FEHLER] Fehler beim Erstellen der user_sessions-Tabelle: {e}")
                db.session.rollback()
                return False
        
        print("\n" + "=" * 60)
        if added_columns:
            print(f"[OK] Migration erfolgreich! {len(added_columns)} Spalte(n) hinzugefuegt.")
        else:
            print("[OK] Migration erfolgreich! Alle Spalten waren bereits vorhanden.")
        print("=" * 60)
        return True


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)
