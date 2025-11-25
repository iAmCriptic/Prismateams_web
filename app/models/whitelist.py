from datetime import datetime
from app import db


class WhitelistEntry(db.Model):
    """Model für Whitelist-Einträge (E-Mail-Adressen und Domains)."""
    __tablename__ = 'whitelist_entries'
    
    id = db.Column(db.Integer, primary_key=True)
    entry = db.Column(db.String(255), nullable=False, unique=True, index=True)
    entry_type = db.Column(db.Enum('email', 'domain', name='whitelist_type'), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relationships
    creator = db.relationship('User', backref='created_whitelist_entries')
    
    def __repr__(self):
        return f'<WhitelistEntry {self.entry} ({self.entry_type})>'
    
    @staticmethod
    def is_email_whitelisted(email):
        """
        Prüft, ob eine E-Mail-Adresse auf der Whitelist steht.
        
        Args:
            email (str): Die zu prüfende E-Mail-Adresse
            
        Returns:
            bool: True wenn die E-Mail-Adresse whitelisted ist, False sonst
        """
        if not email:
            return False
            
        email = email.lower().strip()
        domain = email.split('@')[-1] if '@' in email else ''
        
        email_entry = WhitelistEntry.query.filter_by(
            entry=email,
            entry_type='email',
            is_active=True
        ).first()
        
        if email_entry:
            return True
        
        if domain:
            domain_with_at = '@' + domain
            domain_entry = WhitelistEntry.query.filter_by(
                entry=domain_with_at,
                entry_type='domain',
                is_active=True
            ).first()
            
            if domain_entry:
                return True
        
        return False
    
    @staticmethod
    def add_entry(entry, entry_type, description=None, created_by=None):
        """
        Fügt einen neuen Whitelist-Eintrag hinzu.
        
        Args:
            entry (str): Die E-Mail-Adresse oder Domain
            entry_type (str): 'email' oder 'domain'
            description (str, optional): Beschreibung des Eintrags
            created_by (int, optional): ID des Benutzers, der den Eintrag erstellt hat
            
        Returns:
            WhitelistEntry: Der erstellte Eintrag oder None bei Fehlern
        """
        if not entry or entry_type not in ['email', 'domain']:
            return None
            
        entry = entry.lower().strip()
        
        # Validiere Domain-Format
        if entry_type == 'domain' and not entry.startswith('@'):
            entry = '@' + entry
        
        existing = WhitelistEntry.query.filter_by(entry=entry).first()
        if existing:
            return None
        
        new_entry = WhitelistEntry(
            entry=entry,
            entry_type=entry_type,
            description=description,
            created_by=created_by
        )
        
        try:
            db.session.add(new_entry)
            db.session.commit()
            return new_entry
        except Exception:
            db.session.rollback()
            return None
    
    @staticmethod
    def remove_entry(entry_id):
        """
        Entfernt einen Whitelist-Eintrag.
        
        Args:
            entry_id (int): ID des zu entfernenden Eintrags
            
        Returns:
            bool: True wenn erfolgreich entfernt, False sonst
        """
        entry = WhitelistEntry.query.get(entry_id)
        if not entry:
            return False
            
        try:
            db.session.delete(entry)
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False
    
    @staticmethod
    def toggle_active(entry_id):
        """
        Aktiviert oder deaktiviert einen Whitelist-Eintrag.
        
        Args:
            entry_id (int): ID des Eintrags
            
        Returns:
            bool: True wenn erfolgreich geändert, False sonst
        """
        entry = WhitelistEntry.query.get(entry_id)
        if not entry:
            return False
            
        try:
            entry.is_active = not entry.is_active
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False
