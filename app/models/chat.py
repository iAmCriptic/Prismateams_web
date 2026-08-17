from datetime import datetime
import json
from app import db


class Chat(db.Model):
    __tablename__ = 'chats'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    group_avatar = db.Column(db.String(255), nullable=True)  # Pfad zum Gruppenbild
    description = db.Column(db.Text, nullable=True)  # Beschreibung des Chats
    is_main_chat = db.Column(db.Boolean, default=False, nullable=False)
    is_direct_message = db.Column(db.Boolean, default=False, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, unique=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    members = db.relationship('ChatMember', back_populates='chat', cascade='all, delete-orphan')
    messages = db.relationship('ChatMessage', back_populates='chat', cascade='all, delete-orphan', order_by='ChatMessage.created_at')
    team = db.relationship('Team', backref=db.backref('team_chat', uselist=False), foreign_keys=[team_id])

    @property
    def is_team_chat(self):
        return self.team_id is not None

    def __repr__(self):
        return f'<Chat {self.name}>'


class ChatMember(db.Model):
    __tablename__ = 'chat_members'
    
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_read_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    chat = db.relationship('Chat', back_populates='members')
    user = db.relationship('User', back_populates='chat_memberships')
    
    __table_args__ = (
        db.UniqueConstraint('chat_id', 'user_id', name='unique_chat_member'),
    )
    
    def __repr__(self):
        return f'<ChatMember chat={self.chat_id} user={self.user_id}>'


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=True)  # Nullable for media-only messages
    message_type = db.Column(db.String(20), default='text', nullable=False)  # text, image, video, voice, file, folder_link, calendar_event, poll
    media_url = db.Column(db.String(255), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False)
    
    # Relationships
    chat = db.relationship('Chat', back_populates='messages')
    sender = db.relationship('User', back_populates='sent_messages')
    
    def __repr__(self):
        return f'<ChatMessage {self.id} from user {self.sender_id}>'

    def get_metadata(self):
        if not self.metadata_json:
            return {}
        try:
            return json.loads(self.metadata_json)
        except Exception:
            return {}

    def set_metadata(self, value):
        if not value:
            self.metadata_json = None
            return
        self.metadata_json = json.dumps(value, ensure_ascii=False)


class ChatPin(db.Model):
    """Per-user pinned chats for the chat nav (max 6 enforced in API)."""
    __tablename__ = 'chat_pins'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref='chat_pins')
    chat = db.relationship('Chat', backref='pinned_by')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'chat_id', name='unique_user_chat_pin'),
    )

    def __repr__(self):
        return f'<ChatPin user={self.user_id} chat={self.chat_id}>'


