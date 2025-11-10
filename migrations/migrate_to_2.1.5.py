#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.1.5
Konsolidierte Migration für alle Versionen bis 2.1.5

Diese Migration fasst sämtliche bisherigen Einzelskripte zusammen und führt sie
in der korrekten Reihenfolge aus. Sie deckt folgende Änderungen ab:

1. Version 1.5.2: Briefkasten-Felder in `folders`
2. Version 1.5.6: Freigabe-Felder in `folders` und `files`
3. Borrow Group ID: Mehrfachausleihen für Inventory (`borrow_transactions`)
4. Kalender-Features: Wiederkehrende Termine & öffentliche iCal-Feeds
5. Version 2.1.4: Dashboard-Konfiguration in `users`
6. OLED-Modus & Update-Benachrichtigungen in `users`
7. Lagersystem-Erweiterungen (Sets, Dokumente, Favoriten, Saved Filters, API Tokens)
8. Inventur-Tool Tabellen (`inventories`, `inventory_items`)
9. Wiki-Favoriten Tabelle (`wiki_favorites`)
10. Mehrsprachigkeit (Benutzersprache & Sprach-Systemeinstellungen)

WICHTIG: Die Felder und Tabellen sind in den SQLAlchemy-Modellen bereits
definiert. Bei Neuinstallationen genügt weiterhin `db.create_all()`.
Dieses Skript richtet sich ausschließlich an bestehende Installationen.
"""

import os
import sys
import json

# Projektverzeichnis zum Python-Pfad hinzufügen
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect


def migrate_table(table_name, fields_config, create_indexes=None):
    """Fügt einer bestehenden Tabelle neue Spalten (und optional Indizes) hinzu."""
    inspector = inspect(db.engine)

    if table_name not in inspector.get_table_names():
        print(f"⚠ Warnung: Tabelle '{table_name}' existiert nicht.")
        print("  Die Tabelle wird beim nächsten Start automatisch erstellt.")
        return True

    columns = {col['name']: col for col in inspector.get_columns(table_name)}
    fields_to_add = [field for field in fields_config if field not in columns]

    if not fields_to_add:
        print(f"✓ Alle Felder in '{table_name}' existieren bereits.")
        return True

    print(f"\nFehlende Felder in '{table_name}' gefunden: {', '.join(fields_to_add)}")

    db_url = db.engine.url
    is_sqlite = 'sqlite' in str(db_url)
    is_mysql = 'mysql' in str(db_url) or 'mariadb' in str(db_url)
    is_postgres = 'postgresql' in str(db_url)

    with db.engine.connect() as conn:
        if is_sqlite:
            for field_name in fields_to_add:
                field_type, field_default, field_nullable = fields_config[field_name]
                sql = f"ALTER TABLE {table_name} ADD COLUMN {field_name} {field_type}"

                if field_default is not None:
                    sql += f" DEFAULT {field_default}"

                if not field_nullable:
                    sql += " NOT NULL"

                try:
                    conn.execute(text(sql))
                    print(f"  ✓ {field_name} hinzugefügt")
                except Exception as exc:  # pylint: disable=broad-except
                    print(f"  ⚠ Fehler beim Hinzufügen von {field_name}: {exc}")

            # Indizes unter SQLite einzeln anlegen
            if create_indexes:
                existing_indexes = {
                    idx['name']
                    for idx in inspector.get_indexes(table_name)
                }
                for index_name, index_field, unique in create_indexes:
                    if index_name in existing_indexes:
                        continue
                    try:
                        if unique:
                            conn.execute(text(f"""
                                CREATE UNIQUE INDEX IF NOT EXISTS {index_name}
                                ON {table_name}({index_field})
                                WHERE {index_field} IS NOT NULL
                            """))
                        else:
                            conn.execute(text(f"""
                                CREATE INDEX IF NOT EXISTS {index_name}
                                ON {table_name}({index_field})
                            """))
                        print(f"  ✓ Index {index_name} erstellt")
                    except Exception as exc:  # pylint: disable=broad-except
                        print(f"  ⚠ Index {index_name} konnte nicht erstellt werden: {exc}")

            conn.commit()

        elif is_mysql or is_postgres:
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
                else:
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
                except Exception as exc:  # pylint: disable=broad-except
                    print(f"  ❌ Fehler beim Hinzufügen der Felder: {exc}")
                    return False

            if create_indexes:
                existing_indexes = {
                    idx['name']
                    for idx in inspector.get_indexes(table_name)
                }
                for index_name, index_field, unique in create_indexes:
                    if index_name in existing_indexes:
                        continue
                    try:
                        if unique:
                            conn.execute(text(f"CREATE UNIQUE INDEX {index_name} ON {table_name}({index_field})"))
                        else:
                            conn.execute(text(f"CREATE INDEX {index_name} ON {table_name}({index_field})"))
                        print(f"  ✓ Index {index_name} erstellt")
                    except Exception as exc:  # pylint: disable=broad-except
                        print(f"  ⚠ Index {index_name} konnte nicht erstellt werden: {exc}")

            conn.commit()

        else:
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
            except Exception as exc:  # pylint: disable=broad-except
                print(f"  ❌ Fehler bei generischer Migration: {exc}")
                return False

    return True


def migrate_calendar_events():
    """Migriert `calendar_events` um Felder für wiederkehrende Termine hinzuzufügen."""
    inspector = inspect(db.engine)

    if 'calendar_events' not in inspector.get_table_names():
        print("\n⚠ Warnung: Tabelle 'calendar_events' existiert nicht.")
        print("  Die Tabelle wird beim nächsten Start automatisch erstellt.")
        return True

    print("\n1.4. Migriere 'calendar_events' Tabelle...")

    columns = {col['name']: col for col in inspector.get_columns('calendar_events')}

    fields_config = {
        'recurrence_type': ('VARCHAR(20)', "'none'", False),
        'recurrence_end_date': ('DATETIME', None, True),
        'recurrence_interval': ('INTEGER', '1', False),
        'recurrence_days': ('VARCHAR(50)', None, True),
        'parent_event_id': ('INTEGER', None, True),
        'is_recurring_instance': ('BOOLEAN', '0', False),
        'recurrence_sequence': ('INTEGER', None, True),
        'public_ical_token': ('VARCHAR(64)', None, True),
        'is_public': ('BOOLEAN', '0', False)
    }

    create_indexes = [
        ('idx_calendar_events_public_ical_token', 'public_ical_token', True)
    ]

    success = migrate_table('calendar_events', fields_config, create_indexes)

    db_url = db.engine.url
    is_sqlite = 'sqlite' in str(db_url)

    if 'parent_event_id' not in columns and not is_sqlite:
        try:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    ALTER TABLE calendar_events
                    ADD CONSTRAINT fk_calendar_events_parent_event_id
                    FOREIGN KEY (parent_event_id) REFERENCES calendar_events(id)
                """))
                conn.commit()
                print("  ✓ Foreign Key für parent_event_id erstellt")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  ⚠ Foreign Key konnte nicht erstellt werden: {exc}")

    return success


