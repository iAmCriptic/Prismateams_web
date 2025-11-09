from datetime import datetime
from app import db
import json
import re


class WikiCategory(db.Model):
    __tablename__ = 'wiki_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    color = db.Column(db.String(7), nullable=True)  # Hex color code
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    pages = db.relationship('WikiPage', back_populates='category')
    
    def __repr__(self):
        return f'<WikiCategory {self.name}>'


class WikiTag(db.Model):
    __tablename__ = 'wiki_tags'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Many-to-many relationship with WikiPage
    pages = db.relationship('WikiPage', secondary='wiki_page_tags', back_populates='tags')
    
    def __repr__(self):
        return f'<WikiTag {self.name}>'


# Association table for many-to-many relationship between WikiPage and WikiTag
wiki_page_tags = db.Table('wiki_page_tags',
    db.Column('wiki_page_id', db.Integer, db.ForeignKey('wiki_pages.id'), primary_key=True),
    db.Column('wiki_tag_id', db.Integer, db.ForeignKey('wiki_tags.id'), primary_key=True)
)


class WikiPage(db.Model):
    __tablename__ = 'wiki_pages'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)  # Markdown content
    file_path = db.Column(db.String(500), nullable=False)  # Path to .md file
    
    category_id = db.Column(db.Integer, db.ForeignKey('wiki_categories.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    version_number = db.Column(db.Integer, default=1, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    category = db.relationship('WikiCategory', back_populates='pages')
    creator = db.relationship('User', backref='created_wiki_pages')
    tags = db.relationship('WikiTag', secondary='wiki_page_tags', back_populates='pages')
    versions = db.relationship('WikiPageVersion', back_populates='wiki_page', cascade='all, delete-orphan', order_by='WikiPageVersion.version_number.desc()')
    
    def __repr__(self):
        return f'<WikiPage {self.title}>'
    
    @staticmethod
    def slugify(text):
        """Convert text to URL-friendly slug."""
        # Convert to lowercase
        text = text.lower()
        # Replace spaces and special characters with hyphens
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '-', text)
        # Remove leading/trailing hyphens
        text = text.strip('-')
        return text


class WikiPageVersion(db.Model):
    __tablename__ = 'wiki_page_versions'
    
    id = db.Column(db.Integer, primary_key=True)
    wiki_page_id = db.Column(db.Integer, db.ForeignKey('wiki_pages.id'), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    wiki_page = db.relationship('WikiPage', back_populates='versions')
    creator = db.relationship('User', backref='wiki_page_versions')
    
    def __repr__(self):
        return f'<WikiPageVersion {self.wiki_page_id} v{self.version_number}>'


class WikiFavorite(db.Model):
    __tablename__ = 'wiki_favorites'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    wiki_page_id = db.Column(db.Integer, db.ForeignKey('wiki_pages.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('User', backref='wiki_favorites')
    wiki_page = db.relationship('WikiPage', backref='favorited_by')
    
    # Unique constraint: Ein Benutzer kann eine Wiki-Seite nur einmal favorisieren
    __table_args__ = (db.UniqueConstraint('user_id', 'wiki_page_id', name='unique_user_wiki_favorite'),)
    
    def __repr__(self):
        return f'<WikiFavorite user={self.user_id} wiki_page={self.wiki_page_id}>'


