#!/usr/bin/env python3
"""
Migration Script: Fix Admin Email Permissions
Stellt sicher, dass alle Admin-Benutzer E-Mail-Berechtigungen haben.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.user import User
from app.models.email import EmailPermission

def fix_admin_email_permissions():
    """Stellt sicher, dass alle Admins E-Mail-Berechtigungen haben."""
    app = create_app()
    
    with app.app_context():
        print("🔍 Überprüfe Admin E-Mail-Berechtigungen...")
        
        # Finde alle Admin-Benutzer
        admin_users = User.query.filter_by(is_admin=True).all()
        print(f"📊 Gefunden: {len(admin_users)} Admin-Benutzer")
        
        fixed_count = 0
        for admin in admin_users:
            # Prüfe ob E-Mail-Berechtigungen existieren
            email_perm = EmailPermission.query.filter_by(user_id=admin.id).first()
            
            if not email_perm:
                print(f"⚠️  Admin {admin.email} hat keine E-Mail-Berechtigungen - erstelle sie...")
                
                # Erstelle E-Mail-Berechtigungen
                email_perm = EmailPermission(
                    user_id=admin.id,
                    can_read=True,
                    can_send=True
                )
                db.session.add(email_perm)
                fixed_count += 1
            else:
                print(f"✅ Admin {admin.email} hat bereits E-Mail-Berechtigungen")
        
        if fixed_count > 0:
            db.session.commit()
            print(f"🎉 {fixed_count} Admin E-Mail-Berechtigungen erstellt!")
        else:
            print("✅ Alle Admins haben bereits E-Mail-Berechtigungen")
        
        print("✅ Migration abgeschlossen!")

if __name__ == "__main__":
    fix_admin_email_permissions()
