"""Helpers for optional multi-mailbox mode (Team / Group / Private)."""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet
from flask import current_app
from sqlalchemy import or_

from app import db
from app.models.email import Mailbox, MailboxMembership, MailboxUserPref
from app.models.settings import SystemSettings
from app.models.team import Team, TeamMember

MAIN_MAILBOX_SENTINEL = None  # mailbox_id NULL = globales Hauptpostfach
DEFAULT_MAX_PRIVATE = 3
ENC_KEY_SETTING = 'email_enc_key'

# Provider-Presets für den Postfach-Wizard (Hosts/Ports/Auth)
MAILBOX_PROVIDER_PRESETS = {
    'google': {
        'auth_type': 'oauth',
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': 587,
        'smtp_use_tls': True,
        'smtp_use_ssl': False,
        'imap_server': 'imap.gmail.com',
        'imap_port': 993,
        'imap_use_ssl': True,
    },
    'microsoft': {
        'auth_type': 'oauth',
        'smtp_server': 'smtp.office365.com',
        'smtp_port': 587,
        'smtp_use_tls': True,
        'smtp_use_ssl': False,
        'imap_server': 'outlook.office365.com',
        'imap_port': 993,
        'imap_use_ssl': True,
    },
    'infomaniak': {
        'auth_type': 'password',
        'smtp_server': 'mail.infomaniak.com',
        'smtp_port': 587,
        'smtp_use_tls': True,
        'smtp_use_ssl': False,
        'imap_server': 'mail.infomaniak.com',
        'imap_port': 993,
        'imap_use_ssl': True,
    },
    'ionos': {
        'auth_type': 'password',
        'smtp_server': 'smtp.ionos.de',
        'smtp_port': 587,
        'smtp_use_tls': True,
        'smtp_use_ssl': False,
        'imap_server': 'imap.ionos.de',
        'imap_port': 993,
        'imap_use_ssl': True,
    },
    'custom': {
        'auth_type': 'password',
        'smtp_server': '',
        'smtp_port': 587,
        'smtp_use_tls': True,
        'smtp_use_ssl': False,
        'imap_server': '',
        'imap_port': 993,
        'imap_use_ssl': True,
    },
}


def get_provider_preset(provider: str) -> dict:
    return dict(MAILBOX_PROVIDER_PRESETS.get(provider or 'custom') or MAILBOX_PROVIDER_PRESETS['custom'])


def apply_provider_preset(mailbox: Mailbox, provider: str) -> None:
    """Setzt provider/auth_type und Server-Felder aus dem Preset (ohne Passwörter).

    Ist OAuth für Google/Microsoft nicht konfiguriert, fällt auth_type auf password
    zurück — Hosts/Ports bleiben die Provider-Presets.
    """
    provider = (provider or 'custom').strip().lower()
    if provider not in MAILBOX_PROVIDER_PRESETS:
        provider = 'custom'
    preset = MAILBOX_PROVIDER_PRESETS[provider]
    mailbox.provider = provider
    auth_type = preset.get('auth_type') or 'password'
    if auth_type == 'oauth' and provider in ('google', 'microsoft'):
        try:
            from app.utils.mailbox_oauth import provider_oauth_ready
            if not provider_oauth_ready(provider):
                auth_type = 'password'
        except Exception:
            auth_type = 'password'
    mailbox.auth_type = auth_type
    mailbox.smtp_server = preset.get('smtp_server') or mailbox.smtp_server
    mailbox.smtp_port = int(preset.get('smtp_port') or mailbox.smtp_port or 587)
    mailbox.smtp_use_tls = bool(preset.get('smtp_use_tls', True))
    mailbox.smtp_use_ssl = bool(preset.get('smtp_use_ssl', False))
    mailbox.imap_server = preset.get('imap_server') or mailbox.imap_server
    mailbox.imap_port = int(preset.get('imap_port') or mailbox.imap_port or 993)
    mailbox.imap_use_ssl = bool(preset.get('imap_use_ssl', True))