def migrate_public_calendar_feeds():
    """Erstellt die Tabelle `public_calendar_feeds`, falls sie fehlt."""
    inspector = inspect(db.engine)

    print("\n1.5. Erstelle 'public_calendar_feeds' Tabelle...")

    if 'public_calendar_feeds' in inspector.get_table_names():
        print("  ✓ Tabelle 'public_calendar_feeds' existiert bereits")
        return True

    db_url = db.engine.url
    is_sqlite = 'sqlite' in str(db_url)
    is_mysql = 'mysql' in str(db_url) or 'mariadb' in str(db_url)
    is_postgres = 'postgresql' in str(db_url)

    with db.engine.connect() as conn:
        if is_sqlite:
            sql = """
            CREATE TABLE IF NOT EXISTS public_calendar_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token VARCHAR(64) NOT NULL UNIQUE,
                created_by INTEGER NOT NULL,
                name VARCHAR(200),
                include_all_events BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                last_synced DATETIME,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
            """
        elif is_mysql:
            sql = """
            CREATE TABLE IF NOT EXISTS public_calendar_feeds (
                id INT AUTO_INCREMENT PRIMARY KEY,
                token VARCHAR(64) NOT NULL UNIQUE,
                created_by INT NOT NULL,
                name VARCHAR(200),
                include_all_events BOOLEAN NOT NULL DEFAULT FALSE,
                created_at DATETIME NOT NULL,
                last_synced DATETIME,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
            """
        elif is_postgres:
            sql = """
            CREATE TABLE IF NOT EXISTS public_calendar_feeds (
                id SERIAL PRIMARY KEY,
                token VARCHAR(64) NOT NULL UNIQUE,
                created_by INTEGER NOT NULL,
                name VARCHAR(200),
                include_all_events BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL,
                last_synced TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
            """
        else:
            sql = """
            CREATE TABLE IF NOT EXISTS public_calendar_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token VARCHAR(64) NOT NULL UNIQUE,
                created_by INTEGER NOT NULL,
                name VARCHAR(200),
                include_all_events BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                last_synced DATETIME,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
            """

        try:
            conn.execute(text(sql))
            conn.commit()
            print("  ✓ Tabelle 'public_calendar_feeds' erstellt")
            return True
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  ⚠ Fehler beim Erstellen der Tabelle: {exc}")
            return False


