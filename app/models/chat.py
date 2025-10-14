from datetime import datetime
from app import db


class Chat(db.Model):
    __tablename__ = 'chats'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_main_chat = db.Column(db.Boolean, default=False, nullable=False)
    is_direct_message = db.Column(db.Boolean, default=False, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    members = db.relationship('ChatMember', back_populates='chat', cascade='all, delete-orphan')
    messages = db.relationship('ChatMessage', back_populates='chat', cascade='all, delete-orphan', order_by='ChatMessage.created_at')
    
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
    message_type = db.Column(db.String(20), default='text', nullable=False)  # text, image, video, voice
    media_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False)
    
    # Relationships
    chat = db.relationship('Chat', back_populates='messages')
    sender = db.relationship('User', back_populates='sent_messages')
    
    def __repr__(self):
        return f'<ChatMessage {self.id} from user {self.sender_id}>'



