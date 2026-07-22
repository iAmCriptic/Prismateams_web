from datetime import datetime
from app import db


class ManualFolder(db.Model):
    __tablename__ = 'manual_folders'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    color = db.Column(db.String(16), nullable=False, default='#0d6efd')
    position = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    manuals = db.relationship('Manual', back_populates='folder')

    def __repr__(self):
        return f'<ManualFolder {self.name}>'


class Manual(db.Model):
    __tablename__ = 'manuals'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    folder_id = db.Column(db.Integer, db.ForeignKey('manual_folders.id'), nullable=True)

    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    folder = db.relationship('ManualFolder', back_populates='manuals')

    def __repr__(self):
        return f'<Manual {self.title}>'