def migrate_user_display_settings():
    """Fügt `oled_mode` und `show_update_notifications` zu `users` hinzu und setzt Defaults."""
    print("\n2.1. OLED-Modus & Update-Benachrichtigungen für 'users'...")

    fields_config = {
        'oled_mode': ('BOOLEAN', '0', False),
        'show_update_notifications': ('BOOLEAN', '1', False)
    }

    if not migrate_table('users', fields_config):
        print("❌ Migration für 'users' (OLED/Updates) fehlgeschlagen!")
        return False

    inspector = inspect(db.engine)
    if 'users' not in inspector.get_table_names():
        return True

    columns = {col['name']: col for col in inspector.get_columns('users')}
    if 'show_update_notifications' not in columns:
        return True

    try:
        db_type = db.engine.dialect.name
        if db_type == 'sqlite':
            db.session.execute(text("""
                UPDATE users
                SET show_update_notifications = 1
                WHERE show_update_notifications IS NULL
            """))
            db.session.execute(text("""
                UPDATE users
                SET oled_mode = 0
                WHERE oled_mode IS NULL
            """))
        else:
            db.session.execute(text("""
                UPDATE users
                SET show_update_notifications = TRUE
                WHERE show_update_notifications IS NULL
            """))
            db.session.execute(text("""
                UPDATE users
                SET oled_mode = FALSE
                WHERE oled_mode IS NULL
            """))
        db.session.commit()
        print("  ✓ Standardwerte für bestehende Benutzer gesetzt")
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        print(f"  ⚠ Konnte Standardwerte nicht setzen: {exc}")

    return True


