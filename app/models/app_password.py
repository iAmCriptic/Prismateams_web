"""Scoped app passwords for WebDAV (and similar non-interactive clients).

Klartext nur einmal bei Erstellung; in der DB nur Argon2-Hash.
Benutzername: vorname+nachname.lower + '.' + id  (z. B. enricomatzke.12)
"""

from __future__ import annotations

import re
import secrets
import string
import unicodedata
from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app import db

_ph = PasswordHasher()

LOWER = string.ascii_lowercase
UPPER = string.ascii_uppercase
DIGITS = string.digits
# Keine Anführungszeichen, Doppelpunkt oder Backslash — problematisch in Basic Auth / Shells
SPECIAL = '!@#$%^&*-_=+?'
ALPHABET = LOWER + UPPER + DIGITS + SPECIAL

MIN_LENGTH = 8
MAX_LENGTH = 15
HINT_LEN = 4
MAX_PER_USER = 10

_UMLAUT_MAP = {
    'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
    'Ä': 'ae', 'Ö': 'oe', 'Ü': 'ue',
}


def slug_from_person_name(first_name: str | None, last_name: str | None) -> str:
    """Vor+Nachname → ASCII-Slug ohne Leerzeichen (enricomatzke)."""
    raw = f'{(first_name or "").strip()}{(last_name or "").strip()}'
    for src, dst in _UMLAUT_MAP.items():
        raw = raw.replace(src, dst)
    raw = unicodedata.normalize('NFKD', raw)
    raw = ''.join(c for c in raw if not unicodedata.combining(c))
    slug = re.sub(r'[^a-z0-9]', '', raw.lower())
    return slug or 'user'


def build_app_username(first_name: str | None, last_name: str | None, app_id: int) -> str:
    """z. B. enricomatzke.12"""
    return f'{slug_from_person_name(first_name, last_name)}.{int(app_id)}'


class AppPassword(db.Model):
    __tablename__ = 'app_passwords'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    # WebDAV-Loginname, z. B. enricomatzke.12
    username = db.Column(db.String(120), nullable=True, unique=True, index=True)
    name = db.Column(db.String(100), nullable=False, default='WebDAV')
    password_hash = db.Column(db.String(255), nullable=False)
    # Erste Zeichen zur Anzeige (kein Geheimnis — Klartext bleibt unbekannt)
    hint = db.Column(db.String(16), nullable=False, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship(
        'User',
        backref=db.backref('app_passwords', lazy='dynamic', cascade='all, delete-orphan'),
    )

    def __repr__(self):
        return f'<AppPassword {self.id} user={self.user_id} username={self.username!r}>'

    @staticmethod
    def generate_raw() -> str:
        """Vorgegebenes Passwort: 8–15 Zeichen, Groß/Klein, Ziffer, Sonderzeichen."""
        length = secrets.randbelow(MAX_LENGTH - MIN_LENGTH + 1) + MIN_LENGTH
        for _ in range(32):
            chars = [
                secrets.choice(LOWER),
                secrets.choice(UPPER),
                secrets.choice(DIGITS),
                secrets.choice(SPECIAL),
            ]
            chars.extend(secrets.choice(ALPHABET) for _ in range(length - 4))
            for i in range(len(chars) - 1, 0, -1):
                j = secrets.randbelow(i + 1)
                chars[i], chars[j] = chars[j], chars[i]
            raw = ''.join(chars)
            if (
                any(c in LOWER for c in raw)
                and any(c in UPPER for c in raw)
                and any(c in DIGITS for c in raw)
                and any(c in SPECIAL for c in raw)
            ):
                return raw
        # Fallback (sollte praktisch nie greifen)
        return ''.join(secrets.choice(ALPHABET) for _ in range(length))

    def check_password(self, raw: str) -> bool:
        try:
            _ph.verify(self.password_hash, raw or '')
            if _ph.check_needs_rehash(self.password_hash):
                self.password_hash = _ph.hash(raw)
            return True
        except VerifyMismatchError:
            return False
        except Exception:
            return False

    def touch_used(self):
        self.last_used_at = datetime.utcnow()

    def ensure_username(self, user=None) -> str:
        """Username setzen falls leer; braucht gespeicherte id."""
        if self.username:
            return self.username
        if user is None:
            user = self.user
        if not self.id:
            raise RuntimeError('AppPassword needs an id before username can be assigned')
        first = getattr(user, 'first_name', None) if user else None
        last = getattr(user, 'last_name', None) if user else None
        self.username = build_app_username(first, last, self.id)
        return self.username

    def to_public_dict(self) -> dict:
        return {
            'id': self.id,
            'username': self.username,
            'name': self.name,
            'hint': self.hint,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() + 'Z' if self.last_used_at else None,
        }

    @classmethod
    def create_for_user(cls, user, name: str | None = None):
        """
        Erzeugt ein App-Passwort inkl. Benutzername vorname+nachname.id.
        Returns (AppPassword, raw_password) — Klartext nur einmal zurückgeben.
        """
        user_id = getattr(user, 'id', None)
        if not user_id:
            raise ValueError('user_required')

        count = cls.query.filter_by(user_id=user_id).count()
        if count >= MAX_PER_USER:
            raise ValueError('max_reached')

        label = (name or '').strip()[:100] or 'WebDAV'
        raw = cls.generate_raw()
        row = cls(
            user_id=user_id,
            name=label,
            password_hash=_ph.hash(raw),
            hint=raw[:HINT_LEN],
        )
        db.session.add(row)
        db.session.flush()  # id für username
        row.ensure_username(user)
        db.session.commit()
        return row, raw

    @classmethod
    def find_by_login(cls, login: str):
        """Lookup per App-Username (case-insensitive)."""
        key = (login or '').strip().lower()
        if not key:
            return None
        return cls.query.filter(db.func.lower(cls.username) == key).first()

    @classmethod
    def verify_for_user(cls, user_id: int, raw_password: str):
        """Prüft Klartext gegen alle App-Passwörter des Users. Returns AppPassword oder None."""
        raw = raw_password or ''
        if not raw:
            return None
        rows = cls.query.filter_by(user_id=user_id).order_by(cls.id.asc()).all()
        for row in rows:
            if row.check_password(raw):
                row.touch_used()
                return row
        return None

    @classmethod
    def verify_login(cls, username: str, raw_password: str):
        """
        Auth mit App-Username + Passwort.
        Returns (User, AppPassword) oder (None, None).
        """
        row = cls.find_by_login(username)
        if not row or not row.check_password(raw_password or ''):
            return None, None
        row.touch_used()
        user = row.user
        if user is None:
            from app.models.user import User
            user = User.query.get(row.user_id)
        return user, row