def _setting_bool(key: str, default: bool = False) -> bool:
    setting = SystemSettings.query.filter_by(key=key).first()
    if not setting or setting.value is None or str(setting.value).strip() == '':
        return default
    return str(setting.value).lower() == 'true'


def _setting_int(key: str, default: int) -> int:
    setting = SystemSettings.query.filter_by(key=key).first()
    if not setting or setting.value is None or str(setting.value).strip() == '':
        return default
    try:
        return int(setting.value)
    except (TypeError, ValueError):
        return default


def is_email_multi_enabled() -> bool:
    return _setting_bool('email_multi_enabled', False)


def get_max_private_mailboxes() -> int:
    return max(0, _setting_int('email_max_private_mailboxes', DEFAULT_MAX_PRIVATE))


def is_email_html_design_default() -> bool:
    return _setting_bool('email_compose_html_design_default', True)


def get_led_teams(user) -> list:
    if not user or not getattr(user, 'id', None):
        return []
    return Team.query.filter_by(leader_id=user.id).order_by(Team.name).all()


def user_is_team_leader(user) -> bool:
    return bool(get_led_teams(user))


def can_manage_team(user, team_id: int) -> bool:
    if not user:
        return False
    if getattr(user, 'is_admin', False):
        return True
    team = Team.query.get(team_id)
    return bool(team and team.leader_id == user.id)


def _encryption_key() -> bytes:
    """Fernet key from SystemSettings or derived from SECRET_KEY."""
    setting = SystemSettings.query.filter_by(key=ENC_KEY_SETTING).first()
    if setting and setting.value:
        try:
            key = setting.value.strip().encode()
            Fernet(key)
            return key
        except Exception:
            pass

    secret_seed = current_app.config.get('SECRET_KEY') or os.environ.get('SECRET_KEY') or 'prismateams-fallback'
    digest = hashlib.sha256(f'email-mailbox:{secret_seed}'.encode('utf-8')).digest()
    key = base64.urlsafe_b64encode(digest)

    if not setting:
        db.session.add(SystemSettings(
            key=ENC_KEY_SETTING,
            value=key.decode(),
            description='Fernet-Schlüssel für Multi-Postfach-Passwörter',
        ))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return key


def encrypt_password(plain: str) -> Optional[str]:
    if plain is None or plain == '':
        return None
    f = Fernet(_encryption_key())
    return f.encrypt(plain.encode('utf-8')).decode('utf-8')


def decrypt_password(enc: Optional[str]) -> Optional[str]:
    if not enc:
        return None
    try:
        f = Fernet(_encryption_key())
        return f.decrypt(enc.encode('utf-8')).decode('utf-8')
    except Exception:
        return None


def count_private_mailboxes(user_id: int) -> int:
    return Mailbox.query.filter_by(owner_id=user_id, mailbox_type='private', is_active=True).count()


def can_add_private_mailbox(user) -> bool:
    if not user or not is_email_multi_enabled():
        return False
    return count_private_mailboxes(user.id) < get_max_private_mailboxes()


def user_has_mailbox_access(user, mailbox: Mailbox, permission: str = 'read') -> bool:
    """permission: read | send"""
    if not user or not mailbox or not mailbox.is_active:
        return False
    if getattr(user, 'is_admin', False):
        return True

    if mailbox.mailbox_type == 'private':
        if mailbox.owner_id == user.id:
            return True
        membership = MailboxMembership.query.filter_by(mailbox_id=mailbox.id, user_id=user.id).first()
        if not membership:
            return False
        return membership.can_send if permission == 'send' else membership.can_read

    if mailbox.mailbox_type == 'team' and mailbox.team_id:
        is_member = TeamMember.query.filter_by(team_id=mailbox.team_id, user_id=user.id).first()
        if is_member:
            return True
        # Explizite Membership als Override
        membership = MailboxMembership.query.filter_by(mailbox_id=mailbox.id, user_id=user.id).first()
        if membership:
            return membership.can_send if permission == 'send' else membership.can_read
        return False

    if mailbox.mailbox_type == 'group':
        membership = MailboxMembership.query.filter_by(mailbox_id=mailbox.id, user_id=user.id).first()
        if not membership:
            return False
        return membership.can_send if permission == 'send' else membership.can_read

    return False