def create_inventory_tables():
    """Erstellt die Tabellen des Inventur-Tools."""
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    db_url = db.engine.url
    is_sqlite = 'sqlite' in str(db_url)
    is_mysql = 'mysql' in str(db_url) or 'mariadb' in str(db_url)
    is_postgres = 'postgresql' in str(db_url)

    def create_table(sqlite_sql, mysql_sql, postgres_sql, generic_sql):
        if is_sqlite:
            return sqlite_sql
        if is_mysql:
            return mysql_sql
        if is_postgres:
            return postgres_sql
        return generic_sql

    with db.engine.connect() as conn:
        if 'inventories' not in existing_tables:
            print("2.2. Erstelle Tabelle 'inventories'...")
            sql = create_table(
                """
                CREATE TABLE IF NOT EXISTS inventories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    started_by INTEGER NOT NULL,
                    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (started_by) REFERENCES users (id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS inventories (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    started_by INT NOT NULL,
                    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (started_by) REFERENCES users (id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS inventories (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    started_by INTEGER NOT NULL,
                    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (started_by) REFERENCES users (id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS inventories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    started_by INTEGER NOT NULL,
                    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (started_by) REFERENCES users (id)
                )
                """
            )
            conn.execute(text(sql))
            print("  ✓ Tabelle 'inventories' erstellt")

        if 'inventory_items' not in existing_tables:
            print("2.3. Erstelle Tabelle 'inventory_items'...")
            sql = create_table(
                """
                CREATE TABLE IF NOT EXISTS inventory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inventory_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    checked BOOLEAN NOT NULL DEFAULT 0,
                    notes TEXT,
                    location_changed BOOLEAN NOT NULL DEFAULT 0,
                    new_location VARCHAR(255),
                    condition_changed BOOLEAN NOT NULL DEFAULT 0,
                    new_condition VARCHAR(50),
                    checked_by INTEGER,
                    checked_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (inventory_id) REFERENCES inventories (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (checked_by) REFERENCES users (id),
                    UNIQUE(inventory_id, product_id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS inventory_items (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    inventory_id INT NOT NULL,
                    product_id INT NOT NULL,
                    checked BOOLEAN NOT NULL DEFAULT FALSE,
                    notes TEXT,
                    location_changed BOOLEAN NOT NULL DEFAULT FALSE,
                    new_location VARCHAR(255),
                    condition_changed BOOLEAN NOT NULL DEFAULT FALSE,
                    new_condition VARCHAR(50),
                    checked_by INT,
                    checked_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (inventory_id) REFERENCES inventories (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (checked_by) REFERENCES users (id),
                    UNIQUE KEY uq_inventory_product (inventory_id, product_id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS inventory_items (
                    id SERIAL PRIMARY KEY,
                    inventory_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    checked BOOLEAN NOT NULL DEFAULT FALSE,
                    notes TEXT,
                    location_changed BOOLEAN NOT NULL DEFAULT FALSE,
                    new_location VARCHAR(255),
                    condition_changed BOOLEAN NOT NULL DEFAULT FALSE,
                    new_condition VARCHAR(50),
                    checked_by INTEGER,
                    checked_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (inventory_id) REFERENCES inventories (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (checked_by) REFERENCES users (id),
                    CONSTRAINT uq_inventory_product UNIQUE (inventory_id, product_id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS inventory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inventory_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    checked BOOLEAN NOT NULL DEFAULT 0,
                    notes TEXT,
                    location_changed BOOLEAN NOT NULL DEFAULT 0,
                    new_location VARCHAR(255),
                    condition_changed BOOLEAN NOT NULL DEFAULT 0,
                    new_condition VARCHAR(50),
                    checked_by INTEGER,
                    checked_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (inventory_id) REFERENCES inventories (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (checked_by) REFERENCES users (id),
                    UNIQUE(inventory_id, product_id)
                )
                """
            )
            conn.execute(text(sql))
            print("  ✓ Tabelle 'inventory_items' erstellt")

        conn.commit()

    # Indizes anlegen, falls nicht vorhanden
    inspector = inspect(db.engine)

    for table_name, index_defs in [
        ('inventories', [('ix_inventories_status', ['status'])]),
        ('inventory_items', [
            ('ix_inventory_items_inventory_id', ['inventory_id']),
            ('ix_inventory_items_product_id', ['product_id'])
        ]),
    ]:
        if table_name not in inspector.get_table_names():
            continue

        existing_indexes = {idx['name'] for idx in inspector.get_indexes(table_name)}
        for index_name, columns in index_defs:
            if index_name in existing_indexes:
                continue

            try:
                columns_expr = ', '.join(columns)
                db.session.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({columns_expr})"))
                db.session.commit()
                print(f"  ✓ Index {index_name} für {table_name} erstellt")
            except Exception as exc:  # pylint: disable=broad-except
                db.session.rollback()
                print(f"  ⚠ Index {index_name} konnte nicht erstellt werden: {exc}")

    return True


def ensure_lagersystem_extension_tables():
    """Nutzt SQLAlchemy-Metadaten, um neue Lagertabellen anzulegen."""
    print("\n2.4. Lagersystem-Erweiterungen via db.create_all() sicherstellen...")
    try:
        db.create_all()
        print("  ✓ db.create_all() ausgeführt")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"  ⚠ db.create_all() konnte nicht ausgeführt werden: {exc}")
        return False

    inspector = inspect(db.engine)
    tables_to_check = [
        'product_sets',
        'product_set_items',
        'product_documents',
        'saved_filters',
        'product_favorites',
        'api_tokens'
    ]

    all_exist = True
    for table in tables_to_check:
        if table in inspector.get_table_names():
            print(f"  ✓ Tabelle '{table}' vorhanden")
        else:
            print(f"  ⚠ Tabelle '{table}' fehlt weiterhin")
            all_exist = False

    return all_exist


