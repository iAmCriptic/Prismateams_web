from datetime import datetime

from app import db


class PublicShare(db.Model):
    __tablename__ = 'public_shares'

    id = db.Column(db.Integer, primary_key=True)
    resource_type = db.Column(db.String(32), nullable=False)  # 'file' | 'folder' | 'kanban_board'
    resource_id = db.Column(db.Integer, nullable=False)
    mode = db.Column(db.String(16), nullable=False)  # 'view' | 'edit' | 'dropbox'
    token = db.Column(db.String(255), nullable=False, unique=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    label = db.Column(db.String(255), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    access_logs = db.relationship(
        'ShareAccessLog',
        back_populates='public_share',
        cascade='all, delete-orphan',
        order_by='ShareAccessLog.accessed_at.desc()',
    )

    def __repr__(self):
        return f'<PublicShare {self.resource_type}:{self.resource_id} mode={self.mode} id={self.id}>'


class ShareAccessLog(db.Model):
    __tablename__ = 'share_access_logs'

    id = db.Column(db.Integer, primary_key=True)
    public_share_id = db.Column(db.Integer, db.ForeignKey('public_shares.id'), nullable=False)
    action = db.Column(db.String(32), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    guest_name = db.Column(db.String(255), nullable=True)
    accessed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    public_share = db.relationship('PublicShare', back_populates='access_logs')

    def __repr__(self):
        return f'<ShareAccessLog share={self.public_share_id} action={self.action}>'
