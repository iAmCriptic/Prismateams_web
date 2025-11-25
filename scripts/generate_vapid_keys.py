#!/usr/bin/env python3
"""
VAPID Key Generator für Push-Benachrichtigungen

Dieses Script generiert VAPID-Schlüssel für Web Push-Benachrichtigungen.
Die generierten Schlüssel müssen in der Anwendung konfiguriert werden.
"""

import base64
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend


def generate_vapid_keys():
    """Generiere VAPID-Schlüsselpaar."""
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    public_key = private_key.public_key()
    
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    private_key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    private_key_b64 = base64.urlsafe_b64encode(private_key_bytes).decode('utf-8').rstrip('=')
    public_key_b64 = base64.urlsafe_b64encode(public_key_bytes).decode('utf-8').rstrip('=')
    
    return {
        'private_key_pem': private_pem.decode('utf-8'),
        'public_key_pem': public_pem.decode('utf-8'),
        'private_key_b64': private_key_b64,
        'public_key_b64': public_key_b64
    }


def main():
    """Hauptfunktion."""
    print("VAPID Key Generator für Team Portal")
    print("=" * 50)
    
    keys = generate_vapid_keys()
    
    print("\nGenerierte VAPID-Schlüssel:")
    print("-" * 30)
    
    print(f"\nPrivate Key (Base64):")
    print(keys['private_key_b64'])
    
    print(f"\nPublic Key (Base64):")
    print(keys['public_key_b64'])
    
    print(f"\nPrivate Key (PEM):")
    print(keys['private_key_pem'])
    
    print(f"\nPublic Key (PEM):")
    print(keys['public_key_pem'])
    
    print("\nKonfiguration:")
    print("-" * 20)
    print("1. Kopieren Sie die Base64-Schlüssel in Ihre .env-Datei:")
    print(f"   VAPID_PRIVATE_KEY={keys['private_key_b64']}")
    print(f"   VAPID_PUBLIC_KEY={keys['public_key_b64']}")
    
    print("\n2. Aktualisieren Sie app/utils/notifications.py:")
    print(f"   VAPID_PRIVATE_KEY = \"{keys['private_key_b64']}\"")
    print(f"   VAPID_PUBLIC_KEY = \"{keys['public_key_b64']}\"")
    
    print("\n3. Aktualisieren Sie app/static/js/app.js:")
    print(f"   const applicationServerKey = urlBase64ToUint8Array('{keys['public_key_b64']}');")
    
    print("\n4. Aktualisieren Sie app/static/sw.js:")
    print(f"   VAPID_PRIVATE_KEY = \"{keys['private_key_b64']}\"")
    print(f"   VAPID_PUBLIC_KEY = \"{keys['public_key_b64']}\"")
    
    print("\nWICHTIG:")
    print("- Bewahren Sie den Private Key sicher auf!")
    print("- Teilen Sie den Private Key niemals öffentlich!")
    print("- Verwenden Sie in der Produktion Umgebungsvariablen!")
    
    with open('vapid_keys.json', 'w') as f:
        json.dump(keys, f, indent=2)
    
    print(f"\n💾 Schlüssel wurden in 'vapid_keys.json' gespeichert")
    print("   (Diese Datei sollte nicht in Git committed werden!)")


if __name__ == '__main__':
    main()
