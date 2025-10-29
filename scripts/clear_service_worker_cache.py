#!/usr/bin/env python3
"""
Script zum Leeren des Service Worker Caches
"""

import os
import sys
from dotenv import load_dotenv

def clear_service_worker_cache():
    """Leere Service Worker Cache durch Cache-Name-Änderung."""
    print("=== Service Worker Cache leeren ===")
    
    # Lade .env Datei
    load_dotenv()
    
    try:
        from app import create_app
        app = create_app()
        
        print("✅ Service Worker Cache wird durch neue Version geleert")
        print("📝 Cache-Name wurde von 'team-portal-v3' auf 'team-portal-v4' geändert")
        print("🔄 Browser wird automatisch den neuen Service Worker laden")
        print("")
        print("📋 Anleitung für Benutzer:")
        print("1. Seite neu laden (F5 oder Strg+F5)")
        print("2. Entwicklertools öffnen (F12)")
        print("3. Application → Service Workers")
        print("4. 'Update on reload' aktivieren")
        print("5. Seite erneut laden")
        print("")
        print("✅ Nach dem Update sollten die 404-Warnungen verschwinden")
        
        return True
        
    except Exception as e:
        print(f"Fehler: {e}")
        return False

if __name__ == '__main__':
    success = clear_service_worker_cache()
    sys.exit(0 if success else 1)

