#!/usr/bin/env python3
"""
Migration script to add folder support to email system.
This script adds the folder column to email_messages table and creates the email_folders table.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.email import EmailMessage, EmailFolder
from datetime import datetime

def migrate_email_folders():
    """Add folder support to email system."""
    app = create_app()
    
    with app.app_context():
        try:
            print("Starting email folder migration...")
            
            # Check if folder column already exists
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('email_messages')]
            
            if 'folder' not in columns:
                print("Adding folder column to email_messages table...")
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE email_messages ADD COLUMN folder VARCHAR(100) DEFAULT 'INBOX' NOT NULL"))
                    conn.commit()
                print("Folder column added successfully")
            else:
                print("Folder column already exists")
            
            # Create email_folders table if it doesn't exist
            inspector = db.inspect(db.engine)
            if not inspector.has_table('email_folders'):
                print("Creating email_folders table...")
                db.create_all()
                print("email_folders table created successfully")
            else:
                print("email_folders table already exists")
            
            # Update existing emails to have INBOX folder
            print("Updating existing emails to INBOX folder...")
            existing_emails = EmailMessage.query.filter_by(folder=None).all()
            for email in existing_emails:
                email.folder = 'INBOX'
            
            db.session.commit()
            print(f"Updated {len(existing_emails)} emails to INBOX folder")
            
            # Create default folders if they don't exist
            default_folders = [
                {'name': 'INBOX', 'display_name': 'Posteingang', 'folder_type': 'standard', 'is_system': True},
                {'name': 'Sent', 'display_name': 'Gesendet', 'folder_type': 'standard', 'is_system': True},
                {'name': 'Drafts', 'display_name': 'Entwürfe', 'folder_type': 'standard', 'is_system': True},
                {'name': 'Trash', 'display_name': 'Papierkorb', 'folder_type': 'standard', 'is_system': True},
                {'name': 'Spam', 'display_name': 'Spam', 'folder_type': 'standard', 'is_system': True},
                {'name': 'Archive', 'display_name': 'Archiv', 'folder_type': 'standard', 'is_system': True}
            ]
            
            created_folders = 0
            for folder_data in default_folders:
                existing_folder = EmailFolder.query.filter_by(name=folder_data['name']).first()
                if not existing_folder:
                    folder = EmailFolder(**folder_data)
                    db.session.add(folder)
                    created_folders += 1
                    print(f"Created default folder: {folder_data['display_name']}")
            
            if created_folders > 0:
                db.session.commit()
                print(f"Created {created_folders} default folders")
            else:
                print("Default folders already exist")
            
            print("Email folder migration completed successfully!")
            
        except Exception as e:
            print(f"Migration failed: {str(e)}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    migrate_email_folders()
