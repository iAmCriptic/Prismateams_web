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
    {"key": "indigo", "css": "linear-gradient(135deg, #312e81, #6366f1)"},
    {"key": "violet", "css": "linear-gradient(135deg, #581c87, #a855f7)"},
    {"key": "rose", "css": "linear-gradient(135deg, #be185d, #f472b6)"},
    {"key": "emerald", "css": "linear-gradient(135deg, #065f46, #34d399)"},
    {"key": "amber", "css": "linear-gradient(135deg, #b45309, #fbbf24)"},
    {"key": "crimson", "css": "linear-gradient(135deg, #7f1d1d, #ef4444)"},
    {"key": "midnight", "css": "linear-gradient(135deg, #0f172a, #1e3a8a)"},
    {"key": "aurora", "css": "linear-gradient(135deg, #0d9488, #6366f1)"},
    {"key": "peach", "css": "linear-gradient(135deg, #ea580c, #fb7185)"},
    {"key": "lagoon", "css": "linear-gradient(135deg, #0284c7, #2dd4bf)"},
    {"key": "plum", "css": "linear-gradient(135deg, #4c1d95, #db2777)"},
    {"key": "charcoal", "css": "linear-gradient(135deg, #18181b, #3f3f46)"},
]

CUSTOM_FIELD_TYPES = ("text", "select", "date", "time", "checkbox")
