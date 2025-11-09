#!/usr/bin/env python3
"""
Datenbank-Migration: Wiki Favoriten
Erstellt die neue Tabelle für:
- wiki_favorites

Diese Migration fügt das Favoriten-System für Wiki-Einträge hinzu.
Benutzer können bis zu 5 Wiki-Seiten als Favoriten markieren.

WICHTIG: Die Felder sind bereits in den Modellen definiert.
Diese Migration ist nur für bestehende Datenbanken erforderlich.
Bei neuen Installationen werden die Tabellen automatisch durch db.create_all() erstellt.
"""

import os
import sys

# Füge das Projektverzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import inspect, text


def table_exists(table_name):
    """Prüft ob eine Tabelle existiert."""
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def migrate_wiki_favorites():
    """Erstellt wiki_favorites Tabelle."""
    inspector = inspect(db.engine)
    
    print("\nErstelle 'wiki_favorites' Tabelle...")
    
    if 'wiki_favorites' in inspector.get_table_names():
        print("  ✓ Tabelle 'wiki_favorites' existiert bereits")
        return True
    
    # Prüfe ob die abhängigen Tabellen existieren
    if 'users' not in inspector.get_table_names():
        print("  ⚠ Warnung: Tabelle 'users' existiert nicht.")
        print("    Die Tabelle wird beim nächsten Start automatisch erstellt.")
        return True
    
    if 'wiki_pages' not in inspector.get_table_names():
        print("  ⚠ Warnung: Tabelle 'wiki_pages' existiert nicht.")
        print("    Die Tabelle wird beim nächsten Start automatisch erstellt.")
        return True
    
    db_url = db.engine.url
    is_sqlite = 'sqlite' in str(db_url)
    is_mysql = 'mysql' in str(db_url) or 'mariadb' in str(db_url)
    is_postgres = 'postgresql' in str(db_url)
    
    with db.engine.connect() as conn:
        if is_sqlite:
            sql = """
            CREATE TABLE IF NOT EXISTS wiki_favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                wiki_page_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (wiki_page_id) REFERENCES wiki_pages(id),
                UNIQUE(user_id, wiki_page_id)
            )
            """
        elif is_mysql or is_mariadb:
            sql = """
            CREATE TABLE IF NOT EXISTS wiki_favorites (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                wiki_page_id INT NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (wiki_page_id) REFERENCES wiki_pages(id),
                UNIQUE KEY unique_user_wiki_favorite (user_id, wiki_page_id)
            )
            """
        elif is_postgres:
            sql = """
            CREATE TABLE IF NOT EXISTS wiki_favorites (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                wiki_page_id INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (wiki_page_id) REFERENCES wiki_pages(id),
                CONSTRAINT unique_user_wiki_favorite UNIQUE (user_id, wiki_page_id)
            )
            """
        else:
            # Generische SQL für andere Datenbanken
            sql = """
            CREATE TABLE IF NOT EXISTS wiki_favorites (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                user_id INTEGER NOT NULL,
                wiki_page_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (wiki_page_id) REFERENCES wiki_pages(id),
                UNIQUE(user_id, wiki_page_id)
            )
            """
        
        try:
            conn.execute(text(sql))
            conn.commit()
            print("  ✓ Tabelle 'wiki_favorites' erstellt")
            
            # Erstelle zusätzliche Indizes für bessere Performance
            try:
                if is_sqlite:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_wiki_favorites_user_id ON wiki_favorites(user_id)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_wiki_favorites_wiki_page_id ON wiki_favorites(wiki_page_id)"))
                elif is_mysql or is_mariadb or is_postgres:
                    conn.execute(text("CREATE INDEX idx_wiki_favorites_user_id ON wiki_favorites(user_id)"))
                    conn.execute(text("CREATE INDEX idx_wiki_favorites_wiki_page_id ON wiki_favorites(wiki_page_id)"))
                conn.commit()
                print("  ✓ Indizes erstellt")
            except Exception as e:
                print(f"  ⚠ Indizes konnten nicht erstellt werden (möglicherweise bereits vorhanden): {e}")
            
            return True
        except Exception as e:
            print(f"  ❌ Fehler beim Erstellen der Tabelle: {e}")
            import traceback
            traceback.print_exc()
            return False


def migrate():
    """Führt die Migration aus."""
    app = create_app()
    
    with app.app_context():
        print("=" * 60)
        print("Migration: Wiki Favoriten")
        print("=" * 60)
        
        try:
            # Erstelle die wiki_favorites Tabelle
            if not migrate_wiki_favorites():
                print("\n❌ Migration fehlgeschlagen!")
                return False
            
            # Verifiziere die Migration
            print("\n" + "=" * 60)
            print("Verifiziere Migration...")
            print("=" * 60)
            
            inspector = inspect(db.engine)
            
            if 'wiki_favorites' in inspector.get_table_names():
                columns = {col['name']: col for col in inspector.get_columns('wiki_favorites')}
                required_columns = ['id', 'user_id', 'wiki_page_id', 'created_at']
                missing_columns = [col for col in required_columns if col not in columns]
                
                if missing_columns:
                    print(f"  ❌ Warnung: In 'wiki_favorites' fehlen noch: {missing_columns}")
                    return False
                else:
                    print(f"  ✓ 'wiki_favorites': Alle Felder vorhanden")
                    print(f"    - id: {columns.get('id', {}).get('type', 'N/A')}")
                    print(f"    - user_id: {columns.get('user_id', {}).get('type', 'N/A')}")
                    print(f"    - wiki_page_id: {columns.get('wiki_page_id', {}).get('type', 'N/A')}")
                    print(f"    - created_at: {columns.get('created_at', {}).get('type', 'N/A')}")
            else:
                print("  ⚠ 'wiki_favorites': Tabelle existiert nicht")
                print("    Die Tabelle wird beim nächsten Start automatisch erstellt.")
            
            print("\n" + "=" * 60)
            print("Migration erfolgreich abgeschlossen!")
            print("=" * 60)
            
            print("\nZusammenfassung:")
            print("  - Neue Tabelle: wiki_favorites")
            print("  - Funktion: Benutzer können Wiki-Seiten als Favoriten markieren")
            print("  - Limit: Maximal 5 Favoriten pro Benutzer")
            print("  - Features: Widget 'Meine Wikis' im Dashboard verfügbar")
            
            return True
            
        except Exception as e:
            print(f"\n❌ Fehler bei der Migration: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)

