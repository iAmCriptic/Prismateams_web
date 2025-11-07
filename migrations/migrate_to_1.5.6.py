#!/usr/bin/env python3
"""
Datenbank-Migration: Version 1.5.6
Freigabe-Felder zum folders- und files-Modell hinzufügen

Diese Migration fügt die neuen Felder für das Freigabe-Feature hinzu:
Folders:
- share_enabled (Boolean, default=False)
- share_token (String, unique, nullable)
- share_password_hash (String, nullable)
- share_expires_at (DateTime, nullable)
- share_name (String, nullable)

Files:
- share_enabled (Boolean, default=False)
- share_token (String, unique, nullable)
- share_password_hash (String, nullable)
- share_expires_at (DateTime, nullable)
- share_name (String, nullable)

WICHTIG: Die Felder sind bereits im Modell (app/models/file.py) definiert.
Diese Migration ist nur für bestehende Datenbanken erforderlich.
Bei neuen Installationen werden die Felder automatisch durch db.create_all() erstellt.
"""

import os
import sys

# Füge das Projektverzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect

def migrate_table(table_name, fields_config):
    """Führt die Migration für eine Tabelle aus."""
    inspector = inspect(db.engine)
    
    if table_name not in inspector.get_table_names():
        print(f"⚠ Warnung: Tabelle '{table_name}' existiert nicht.")
        print("  Die Tabelle wird beim nächsten Start automatisch erstellt.")
        return True
    
    # Prüfe ob die Felder bereits existieren
    columns = {col['name']: col for col in inspector.get_columns(table_name)}
    
    fields_to_add = []
    for field_name, _ in fields_config.items():
        if field_name not in columns:
            fields_to_add.append(field_name)
    
    if not fields_to_add:
        print(f"✓ Alle Felder in '{table_name}' existieren bereits. Migration nicht erforderlich.")
        return True
    
    print(f"\nFehlende Felder in '{table_name}' gefunden: {', '.join(fields_to_add)}")
    print(f"Starte Migration für '{table_name}'...")
    
    # Bestimme die Datenbank-Engine
    db_url = db.engine.url
    is_sqlite = 'sqlite' in str(db_url)
    is_mysql = 'mysql' in str(db_url) or 'mariadb' in str(db_url)
    is_postgres = 'postgresql' in str(db_url)
    
    with db.engine.connect() as conn:
        if is_sqlite:
            print(f"\nFühre SQLite-Migration für '{table_name}' aus...")
            # SQLite unterstützt nur ein ALTER TABLE ADD COLUMN pro Statement
            for field_name in fields_to_add:
                field_type, field_default, field_nullable = fields_config[field_name]
                
                # Baue SQL-Statement
                sql = f"ALTER TABLE {table_name} ADD COLUMN {field_name} {field_type}"
                
                if field_default is not None:
                    sql += f" DEFAULT {field_default}"
                
                if not field_nullable:
                    sql += " NOT NULL"
                
                try:
                    conn.execute(text(sql))
                    print(f"  ✓ {field_name} hinzugefügt")
                except Exception as e:
                    print(f"  ⚠ Fehler beim Hinzufügen von {field_name}: {e}")
            
            # Unique Index für share_token (nur wenn nicht NULL)
            if 'share_token' in fields_to_add:
                try:
                    conn.execute(text(f"""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_{table_name}_share_token 
                        ON {table_name}(share_token) 
                        WHERE share_token IS NOT NULL
                    """))
                    print("  ✓ Unique Index für share_token erstellt")
                except Exception as e:
                    print(f"  ⚠ Index-Erstellung übersprungen: {e}")
            
            conn.commit()
        
        elif is_mysql or is_postgres:
            print(f"\nFühre {db_url.drivername}-Migration für '{table_name}' aus...")
            # MySQL/MariaDB/PostgreSQL unterstützen mehrere Spalten in einem ALTER TABLE
            alter_statements = []
            
            for field_name in fields_to_add:
                field_type, field_default, field_nullable = fields_config[field_name]
                
                if is_mysql:
                    # MySQL verwendet BOOLEAN als TINYINT(1)
                    if field_type == 'BOOLEAN':
                        alter_sql = "ADD COLUMN {} TINYINT(1)".format(field_name)
                    else:
                        alter_sql = f"ADD COLUMN {field_name} {field_type}"
                else:  # PostgreSQL
                    alter_sql = f"ADD COLUMN {field_name} {field_type}"
                
                if field_default is not None:
                    alter_sql += f" DEFAULT {field_default}"
                
                if not field_nullable:
                    alter_sql += " NOT NULL"
                
                alter_statements.append(alter_sql)
            
            if alter_statements:
                alter_sql = f"ALTER TABLE {table_name} {', '.join(alter_statements)}"
                try:
                    conn.execute(text(alter_sql))
                    print(f"  ✓ {len(alter_statements)} Felder hinzugefügt")
                except Exception as e:
                    print(f"  ❌ Fehler beim Hinzufügen der Felder: {e}")
                    return False
            
            # Unique Index für share_token
            if 'share_token' in fields_to_add:
                try:
                    conn.execute(text(f"CREATE UNIQUE INDEX idx_{table_name}_share_token ON {table_name}(share_token)"))
                    print("  ✓ Unique Index für share_token erstellt")
                except Exception as e:
                    print(f"  ⚠ Index-Erstellung übersprungen: {e}")
            
            conn.commit()
        
        else:
            # Generische Migration für andere Datenbanken
            print(f"\nFühre generische Migration für {db_url.drivername} aus...")
            try:
                for field_name in fields_to_add:
                    field_type, field_default, field_nullable = fields_config[field_name]
                    
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {field_name} {field_type}"
                    
                    if field_default is not None:
                        sql += f" DEFAULT {field_default}"
                    
                    if not field_nullable:
                        sql += " NOT NULL"
                    
                    conn.execute(text(sql))
                    print(f"  ✓ {field_name} hinzugefügt")
                
                conn.commit()
            except Exception as e:
                print(f"  ❌ Fehler bei generischer Migration: {e}")
                print("  Bitte führen Sie die Migration manuell für Ihre Datenbank aus.")
                return False
    
    return True

