"""Shared Flask blueprint and constants for the kanban module."""

from flask import Blueprint

kanban_bp = Blueprint("kanban", "app.blueprints.kanban")

BOARD_BACKGROUNDS = [
    {"key": "teal", "css": "linear-gradient(135deg, #0f766e, #14b8a6)"},
    {"key": "slate", "css": "linear-gradient(135deg, #334155, #64748b)"},
    {"key": "ocean", "css": "linear-gradient(135deg, #0ea5e9, #0369a1)"},
    {"key": "forest", "css": "linear-gradient(135deg, #166534, #22c55e)"},
    {"key": "sunset", "css": "linear-gradient(135deg, #c2410c, #f59e0b)"},
    {"key": "berry", "css": "linear-gradient(135deg, #9f1239, #e11d48)"},
]

CUSTOM_FIELD_TYPES = ("text", "select", "date", "time", "checkbox")
