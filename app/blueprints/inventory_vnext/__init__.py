from flask import Blueprint, jsonify
from flask_login import current_user

from .inventory_sessions import inventory_sessions_bp
from .legacy_aliases import legacy_aliases_bp
from .maintenance import maintenance_bp
from .products import products_bp
from .stock import stock_bp

inventory_vnext_bp = Blueprint("inventory_api", __name__, url_prefix="/inventory/api")

inventory_vnext_bp.register_blueprint(products_bp)
inventory_vnext_bp.register_blueprint(stock_bp)
inventory_vnext_bp.register_blueprint(inventory_sessions_bp)
inventory_vnext_bp.register_blueprint(maintenance_bp)
inventory_vnext_bp.register_blueprint(legacy_aliases_bp)


@inventory_vnext_bp.before_request
def require_inventory_module_access():
    """Alle /inventory/api/* Routen: Login + module_inventory."""
    from flask import request
    from app.utils.access_control import has_module_access
    from app.blueprints.inventory._bp import deny_inventory_module_access

    if request.method == "OPTIONS":
        return None
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401
    if has_module_access(current_user, "module_inventory"):
        return None
    return deny_inventory_module_access()
