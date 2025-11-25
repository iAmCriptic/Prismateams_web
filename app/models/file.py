from datetime import datetime
from app import db


class Folder(db.Model):
    __tablename__ = 'folders'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    is_dropbox = db.Column(db.Boolean, default=False, nullable=False)
    dropbox_token = db.Column(db.String(255), nullable=True, unique=True)
    dropbox_password_hash = db.Column(db.String(255), nullable=True)
    
    share_enabled = db.Column(db.Boolean, default=False, nullable=False)
    share_token = db.Column(db.String(255), nullable=True, unique=True)
    share_password_hash = db.Column(db.String(255), nullable=True)
    share_expires_at = db.Column(db.DateTime, nullable=True)
    share_name = db.Column(db.String(255), nullable=True)
    
    parent = db.relationship('Folder', remote_side=[id], backref='subfolders')
    files = db.relationship('File', back_populates='folder', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Folder {self.name}>'
    
    @property
    def path(self):
        """Get the full path of the folder."""
        if self.parent:
            return f"{self.parent.path}/{self.name}"
        return self.name


class File(db.Model):
    __tablename__ = 'files'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    folder_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    mime_type = db.Column(db.String(100), nullable=True)
    version_number = db.Column(db.Integer, default=1, nullable=False)
    is_current = db.Column(db.Boolean, default=True, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Sharing fields
    share_enabled = db.Column(db.Boolean, default=False, nullable=False)
    share_token = db.Column(db.String(255), nullable=True, unique=True)
    share_password_hash = db.Column(db.String(255), nullable=True)
    share_expires_at = db.Column(db.DateTime, nullable=True)
    share_name = db.Column(db.String(255), nullable=True)

    folder = db.relationship('Folder', back_populates='files')
    uploader = db.relationship('User', back_populates='uploaded_files')
    versions = db.relationship('FileVersion', back_populates='file', cascade='all, delete-orphan', order_by='FileVersion.version_number.desc()')
    
    def __repr__(self):
        return f'<File {self.name}>'


class FileVersion(db.Model):
    __tablename__ = 'file_versions'
    
    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    file = db.relationship('File', back_populates='versions')
    
    def __repr__(self):
        return f'<FileVersion {self.file_id} v{self.version_number}>'



