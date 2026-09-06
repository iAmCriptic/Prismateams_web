"""Shared Flask blueprint and constants for the inventory module."""

from flask import Blueprint

inventory_bp = Blueprint("inventory", "app.blueprints.inventory")

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx'}
DOCUMENT_FILE_TYPES = {'handbook', 'datasheet', 'invoice', 'warranty', 'dguv', 'other'}
DEFAULT_DGUV_INTERVAL_MONTHS = 12
CART_SET_META_KEY = 'borrow_cart_set_meta'
CART_QTY_META_KEY = 'borrow_cart_quantities'
RETIRED_FOLDER_NAME = 'Papierkorb'
