from datetime import datetime, timedelta
from app import db


class Folder(db.Model):
    __tablename__ = 'folders'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True, index=True)
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
    share_mode = db.Column(db.String(16), nullable=False, default='edit')
    color = db.Column(db.String(16), nullable=True)

    space = db.Column(db.String(16), nullable=False, default='public')
    is_personal_root = db.Column(db.Boolean, default=False, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True, index=True)
    is_team_root = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)
    deleted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    parent = db.relationship('Folder', remote_side=[id], backref='subfolders')
    files = db.relationship('File', back_populates='folder', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Folder {self.name}>'
    
    @property
    def path(self):
        """Get the full path of the folder (request-local cache + iterative walk)."""
        from flask import g, has_request_context

        cache = None
        if has_request_context():
            cache = getattr(g, '_folder_path_cache', None)
            if cache is None:
                cache = {}
                g._folder_path_cache = cache
            if self.id in cache:
                return cache[self.id]

        parts = []
        current = self
        seen = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            if cache is not None and current.id in cache:
                parts.append(cache[current.id])
                break
            parts.append(current.name)
            current = current.parent
        parts.reverse()
        value = '/'.join(parts) if parts else self.name
        if cache is not None and self.id is not None:
            cache[self.id] = value
        return value

    @staticmethod
    def prefetch_paths(folders):
        """
        Lädt alle Ancestors in wenigen Queries und füllt den Request-Pfad-Cache.
        Vermeidet N+1 bei Listen (Chat-Ordnerwahl, Events, …).
        """
        from flask import g, has_request_context

        folders = [f for f in (folders or []) if f is not None]
        if not folders:
            return {}

        by_id = {f.id: f for f in folders if f.id is not None}
        missing = {
            f.parent_id for f in folders
            if f.parent_id and f.parent_id not in by_id
        }
        while missing:
            rows = Folder.query.filter(Folder.id.in_(list(missing))).all()
            if not rows:
                break
            missing = set()
            for row in rows:
                by_id[row.id] = row
                if row.parent_id and row.parent_id not in by_id:
                    missing.add(row.parent_id)

        cache = {}
        if has_request_context():
            existing = getattr(g, '_folder_path_cache', None)
            if existing is None:
                existing = {}
                g._folder_path_cache = existing
            cache = existing

        def path_of(fid):
            if fid in cache:
                return cache[fid]
            node = by_id.get(fid)
            if node is None:
                return ''
            if not node.parent_id or node.parent_id not in by_id:
                value = node.name
            else:
                parent_path = path_of(node.parent_id)
                value = f'{parent_path}/{node.name}' if parent_path else node.name
            cache[fid] = value
            return value

        for folder in folders:
            if folder.id is not None:
                path_of(folder.id)
        return {fid: cache[fid] for fid in by_id if fid in cache}

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class File(db.Model):
    __tablename__ = 'files'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    folder_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True, index=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False)
    mime_type = db.Column(db.String(100), nullable=True)
    version_number = db.Column(db.Integer, default=1, nullable=False)
    is_current = db.Column(db.Boolean, default=True, nullable=False, index=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Sharing fields
    share_enabled = db.Column(db.Boolean, default=False, nullable=False)
    share_token = db.Column(db.String(255), nullable=True, unique=True)
    share_password_hash = db.Column(db.String(255), nullable=True)
    share_expires_at = db.Column(db.DateTime, nullable=True)
    share_name = db.Column(db.String(255), nullable=True)
    share_mode = db.Column(db.String(16), nullable=False, default='edit')

    space = db.Column(db.String(16), nullable=False, default='public')
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)
    deleted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    folder = db.relationship('Folder', back_populates='files')
    uploader = db.relationship('User', foreign_keys=[uploaded_by], back_populates='uploaded_files')
    versions = db.relationship('FileVersion', back_populates='file', cascade='all, delete-orphan', order_by='FileVersion.version_number.desc()')

    __table_args__ = (
        db.Index('ix_files_folder_deleted', 'folder_id', 'deleted_at'),
    )
    
    def __repr__(self):
        return f'<File {self.name}>'

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class FileVersion(db.Model):
    __tablename__ = 'file_versions'
    
    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    file = db.relationship('File', back_populates='versions')
    
    def __repr__(self):
        return f'<FileVersion {self.file_id} v{self.version_number}>'


class FileStorageException(db.Model):
    """Per-user overrides for max file size and/or storage quota."""
    __tablename__ = 'file_storage_exceptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    max_file_size_bytes = db.Column(db.BigInteger, nullable=True)
    quota_bytes = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])

    def __repr__(self):
        return f'<FileStorageException user={self.user_id}>'


class ResourceACL(db.Model):
    """Internal user/team/all sharing (separate from public link shares)."""
    __tablename__ = 'resource_acl'

    id = db.Column(db.Integer, primary_key=True)
    resource_type = db.Column(db.String(16), nullable=False)  # file | folder
    resource_id = db.Column(db.Integer, nullable=False)
    grantee_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    grantee_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True, index=True)
    permission = db.Column(db.String(16), nullable=False, default='view')  # view | edit
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    grantee = db.relationship('User', foreign_keys=[grantee_user_id])
    creator = db.relationship('User', foreign_keys=[created_by])

    __table_args__ = (
        db.Index('ix_resource_acl_type_id', 'resource_type', 'resource_id'),
    )

    @property
    def share_all(self):
        return self.grantee_user_id is None and self.grantee_team_id is None

    def __repr__(self):
        return (
            f'<ResourceACL {self.resource_type}:{self.resource_id} '
            f'-> user={self.grantee_user_id} team={self.grantee_team_id}>'
        )


class FolderFavorite(db.Model):
    """Per-user folder favorites for quick access in the files nav (max 10 enforced in API)."""
    __tablename__ = 'folder_favorites'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    folder_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref='folder_favorites')
    folder = db.relationship('Folder', backref='favorited_by')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'folder_id', name='unique_user_folder_favorite'),
    )

    def __repr__(self):
        return f'<FolderFavorite user={self.user_id} folder={self.folder_id}>'


class FileEditLock(db.Model):
    """Exclusive soft-lock so only one user can edit a text/markdown file at a time."""
    __tablename__ = 'file_edit_locks'

    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False, unique=True, index=True)
    locked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    session_key = db.Column(db.String(128), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    last_heartbeat_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    file = db.relationship('File')
    locker = db.relationship('User', foreign_keys=[locked_by])

    @property
    def is_active(self):
        return self.expires_at > datetime.utcnow()

    def refresh(self, ttl_seconds=90):
        now = datetime.utcnow()
        self.last_heartbeat_at = now
        self.expires_at = now + timedelta(seconds=ttl_seconds)

    def __repr__(self):
        return f'<FileEditLock file={self.file_id} by={self.locked_by}>'
