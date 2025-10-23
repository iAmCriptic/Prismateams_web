#!/usr/bin/env python3
"""
Migration script to add email confirmation fields to users table.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app import create_app, db
from sqlalchemy import text

def migrate_user_table():
    """Add email confirmation fields to users table."""
    app = create_app()
    
    with app.app_context():
        try:
            # Check if columns already exist (MySQL syntax)
            result = db.session.execute(text("SHOW COLUMNS FROM users"))
            columns = [row[0] for row in result.fetchall()]
            
            if 'confirmation_code' not in columns:
                print("Adding confirmation_code column...")
                db.session.execute(text("ALTER TABLE users ADD COLUMN confirmation_code VARCHAR(6)"))
                
            if 'confirmation_code_expires' not in columns:
                print("Adding confirmation_code_expires column...")
                db.session.execute(text("ALTER TABLE users ADD COLUMN confirmation_code_expires DATETIME"))
                
            if 'is_email_confirmed' not in columns:
                print("Adding is_email_confirmed column...")
                db.session.execute(text("ALTER TABLE users ADD COLUMN is_email_confirmed BOOLEAN DEFAULT FALSE"))
            
            db.session.commit()
            print("Migration completed successfully!")
            
        except Exception as e:
            print(f"Migration failed: {e}")
            db.session.rollback()
            return False
            
    return True

if __name__ == "__main__":
    migrate_user_table()