def get_accessible_mailboxes(user, permission: str = 'read') -> list:
    """
    Gibt zugängliche Multi-Postfächer zurück (ohne Hauptpostfach-Sentinel).
    Bei deaktiviertem Multi: leere Liste.
    """
    if not user or not is_email_multi_enabled():
        return []

    team_ids = [
        m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()
    ]
    membership_ids = [
        m.mailbox_id for m in MailboxMembership.query.filter_by(user_id=user.id).all()
    ]

    q = Mailbox.query.filter(Mailbox.is_active.is_(True))
    clauses = [
        Mailbox.owner_id == user.id,
        Mailbox.id.in_(membership_ids) if membership_ids else False,
        Mailbox.team_id.in_(team_ids) if team_ids else False,
    ]
    # Filter False-clauses
    clauses = [c for c in clauses if c is not False]
    if not clauses:
        return []

    mailboxes = q.filter(or_(*clauses)).order_by(Mailbox.mailbox_type, Mailbox.display_name).all()
    from app.utils.team_module_settings import is_team_section_enabled
    return [
        mb for mb in mailboxes
        if user_has_mailbox_access(user, mb, permission)
        and (
            mb.mailbox_type != 'team'
            or not mb.team_id
            or is_team_section_enabled(mb.team_id, 'email')
        )
    ]


def get_mailbox_for_user(user, mailbox_id: Optional[int], permission: str = 'read') -> Optional[Mailbox]:
    """Lädt ein Postfach und prüft Zugriff. mailbox_id None = Hauptpostfach (kein DB-Objekt)."""
    if mailbox_id is None:
        return None
    mailbox = Mailbox.query.get(mailbox_id)
    if not mailbox or not user_has_mailbox_access(user, mailbox, permission):
        return None
    return mailbox


def get_main_smtp_config() -> dict:
    return {
        'server': current_app.config.get('MAIL_SERVER'),
        'port': int(current_app.config.get('MAIL_PORT', 587) or 587),
        'use_tls': current_app.config.get('MAIL_USE_TLS', True),
        'use_ssl': current_app.config.get('MAIL_USE_SSL', False),
        'user': current_app.config.get('MAIL_USERNAME'),
        'password': current_app.config.get('MAIL_PASSWORD'),
        'sender': current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('MAIL_USERNAME'),
    }


def get_main_imap_config() -> dict:
    return {
        'server': current_app.config.get('IMAP_SERVER'),
        'port': int(current_app.config.get('IMAP_PORT', 993) or 993),
        'use_ssl': current_app.config.get('IMAP_USE_SSL', True),
        'user': current_app.config.get('MAIL_USERNAME'),
        'password': current_app.config.get('MAIL_PASSWORD'),
    }


def get_mailbox_smtp_config(mailbox: Optional[Mailbox] = None) -> dict:
    if mailbox is None:
        return get_main_smtp_config()
    password = decrypt_password(mailbox.smtp_password_enc) or decrypt_password(mailbox.imap_password_enc)
    use_ssl = bool(getattr(mailbox, 'smtp_use_ssl', False))
    use_tls = bool(mailbox.smtp_use_tls) and not use_ssl
    auth_type = getattr(mailbox, 'auth_type', None) or 'password'
    user = mailbox.smtp_username or mailbox.imap_username or getattr(mailbox, 'oauth_email', None)
    cfg = {
        'server': mailbox.smtp_server,
        'port': int(mailbox.smtp_port or (465 if use_ssl else 587)),
        'use_tls': use_tls,
        'use_ssl': use_ssl,
        'user': user,
        'password': password,
        'sender': user,
        'auth_type': auth_type,
        'mailbox': mailbox,
    }
    return cfg


