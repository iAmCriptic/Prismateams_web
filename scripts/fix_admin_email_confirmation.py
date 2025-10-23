#!/usr/bin/env python3
"""
Migration Script: Fix Admin Email Confirmation
Stellt sicher, dass alle Admin-Benutzer automatisch als E-Mail-bestätigt markiert werden.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.user import User

def fix_admin_email_confirmation():
    """Stellt sicher, dass alle Admins automatisch als E-Mail-bestätigt markiert werden."""
    app = create_app()
    
    with app.app_context():
        print("🔍 Überprüfe Admin E-Mail-Bestätigung...")
        
        # Finde alle Admin-Benutzer
        admin_users = User.query.filter_by(is_admin=True).all()
        print(f"📊 Gefunden: {len(admin_users)} Admin-Benutzer")
        
        fixed_count = 0
        for admin in admin_users:
            if not admin.is_email_confirmed:
                print(f"⚠️  Admin {admin.email} ist nicht E-Mail-bestätigt - setze auf bestätigt...")
                
                # Setze E-Mail-Bestätigung auf True
                admin.is_email_confirmed = True
                fixed_count += 1
            else:
                print(f"✅ Admin {admin.email} ist bereits E-Mail-bestätigt")
        
        if fixed_count > 0:
            db.session.commit()
            print(f"🎉 {fixed_count} Admin E-Mail-Bestätigungen gesetzt!")
        else:
            print("✅ Alle Admins sind bereits E-Mail-bestätigt")
        
        print("✅ Migration abgeschlossen!")

if __name__ == "__main__":
    fix_admin_email_confirmation()