def create_wiki_favorites_table():
    """Erstellt die Tabelle `wiki_favorites`, falls sie fehlt."""
    inspector = inspect(db.engine)

    print("\n2.5. Erstelle 'wiki_favorites' Tabelle...")

    if 'wiki_favorites' in inspector.get_table_names():
        print("  ✓ Tabelle 'wiki_favorites' existiert bereits")
        return True

    if 'users' not in inspector.get_table_names() or 'wiki_pages' not in inspector.get_table_names():
        print("  ⚠ Abhängige Tabellen fehlen, 'wiki_favorites' wird später automatisch erstellt.")
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
        elif is_mysql:
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

        try:
            conn.execute(text(sql))
            conn.commit()
            print("  ✓ Tabelle 'wiki_favorites' erstellt")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  ❌ Fehler beim Erstellen der Tabelle: {exc}")
            return False

    try:
        db.session.execute(text("CREATE INDEX idx_wiki_favorites_user_id ON wiki_favorites(user_id)"))
        db.session.execute(text("CREATE INDEX idx_wiki_favorites_wiki_page_id ON wiki_favorites(wiki_page_id)"))
        db.session.commit()
        print("  ✓ Indizes für 'wiki_favorites' erstellt")
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        print(f"  ⚠ Indizes für 'wiki_favorites' konnten nicht erstellt werden: {exc}")

    return True


def ensure_user_language_column():
    """Stellt sicher, dass die Spalte `language` in `users` existiert."""
    inspector = inspect(db.engine)

    if 'users' not in inspector.get_table_names():
        print("\n⚠ Tabelle 'users' existiert nicht – Sprachspalte wird übersprungen.")
        return True

    columns = {col['name'] for col in inspector.get_columns('users')}
    if 'language' in columns:
        print("\n3.1. Spalte 'language' existiert bereits in 'users'.")
        return True

    print("\n3.1. Füge Spalte 'language' zu 'users' hinzu...")

    dialect = db.engine.dialect.name
    column_type = 'TEXT' if dialect == 'sqlite' else 'VARCHAR(10)'

    add_column_sql = f"ALTER TABLE users ADD COLUMN language {column_type} DEFAULT 'de' NOT NULL"

    try:
        with db.engine.connect() as conn:
            conn.execute(text(add_column_sql))
            conn.commit()
        print("  ✓ Spalte 'language' hinzugefügt.")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"  ❌ Fehler beim Hinzufügen der Sprachspalte: {exc}")
        return False

    return ensure_user_language_defaults()


def ensure_user_language_defaults():
    """Setzt Standardwerte für `language` bei bestehenden Benutzern."""
    inspector = inspect(db.engine)
    if 'users' not in inspector.get_table_names():
        return True

    columns = {col['name'] for col in inspector.get_columns('users')}
    if 'language' not in columns:
        print("⚠ Sprachspalte fehlt weiterhin – Abbruch.")
        return False

    try:
        db.session.execute(
            text("""
                UPDATE users
                SET language = 'de'
                WHERE language IS NULL OR TRIM(language) = ''
            """)
        )
        db.session.commit()
        print("  ✓ Standardsprache für bestehende Benutzer gesetzt.")
        return True
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        print(f"  ⚠ Konnte Standardsprache nicht setzen: {exc}")
        return False


def ensure_system_language_settings():
    """Legt Sprach-bezogene SystemSettings an."""
    from app.models.settings import SystemSettings  # pylint: disable=import-outside-toplevel

    defaults = [
        ('default_language', 'de', 'Standardsprache für die Benutzeroberfläche'),
        ('email_language', 'de', 'Standardsprache für System-E-Mails'),
        ('available_languages', json.dumps(["de", "en", "pt", "es", "ru"]), 'Liste der aktivierten Sprachen'),
    ]

    created_any = False

    for key, value, description in defaults:
        setting = SystemSettings.query.filter_by(key=key).first()
        if not setting:
            db.session.add(SystemSettings(key=key, value=value, description=description))
            created_any = True
            print(f"  ✓ SystemSetting '{key}' hinzugefügt.")
        else:
            updated = False
            if not setting.value:
                setting.value = value
                updated = True
            if description and not setting.description:
                setting.description = description
                updated = True
            if updated:
                created_any = True
                print(f"  ✓ SystemSetting '{key}' aktualisiert.")

    if created_any:
        db.session.commit()
    else:
        print("  ✓ Sprach-Systemeinstellungen bereits vorhanden.")

    return True


