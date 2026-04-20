#!/usr/bin/env python3
"""
Datenbank-Migration: Version 2.4.0
Konsolidierte Migration — fasst die bisherigen Skripte im Ordner migrations zusammen:

- migrate_to_2.3.5.py (Stand bis 2.3.5 inkl. Passwort-Reset-Felder)
- migrate_to_2.4.1.py (inhaltlich deckungsgleich mit 2.3.5 bis auf fehlende
  password_reset_*-Schritte; diese bleiben hier aus 2.3.5 erhalten)
- migrate_security_features.py (2FA, Rate-Limiting, user_sessions)
- migrate_assessment_module.py (Bewertungsmodul, Theme-Spalte, Defaults)

WICHTIG: Tabellen/Spalten sind in den SQLAlchemy-Modellen definiert. Neuinstallationen
genügen weiterhin db.create_all(). Dieses Skript richtet sich an bestehende Datenbanken.

Aufruf:
  python migrations/migrate_to_2.4.0.py              # vollständige konsolidierte Migration
  python migrations/migrate_to_2.4.0.py --security-only   # nur 2FA/Rate-Limit/user_sessions
    (wird vom App-Start genutzt, falls Sicherheits-Spalten fehlen — ohne restliche Schritte)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.role import UserModuleRole
from app.models.email import EmailMessage
from app.models.guest import GuestShareAccess
from app.models.assessment import AssessmentAppSetting, AssessmentRole, AssessmentUser
from sqlalchemy import text, inspect

DEFAULT_ASSESSMENT_ROLES = ["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"]
DEFAULT_ASSESSMENT_SETTINGS = {
    "welcome_title": "Willkommen im Bewertungstool",
    "welcome_subtitle": "Bewerten, Ränge prüfen und Verwaltung – alles an einem Ort.",
    "module_label": "Bewertung",
    "logo_url": "",
    "ranking_sort_mode": "total",
    "ranking_active_mode": "standard",
}


def table_exists(table_name):
    """Prüft ob eine Tabelle existiert."""
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def column_exists(table_name, column_name):
    """Prüft ob eine Spalte in einer Tabelle existiert."""
    inspector = inspect(db.engine)
    if not table_exists(table_name):
        return False
    columns = {col["name"] for col in inspector.get_columns(table_name)}
    return column_name in columns


def index_exists(inspector, table_name, index_name):
    """Prüft ob ein Index bereits existiert."""
    if table_name not in inspector.get_table_names():
        return False
    indexes = inspector.get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def migrate_role_system():
    """Migration zum Rollensystem (aus migrate_to_2.3.5 / 2.4.1)."""
    print("\n" + "=" * 60)
    print("Migration: Rollensystem")
    print("=" * 60)

    inspector = inspect(db.engine)
    tables = inspector.get_table_names()

    if "user_module_roles" not in tables:
        print("[INFO] Erstelle user_module_roles Tabelle...")
        UserModuleRole.__table__.create(db.engine, checkfirst=True)
        print("[OK] Tabelle user_module_roles erstellt")
    else:
        print("[INFO] Tabelle user_module_roles existiert bereits")

    if "users" in tables:
        columns = {col["name"] for col in inspector.get_columns("users")}

        if "has_full_access" not in columns:
            print("[INFO] Füge has_full_access Spalte zu users Tabelle hinzu...")
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN has_full_access BOOLEAN DEFAULT FALSE NOT NULL"
                    )
                )
            print("[OK] Spalte has_full_access hinzugefügt")
            db.session.expire_all()
        else:
            print("[INFO] Spalte has_full_access existiert bereits")

        print("[INFO] Setze has_full_access=True für alle bestehenden Benutzer...")
        with db.engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE users SET has_full_access = TRUE WHERE has_full_access = FALSE OR has_full_access IS NULL"
                )
            )
            updated_count = result.rowcount
        print(f"[OK] {updated_count} Benutzer aktualisiert (has_full_access=True)")

    print("  ✓ Rollensystem Migration abgeschlossen")
    return True


def migrate_music_module():
    """Migration für Musikmodul."""
    print("\n" + "=" * 60)
    print("Migration: Musikmodul")
    print("=" * 60)

    inspector = inspect(db.engine)
    tables = inspector.get_table_names()

    if "music_wishes" in tables:
        columns = {col["name"] for col in inspector.get_columns("music_wishes")}
        if "public_token" in columns:
            print("[INFO] Entferne public_token Spalte aus music_wishes...")
            try:
                with db.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE music_wishes DROP COLUMN public_token"))
                print("[OK] Spalte public_token entfernt")
            except Exception as e:
                print(f"[WARNUNG] Konnte Spalte public_token nicht entfernen: {e}")

    try:
        db.create_all()
        print("[OK] Musikmodul-Tabellen erfolgreich erstellt/aktualisiert")
    except Exception as e:
        print(f"[FEHLER] Fehler beim Erstellen der Tabellen: {e}")
        raise

    print("  ✓ Musikmodul Migration abgeschlossen")
    return True


def migrate_music_wish_count():
    """Migration: wish_count auf music_wishes."""
    print("\n" + "=" * 60)
    print("Migration: Musikmodul - wish_count")
    print("=" * 60)

    inspector = inspect(db.engine)
    if "music_wishes" not in inspector.get_table_names():
        print("  ⚠ Tabelle 'music_wishes' existiert nicht (wird beim nächsten Start erstellt)")
        return True

    columns = [col["name"] for col in inspector.get_columns("music_wishes")]

    if "wish_count" not in columns:
        print("Füge wish_count Spalte hinzu...")
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE music_wishes ADD COLUMN wish_count INTEGER DEFAULT 1 NOT NULL"
                )
            )
        print("✓ Spalte hinzugefügt")
    else:
        print("✓ Spalte wish_count existiert bereits")

    print("Setze bestehende Einträge auf wish_count=1...")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE music_wishes SET wish_count = 1 WHERE wish_count IS NULL OR wish_count = 0"
            )
        )
    print("✓ Migration abgeschlossen")
    return True


def migrate_music_indexes():
    """Performance-Indizes Music-Tabellen."""
    print("\n" + "=" * 60)
    print("Migration: Music-Modul Performance-Indizes")
    print("=" * 60)

    inspector = inspect(db.engine)

    if "music_wishes" not in inspector.get_table_names():
        print("[WARNUNG] Tabelle 'music_wishes' existiert nicht - überspringe Indizes")
    else:
        print("[INFO] Füge Indizes zu music_wishes Tabelle hinzu...")

        if not index_exists(inspector, "music_wishes", "idx_wish_status"):
            with db.engine.begin() as conn:
                conn.execute(text("CREATE INDEX idx_wish_status ON music_wishes(status)"))
            print("  ✓ Index idx_wish_status erstellt")
        else:
            print("  - Index idx_wish_status existiert bereits")

        if not index_exists(inspector, "music_wishes", "idx_wish_provider_track"):
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE INDEX idx_wish_provider_track ON music_wishes(provider, track_id)"
                    )
                )
            print("  ✓ Index idx_wish_provider_track erstellt")
        else:
            print("  - Index idx_wish_provider_track existiert bereits")

        if not index_exists(inspector, "music_wishes", "idx_wish_created"):
            with db.engine.begin() as conn:
                conn.execute(text("CREATE INDEX idx_wish_created ON music_wishes(created_at)"))
            print("  ✓ Index idx_wish_created erstellt")
        else:
            print("  - Index idx_wish_created existiert bereits")

        if not index_exists(inspector, "music_wishes", "idx_wish_updated"):
            with db.engine.begin() as conn:
                conn.execute(text("CREATE INDEX idx_wish_updated ON music_wishes(updated_at)"))
            print("  ✓ Index idx_wish_updated erstellt")
        else:
            print("  - Index idx_wish_updated existiert bereits")

    print()

    if "music_queue" not in inspector.get_table_names():
        print("[WARNUNG] Tabelle 'music_queue' existiert nicht - überspringe Indizes")
    else:
        print("[INFO] Füge Indizes zu music_queue Tabelle hinzu...")

        if not index_exists(inspector, "music_queue", "idx_queue_status"):
            with db.engine.begin() as conn:
                conn.execute(text("CREATE INDEX idx_queue_status ON music_queue(status)"))
            print("  ✓ Index idx_queue_status erstellt")
        else:
            print("  - Index idx_queue_status existiert bereits")

        if not index_exists(inspector, "music_queue", "idx_queue_status_position"):
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE INDEX idx_queue_status_position ON music_queue(status, position)"
                    )
                )
            print("  ✓ Index idx_queue_status_position erstellt")
        else:
            print("  - Index idx_queue_status_position existiert bereits")

        if not index_exists(inspector, "music_queue", "idx_queue_wish_id"):
            with db.engine.begin() as conn:
                conn.execute(text("CREATE INDEX idx_queue_wish_id ON music_queue(wish_id)"))
            print("  ✓ Index idx_queue_wish_id erstellt")
        else:
            print("  - Index idx_queue_wish_id existiert bereits")

    print("  ✓ Music-Modul Indizes Migration abgeschlossen")
    return True


def migrate_preferred_layout():
    """preferred_layout auf users."""
    print("\n" + "=" * 60)
    print("Migration: preferred_layout Spalte")
    print("=" * 60)

    inspector = inspect(db.engine)

    if "users" not in inspector.get_table_names():
        print("[WARNUNG] Tabelle 'users' existiert nicht")
        return False

    columns = {col["name"] for col in inspector.get_columns("users")}

    if "preferred_layout" not in columns:
        print("[INFO] Füge preferred_layout Spalte zu users Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                ALTER TABLE users
                ADD COLUMN preferred_layout VARCHAR(20) DEFAULT 'auto' NOT NULL
            """
                )
            )
        print("[OK] Spalte preferred_layout hinzugefügt")

        print("[INFO] Setze preferred_layout='auto' für alle bestehenden Benutzer...")
        with db.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                UPDATE users
                SET preferred_layout = 'auto'
                WHERE preferred_layout IS NULL
            """
                )
            )
            updated_count = result.rowcount
        print(f"[OK] {updated_count} Benutzer aktualisiert")
    else:
        print("[INFO] Spalte preferred_layout existiert bereits")

    print("  ✓ preferred_layout Migration abgeschlossen")
    return True


def migrate_email_attachments_filename():
    """email_attachments.filename auf VARCHAR(500)."""
    print("\n" + "=" * 60)
    print("Migration: email_attachments filename-Feld Erweiterung")
    print("=" * 60)

    if "email_attachments" not in inspect(db.engine).get_table_names():
        print("Tabelle 'email_attachments' existiert nicht. Migration übersprungen.")
        return True

    result = db.session.execute(
        text(
            """
        SELECT CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'email_attachments'
        AND COLUMN_NAME = 'filename'
    """
        )
    )
    current_length = result.fetchone()

    if current_length:
        current_length = current_length[0]
        print(f"Aktuelle Feldgröße: {current_length} Zeichen")

        if current_length and current_length >= 500:
            print("Feld ist bereits ausreichend groß (>= 500 Zeichen). Migration nicht erforderlich.")
            return True

    print("Erweitere filename-Feld auf VARCHAR(500)...")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
            ALTER TABLE email_attachments
            MODIFY filename VARCHAR(500) NOT NULL
        """
            )
        )
    print("✓ Feld erfolgreich auf VARCHAR(500) erweitert")

    print("  ✓ email_attachments filename Migration abgeschlossen")
    return True