def get_mailbox_imap_config(mailbox: Optional[Mailbox] = None) -> dict:
    if mailbox is None:
        return get_main_imap_config()
    auth_type = getattr(mailbox, 'auth_type', None) or 'password'
    user = mailbox.imap_username or getattr(mailbox, 'oauth_email', None)
    return {
        'server': mailbox.imap_server,
        'port': int(mailbox.imap_port or 993),
        'use_ssl': bool(mailbox.imap_use_ssl),
        'user': user,
        'password': decrypt_password(mailbox.imap_password_enc),
        'auth_type': auth_type,
        'mailbox': mailbox,
    }


def mailbox_upload_dir() -> str:
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'mailboxes')
    os.makedirs(path, exist_ok=True)
    return path


def get_mailbox_use_logo(user, mailbox: Optional[Mailbox] = None) -> bool:
    """Ob der Nutzer das Postfach-Logo verwenden will (Default: True)."""
    if not user or not mailbox or not getattr(mailbox, 'id', None):
        return True
    pref = MailboxUserPref.query.filter_by(mailbox_id=mailbox.id, user_id=user.id).first()
    if pref is None:
        return True
    return bool(pref.use_logo)


def set_mailbox_use_logo(user, mailbox: Mailbox, use_logo: bool) -> MailboxUserPref:
    pref = MailboxUserPref.query.filter_by(mailbox_id=mailbox.id, user_id=user.id).first()
    if pref is None:
        pref = MailboxUserPref(mailbox_id=mailbox.id, user_id=user.id, use_logo=use_logo)
        db.session.add(pref)
    else:
        pref.use_logo = use_logo
    return pref


def get_mailbox_logo_data(mailbox: Optional[Mailbox] = None, user=None, use_logo: Optional[bool] = None):
    """
    Returns (logo_bytes, mime_type, filename) or (None, None, None).
    Team-/Postfach-Logo nur wenn use_logo True (Default/User-Pref).
    Sonst Fallback auf Portal-Logo.
    """
    allow_mailbox_logo = True
    if use_logo is not None:
        allow_mailbox_logo = bool(use_logo)
    elif user is not None and mailbox is not None:
        allow_mailbox_logo = get_mailbox_use_logo(user, mailbox)

    if allow_mailbox_logo and mailbox and mailbox.logo_filename:
        path = os.path.join(mailbox_upload_dir(), mailbox.logo_filename)
        if os.path.exists(path):
            with open(path, 'rb') as f:
                data = f.read()
            ext = os.path.splitext(mailbox.logo_filename)[1].lower()
            mime = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
            }.get(ext, 'image/png')
            return data, mime, mailbox.logo_filename
    try:
        from app.utils.email_sender import get_logo_data
        return get_logo_data()
    except Exception:
        return None, None, None


def get_active_sync_mailboxes() -> list:
    """Alle aktiven Multi-Postfächer mit IMAP-Zugangsdaten (für Scheduler)."""
    if not is_email_multi_enabled():
        return []
    result = []
    for mb in Mailbox.query.filter_by(is_active=True).all():
        cfg = get_mailbox_imap_config(mb)
        if cfg.get('server') and cfg.get('user') and cfg.get('password'):
            result.append(mb)
    return result


