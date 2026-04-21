from flask import Blueprint, request
from flask_login import current_user, login_required

from app import db
from app.models.inventory import Product
from app.services.inventory import LifecycleService

from .common import api_error, api_ok

products_bp = Blueprint("inventory_vnext_products", __name__)


@products_bp.route("/products", methods=["GET"])
@login_required
def list_products():
    item_type = request.args.get("item_type")
    status = request.args.get("status")

    query = Product.query
    if item_type:
        query = query.filter_by(item_type=item_type)
    if status:
        query = query.filter_by(status=status)

    products = query.order_by(Product.name.asc()).all()
    return api_ok(
        {
            "products": [
                {
                    "id": p.id,
                    "name": p.name,
                    "item_type": p.item_type,
                    "status": p.status,
                    "min_stock": p.min_stock,
                    "on_hand": p.total_on_hand,
                    "reserved": p.total_reserved,
                    "available": p.total_available,
                    "needs_reorder": p.needs_reorder,
                }
                for p in products
            ]
        }
    )


@products_bp.route("/products/<int:product_id>/lifecycle", methods=["POST"])
@login_required
def change_lifecycle(product_id):
    product = Product.query.get_or_404(product_id)
    data = request.get_json() or {}

    new_status = (data.get("status") or "").strip()
    reason = (data.get("reason") or "").strip() or None
    note = (data.get("note") or "").strip() or None
    if not new_status:
        return api_error("status_required", "Neuer Status ist erforderlich.", 400)

    try:
        LifecycleService.change_status(
            product=product,
            new_status=new_status,
            changed_by=current_user.id,
            reason=reason,
            note=note,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return api_error("invalid_transition", str(exc), 409)

    return api_ok(
        {
            "product": {
                "id": product.id,
                "status": product.status,
            }
        }
    )
