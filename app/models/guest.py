from datetime import datetime
from app import db


class GuestShareAccess(db.Model):
    """Modell für Gast-Account-Zugriff auf Freigabelinks."""
    __tablename__ = 'guest_share_access'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    share_token = db.Column(db.String(255), nullable=False, index=True)  # Share-Token von File oder Folder
    share_type = db.Column(db.String(20), nullable=False)  # 'file' oder 'folder'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationship
    user = db.relationship('User', backref='guest_share_accesses')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'share_token', name='unique_guest_share_access'),
    )
    
    def __repr__(self):
        return f'<GuestShareAccess user={self.user_id} token={self.share_token} type={self.share_type}>'