def migrate():
    """Führt die Migration aus."""
    print("=" * 60)
    print("Migration zu Version 1.5.6")
    print("Freigabe-Felder hinzufügen")
    print("=" * 60)
    
    # Erstelle die Flask-App
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        try:
            # Felder-Konfiguration für beide Tabellen (identisch)
            fields_config = {
                'share_enabled': ('BOOLEAN', '0', False),  # field_type, default, nullable
                'share_token': ('VARCHAR(255)', None, True),
                'share_password_hash': ('VARCHAR(255)', None, True),
                'share_expires_at': ('DATETIME', None, True),
                'share_name': ('VARCHAR(255)', None, True)
            }
            
            # Migriere folders-Tabelle
            if not migrate_table('folders', fields_config):
                print("❌ Migration für 'folders' fehlgeschlagen!")
                return False
            
            # Migriere files-Tabelle
            if not migrate_table('files', fields_config):
                print("❌ Migration für 'files' fehlgeschlagen!")
                return False
            
            # Verifiziere die Migration
            print("\nVerifiziere Migration...")
            inspector = inspect(db.engine)
            
            required_fields = ['share_enabled', 'share_token', 'share_password_hash', 'share_expires_at', 'share_name']
            
            for table_name in ['folders', 'files']:
                if table_name not in inspector.get_table_names():
                    continue
                
                columns_after = {col['name']: col for col in inspector.get_columns(table_name)}
                missing_fields = [f for f in required_fields if f not in columns_after]
                
                if missing_fields:
                    print(f"  ❌ Warnung: In '{table_name}' fehlen noch: {missing_fields}")
                    print("  Bitte überprüfen Sie die Datenbank-Logs.")
                else:
                    print(f"  ✓ Migration für '{table_name}' erfolgreich abgeschlossen!")
            
            print("\n" + "=" * 60)
            print("Migration abgeschlossen!")
            print("=" * 60)
            print("\nHinzugefügte Felder (folders & files):")
            print("  - share_enabled (BOOLEAN, DEFAULT FALSE)")
            print("  - share_token (VARCHAR(255), UNIQUE, NULLABLE)")
            print("  - share_password_hash (VARCHAR(255), NULLABLE)")
            print("  - share_expires_at (DATETIME, NULLABLE)")
            print("  - share_name (VARCHAR(255), NULLABLE)")
        
        except Exception as e:
            print(f"\n❌ Fehler bei der Migration: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    migrate()