def migrate_mark_sent_emails_as_read():
    """Sent-Ordner als gelesen markieren."""
    print("\n" + "=" * 60)
    print("Migration: Markiere E-Mails im Sent-Ordner als gelesen")
    print("=" * 60)

    sent_folders = ["Sent", "Sent Messages"]
    total_updated = 0
    for folder_name in sent_folders:
        emails = (
            EmailMessage.query.filter_by(folder=folder_name).filter_by(is_read=False).all()
        )

        count = len(emails)
        if count > 0:
            print(f"Markiere {count} E-Mails im Ordner '{folder_name}' als gelesen...")

            for email in emails:
                email.is_read = True
                email.is_sent = True

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
    """Buchungsmodul-Tabellen und booking_forms-Spalten."""
    print("\n" + "=" * 60)
    print("Migration: Buchungsmodul")
    print("=" * 60)

    print("Erstelle alle Buchungsmodul-Tabellen...")
    try:
        db.create_all()
        print("  ✓ Buchungsmodul-Tabellen erstellt/aktualisiert")
    except Exception as e:
        print(f"  ⚠ Fehler beim Erstellen der Tabellen: {e}")

    if table_exists("booking_forms"):
        if not column_exists("booking_forms", "secondary_logo_path"):
            print("  - Füge Spalte secondary_logo_path zu booking_forms hinzu...")
            db.session.execute(
                text("ALTER TABLE booking_forms ADD COLUMN secondary_logo_path VARCHAR(500)")
            )
            db.session.commit()
            print("    ✓ Spalte secondary_logo_path hinzugefügt")

        if not column_exists("booking_forms", "pdf_application_text"):
            print("  - Füge Spalte pdf_application_text zu booking_forms hinzu...")
            db.session.execute(
                text("ALTER TABLE booking_forms ADD COLUMN pdf_application_text TEXT")
            )
            db.session.commit()
            print("    ✓ Spalte pdf_application_text hinzugefügt")

        if not column_exists("booking_forms", "pdf_footer_text"):
            print("  - Füge Spalte pdf_footer_text zu booking_forms hinzu...")
            db.session.execute(text("ALTER TABLE booking_forms ADD COLUMN pdf_footer_text TEXT"))
            db.session.commit()
            print("    ✓ Spalte pdf_footer_text hinzugefügt")

    print("  ✓ Buchungsmodul Migration abgeschlossen")
    return True


