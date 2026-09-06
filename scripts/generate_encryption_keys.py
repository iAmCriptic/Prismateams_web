#!/usr/bin/env python3
"""
Encryption Key Generator für Credentials, Mailbox und Music Module.

Die generierten Schlüssel müssen in der .env-Datei konfiguriert werden.
"""

from cryptography.fernet import Fernet


def generate_encryption_key():
    """Generiere einen Fernet-Verschlüsselungsschlüssel."""
    return Fernet.generate_key().decode('utf-8')


def main():
    print("Encryption Key Generator für Team Portal")
    print("=" * 50)

    credential_key = generate_encryption_key()
    mailbox_key = generate_encryption_key()
    music_key = generate_encryption_key()

    print("\nGenerierte Verschlüsselungsschlüssel:")
    print("-" * 40)
    print(f"\n1. Credential Encryption Key:")
    print(f"   CREDENTIAL_ENCRYPTION_KEY={credential_key}")
    print(f"\n2. Mailbox Encryption Key:")
    print(f"   MAILBOX_ENCRYPTION_KEY={mailbox_key}")
    print(f"\n3. Music Token Encryption Key:")
    print(f"   MUSIC_ENCRYPTION_KEY={music_key}")

    print("\nKonfiguration:")
    print("-" * 20)
    print("Kopieren Sie die Schlüssel in Ihre .env-Datei:")
    print(f"\n   CREDENTIAL_ENCRYPTION_KEY={credential_key}")
    print(f"   MAILBOX_ENCRYPTION_KEY={mailbox_key}")
    print(f"   MUSIC_ENCRYPTION_KEY={music_key}")

    print("\nHinweise:")
    print("- Wenn bereits Postfach-Passwörter mit dem alten DB-Key (email_enc_key)")
    print("  verschlüsselt sind: setzen Sie MAILBOX_ENCRYPTION_KEY auf den alten")
    print("  Wert aus SystemSettings, oder lassen Sie die Migration 3.4.2 den")
    print("  Hinweis ausgeben und führen Sie sie danach erneut aus.")
    print("- Keys ändern macht bestehende Ciphertexte unlesbar, sofern nicht")
    print("  vorher umgeschlüsselt wurde.")


if __name__ == '__main__':
    main()
