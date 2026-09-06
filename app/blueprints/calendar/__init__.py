"""Calendar module package. Public API matches the former calendar.py."""

from app.blueprints.calendar._bp import DEFAULT_EVENT_COLOR, calendar_bp, logger
from app.blueprints.calendar.helpers import (
    event_to_api_dict,
    generate_recurring_instances,
    sanitize_event_color,
)

from app.blueprints.calendar import events as _events  # noqa: F401
from app.blueprints.calendar import feeds as _feeds  # noqa: F401

__all__ = [
    "DEFAULT_EVENT_COLOR",
    "calendar_bp",
    "event_to_api_dict",
    "generate_recurring_instances",
    "logger",
    "sanitize_event_color",
]