def migrate_excalidraw():
    """Excalidraw / canvases."""
    print("\n" + "=" * 60)
    print("Migration: Excalidraw Integration")
    print("=" * 60)

    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()

    for table_name in ["canvas_text_fields", "canvas_elements"]:
        if table_name in existing_tables:
            try:
                print(f"🗑️  Lösche alte Tabelle: {table_name}")
                db.session.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
                db.session.commit()
                print(f"   ✓ Tabelle '{table_name}' gelöscht")
            except Exception as e:
                print(f"   ⚠ Fehler beim Löschen von '{table_name}': {e}")
                db.session.rollback()

    if "canvases" in existing_tables:
        try:
            print("📝 Aktualisiere canvases-Tabelle...")

            columns = [col["name"] for col in inspector.get_columns("canvases")]

            if "excalidraw_data" not in columns:
                print("   + Füge Spalte 'excalidraw_data' hinzu...")
                db.session.execute(text("ALTER TABLE canvases ADD COLUMN excalidraw_data TEXT NULL"))
                db.session.commit()
                print("   ✓ Spalte 'excalidraw_data' hinzugefügt")

            if "room_id" not in columns:
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
    """Gast-Felder auf users."""
    print("\n" + "=" * 60)
    print("Migration: Gast-Account-Felder zum User-Modell")
    print("=" * 60)

    inspector = inspect(db.engine)

    if "users" not in inspector.get_table_names():
        print("[WARNUNG] Tabelle 'users' existiert nicht")
        return False

    columns = {col["name"] for col in inspector.get_columns("users")}

    if "is_guest" not in columns:
        print("[INFO] Füge is_guest Spalte zu users Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN is_guest BOOLEAN DEFAULT FALSE NOT NULL")
            )
        print("[OK] Spalte is_guest hinzugefügt")
    else:
        print("[INFO] Spalte is_guest existiert bereits")

    if "guest_expires_at" not in columns:
        print("[INFO] Füge guest_expires_at Spalte zu users Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN guest_expires_at DATETIME NULL"))
        print("[OK] Spalte guest_expires_at hinzugefügt")
    else:
        print("[INFO] Spalte guest_expires_at existiert bereits")

    if "guest_username" not in columns:
        print("[INFO] Füge guest_username Spalte zu users Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN guest_username VARCHAR(100) NULL"))
        print("[OK] Spalte guest_username hinzugefügt")
    else:
        print("[INFO] Spalte guest_username existiert bereits")

    print("[INFO] Setze is_guest=False für alle bestehenden Benutzer...")
    with db.engine.begin() as conn:
        result = conn.execute(text("UPDATE users SET is_guest = FALSE WHERE is_guest IS NULL"))
        updated_count = result.rowcount
    print(f"[OK] {updated_count} Benutzer aktualisiert (is_guest=FALSE)")

    print("  ✓ Gast-Account-Felder Migration abgeschlossen")
    return True


