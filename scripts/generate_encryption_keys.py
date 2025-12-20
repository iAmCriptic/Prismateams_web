#!/usr/bin/env python3
"""
Encryption Key Generator für Credentials und Music Module

Dieses Script generiert Verschlüsselungsschlüssel für:
- Credentials-Modul (credential_key.key)
- Music-Modul (music_token_key.key)

Die generierten Schlüssel müssen in der .env-Datei konfiguriert werden.
"""

from cryptography.fernet import Fernet
import base64


def generate_encryption_key():
    """Generiere einen Fernet-Verschlüsselungsschlüssel."""
    key = Fernet.generate_key()
    return key.decode('utf-8')


def main():
    """Hauptfunktion."""
    print("Encryption Key Generator für Team Portal")
    print("=" * 50)
    
    # Generiere Keys
    credential_key = generate_encryption_key()
    music_key = generate_encryption_key()
    
    print("\nGenerierte Verschlüsselungsschlüssel:")
    print("-" * 40)
    
    print(f"\n1. Credential Encryption Key:")
    print(f"   CREDENTIAL_ENCRYPTION_KEY={credential_key}")
    
    print(f"\n2. Music Token Encryption Key:")
    print(f"   MUSIC_ENCRYPTION_KEY={music_key}")
    
    print("\nKonfiguration:")
    print("-" * 20)
    print("1. Kopieren Sie die Schlüssel in Ihre .env-Datei:")
    print(f"\n   CREDENTIAL_ENCRYPTION_KEY={credential_key}")
    print(f"   MUSIC_ENCRYPTION_KEY={music_key}")
    
    print("\nWICHTIG:")
    print("- Bewahren Sie die Keys sicher auf!")
    print("- Teilen Sie die Keys niemals öffentlich!")
    print("- Verwenden Sie in der Produktion Umgebungsvariablen!")
    print("- Wenn Sie die Keys ändern, können verschlüsselte Daten nicht mehr entschlüsselt werden!")
    
    print("\n💡 Tipp:")
    print("   Sie können dieses Script jederzeit erneut ausführen, um neue Keys zu generieren.")
    print("   Beachten Sie jedoch, dass alte verschlüsselte Daten dann nicht mehr entschlüsselt werden können.")


if __name__ == '__main__':
    main()


