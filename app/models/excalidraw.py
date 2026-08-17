from datetime import datetime
import secrets

from app import db


class ExcalidrawDrawing(db.Model):
    __tablename__ = 'excalidraw_drawings'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    thumbnail_path = db.Column(db.String(500), nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    visibility = db.Column(db.String(20), nullable=False, default='public', index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, index=True)

    room_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    room_key = db.Column(db.String(64), nullable=False)

    version_number = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship('User', backref='excalidraw_drawings')
    versions = db.relationship(
        'ExcalidrawDrawingVersion',
        back_populates='drawing',
        cascade='all, delete-orphan',
        order_by='ExcalidrawDrawingVersion.version_number.desc()',
    )

    def __repr__(self):
        return f'<ExcalidrawDrawing {self.id} {self.name}>'

    @staticmethod
    def generate_room_id():
        return secrets.token_hex(16)

    @staticmethod
    def generate_room_key():
        return secrets.token_hex(16)


class ExcalidrawDrawingVersion(db.Model):
    __tablename__ = 'excalidraw_drawing_versions'

    id = db.Column(db.Integer, primary_key=True)
    drawing_id = db.Column(db.Integer, db.ForeignKey('excalidraw_drawings.id'), nullable=False, index=True)
    version_number = db.Column(db.Integer, nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    drawing = db.relationship('ExcalidrawDrawing', back_populates='versions')
    creator = db.relationship('User', backref='excalidraw_drawing_versions')

    def __repr__(self):
        return f'<ExcalidrawDrawingVersion {self.drawing_id} v{self.version_number}>'