def migrate_guest_share_access_table():
    """Tabelle guest_share_access."""
    print("\n" + "=" * 60)
    print("Migration: GuestShareAccess Tabelle")
    print("=" * 60)

    inspector = inspect(db.engine)
    tables = inspector.get_table_names()

    if "guest_share_access" not in tables:
        print("[INFO] Erstelle guest_share_access Tabelle...")
        GuestShareAccess.__table__.create(db.engine, checkfirst=True)
        print("[OK] Tabelle guest_share_access erstellt")
    else:
        print("[INFO] Tabelle guest_share_access existiert bereits")

    print("  ✓ GuestShareAccess Tabelle Migration abgeschlossen")
    return True


def migrate_must_change_password():
    """must_change_password auf users."""
    print("\n" + "=" * 60)
    print("Migration: must_change_password Spalte")
    print("=" * 60)

    inspector = inspect(db.engine)

    if "users" not in inspector.get_table_names():
        print("[WARNUNG] Tabelle 'users' existiert nicht")
        return False

    if not column_exists("users", "must_change_password"):
        print("[INFO] Füge must_change_password Spalte zu users Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                ALTER TABLE users
                ADD COLUMN must_change_password BOOLEAN DEFAULT FALSE NOT NULL
            """
                )
            )
        print("[OK] Spalte must_change_password hinzugefügt")

        print("[INFO] Setze must_change_password=FALSE für alle bestehenden Benutzer...")
        with db.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                UPDATE users
                SET must_change_password = FALSE
                WHERE must_change_password IS NULL
            """
                )
            )
            updated_count = result.rowcount
        print(f"[OK] {updated_count} Benutzer aktualisiert (must_change_password=FALSE)")
    else:
        print("[INFO] Spalte must_change_password existiert bereits")

    print("  ✓ must_change_password Migration abgeschlossen")
    return True


