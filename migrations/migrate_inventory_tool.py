"""
Migration: Inventurtool - Neue Tabellen für Inventuren
Führt die neuen Tabellen für das Inventurtool ein.
"""
import os
import sys
from app import create_app, db
from sqlalchemy import text, inspect


def migrate_table(table_name, fields_config, create_indexes=None):
    """
    Hilfsfunktion zum Hinzufügen von Spalten zu einer bestehenden Tabelle.
    
    Args:
        table_name: Name der Tabelle
        fields_config: Liste von Tupeln (spalten_name, spalten_definition)
        create_indexes: Liste von Index-Definitionen (optional)
    """
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()
    
    if table_name not in existing_tables:
        print(f"Tabelle '{table_name}' existiert nicht. Überspringe Migration.")
        return False
    
    existing_columns = [col['name'] for col in inspector.get_columns(table_name)]
    
    for column_name, column_definition in fields_config:
        if column_name not in existing_columns:
            print(f"Hinzufügen von Spalte '{column_name}' zu Tabelle '{table_name}'...")
            try:
                db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}"))
                print(f"Spalte '{column_name}' erfolgreich hinzugefügt.")
            except Exception as e:
                print(f"Fehler beim Hinzufügen von Spalte '{column_name}': {e}")
                return False
        else:
            print(f"Spalte '{column_name}' existiert bereits in Tabelle '{table_name}'. Überspringe.")
    
    # Indexe erstellen
    if create_indexes:
        existing_indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
        for index_name, index_definition in create_indexes:
            if index_name not in existing_indexes:
                print(f"Erstelle Index '{index_name}' für Tabelle '{table_name}'...")
                try:
                    db.session.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({index_definition})"))
                    print(f"Index '{index_name}' erfolgreich erstellt.")
                except Exception as e:
                    print(f"Fehler beim Erstellen von Index '{index_name}': {e}")
            else:
                print(f"Index '{index_name}' existiert bereits. Überspringe.")
    
    return True


def migrate():
    """Führt die Migration für das Inventurtool durch."""
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        print("=== Inventurtool Migration ===")
        
        # Inventories Tabelle
        if 'inventories' not in existing_tables:
            print("Erstelle Tabelle 'inventories'...")
            db.session.execute(text("""
                CREATE TABLE inventories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    status VARCHAR(20) DEFAULT 'active' NOT NULL,
                    started_by INTEGER NOT NULL,
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    completed_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (started_by) REFERENCES users (id)
                );
            """))
            db.session.execute(text("CREATE INDEX ix_inventories_status ON inventories (status);"))
            print("Tabelle 'inventories' erstellt.")
        else:
            print("Tabelle 'inventories' existiert bereits.")
        
        # Inventory Items Tabelle
        if 'inventory_items' not in existing_tables:
            print("Erstelle Tabelle 'inventory_items'...")
            db.session.execute(text("""
                CREATE TABLE inventory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inventory_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    checked BOOLEAN DEFAULT 0 NOT NULL,
                    notes TEXT,
                    location_changed BOOLEAN DEFAULT 0 NOT NULL,
                    new_location VARCHAR(255),
                    condition_changed BOOLEAN DEFAULT 0 NOT NULL,
                    new_condition VARCHAR(50),
                    checked_by INTEGER,
                    checked_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (inventory_id) REFERENCES inventories (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (checked_by) REFERENCES users (id),
                    UNIQUE(inventory_id, product_id)
                );
            """))
            db.session.execute(text("CREATE INDEX ix_inventory_items_inventory_id ON inventory_items (inventory_id);"))
            db.session.execute(text("CREATE INDEX ix_inventory_items_product_id ON inventory_items (product_id);"))
            print("Tabelle 'inventory_items' erstellt.")
        else:
            print("Tabelle 'inventory_items' existiert bereits.")
        
        db.session.commit()
        print("=== Migration abgeschlossen ===")
        return True


if __name__ == '__main__':
    if migrate():
        print("Migration erfolgreich!")
        sys.exit(0)
    else:
        print("Migration fehlgeschlagen!")
        sys.exit(1)

