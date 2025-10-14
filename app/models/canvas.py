from datetime import datetime
from app import db


class Canvas(db.Model):
    __tablename__ = 'canvases'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    text_fields = db.relationship('CanvasTextField', back_populates='canvas', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Canvas {self.name}>'


class CanvasTextField(db.Model):
    __tablename__ = 'canvas_text_fields'
    
    id = db.Column(db.Integer, primary_key=True)
    canvas_id = db.Column(db.Integer, db.ForeignKey('canvases.id'), nullable=False)
    content = db.Column(db.Text, nullable=True)
    
    # Position and size
    pos_x = db.Column(db.Integer, default=0, nullable=False)
    pos_y = db.Column(db.Integer, default=0, nullable=False)
    width = db.Column(db.Integer, default=200, nullable=False)
    height = db.Column(db.Integer, default=100, nullable=False)
    
    # Styling
    font_size = db.Column(db.Integer, default=14)
    color = db.Column(db.String(7), default='#000000')
    background_color = db.Column(db.String(7), default='#ffffff')
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    canvas = db.relationship('Canvas', back_populates='text_fields')
    
    def __repr__(self):
        return f'<CanvasTextField {self.id} on canvas {self.canvas_id}>'



