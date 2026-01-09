from datetime import datetime
from app import db
import re


class Comment(db.Model):
    __tablename__ = 'comments'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Polymorphe Verknüpfung: content_type und content_id
    content_type = db.Column(db.String(50), nullable=False)  # 'file', 'wiki', 'canvas'
    content_id = db.Column(db.Integer, nullable=False)
    
    # Kommentar-Inhalt
    content = db.Column(db.Text, nullable=False)
    
    # Autor
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Threading: parent_id für Antworten
    parent_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Soft delete
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    author = db.relationship('User', backref='comments')
    parent = db.relationship('Comment', remote_side=[id], backref='replies')
    
    def __repr__(self):
        return f'<Comment {self.id} on {self.content_type}:{self.content_id}>'
    
    def get_content_object(self):
        """Gibt das verknüpfte Objekt zurück."""
        if self.content_type == 'file':
            from app.models.file import File
            return File.query.get(self.content_id)
        elif self.content_type == 'wiki':
            from app.models.wiki import WikiPage
            return WikiPage.query.get(self.content_id)
        return None
    
    def get_content_url(self):
        """Gibt die URL zum verknüpften Objekt zurück."""
        if self.content_type == 'file':
            return f"/files/view/{self.content_id}"
        elif self.content_type == 'wiki':
            page = self.get_content_object()
            if page:
                return f"/wiki/view/{page.slug}"
            return "/wiki"
        return "/"
    
    def soft_delete(self):
        """Soft-Delete des Kommentars."""
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()
        db.session.commit()
    
    @staticmethod
    def extract_mentions(text):
        """Extrahiert @-Mentions aus Text."""
        # Pattern: @username oder @Vorname Nachname (mindestens 2 Zeichen nach @)
        pattern = r'@(\w{2,}(?:\s+\w+)?)'
        matches = re.findall(pattern, text)
        # Entferne Duplikate
        return list(set(matches))


class CommentMention(db.Model):
    __tablename__ = 'comment_mentions'
    
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Wurde die Benachrichtigung bereits gesendet?
    notification_sent = db.Column(db.Boolean, default=False, nullable=False)
    notification_sent_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    comment = db.relationship('Comment', backref='mentions')
    user = db.relationship('User', backref='comment_mentions')
    
    __table_args__ = (
        db.UniqueConstraint('comment_id', 'user_id', name='unique_comment_mention'),
    )
    
    def __repr__(self):
        return f'<CommentMention comment={self.comment_id} user={self.user_id}>'

