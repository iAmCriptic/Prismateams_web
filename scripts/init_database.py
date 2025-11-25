#!/usr/bin/env python3
"""
Datenbank-Initialisierungsskript für das Team Portal.
Dieses Skript stellt sicher, dass alle Tabellen korrekt erstellt werden.
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import *

def init_database():
    """Initialisiert die Datenbank mit allen erforderlichen Tabellen."""
    print("Starte Datenbank-Initialisierung...")
    
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        try:
            print("Erstelle alle Datenbank-Tabellen...")
            db.create_all()
            print("Alle Tabellen erfolgreich erstellt/aktualisiert")
            
            # Überprüfe, ob alle erwarteten Tabellen existieren
            expected_tables = [
                'users', 'chats', 'chat_messages', 'chat_members',
                'files', 'file_versions', 'folders',
                'calendar_events', 'event_participants',
                'email_messages', 'email_attachments', 'email_permissions',
                'credentials', 'manuals', 'canvases', 'canvas_text_fields',
                'system_settings', 'whitelist_entries',
                'notification_settings', 'chat_notification_settings',
                'push_subscriptions', 'notification_logs'
            ]
            
            print("\nUeberpruefe vorhandene Tabellen...")
            inspector = db.inspect(db.engine)
            existing_tables = inspector.get_table_names()
            
            missing_tables = []
            for table in expected_tables:
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
            else:
                print(f"\nAlle {len(expected_tables)} erwarteten Tabellen sind vorhanden!")
            
            print("\nInitialisiere Standard-Einstellungen...")
            
            if not SystemSettings.query.filter_by(key='email_footer_text').first():
                footer = SystemSettings(
                    key='email_footer_text',
                    value='Mit freundlichen Gruessen\nIhr Team',
                    description='Standard-Footer fuer E-Mails'
                )
                db.session.add(footer)
                print("E-Mail-Footer-Einstellung hinzugefuegt")
            
            if not SystemSettings.query.filter_by(key='email_footer_image').first():
                footer_img = SystemSettings(
                    key='email_footer_image',
                    value='',
                    description='Footer-Bild URL fuer E-Mails'
                )
                db.session.add(footer_img)
                print("E-Mail-Footer-Bild-Einstellung hinzugefuegt")
            
            if not SystemSettings.query.filter_by(key='email_html_storage_type').first():
                html_storage = SystemSettings(
                    key='email_html_storage_type',
                    value=app.config.get('EMAIL_HTML_STORAGE_TYPE', 'LONGTEXT'),
                    description='Datenbank-Typ fuer HTML-E-Mail-Speicherung'
                )
                db.session.add(html_storage)
                print("E-Mail HTML-Speicherung konfiguriert")
            
            if not SystemSettings.query.filter_by(key='email_html_max_length').first():
                html_max_length = SystemSettings(
                    key='email_html_max_length',
                    value=str(app.config.get('EMAIL_HTML_MAX_LENGTH', 0)),
                    description='Maximale HTML-E-Mail-Laenge (0 = unbegrenzt)'
                )
                db.session.add(html_max_length)
                print("E-Mail HTML-Maximallaenge konfiguriert")
            
            main_chat = Chat.query.filter_by(is_main_chat=True).first()
            if not main_chat:
                main_chat = Chat(
                    name='Team Chat',
                    is_main_chat=True,
                    is_direct_message=False
                )
                db.session.add(main_chat)
                db.session.flush()
                print("Haupt-Chat erstellt")
                
                active_users = User.query.filter_by(is_active=True).all()
                for user in active_users:
                    member = ChatMember(
                        chat_id=main_chat.id,
                        user_id=user.id
                    )
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
    
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        try:
            user_count = User.query.count()
            chat_count = Chat.query.count()
            file_count = File.query.count()
            
            print(f"Benutzer: {user_count}")
            print(f"Chats: {chat_count}")
            print(f"Dateien: {file_count}")
            
            db.session.execute(db.text('SELECT 1'))
            print("Datenbankverbindung funktioniert")
            
            return True
            
        except Exception as e:
            print(f"Datenbank-Gesundheitscheck fehlgeschlagen: {e}")
            return False

if __name__ == '__main__':
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
