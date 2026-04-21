from flask import Blueprint

from .inventory_sessions import inventory_sessions_bp
from .legacy_aliases import legacy_aliases_bp
from .maintenance import maintenance_bp
from .products import products_bp
from .stock import stock_bp

inventory_vnext_bp = Blueprint("inventory_vnext", __name__, url_prefix="/vnext/api")

inventory_vnext_bp.register_blueprint(products_bp)
inventory_vnext_bp.register_blueprint(stock_bp)
inventory_vnext_bp.register_blueprint(inventory_sessions_bp)
inventory_vnext_bp.register_blueprint(maintenance_bp)
inventory_vnext_bp.register_blueprint(legacy_aliases_bp)
