"""ToDo-Modul Datenmodell."""

from datetime import datetime
from app import db


class TodoItem(db.Model):
    """Eigenständige ToDo-Aufgabe (Privat, Team-Pool oder Public-Pool)."""

    __tablename__ = 'todo_items'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    visibility = db.Column(db.String(20), nullable=False, default='private', index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=True, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    due_date = db.Column(db.Date, nullable=True, index=True)
    due_time = db.Column(db.Time, nullable=True)
    is_completed = db.Column(db.Boolean, nullable=False, default=False, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = db.relationship('Team', foreign_keys=[team_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    assignee = db.relationship('User', foreign_keys=[assignee_id])
    completed_by = db.relationship('User', foreign_keys=[completed_by_id])

    def __repr__(self):
        return f'<TodoItem id={self.id} vis={self.visibility} done={self.is_completed}>'
