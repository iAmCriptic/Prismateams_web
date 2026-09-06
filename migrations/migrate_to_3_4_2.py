"""
Portal 3.4.2: Mailbox-Fernet-Key aus Env (MAILBOX_ENCRYPTION_KEY).

- Re-encryptiert smtp/imap_password_enc auf den Env-Key (falls gesetzt)
- Entfernt Legacy-SystemSettings email_enc_key nach erfolgreicher Migration
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def run(db=None, report=None):
    if db is None:
        from app import create_app, db as _db
        app = create_app()
        ctx = app.app_context()
        ctx.push()
        db = _db
    else:
        ctx = None

    class _Nop:
        def note_ok(self, *a, **k): pass
        def note_warn(self, *a, **k): pass
        def note_skip(self, *a, **k): pass
        def note_error(self, *a, **k): pass

    report = report or _Nop()

    try:
        from cryptography.fernet import Fernet

        from app.models.email import Mailbox
        from app.models.settings import SystemSettings
        from app.utils.encryption import read_encryption_key
        from app.utils.multi_mailboxes import (
            ENC_KEY_SETTING,
            _encryption_key,
            _encryption_key_candidates,
            decrypt_password,
            encrypt_password,
        )

        env_key = read_encryption_key('MAILBOX_ENCRYPTION_KEY')
        if not env_key:
            legacy = SystemSettings.query.filter_by(key=ENC_KEY_SETTING).first()
            if legacy and legacy.value:
                report.note_warn(
                    f'Setze MAILBOX_ENCRYPTION_KEY={legacy.value.strip()} in .env, '
                    'dann Migration erneut ausführen, um den DB-Key zu entfernen.'
                )
            else:
                report.note_skip(
                    'MAILBOX_ENCRYPTION_KEY nicht gesetzt — Legacy-Keys bleiben nutzbar'
                )
            report.note_ok('migrate_to_3_4_2 abgeschlossen (kein Re-Encrypt)')
            return

        try:
            Fernet(env_key)
        except Exception as exc:
            report.note_error(f'MAILBOX_ENCRYPTION_KEY ungültig: {exc}')
            raise

        primary = _encryption_key()
        if primary != env_key:
            report.note_warn('Primärer Key ist unerwartet nicht MAILBOX_ENCRYPTION_KEY')

        changed = 0
        failed = 0
        for mb in Mailbox.query.all():
            row_changed = False
            for field in ('smtp_password_enc', 'imap_password_enc'):
                enc = getattr(mb, field, None)
                if not enc:
                    continue
                plain = decrypt_password(enc)
                if plain is None:
                    failed += 1
                    report.note_warn(f'Mailbox {mb.id}: {field} nicht entschlüsselbar')
                    continue
                # Neu mit Primär-Key (Env) verschlüsseln
                new_enc = encrypt_password(plain)
                if new_enc != enc:
                    setattr(mb, field, new_enc)
                    row_changed = True
            if row_changed:
                changed += 1

        if changed:
            db.session.commit()
            report.note_ok(f'{changed} Mailbox(en) auf MAILBOX_ENCRYPTION_KEY umgeschlüsselt')
        else:
            report.note_skip('Keine Mailbox-Passwörter zum Umschlüsseln')

        if failed:
            report.note_warn(f'{failed} Feld(er) nicht umschlüsselbar — DB-Key bleibt vorerst')
        else:
            legacy = SystemSettings.query.filter_by(key=ENC_KEY_SETTING).first()
            if legacy:
                db.session.delete(legacy)
                db.session.commit()
                report.note_ok(f'SystemSettings.{ENC_KEY_SETTING} entfernt')
            else:
                report.note_skip(f'SystemSettings.{ENC_KEY_SETTING} nicht vorhanden')

        # Sanity: Kandidaten enthalten Env
        cands = _encryption_key_candidates()
        if cands and cands[0] == env_key:
            report.note_ok('Primärer Mailbox-Key = MAILBOX_ENCRYPTION_KEY')
        report.note_ok('migrate_to_3_4_2 abgeschlossen')
    except Exception as exc:
        report.note_error(f'migrate_to_3_4_2 fehlgeschlagen: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
