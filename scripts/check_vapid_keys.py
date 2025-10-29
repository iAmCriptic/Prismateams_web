#!/usr/bin/env python3
"""
Script zum Prüfen der VAPID Keys Konfiguration
"""

import os
import sys
from dotenv import load_dotenv

def check_vapid_keys():
    """Prüfe VAPID Keys Konfiguration."""
    print("=== VAPID Keys Konfiguration prüfen ===")
    
    # Lade .env Datei
    load_dotenv()
    
    # Prüfe Environment Variablen
    private_key = os.environ.get('VAPID_PRIVATE_KEY')
    public_key = os.environ.get('VAPID_PUBLIC_KEY')
    
    print(f"VAPID_PRIVATE_KEY: {'OK - Gesetzt' if private_key else 'FEHLER - Nicht gesetzt'}")
    print(f"VAPID_PUBLIC_KEY: {'OK - Gesetzt' if public_key else 'FEHLER - Nicht gesetzt'}")
    
    if not private_key or not public_key:
        print("\nFEHLER: VAPID Keys nicht konfiguriert!")
        print("Lösung:")
        print("1. Führe aus: python scripts/generate_vapid_keys.py")
        print("2. Kopiere die Keys in deine .env Datei")
        print("3. Starte die App neu")
        return False
    
    # Prüfe Key-Format
    if not private_key.startswith('MIG'):
        print("WARNUNG: VAPID_PRIVATE_KEY hat nicht das erwartete Format")
    
    if not public_key.startswith('MFkw'):
        print("WARNUNG: VAPID_PUBLIC_KEY hat nicht das erwartete Format")
    
    print("\nSUCCESS: VAPID Keys sind konfiguriert!")
    print("Push-Benachrichtigungen sollten funktionieren.")
    
    return True

if __name__ == '__main__':
    success = check_vapid_keys()
    sys.exit(0 if success else 1)
