from datetime import datetime
from app import db
import json


class MusicProviderToken(db.Model):
    __tablename__ = 'music_provider_tokens'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    provider = db.Column(db.String(20), nullable=False)
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)
    scope = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = db.relationship('User', backref='music_provider_tokens')
    __table_args__ = (db.UniqueConstraint('user_id', 'provider', name='unique_user_provider'),)

    def is_expired(self):
        if not self.token_expires_at:
            return False
        return datetime.utcnow() >= self.token_expires_at

    def get_scopes(self):
        if self.scope:
            try:
                return json.loads(self.scope)
            except:
                return []
        return []

    def set_scopes(self, scopes):
        if scopes:
            self.scope = json.dumps(scopes)
        else:
            self.scope = None

    def __repr__(self):
        return f'<MusicProviderToken {self.provider} for User {self.user_id}>'


class MusicWish(db.Model):
    __tablename__ = 'music_wishes'
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(20), nullable=False)  # 'spotify' or 'youtube'
    track_id = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    artist = db.Column(db.String(255), nullable=True)
    album = db.Column(db.String(255), nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    track_url = db.Column(db.String(500), nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    added_by_name = db.Column(db.String(255), nullable=True)  # Anonym, optional
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending, in_queue, played
    wish_count = db.Column(db.Integer, default=1, nullable=False)  # Anzahl der Wünsche für dieses Lied
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    queue_entry = db.relationship('MusicQueue', back_populates='wish', uselist=False, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<MusicWish {self.title} by {self.artist}>'


class MusicQueue(db.Model):
    __tablename__ = 'music_queue'
    id = db.Column(db.Integer, primary_key=True)
    wish_id = db.Column(db.Integer, db.ForeignKey('music_wishes.id'), nullable=False, unique=True)
    position = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending, playing, played
    added_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Wer hat es zur Queue hinzugefügt
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    played_at = db.Column(db.DateTime, nullable=True)

    wish = db.relationship('MusicWish', back_populates='queue_entry')
    adder = db.relationship('User', backref='music_queue_entries')

    def __repr__(self):
        return f'<MusicQueue {self.wish.title} (Pos: {self.position})>'


class MusicPlaylist(db.Model):
    __tablename__ = 'music_playlists'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    provider = db.Column(db.String(20), nullable=False)
    playlist_id = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    track_count = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='music_playlists')

    __table_args__ = (db.UniqueConstraint('user_id', 'provider', 'playlist_id', name='unique_user_provider_playlist'),)

    def __repr__(self):
        return f'<MusicPlaylist {self.name} ({self.provider})>'


class MusicSettings(db.Model):
    __tablename__ = 'music_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<MusicSettings {self.key}={self.value}>'

