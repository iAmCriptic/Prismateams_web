#!/usr/bin/env python3
"""
Datenbank-Initialisierungsskript für das Team Portal.
Stellt sicher, dass alle Tabellen korrekt erstellt werden (Fresh-Install + Repair).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Keine Background-Jobs / kein doppeltes Auto-Migrate während Init
os.environ.setdefault("PRISMATEAMS_SKIP_BACKGROUND_JOBS", "1")
os.environ.setdefault("PRISMATEAMS_FORCE_SCHEMA_INIT", "1")

from app import create_app, db
from app.models import *
from app.utils.schema_init import CRITICAL_TABLES, ensure_all_tables


def init_database():
    """Initialisiert die Datenbank mit allen erforderlichen Tabellen."""
    print("Starte Datenbank-Initialisierung...")

    config_name = os.getenv("FLASK_ENV", "production")
    app = create_app(config_name)

    with app.app_context():
        try:
            print("Erstelle / prüfe alle Datenbank-Tabellen...")
            ok, missing = ensure_all_tables(db)
            if not ok:
                print(f"\nFEHLER: Kritische Tabellen fehlen noch: {', '.join(missing)}")
                return False

            # Migrationen (create_app hat sie ggf. schon wegen RUNNING_MIGRATIONS übersprungen)
            if not os.getenv("PRISMATEAMS_RUNNING_MIGRATIONS"):
                try:
                    from app.utils.auto_migrate import run_pending_migrations

                    run_pending_migrations(db)
                    ensure_all_tables(db)
                except Exception as mig_err:
                    print(f"[WARNUNG] Migrationen: {mig_err}")

            print("\nUeberpruefe kritische Tabellen...")
            from sqlalchemy import inspect as sa_inspect

            inspector = sa_inspect(db.engine)
            existing_tables = set(inspector.get_table_names())

            missing_tables = []
            for table in CRITICAL_TABLES:
                if table == "schema_migrations":
                    # wird von auto_migrate angelegt
                    if table in existing_tables:
                        print(f"OK: {table}")
                    else:
                        print(f"FEHLT (optional bis erste Migration): {table}")
                    continue
                if table in existing_tables:
                    print(f"OK: {table}")
                else:
                    print(f"FEHLT: {table}")
                    missing_tables.append(table)

            if missing_tables:
                print(f"\nWARNUNG: {len(missing_tables)} Tabellen fehlen:")
                for table in missing_tables:
                    print(f"   - {table}")
                return False

            print(f"\nAlle kritischen Tabellen sind vorhanden ({len(CRITICAL_TABLES)} geprüft)!")

            print("\nInitialisiere Standard-Einstellungen...")

            if not SystemSettings.query.filter_by(key="email_footer_text").first():
                footer = SystemSettings(
                    key="email_footer_text",
                    value="Mit freundlichen Gruessen\nIhr Team",
                    description="Standard-Footer fuer E-Mails",
                )
                db.session.add(footer)
                print("E-Mail-Footer-Einstellung hinzugefuegt")

            if not SystemSettings.query.filter_by(key="email_footer_image").first():
                footer_img = SystemSettings(
                    key="email_footer_image",
                    value="",
                    description="Footer-Bild URL fuer E-Mails",
                )
                db.session.add(footer_img)
                print("E-Mail-Footer-Bild-Einstellung hinzugefuegt")

            if not SystemSettings.query.filter_by(key="email_html_storage_type").first():
                html_storage = SystemSettings(
                    key="email_html_storage_type",
                    value=app.config.get("EMAIL_HTML_STORAGE_TYPE", "LONGTEXT"),
                    description="Datenbank-Typ fuer HTML-E-Mail-Speicherung",
                )
                db.session.add(html_storage)
                print("E-Mail HTML-Speicherung konfiguriert")

            if not SystemSettings.query.filter_by(key="email_html_max_length").first():
                html_max_length = SystemSettings(
                    key="email_html_max_length",
                    value=str(app.config.get("EMAIL_HTML_MAX_LENGTH", 0)),
                    description="Maximale HTML-E-Mail-Laenge (0 = unbegrenzt)",
                )
                db.session.add(html_max_length)
                print("E-Mail HTML-Maximallaenge konfiguriert")

            main_chat = Chat.query.filter_by(is_main_chat=True).first()
            if not main_chat:
                main_chat = Chat(
                    name="Team Chat",
                    is_main_chat=True,
                    is_direct_message=False,
                )
                db.session.add(main_chat)
                db.session.flush()
                print("Haupt-Chat erstellt")

                active_users = User.query.filter_by(is_active=True).all()
                for user in active_users:
                    member = ChatMember(chat_id=main_chat.id, user_id=user.id)
                    db.session.add(member)
                print(f"{len(active_users)} Benutzer zum Haupt-Chat hinzugefuegt")

            db.session.commit()
            print("\nAlle Aenderungen gespeichert")
            print("\nDatenbank-Initialisierung erfolgreich abgeschlossen!")
            return True

        except Exception as e:
            print(f"\nFehler bei der Datenbank-Initialisierung: {e}")
            db.session.rollback()
            return False


def check_database_health():
    """Ueberprueft die Gesundheit der Datenbank."""
    print("\nUeberpruefe Datenbank-Gesundheit...")

    config_name = os.getenv("FLASK_ENV", "production")
    app = create_app(config_name)

    with app.app_context():
        try:
            user_count = User.query.count()
            chat_count = Chat.query.count()
            file_count = File.query.count()

            print(f"Benutzer: {user_count}")
            print(f"Chats: {chat_count}")
            print(f"Dateien: {file_count}")

            ok, missing = ensure_all_tables(db)
            if not ok:
                print(f"Kritische Tabellen fehlen: {', '.join(missing)}")
                return False

            db.session.execute(db.text("SELECT 1"))
            print("Datenbankverbindung funktioniert")
            return True

        except Exception as e:
            print(f"Datenbank-Gesundheitscheck fehlgeschlagen: {e}")
            return False


if __name__ == "__main__":
    print("=" * 60)
    print("TEAM PORTAL - DATENBANK-INITIALISIERUNG")
    print("=" * 60)

    success = init_database()

    if success:
        health_ok = check_database_health()

        if health_ok:
            print("\nDatenbank ist vollstaendig eingerichtet und funktionsfaehig!")
            sys.exit(0)
        else:
            print("\nDatenbank ist eingerichtet, aber es gibt Gesundheitsprobleme.")
            sys.exit(1)
    else:
        print("\nDatenbank-Initialisierung fehlgeschlagen!")
        sys.exit(1)
