from datetime import datetime, timedelta
from app import db
import hashlib
import hmac
import secrets


class ApiToken(db.Model):
    """API-Token für Mobile API Authentifizierung (nur Hash in der DB)."""
    __tablename__ = 'api_tokens'

    PREFIX_LEN = 8

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    # SHA-256-Hex des Klartext-Tokens (kein Klartext in der DB)
    token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    token_prefix = db.Column(db.String(16), nullable=True, index=True)
    name = db.Column(db.String(100), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])

    def __repr__(self):
        prefix = self.token_prefix or (self.token[:10] if self.token else '?')
        return f'<ApiToken {prefix}… for User {self.user_id}>'

    @staticmethod
    def generate_token():
        """Generiert einen neuen sicheren Klartext-Token."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256((raw_token or '').encode('utf-8')).hexdigest()

    @staticmethod
    def _looks_like_hash(value: str) -> bool:
        if not value or len(value) != 64:
            return False
        try:
            int(value, 16)
            return True
        except ValueError:
            return False

    @classmethod
    def find_by_raw_token(cls, raw_token: str):
        """Lookup per Prefix + constant-time Hash-Vergleich (inkl. Legacy-Klartext)."""
        raw = (raw_token or '').strip()
        if not raw:
            return None

        digest = cls.hash_token(raw)
        prefix = raw[: cls.PREFIX_LEN]

        candidates = []
        if prefix:
            candidates = cls.query.filter_by(token_prefix=prefix).all()
        if not candidates:
            by_hash = cls.query.filter_by(token=digest).first()
            if by_hash:
                return by_hash
            # Legacy: unmigrierte Klartext-Zeilen
            return cls.query.filter_by(token=raw).first()

        for row in candidates:
            stored = row.token or ''
            if cls._looks_like_hash(stored):
                if hmac.compare_digest(stored, digest):
                    return row
            elif hmac.compare_digest(stored, raw):
                return row
        return None

    def is_expired(self):
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def mark_as_used(self):
        self.last_used_at = datetime.utcnow()
        db.session.commit()

    @staticmethod
    def create_token(user_id, name=None, expires_in_days=None):
        """
        Erstellt einen neuen API-Token.
        Returns (ApiToken, raw_token) — Klartext nur einmal zurückgeben.
        """
        raw = ApiToken.generate_token()
        token = ApiToken(
            user_id=user_id,
            token=ApiToken.hash_token(raw),
            token_prefix=raw[: ApiToken.PREFIX_LEN],
            name=name,
            expires_at=(
                datetime.utcnow() + timedelta(days=expires_in_days)
                if expires_in_days
                else None
            ),
        )
        db.session.add(token)
        db.session.commit()
        return token, raw
