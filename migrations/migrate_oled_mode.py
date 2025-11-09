#!/usr/bin/env python3
"""
Datenbank-Migration: OLED-Modus
Fügt das oled_mode Feld zur users Tabelle hinzu.

WICHTIG: Das Feld ist bereits im User-Model definiert.
Diese Migration ist nur für bestehende Datenbanken erforderlich.
Bei neuen Installationen wird das Feld automatisch durch db.create_all() erstellt.
"""

import os
import sys

# Füge das Projektverzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect


def migrate_table(table_name, fields_config, create_indexes=None):
    """Führt die Migration für eine Tabelle aus."""
    inspector = inspect(db.engine)
    
    if table_name not in inspector.get_table_names():
        print(f"[WARN] Warnung: Tabelle '{table_name}' existiert nicht.")
        print("  Die Tabelle wird beim nächsten Start automatisch erstellt.")
        return True
    
    # Prüfe ob die Felder bereits existieren
    columns = {col['name']: col for col in inspector.get_columns(table_name)}
    
    fields_to_add = []
    for field_name, _ in fields_config.items():
        if field_name not in columns:
            fields_to_add.append(field_name)
    
    if not fields_to_add:
        print(f"[OK] Alle Felder in '{table_name}' existieren bereits.")
        return True
    
    print(f"\nFehlende Felder in '{table_name}' gefunden: {', '.join(fields_to_add)}")
    
    # Bestimme die Datenbank-Engine
    db_url = db.engine.url
    is_sqlite = 'sqlite' in str(db_url)
    is_mysql = 'mysql' in str(db_url) or 'mariadb' in str(db_url)
    is_postgres = 'postgresql' in str(db_url)
    
    with db.engine.connect() as conn:
        if is_sqlite:
            # SQLite unterstützt nur ein ALTER TABLE ADD COLUMN pro Statement
            for field_name in fields_to_add:
                field_type, field_default, field_nullable = fields_config[field_name]
                
                sql = f"ALTER TABLE {table_name} ADD COLUMN {field_name} {field_type}"
                
                if field_default is not None:
                    sql += f" DEFAULT {field_default}"
                
                if not field_nullable:
                    sql += " NOT NULL"
                
                try:
                    conn.execute(text(sql))
                    print(f"  [OK] {field_name} hinzugefügt")
                except Exception as e:
                    print(f"  [WARN] Fehler beim Hinzufügen von {field_name}: {e}")
            
            conn.commit()
        
        elif is_mysql or is_postgres:
            # MySQL/MariaDB/PostgreSQL unterstützen mehrere Spalten in einem ALTER TABLE
            alter_statements = []
            
            for field_name in fields_to_add:
                field_type, field_default, field_nullable = fields_config[field_name]
                
                if is_mysql:
                    if field_type == 'BOOLEAN':
                        alter_sql = f"ADD COLUMN {field_name} TINYINT(1)"
                    elif field_type == 'TEXT':
                        alter_sql = f"ADD COLUMN {field_name} TEXT"
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
                    print(f"  [OK] {len(alter_statements)} Felder hinzugefügt")
                except Exception as e:
                    print(f"  [ERROR] Fehler beim Hinzufügen der Felder: {e}")
                    return False
            
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
                    print(f"  [OK] {field_name} hinzugefügt")
                
                conn.commit()
            except Exception as e:
                print(f"  [ERROR] Fehler bei generischer Migration: {e}")
                return False
    
    return True


def migrate():
    """Führt die Migration für OLED-Modus und Update-Notifications aus."""
    print("=" * 60)
    print("Migration: OLED-Modus & Update-Notifications")
    print("=" * 60)
    
    # Erstelle die Flask-App
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        try:
            print("\nFüge 'oled_mode' und 'show_update_notifications' Felder zu 'users' Tabelle hinzu...")
            fields_config = {
                'oled_mode': ('BOOLEAN', '0', False),
                'show_update_notifications': ('BOOLEAN', '1', False)
            }
            
            if not migrate_table('users', fields_config):
                print("[ERROR] Migration für 'users' fehlgeschlagen!")
                return False
            
            # Setze Standardwert für show_update_notifications für bestehende Benutzer
            inspector = inspect(db.engine)
            if 'users' in inspector.get_table_names():
                columns = {col['name']: col for col in inspector.get_columns('users')}
                if 'show_update_notifications' in columns:
                    db_type = db.engine.dialect.name
                    try:
                        if db_type == 'sqlite':
                            db.session.execute(text("""
                                UPDATE users 
                                SET show_update_notifications = 1 
                                WHERE show_update_notifications IS NULL
                            """))
                        else:
                            db.session.execute(text("""
                                UPDATE users 
                                SET show_update_notifications = TRUE 
                                WHERE show_update_notifications IS NULL
                            """))
                        db.session.commit()
                        print("[OK] Standardwerte für 'show_update_notifications' gesetzt.")
                    except Exception as e:
                        print(f"[WARN] Warnung beim Setzen der Standardwerte: {e}")
                        db.session.rollback()
            
            # Verifiziere die Migration
            print("\n" + "=" * 60)
            print("Verifiziere Migration...")
            print("=" * 60)
            
            inspector = inspect(db.engine)
            
            if 'users' not in inspector.get_table_names():
                print("  [WARN] Tabelle 'users' existiert nicht (wird beim nächsten Start erstellt)")
                return True
            
            columns_after = {col['name']: col for col in inspector.get_columns('users')}
            
            if 'oled_mode' not in columns_after:
                print("  [ERROR] Warnung: 'oled_mode' Feld fehlt noch in 'users'")
                return False
            else:
                print("  [OK] 'users': 'oled_mode' Feld vorhanden")
            
            if 'show_update_notifications' not in columns_after:
                print("  [ERROR] Warnung: 'show_update_notifications' Feld fehlt noch in 'users'")
                return False
            else:
                print("  [OK] 'users': 'show_update_notifications' Feld vorhanden")
            
            print("\n" + "=" * 60)
            print("Migration erfolgreich abgeschlossen!")
            print("=" * 60)
            
            return True
        
        except Exception as e:
            print(f"\n[ERROR] Fehler bei der Migration: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)