def verify_migration():
    """Prüft, ob die wichtigsten Tabellen und Felder vorhanden sind."""
    print("\n" + "=" * 60)
    print("Verifiziere Migration...")
    print("=" * 60)

    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()

    checks = [
        ('folders', ['is_dropbox', 'dropbox_token', 'dropbox_password_hash',
                     'share_enabled', 'share_token', 'share_password_hash',
                     'share_expires_at', 'share_name']),
        ('files', ['share_enabled', 'share_token', 'share_password_hash',
                   'share_expires_at', 'share_name']),
        ('borrow_transactions', ['borrow_group_id']),
        ('calendar_events', ['recurrence_type', 'recurrence_end_date', 'recurrence_interval',
                             'recurrence_days', 'parent_event_id', 'is_recurring_instance',
                             'recurrence_sequence', 'public_ical_token', 'is_public']),
        ('users', ['dashboard_config', 'oled_mode', 'show_update_notifications', 'language']),
        ('inventories', ['status', 'started_by']),
        ('inventory_items', ['inventory_id', 'product_id', 'checked']),
        ('product_sets', ['name', 'created_by']),
        ('product_documents', ['product_id', 'file_path', 'file_type']),
        ('saved_filters', ['user_id', 'filter_data']),
        ('product_favorites', ['user_id', 'product_id']),
        ('api_tokens', ['user_id', 'token']),
    ]

    all_success = True
    for table_name, required_fields in checks:
        if table_name not in table_names:
            print(f"  ⚠ Tabelle '{table_name}' existiert nicht (wird ggf. später erstellt)")
            all_success = False
            continue

        columns_after = {col['name']: col for col in inspector.get_columns(table_name)}
        missing_fields = [field for field in required_fields if field not in columns_after]

        if missing_fields:
            print(f"  ❌ Warnung: In '{table_name}' fehlen noch: {missing_fields}")
            all_success = False
        else:
            print(f"  ✓ '{table_name}': Alle Felder vorhanden")

    if 'public_calendar_feeds' in table_names:
        print("  ✓ 'public_calendar_feeds': Tabelle vorhanden")
    else:
        print("  ⚠ 'public_calendar_feeds': Tabelle fehlt (wird ggf. später erstellt)")
        all_success = False

    if 'wiki_favorites' in table_names:
        print("  ✓ 'wiki_favorites': Tabelle vorhanden")
    else:
        print("  ⚠ 'wiki_favorites': Tabelle fehlt (wird ggf. später erstellt)")
        all_success = False

    print("\n" + "=" * 60)
    if all_success:
        print("Migration erfolgreich abgeschlossen!")
    else:
        print("Migration abgeschlossen mit Warnungen!")
    print("=" * 60)

    print("\nZusammenfassung der hinzugefügten Features:")
    print("  - Version 1.5.2: Briefkasten-Felder (folders)")
    print("  - Version 1.5.6: Freigabe-Felder (folders & files)")
    print("  - Borrow Group ID: Mehrfachausleihen (borrow_transactions)")
    print("  - Kalender-Features: Wiederkehrende Termine & iCal-Feeds")
    print("  - Version 2.1.4: Dashboard-Konfiguration (users)")
    print("  - OLED-Modus & Update-Notifications (users)")
    print("  - Mehrsprachigkeit: Benutzersprache & Sprach-Systemeinstellungen")
    print("  - Lagersystem-Erweiterungen: Sets, Dokumente, Favoriten, Saved Filters, API Tokens")
    print("  - Inventur-Tool Tabellen: inventories & inventory_items")
    print("  - Wiki-Favoriten Tabelle: wiki_favorites")

    return all_success


