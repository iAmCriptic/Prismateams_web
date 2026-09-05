from datetime import datetime
from app import db
import json
from flask import current_app


class EmailMessage(db.Model):
    __tablename__ = 'email_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(100), nullable=True)  # IMAP UID (not unique, can be same across folders)
    message_id = db.Column(db.String(255), unique=True, nullable=True)
    subject = db.Column(db.String(500), nullable=False)
    sender = db.Column(db.String(255), nullable=False)
    recipients = db.Column(db.Text, nullable=False)  # JSON string
    cc = db.Column(db.Text, nullable=True)
    bcc = db.Column(db.Text, nullable=True)
    body_text = db.Column(db.Text, nullable=True)  # TEXT can handle up to 65,535 characters
    body_html = db.Column(db.Text, nullable=True)  # TEXT can handle large content (up to 1GB in most databases)
    
    # Metadata
    is_read = db.Column(db.Boolean, default=False)
    is_sent = db.Column(db.Boolean, default=False)  # True if sent from portal
    has_attachments = db.Column(db.Boolean, default=False)
    folder = db.Column(db.String(100), default='INBOX', nullable=False, index=True)  # IMAP folder
    
    # IMAP synchronization tracking
    imap_uid = db.Column(db.String(100), nullable=True)  # IMAP UID for this specific folder
    last_imap_sync = db.Column(db.DateTime, nullable=True)  # Last time synced from IMAP
    is_deleted_imap = db.Column(db.Boolean, default=False)  # Marked as deleted in IMAP

    # User-driven organisational flags (mail manager update)
    # color_dot: free-form short label token (e.g. "red", "green", "blue", "yellow", "purple")
    # is_flagged: mirror of IMAP \Flagged flag if supported
    # imap_color_keyword: IMAP keyword that was written alongside color_dot (null if server
    # does not support keywords)
    color_dot = db.Column(db.String(24), nullable=True)
    is_flagged = db.Column(db.Boolean, default=False, nullable=False)
    imap_color_keyword = db.Column(db.String(64), nullable=True)
    last_flag_sync_at = db.Column(db.DateTime, nullable=True)

    sent_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # NULL = globales Hauptpostfach (App-Config); sonst Multi-Postfach
    mailbox_id = db.Column(db.Integer, db.ForeignKey('mailboxes.id'), nullable=True, index=True)
    
    received_at = db.Column(db.DateTime, nullable=True, index=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    attachments = db.relationship('EmailAttachment', back_populates='email', cascade='all, delete-orphan')
    mailbox = db.relationship('Mailbox', back_populates='messages')

    __table_args__ = (
        db.Index('ix_email_messages_mailbox_folder_received', 'mailbox_id', 'folder', 'received_at'),
        db.Index('ix_email_messages_folder_is_read', 'folder', 'is_read'),
    )
    
    def __repr__(self):
        return f'<EmailMessage {self.subject}>'


class EmailAttachment(db.Model):
    __tablename__ = 'email_attachments'
    
    id = db.Column(db.Integer, primary_key=True)
    email_id = db.Column(db.Integer, db.ForeignKey('email_messages.id'), nullable=False, index=True)
    
    filename = db.Column(db.String(500), nullable=False)  # Erweitert von 255 auf 500 für längere Dateinamen
    content_type = db.Column(db.String(100), nullable=False)
    size = db.Column(db.Integer, nullable=False)  # Size in bytes
    content = db.Column(db.LargeBinary, nullable=True)  # File content (can be None for file storage)
    file_path = db.Column(db.String(500), nullable=True)  # Path to file on disk
    is_inline = db.Column(db.Boolean, default=False)  # True if inline image
    content_id = db.Column(db.String(255), nullable=True)  # Content-ID for inline images
    is_large_file = db.Column(db.Boolean, default=False)  # Flag for files stored on disk
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    email = db.relationship('EmailMessage', back_populates='attachments')
    
    def __repr__(self):
        return f'<EmailAttachment {self.filename}>'
    
    def get_data_url(self):
        """Get data URL for inline images."""
        if self.is_inline and self.content_type.startswith('image/'):
            import base64
            if self.content:
                return f"data:{self.content_type};base64,{base64.b64encode(self.content).decode()}"
            elif self.file_path:
                try:
                    import os
                    with open(self.file_path, 'rb') as f:
                        content = f.read()
                        return f"data:{self.content_type};base64,{base64.b64encode(content).decode()}"
                except:
                    return None
        return None
    
    def get_content(self):
        """Get attachment content from database or file system."""
        if self.content:
            return self.content
        elif self.file_path:
            try:
                import os
                with open(self.file_path, 'rb') as f:
                    return f.read()
            except:
                return None
        return None


class EmailFolder(db.Model):
    __tablename__ = 'email_folders'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # IMAP folder name
    display_name = db.Column(db.String(100), nullable=False)  # Display name in UI
    folder_type = db.Column(db.String(20), default='custom', nullable=False)  # 'standard' or 'custom'
    is_system = db.Column(db.Boolean, default=False, nullable=False)  # True for system folders like INBOX
    parent_folder = db.Column(db.String(100), nullable=True)  # For nested folders
    separator = db.Column(db.String(5), default='/', nullable=False)  # IMAP folder separator
    # NULL = Hauptpostfach; sonst Ordner eines Multi-Postfachs
    mailbox_id = db.Column(db.Integer, db.ForeignKey('mailboxes.id'), nullable=True, index=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_synced = db.Column(db.DateTime, nullable=True)

    mailbox = db.relationship('Mailbox', back_populates='folders')

    __table_args__ = (
        db.UniqueConstraint('name', 'mailbox_id', name='uq_email_folder_name_mailbox'),
    )
    
    def __repr__(self):
        return f'<EmailFolder {self.name}>'

    @property
    def depth(self):
        """Hierarchy depth based on parent_folder chain (0 = top-level)."""
        if not self.parent_folder:
            return 0
        sep = self.separator or '/'
        return self.parent_folder.count(sep) + 1

    @property
    def short_name(self):
        """Return the folder label without the parent path."""
        sep = self.separator or '/'
        if sep and sep in (self.name or ''):
            return self.name.rsplit(sep, 1)[-1]
        return self.name

    @staticmethod
    def get_folder_display_name(imap_name):
        """Convert IMAP folder name to display name."""
        display_names = {
            'INBOX': 'Posteingang',
            'Sent': 'Gesendet',
            'Sent Messages': 'Gesendet',
            'Drafts': 'Entwürfe',
            'Trash': 'Papierkorb',
            'Deleted Messages': 'Papierkorb',
            'Spam': 'Spam',
            'Junk': 'Spam',
            'Archive': 'Archiv',
            'Archives': 'Archiv',
            'All Mail': 'Alle Mails',
            'Starred': 'Markiert',
            'Important': 'Wichtig',
            # Gmail EN
            '[Gmail]/Sent Mail': 'Gesendet',
            '[Google Mail]/Sent Mail': 'Gesendet',
            '[Gmail]/Drafts': 'Entwürfe',
            '[Google Mail]/Drafts': 'Entwürfe',
            '[Gmail]/Trash': 'Papierkorb',
            '[Google Mail]/Trash': 'Papierkorb',
            '[Gmail]/Bin': 'Papierkorb',
            '[Gmail]/Spam': 'Spam',
            '[Google Mail]/Spam': 'Spam',
            '[Gmail]/Starred': 'Markiert',
            '[Google Mail]/Starred': 'Markiert',
            '[Gmail]/Important': 'Wichtig',
            '[Google Mail]/Important': 'Wichtig',
            '[Gmail]/All Mail': 'Alle Mails',
            '[Google Mail]/All Mail': 'Alle Mails',
            # Gmail DE
            '[Gmail]/Gesendet': 'Gesendet',
            '[Google Mail]/Gesendet': 'Gesendet',
            '[Gmail]/Papierkorb': 'Papierkorb',
            '[Google Mail]/Papierkorb': 'Papierkorb',
            '[Gmail]/Alle Nachrichten': 'Alle Mails',
            '[Google Mail]/Alle Nachrichten': 'Alle Mails',
            '[Gmail]/Markiert': 'Markiert',
            '[Gmail]/Wichtig': 'Wichtig',
        }
        if imap_name in display_names:
            return display_names[imap_name]

        # Modified UTF-7 Leaf (z. B. [Gmail]/Entw&APw-rfe → Entwürfe)
        leaf = (imap_name or '').replace('\\', '/').rsplit('/', 1)[-1]
        if '&' in leaf:
            import base64
            import re

            def _repl(match):
                body = match.group(1)
                if body == '':
                    return '&'
                raw = body.replace(',', '/')
                pad = '=' * (-len(raw) % 4)
                try:
                    return base64.b64decode(raw + pad).decode('utf-16-be')
                except Exception:
                    return match.group(0)

            try:
                leaf = re.sub(r'&([^-]*)-', _repl, leaf)
            except Exception:
                pass

        leaf_map = {
            'Papierkorb': 'Papierkorb',
            'Trash': 'Papierkorb',
            'Gesendet': 'Gesendet',
            'Sent Mail': 'Gesendet',
            'Entwürfe': 'Entwürfe',
            'Drafts': 'Entwürfe',
            'Spam': 'Spam',
            'Alle Nachrichten': 'Alle Mails',
            'All Mail': 'Alle Mails',
            'Markiert': 'Markiert',
            'Starred': 'Markiert',
            'Wichtig': 'Wichtig',
            'Important': 'Wichtig',
        }
        if leaf in leaf_map:
            return leaf_map[leaf]
        return leaf or imap_name


class EmailPermission(db.Model):
    __tablename__ = 'email_permissions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    can_read = db.Column(db.Boolean, default=True, nullable=False)
    can_send = db.Column(db.Boolean, default=True, nullable=False)
    
    # Relationships
    user = db.relationship('User', back_populates='email_permissions')
    
    def __repr__(self):
        return f'<EmailPermission user={self.user_id} read={self.can_read} send={self.can_send}>'


class Mailbox(db.Model):
    """Multi-Postfach: team | group | private (Hauptpostfach bleibt App-Config)."""
    __tablename__ = 'mailboxes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    display_name = db.Column(db.String(200), nullable=False)
    mailbox_type = db.Column(db.String(20), nullable=False, index=True)  # team | group | private
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True, index=True)

    # google | microsoft | infomaniak | ionos | custom
    provider = db.Column(db.String(32), nullable=False, default='custom', index=True)
    # password | oauth
    auth_type = db.Column(db.String(16), nullable=False, default='password')

    smtp_server = db.Column(db.String(255), nullable=True)
    smtp_port = db.Column(db.Integer, nullable=True, default=587)
    smtp_use_tls = db.Column(db.Boolean, nullable=False, default=True)
    smtp_use_ssl = db.Column(db.Boolean, nullable=False, default=False)
    smtp_username = db.Column(db.String(255), nullable=True)
    smtp_password_enc = db.Column(db.Text, nullable=True)

    imap_server = db.Column(db.String(255), nullable=True)
    imap_port = db.Column(db.Integer, nullable=True, default=993)
    imap_use_ssl = db.Column(db.Boolean, nullable=False, default=True)
    imap_username = db.Column(db.String(255), nullable=True)
    imap_password_enc = db.Column(db.Text, nullable=True)

    oauth_access_token_enc = db.Column(db.Text, nullable=True)
    oauth_refresh_token_enc = db.Column(db.Text, nullable=True)
    oauth_expires_at = db.Column(db.DateTime, nullable=True)
    oauth_email = db.Column(db.String(255), nullable=True)

    footer_html = db.Column(db.Text, nullable=True)
    logo_filename = db.Column(db.String(255), nullable=True)
    color = db.Column(db.String(7), nullable=False, default='#0d6efd')
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = db.relationship('User', foreign_keys=[owner_id], backref=db.backref('owned_mailboxes', lazy='dynamic'))
    team = db.relationship('Team', backref=db.backref('mailboxes', lazy='dynamic'))
    memberships = db.relationship('MailboxMembership', back_populates='mailbox', cascade='all, delete-orphan')
    # Wichtig: cascade delete — sonst setzt SQLAlchemy mailbox_id auf NULL (= Hauptpostfach)!
    messages = db.relationship(
        'EmailMessage',
        back_populates='mailbox',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )
    folders = db.relationship(
        'EmailFolder',
        back_populates='mailbox',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )

    def __repr__(self):
        return f'<Mailbox {self.id} {self.mailbox_type} {self.display_name}>'


class MailboxMembership(db.Model):
    """Zuordnung Nutzer ↔ Postfach (Gruppen/explizite Rechte; Team-Zugriff auch über TeamMember)."""
    __tablename__ = 'mailbox_memberships'

    id = db.Column(db.Integer, primary_key=True)
    mailbox_id = db.Column(db.Integer, db.ForeignKey('mailboxes.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    can_read = db.Column(db.Boolean, nullable=False, default=True)
    can_send = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    mailbox = db.relationship('Mailbox', back_populates='memberships')
    user = db.relationship('User', backref=db.backref('mailbox_memberships', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('mailbox_id', 'user_id', name='uq_mailbox_membership'),
    )

    def __repr__(self):
        return f'<MailboxMembership mailbox={self.mailbox_id} user={self.user_id}>'


class MailboxUserPref(db.Model):
    """Pro Nutzer: Präferenzen für ein zugängliches Postfach (z. B. Team-Logo nutzen)."""
    __tablename__ = 'mailbox_user_prefs'

    id = db.Column(db.Integer, primary_key=True)
    mailbox_id = db.Column(db.Integer, db.ForeignKey('mailboxes.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    use_logo = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    mailbox = db.relationship('Mailbox', backref=db.backref('user_prefs', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('mailbox_prefs', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('mailbox_id', 'user_id', name='uq_mailbox_user_pref'),
    )

    def __repr__(self):
        return f'<MailboxUserPref mailbox={self.mailbox_id} user={self.user_id} use_logo={self.use_logo}>'

