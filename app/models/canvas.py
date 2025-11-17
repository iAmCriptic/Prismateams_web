from datetime import datetime
from app import db
import json


class Canvas(db.Model):
    __tablename__ = 'canvases'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # Excalidraw-Daten als JSON (kompletter Excalidraw-Export)
    excalidraw_data = db.Column(db.Text, nullable=True)
    
    # Room-ID für Excalidraw-Room Kollaboration (optional)
    room_id = db.Column(db.String(100), nullable=True)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def get_excalidraw_data(self):
        """Gibt die Excalidraw-Daten als Dictionary zurück."""
        if self.excalidraw_data:
            try:
                return json.loads(self.excalidraw_data)
            except json.JSONDecodeError:
                return None
        return None
    
    def set_excalidraw_data(self, data):
        """Setzt die Excalidraw-Daten aus einem Dictionary."""
        if data:
            self.excalidraw_data = json.dumps(data)
        else:
            self.excalidraw_data = None
    
    def __repr__(self):
        return f'<Canvas {self.name}>'

