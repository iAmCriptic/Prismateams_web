"""Shared Flask blueprint and constants for the calendar module."""

import logging

from flask import Blueprint

calendar_bp = Blueprint("calendar", "app.blueprints.calendar")
logger = logging.getLogger("app.blueprints.calendar")
DEFAULT_EVENT_COLOR = "#0d6efd"