def migrate():
    """Führt alle Migrationen aus."""
    print("=" * 60)
    print("Migration zu Version 2.1.5")
    print("Konsolidierte Migration für alle Versionen bis 2.1.5")
    print("=" * 60)

    app = create_app(os.getenv('FLASK_ENV', 'development'))

    with app.app_context():
        try:
            # 1. Version 1.5.2: Briefkasten-Felder zu 'folders'
            print("\n1.1. Version 1.5.2: Briefkasten-Felder zu 'folders'...")
            fields_config = {
                'is_dropbox': ('BOOLEAN', '0', False),
                'dropbox_token': ('VARCHAR(255)', None, True),
                'dropbox_password_hash': ('VARCHAR(255)', None, True)
            }
            create_indexes = [('idx_folders_dropbox_token', 'dropbox_token', True)]
            if not migrate_table('folders', fields_config, create_indexes):
                print("❌ Migration für 'folders' (1.5.2) fehlgeschlagen!")
                return False

            # 2. Version 1.5.6: Freigabe-Felder zu 'folders' und 'files'
            print("\n1.2. Version 1.5.6: Freigabe-Felder zu 'folders' und 'files'...")
            fields_config = {
                'share_enabled': ('BOOLEAN', '0', False),
                'share_token': ('VARCHAR(255)', None, True),
                'share_password_hash': ('VARCHAR(255)', None, True),
                'share_expires_at': ('DATETIME', None, True),
                'share_name': ('VARCHAR(255)', None, True)
            }
            if not migrate_table('folders', fields_config, [('idx_folders_share_token', 'share_token', True)]):
                print("❌ Migration für 'folders' (1.5.6) fehlgeschlagen!")
                return False
            if not migrate_table('files', fields_config, [('idx_files_share_token', 'share_token', True)]):
                print("❌ Migration für 'files' (1.5.6) fehlgeschlagen!")
                return False

            # 3. Borrow Group ID für Inventory
            print("\n1.3. Borrow Group ID für 'borrow_transactions'...")
            fields_config = {'borrow_group_id': ('VARCHAR(50)', None, True)}
            create_indexes = [('idx_borrow_transactions_borrow_group_id', 'borrow_group_id', False)]
            if not migrate_table('borrow_transactions', fields_config, create_indexes):
                print("❌ Migration für 'borrow_transactions' fehlgeschlagen!")
                return False

            # 4. Kalender-Features
            if not migrate_calendar_events():
                print("❌ Migration für 'calendar_events' fehlgeschlagen!")
                return False

            if not migrate_public_calendar_feeds():
                print("❌ Migration für 'public_calendar_feeds' fehlgeschlagen!")
                return False

            # 5. Version 2.1.4: Dashboard-Konfiguration
            print("\n1.6. Version 2.1.4: Dashboard-Konfiguration zu 'users'...")
            fields_config = {'dashboard_config': ('TEXT', None, True)}
            if not migrate_table('users', fields_config):
                print("❌ Migration für 'users' (2.1.4) fehlgeschlagen!")
                return False

            # 6. OLED-Modus & Update-Notifications
            if not migrate_user_display_settings():
                return False

            # 7. Lagersystem-Erweiterungen
            if not ensure_lagersystem_extension_tables():
                print("⚠ Lagersystem-Erweiterungen konnten nicht vollständig verifiziert werden.")

            # 8. Inventur-Tool Tabellen
            if not create_inventory_tables():
                print("❌ Inventur-Tabellen konnten nicht erstellt werden!")
                return False

            # 9. Wiki-Favoriten
            if not create_wiki_favorites_table():
                print("❌ Wiki-Favoriten konnten nicht erstellt werden!")
                return False

            # 10. Mehrsprachigkeit
            if not ensure_user_language_column():
                print("❌ Sprachspalte konnte nicht angelegt werden!")
                return False
            if not ensure_system_language_settings():
                print("❌ Sprach-Systemeinstellungen konnten nicht angelegt werden!")
                return False

            return verify_migration()

        except Exception as exc:  # pylint: disable=broad-except
            print(f"\n❌ Fehler bei der Migration: {exc}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)

