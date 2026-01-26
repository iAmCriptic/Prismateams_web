"""
Migration script for OAuth2 and Webhook tables.

Run this script to add OAuth2 and Webhook support to an existing database.
Usage: python -c "from migrations.migrate_oauth_webhooks import migrate; migrate()"
"""
import os
import sys

# Add the parent directory to the path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime


def migrate():
    """Run the migration."""
    from app import create_app, db
    from sqlalchemy import text, inspect
    
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        print("=" * 60)
        print("OAuth2 und Webhook Migration")
        print("=" * 60)
        
        # Check which tables need to be created
        tables_to_create = []
        
        if 'webhook' not in existing_tables:
            tables_to_create.append('webhook')
        else:
            print("✓ Tabelle 'webhook' existiert bereits")
            
        if 'webhook_delivery' not in existing_tables:
            tables_to_create.append('webhook_delivery')
        else:
            print("✓ Tabelle 'webhook_delivery' existiert bereits")
            
        if 'oauth2_client' not in existing_tables:
            tables_to_create.append('oauth2_client')
        else:
            print("✓ Tabelle 'oauth2_client' existiert bereits")
            
        if 'oauth2_authorization_code' not in existing_tables:
            tables_to_create.append('oauth2_authorization_code')
        else:
            print("✓ Tabelle 'oauth2_authorization_code' existiert bereits")
            
        if 'oauth2_token' not in existing_tables:
            tables_to_create.append('oauth2_token')
        else:
            print("✓ Tabelle 'oauth2_token' existiert bereits")
        
        if not tables_to_create:
            print("\n✓ Alle Tabellen existieren bereits. Migration abgeschlossen.")
            return
        
        print(f"\nErstelle {len(tables_to_create)} neue Tabelle(n): {', '.join(tables_to_create)}")
        
        # Import models to ensure they're registered
        from app.models.webhook import Webhook, WebhookDelivery
        from app.models.oauth import OAuth2Client, OAuth2AuthorizationCode, OAuth2Token
        
        # Create tables
        try:
            # Create all tables that don't exist
            db.create_all()
            
            print("\n✓ Tabellen erfolgreich erstellt:")
            for table in tables_to_create:
                print(f"  - {table}")
            
            # Create indexes if they don't exist
            print("\nErstelle Indizes...")
            
            # The indexes are already defined in the model, so create_all() handles them
            
            print("✓ Indizes erstellt")
            
            db.session.commit()
            
            print("\n" + "=" * 60)
            print("Migration erfolgreich abgeschlossen!")
            print("=" * 60)
            
            print("\nNächste Schritte:")
            print("1. Starten Sie die Anwendung neu")
            print("2. Erstellen Sie OAuth2-Clients über /settings/admin/oauth")
            print("3. Konfigurieren Sie Webhooks über /settings/admin/webhooks")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n✗ Fehler bei der Migration: {e}")
            raise


def rollback():
    """Rollback the migration (drop tables)."""
    from app import create_app, db
    from sqlalchemy import text
    
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        print("WARNUNG: Dies löscht alle OAuth2- und Webhook-Daten!")
        confirm = input("Fortfahren? (ja/nein): ")
        
        if confirm.lower() != 'ja':
            print("Abgebrochen.")
            return
        
        tables = [
            'webhook_delivery',
            'webhook',
            'oauth2_token',
            'oauth2_authorization_code',
            'oauth2_client',
        ]
        
        for table in tables:
            try:
                db.session.execute(text(f"DROP TABLE IF EXISTS {table}"))
                print(f"✓ Tabelle '{table}' gelöscht")
            except Exception as e:
                print(f"✗ Fehler beim Löschen von '{table}': {e}")
        
        db.session.commit()
        print("\nRollback abgeschlossen.")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='OAuth2 und Webhook Migration')
    parser.add_argument('--rollback', action='store_true', help='Rollback der Migration')
    
    args = parser.parse_args()
    
    if args.rollback:
        rollback()
    else:
        migrate()
