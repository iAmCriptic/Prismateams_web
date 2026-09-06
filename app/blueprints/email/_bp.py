"""Shared Flask blueprint for the email module."""

import logging

from flask import Blueprint

email_bp = Blueprint("email", "app.blueprints.email")
logger = logging.getLogger("app.blueprints.email")
EMAIL_LIST_PER_PAGE = 50
