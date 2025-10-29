#!/usr/bin/env python3
"""
Debug-Script für Push-Subscriptions
"""

import os
import sys
from dotenv import load_dotenv

def debug_push_subscriptions():
    """Debug Push-Subscriptions in der Datenbank."""
    print("=== Push-Subscriptions Debug ===")
    
    # Lade .env Datei
    load_dotenv()
    
    try:
        from app import create_app
        from app.models.notification import PushSubscription, User
        
        app = create_app()
        with app.app_context():
            # Alle Push-Subscriptions
            all_subs = PushSubscription.query.all()
            print(f"Gesamte Push-Subscriptions: {len(all_subs)}")
            
            # Aktive Push-Subscriptions
            active_subs = PushSubscription.query.filter_by(is_active=True).all()
            print(f"Aktive Push-Subscriptions: {len(active_subs)}")
            
            # Inaktive Push-Subscriptions
            inactive_subs = PushSubscription.query.filter_by(is_active=False).all()
            print(f"Inaktive Push-Subscriptions: {len(inactive_subs)}")
            
            # Details der aktiven Subscriptions
            if active_subs:
                print("\n=== Aktive Push-Subscriptions Details ===")
                for i, sub in enumerate(active_subs):
                    user = User.query.get(sub.user_id)
                    print(f"Subscription {i+1}:")
                    print(f"  ID: {sub.id}")
                    print(f"  User: {user.username if user else 'UNKNOWN'} (ID: {sub.user_id})")
                    print(f"  Endpoint: {sub.endpoint[:50]}...")
                    print(f"  Active: {sub.is_active}")
                    print(f"  Last Used: {sub.last_used}")
                    print(f"  Created: {sub.created_at}")
                    print()
            else:
                print("\n❌ Keine aktiven Push-Subscriptions gefunden!")
                print("Lösung:")
                print("1. Gehe zu Einstellungen → Benachrichtigungen")
                print("2. Klicke 'Push-Benachrichtigungen aktivieren'")
                print("3. Erteile Browser-Berechtigung")
                print("4. Versuche Test-Push erneut")
            
            # Benutzer mit Push-Subscriptions
            users_with_subs = User.query.join(PushSubscription).filter(
                PushSubscription.is_active == True
            ).all()
            
            print(f"\nBenutzer mit aktiven Push-Subscriptions: {len(users_with_subs)}")
            for user in users_with_subs:
                user_subs = PushSubscription.query.filter_by(
                    user_id=user.id, 
                    is_active=True
                ).count()
                print(f"  - {user.username}: {user_subs} Subscription(s)")
            
            return len(active_subs) > 0
            
    except Exception as e:
        print(f"Fehler beim Debuggen: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = debug_push_subscriptions()
    sys.exit(0 if success else 1)

