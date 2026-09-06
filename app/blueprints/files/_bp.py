"""Shared Flask blueprint and constants for the files module."""

from flask import Blueprint

files_bp = Blueprint("files", "app.blueprints.files")

MAX_FILE_VERSIONS = 3
MAX_FILE_PREVIEW_CHARS = 240
FILES_BROWSE_PAGE_SIZE = 48