def migrate_contacts_table():
    """Tabelle contacts."""
    print("\n" + "=" * 60)
    print("Migration: Erstelle contacts Tabelle")
    print("=" * 60)

    if table_exists("contacts"):
        print("✓ Tabelle 'contacts' existiert bereits. Migration übersprungen.")
        return True

    print("Erstelle Tabelle 'contacts'...")

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
            CREATE TABLE contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL,
                phone VARCHAR(50),
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER NOT NULL,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        """
            )
        )
        print("Erstelle Indizes...")
        conn.execute(text("CREATE INDEX idx_contacts_email ON contacts(email)"))
        conn.execute(text("CREATE INDEX idx_contacts_name ON contacts(name)"))
    print("✓ Migration erfolgreich abgeschlossen!")

    print("  ✓ contacts Tabelle Migration abgeschlossen")
    return True


def migrate_password_reset_fields():
    """Passwort-Reset-Felder auf users."""
    print("\n" + "=" * 60)
    print("Migration: Passwort-Reset-Felder")
    print("=" * 60)

    inspector = inspect(db.engine)

    if "users" not in inspector.get_table_names():
        print("[WARNUNG] Tabelle 'users' existiert nicht")
        return False

    columns = {col["name"] for col in inspector.get_columns("users")}

    if "password_reset_code" not in columns:
        print("[INFO] Füge password_reset_code Spalte zu users Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN password_reset_code VARCHAR(6) NULL"))
        print("[OK] Spalte password_reset_code hinzugefügt")
    else:
        print("[INFO] Spalte password_reset_code existiert bereits")

    if "password_reset_code_expires" not in columns:
        print("[INFO] Füge password_reset_code_expires Spalte zu users Tabelle hinzu...")
        with db.engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN password_reset_code_expires DATETIME NULL")
            )
        print("[OK] Spalte password_reset_code_expires hinzugefügt")
    else:
        print("[INFO] Spalte password_reset_code_expires existiert bereits")

    print("  ✓ Passwort-Reset-Felder Migration abgeschlossen")
    return True


def migrate_security_features():
    """Aus migrate_security_features.py: 2FA-Spalten, Login-Throttling, user_sessions."""
    print("\n" + "=" * 60)
    print("Datenbank-Migration: Sicherheitsfeatures")
    print("=" * 60)

    inspector = inspect(db.engine)
    db_type = db.engine.dialect.name
    print(f"   [INFO] Datenbanktyp: {db_type}")

    new_columns = [
        ("totp_secret", "VARCHAR", None),
        ("totp_enabled", "BOOLEAN", False),
        ("password_changed_at", "DATETIME", None),
        ("failed_login_attempts", "INTEGER", 0),
        ("failed_login_until", "DATETIME", None),
    ]

    print("\n1. Prüfe users-Tabelle...")
    if not table_exists("users"):
        print("   FEHLER: users-Tabelle existiert nicht!")
        return False
    print("   [OK] users-Tabelle gefunden")

    print("\n2. Füge neue Spalten zur users-Tabelle hinzu...")
    added_columns = []

    for column_name, column_type, default_value in new_columns:
        if column_exists("users", column_name):
            print(f"   - {column_name}: bereits vorhanden")
        else:
            try:
                alter_sql = None
                if db_type == "mysql":
                    if default_value is None:
                        if column_type == "VARCHAR":
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} VARCHAR(255) NULL"
                        elif column_type == "DATETIME":
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} DATETIME NULL"
                        elif column_type == "BOOLEAN":
                            alter_sql = (
                                f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN NOT NULL DEFAULT 0"
                            )
                        elif column_type == "INTEGER":
                            alter_sql = (
                                f"ALTER TABLE users ADD COLUMN {column_name} INTEGER NOT NULL DEFAULT 0"
                            )
                    else:
                        if column_type == "BOOLEAN":
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN NOT NULL DEFAULT {1 if default_value else 0}"
                        elif column_type == "INTEGER":
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} INTEGER NOT NULL DEFAULT {default_value}"
                        else:
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} {column_type} NOT NULL DEFAULT '{default_value}'"
                elif db_type == "sqlite":
                    if default_value is None:
                        if column_type == "VARCHAR":
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} VARCHAR(255)"
                        elif column_type == "DATETIME":
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} DATETIME"
                        elif column_type == "BOOLEAN":
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN DEFAULT 0"
                        elif column_type == "INTEGER":
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} INTEGER DEFAULT 0"
                    else:
                        if column_type == "BOOLEAN":
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN DEFAULT {1 if default_value else 0}"
                        elif column_type == "INTEGER":
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} INTEGER DEFAULT {default_value}"
                        else:
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column_name} {column_type} DEFAULT '{default_value}'"

                if alter_sql is None:
                    print(
                        f"   - {column_name}: Unbekannter Datenbanktyp {db_type} oder Spaltentyp {column_type}, ueberspringe"
                    )
                    continue

                db.session.execute(text(alter_sql))
                db.session.commit()
                print(f"   [OK] {column_name}: hinzugefuegt")
                added_columns.append(column_name)
            except Exception as e:
                print(f"   [FEHLER] {column_name}: Fehler - {e}")
                db.session.rollback()

    print("\n3. Prüfe user_sessions-Tabelle...")
    if table_exists("user_sessions"):
        print("   [OK] user_sessions-Tabelle bereits vorhanden")
    else:
        print("   - Erstelle user_sessions-Tabelle...")
        try:
            if db_type == "mysql":
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
            elif db_type == "sqlite":
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
            else:
                print(f"   ✗ Unbekannter Datenbanktyp {db_type}, überspringe Tabellenerstellung")
                return False

            db.session.execute(text(create_table_sql))
            db.session.commit()

            if db_type == "sqlite":
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id)",
                    "CREATE INDEX IF NOT EXISTS idx_user_sessions_session_id ON user_sessions(session_id)",
                    "CREATE INDEX IF NOT EXISTS idx_user_sessions_is_active ON user_sessions(is_active)",
                ]
                for index_sql in indexes:
                    try:
                        db.session.execute(text(index_sql))
                    except Exception:
                        pass
                db.session.commit()

            print("   [OK] user_sessions-Tabelle erstellt")
        except Exception as e:
            print(f"   [FEHLER] Fehler beim Erstellen der user_sessions-Tabelle: {e}")
            db.session.rollback()
            return False

    print("\n" + "=" * 60)
    if added_columns:
        print(f"[OK] Sicherheitsmigration: {len(added_columns)} Spalte(n) hinzugefuegt.")
    else:
        print("[OK] Sicherheitsmigration: Alle users-Spalten waren bereits vorhanden.")
    print("=" * 60)
    return True


def _ensure_assessment_theme_column():
    inspector = inspect(db.engine)
    if "ass_users" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("ass_users")}
    if "theme_mode" in columns:
        return
    stmt = "ALTER TABLE ass_users ADD COLUMN theme_mode VARCHAR(16) NOT NULL DEFAULT 'light'"
    with db.engine.begin() as connection:
        connection.execute(text(stmt))


def migrate_assessment_module():
    """Aus migrate_assessment_module.py."""
    print("\n" + "=" * 60)
    print("Migration: Assessment-Modul")
    print("=" * 60)

    db.create_all()
    _ensure_assessment_theme_column()

    role_map = {}
    for role_name in DEFAULT_ASSESSMENT_ROLES:
        role = AssessmentRole.query.filter_by(name=role_name).first()
        if not role:
            role = AssessmentRole(name=role_name)
            db.session.add(role)
            db.session.flush()
        role_map[role_name] = role

    admin = AssessmentUser.query.filter_by(username="admin").first()
    if not admin:
        admin = AssessmentUser(
            username="admin",
            display_name="Administrator",
            is_admin=True,
            must_change_password=True,
            is_active=True,
        )
        admin.set_password("password")
        db.session.add(admin)
        db.session.flush()

    if role_map["Administrator"] not in admin.roles:
        admin.roles.append(role_map["Administrator"])

    for key, value in DEFAULT_ASSESSMENT_SETTINGS.items():
        setting = AssessmentAppSetting.query.filter_by(setting_key=key).first()
        if not setting:
            db.session.add(AssessmentAppSetting(setting_key=key, setting_value=value))

    db.session.commit()
    print("[OK] Assessment module migration erfolgreich ausgefuehrt")
    return True


def migrate(security_only: bool = False):
    """Führt alle konsolidierten Migrationen aus (Reihenfolge: Kern → Sicherheit → Assessment).

    Mit security_only=True nur migrate_security_features() — für den automatischen Start,
    damit keine destruktiven Schritte (z. B. Excalidraw) bei fehlenden Sicherheits-Spalten laufen.
    """
    print("=" * 60)
    print("Datenbank-Migration: Version 2.4.0 (konsolidiert)")
    print("=" * 60)

    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        try:
            if security_only:
                print("\n[Modus: --security-only]\n")
                ok = migrate_security_features()
                if ok:
                    print("\n✅ Sicherheitsmigration abgeschlossen.")
                return ok

            steps = [
                ("Rollensystem", migrate_role_system),
                ("Musikmodul", migrate_music_module),
                ("Musikmodul wish_count", migrate_music_wish_count),
                ("Music-Indizes", migrate_music_indexes),
                ("preferred_layout", migrate_preferred_layout),
                ("email_attachments filename", migrate_email_attachments_filename),
                ("Sent-E-Mails", migrate_mark_sent_emails_as_read),
                ("Buchungsmodul", migrate_booking_module),
                ("Excalidraw", migrate_excalidraw),
                ("Gast-Account-Felder", migrate_guest_account_fields),
                ("GuestShareAccess", migrate_guest_share_access_table),
                ("must_change_password", migrate_must_change_password),
                ("contacts", migrate_contacts_table),
                ("Passwort-Reset-Felder", migrate_password_reset_fields),
                ("Sicherheitsfeatures", migrate_security_features),
                ("Assessment-Modul", migrate_assessment_module),
            ]
            total = len(steps)
            for i, (label, fn) in enumerate(steps, start=1):
                print(f"\n[{i}/{total}] {label}...")
                if not fn():
                    print(f"❌ Migration fehlgeschlagen: {label}")
                    return False

            print()
            print("=" * 60)
            print("✅ Alle Migrationen erfolgreich abgeschlossen!")
            print("=" * 60)
            print()
            print("Die Datenbank wurde erfolgreich auf Version 2.4.0 (konsolidiert) aktualisiert.")
            return True

        except Exception as e:
            print(f"\n❌ Fehler bei der Migration: {e}")
            import traceback

            traceback.print_exc()
            db.session.rollback()
            return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PrismaTeams DB-Migration 2.4.0 (konsolidiert)")
    parser.add_argument(
        "--security-only",
        action="store_true",
        help="Nur Sicherheits-Spalten und user_sessions (idempotent, für Auto-Update beim Start)",
    )
    args = parser.parse_args()
    success = migrate(security_only=args.security_only)
    sys.exit(0 if success else 1)
