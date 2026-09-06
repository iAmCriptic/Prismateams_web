"""Kanban module package. Public API matches the former kanban.py."""

from app.blueprints.kanban._bp import BOARD_BACKGROUNDS, CUSTOM_FIELD_TYPES, kanban_bp

from app.blueprints.kanban import attachments as _attachments  # noqa: F401
from app.blueprints.kanban import boards as _boards  # noqa: F401
from app.blueprints.kanban import cards as _cards  # noqa: F401
from app.blueprints.kanban import members as _members  # noqa: F401
from app.blueprints.kanban import views as _views  # noqa: F401

__all__ = [
    "BOARD_BACKGROUNDS",
    "CUSTOM_FIELD_TYPES",
    "kanban_bp",
]
