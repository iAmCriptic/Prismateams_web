#!/usr/bin/env python3
"""
Migration script to add bidirectional IMAP sync support.
This script adds the new IMAP tracking columns to email_messages table.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.email import EmailMessage
from datetime import datetime

def migrate_bidirectional_sync():
    """Add bidirectional IMAP sync support."""
    app = create_app()
    
    with app.app_context():
        try:
            print("Starting bidirectional IMAP sync migration...")
            
            # Check if new columns already exist
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('email_messages')]
            
            # Add imap_uid column if it doesn't exist
            if 'imap_uid' not in columns:
                print("Adding imap_uid column to email_messages table...")
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE email_messages ADD COLUMN imap_uid VARCHAR(100) NULL"))
                    conn.commit()
                print("imap_uid column added successfully")
            else:
                print("imap_uid column already exists")
            
            # Add last_imap_sync column if it doesn't exist
            if 'last_imap_sync' not in columns:
                print("Adding last_imap_sync column to email_messages table...")
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE email_messages ADD COLUMN last_imap_sync DATETIME NULL"))
                    conn.commit()
                print("last_imap_sync column added successfully")
            else:
                print("last_imap_sync column already exists")
            
            # Add is_deleted_imap column if it doesn't exist
            if 'is_deleted_imap' not in columns:
                print("Adding is_deleted_imap column to email_messages table...")
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE email_messages ADD COLUMN is_deleted_imap BOOLEAN DEFAULT FALSE NOT NULL"))
                    conn.commit()
                print("is_deleted_imap column added successfully")
            else:
                print("is_deleted_imap column already exists")
            
            # Update existing emails with default values
            print("Updating existing emails with default values...")
            existing_emails = EmailMessage.query.filter_by(imap_uid=None).all()
            for email in existing_emails:
                email.is_deleted_imap = False
                email.last_imap_sync = datetime.utcnow()
            
            db.session.commit()
            print(f"Updated {len(existing_emails)} emails with default values")
            
            print("Bidirectional IMAP sync migration completed successfully!")
            
        except Exception as e:
            print(f"Migration failed: {str(e)}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    migrate_bidirectional_sync()