def apply_mailbox_credentials(mailbox: Mailbox, form, *, password_fields=('smtp_password', 'imap_password')) -> None:
    """Übernimmt Formularfelder auf ein Mailbox-Objekt (Passwort nur wenn neu gesetzt)."""
    name = (form.get('name') or form.get('display_name') or mailbox.name or '').strip()
    if name:
        mailbox.name = name
        mailbox.display_name = name

    provider = (form.get('provider') or getattr(mailbox, 'provider', None) or 'custom').strip().lower()
    if provider not in MAILBOX_PROVIDER_PRESETS:
        provider = 'custom'
    mailbox.provider = provider
    preset = MAILBOX_PROVIDER_PRESETS[provider]
    auth_type = (form.get('auth_type') or preset.get('auth_type') or 'password').strip().lower()
    if auth_type not in ('password', 'oauth'):
        auth_type = 'password'
    # Ohne eingerichtetes OAuth: Google/Microsoft per IMAP/SMTP-Preset + Passwort
    if auth_type == 'oauth' and provider in ('google', 'microsoft'):
        try:
            from app.utils.mailbox_oauth import provider_oauth_ready
            if not provider_oauth_ready(provider):
                auth_type = 'password'
        except Exception:
            auth_type = 'password'
    mailbox.auth_type = auth_type

    # Preset-Hosts für bekannte Provider, sofern Felder leer
    smtp_server = (form.get('smtp_server') or '').strip() or (
        preset.get('smtp_server') if provider != 'custom' else None
    )
    imap_server = (form.get('imap_server') or '').strip() or (
        preset.get('imap_server') if provider != 'custom' else None
    )
    smtp_port = form.get('smtp_port') or (preset.get('smtp_port') if provider != 'custom' else None) or 587
    imap_port = form.get('imap_port') or (preset.get('imap_port') if provider != 'custom' else None) or 993
    # Checkboxen fehlen im POST wenn unchecked — Preset nur wenn Provider ≠ custom
    # und keine Flags mitgeschickt wurden (vereinfachte Preset-Formulare).
    smtp_flags_present = ('smtp_use_ssl' in form) or ('smtp_use_tls' in form)
    if smtp_flags_present or provider == 'custom':
        smtp_use_ssl = form.get('smtp_use_ssl') in ('on', 'true', True, '1')
        smtp_use_tls = form.get('smtp_use_tls') in ('on', 'true', True, '1') and not smtp_use_ssl
    else:
        smtp_use_ssl = bool(preset.get('smtp_use_ssl', False))
        smtp_use_tls = bool(preset.get('smtp_use_tls', True)) and not smtp_use_ssl
    if ('imap_use_ssl' in form) or provider == 'custom':
        imap_use_ssl = form.get('imap_use_ssl') in ('on', 'true', True, '1')
    else:
        imap_use_ssl = bool(preset.get('imap_use_ssl', True))

    mailbox.smtp_server = smtp_server or None
    mailbox.smtp_port = int(smtp_port or 587)
    mailbox.smtp_use_ssl = smtp_use_ssl
    mailbox.smtp_use_tls = bool(smtp_use_tls) and not smtp_use_ssl
    mailbox.smtp_username = (form.get('smtp_username') or '').strip() or None
    mailbox.imap_server = imap_server or None
    mailbox.imap_port = int(imap_port or 993)
    mailbox.imap_use_ssl = imap_use_ssl
    mailbox.imap_username = (form.get('imap_username') or '').strip() or None
    if form.get('footer_html') is not None:
        mailbox.footer_html = form.get('footer_html')
    color = (form.get('color') or '').strip()
    if color and color.startswith('#') and len(color) in (4, 7):
        mailbox.color = color

    if auth_type == 'password':
        smtp_pw = (form.get('smtp_password') or '').strip()
        imap_pw = (form.get('imap_password') or '').strip()
        if smtp_pw and smtp_pw != '••••••••':
            mailbox.smtp_password_enc = encrypt_password(smtp_pw)
        if imap_pw and imap_pw != '••••••••':
            mailbox.imap_password_enc = encrypt_password(imap_pw)
        if smtp_pw and smtp_pw != '••••••••' and not mailbox.imap_password_enc:
            mailbox.imap_password_enc = mailbox.smtp_password_enc
        if imap_pw and imap_pw != '••••••••' and not mailbox.smtp_password_enc:
            mailbox.smtp_password_enc = mailbox.imap_password_enc


