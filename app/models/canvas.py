from datetime import datetime

from app import db


class CanvasDocument(db.Model):
    """Canvas document backed by HyCanvas with local .hyc snapshot & visibility."""

    __tablename__ = 'canvas_documents'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    design_type = db.Column(db.String(64), nullable=False, default='whiteboard')
    preset_key = db.Column(db.String(64), nullable=False, default='whiteboard')
    width = db.Column(db.Integer, nullable=False, default=1920)
    height = db.Column(db.Integer, nullable=False, default=1080)

    hycanvas_design_id = db.Column(db.String(128), nullable=True, unique=True, index=True)
    file_path = db.Column(db.String(500), nullable=True)
    thumbnail_path = db.Column(db.String(500), nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    visibility = db.Column(db.String(20), nullable=False, default='private', index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship('User', backref='canvas_documents')

    def __repr__(self):
        return f'<CanvasDocument {self.id} {self.name}>'