def purge_mailbox_data(mailbox_id: int) -> dict:
    """Löscht alle Mails, Anhänge und Ordner eines Multi-Postfachs (nicht das Hauptpostfach)."""
    from app.models.email import EmailAttachment, EmailFolder, EmailMessage

    if mailbox_id is None:
        raise ValueError('Hauptpostfach (mailbox_id=None) darf nicht per purge gelöscht werden')

    msg_ids = [
        row[0]
        for row in db.session.query(EmailMessage.id).filter_by(mailbox_id=mailbox_id).all()
    ]
    n_att = 0
    if msg_ids:
        # Chunked, falls sehr viele IDs
        chunk = 500
        for i in range(0, len(msg_ids), chunk):
            part = msg_ids[i:i + chunk]
            n_att += (
                EmailAttachment.query.filter(EmailAttachment.email_id.in_(part))
                .delete(synchronize_session=False)
            )
    n_msg = EmailMessage.query.filter_by(mailbox_id=mailbox_id).delete(synchronize_session=False)
    n_fold = EmailFolder.query.filter_by(mailbox_id=mailbox_id).delete(synchronize_session=False)
    n_mem = MailboxMembership.query.filter_by(mailbox_id=mailbox_id).delete(synchronize_session=False)
    n_pref = MailboxUserPref.query.filter_by(mailbox_id=mailbox_id).delete(synchronize_session=False)
    return {
        'messages': int(n_msg or 0),
        'folders': int(n_fold or 0),
        'attachments': int(n_att or 0),
        'memberships': int(n_mem or 0),
        'prefs': int(n_pref or 0),
    }


def delete_mailbox(mailbox: Mailbox) -> dict:
    """Entfernt ein Multi-Postfach inkl. aller zugehörigen Daten (kein SET NULL → Hauptpostfach)."""
    if mailbox is None or getattr(mailbox, 'id', None) is None:
        raise ValueError('Ungültiges Postfach')

    mid = mailbox.id
    stats = purge_mailbox_data(mid)

    logo = getattr(mailbox, 'logo_filename', None)
    if logo:
        try:
            path = os.path.join(mailbox_upload_dir(), logo)
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    db.session.delete(mailbox)
    return stats


def cleanup_orphaned_multi_mailbox_rows() -> dict:
    """Löscht Ordner/Mails deren mailbox_id auf kein Postfach mehr zeigt."""
    from app.models.email import EmailAttachment, EmailFolder, EmailMessage

    living = {row[0] for row in db.session.query(Mailbox.id).all()}
    orphan_folder_ids = [
        row[0]
        for row in db.session.query(EmailFolder.id, EmailFolder.mailbox_id)
        .filter(EmailFolder.mailbox_id.isnot(None))
        .all()
        if row[1] not in living
    ]
    orphan_msg_ids = [
        row[0]
        for row in db.session.query(EmailMessage.id, EmailMessage.mailbox_id)
        .filter(EmailMessage.mailbox_id.isnot(None))
        .all()
        if row[1] not in living
    ]
    n_att = 0
    if orphan_msg_ids:
        chunk = 500
        for i in range(0, len(orphan_msg_ids), chunk):
            part = orphan_msg_ids[i:i + chunk]
            n_att += (
                EmailAttachment.query.filter(EmailAttachment.email_id.in_(part))
                .delete(synchronize_session=False)
            )
        EmailMessage.query.filter(EmailMessage.id.in_(orphan_msg_ids)).delete(
            synchronize_session=False
        )
    n_fold = 0
    if orphan_folder_ids:
        n_fold = EmailFolder.query.filter(EmailFolder.id.in_(orphan_folder_ids)).delete(
            synchronize_session=False
        )
    return {
        'orphan_messages': len(orphan_msg_ids),
        'orphan_folders': n_fold or len(orphan_folder_ids),
        'orphan_attachments': n_att,
    }
