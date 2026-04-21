from flask import Blueprint, request
from flask_login import current_user, login_required

from app import db
from app.models.inventory import Product, ProductLot
from app.services.inventory import StockService

from .common import api_error, api_ok

stock_bp = Blueprint("inventory_vnext_stock", __name__)


@stock_bp.route("/stock/<int:product_id>", methods=["GET"])
@login_required
def product_stock(product_id):
    product = Product.query.get_or_404(product_id)
    lots = ProductLot.query.filter_by(product_id=product.id).order_by(ProductLot.created_at.desc()).all()
    return api_ok(
        {
            "product": {
                "id": product.id,
                "name": product.name,
                "item_type": product.item_type,
                "min_stock": product.min_stock,
                "on_hand": product.total_on_hand,
                "reserved": product.total_reserved,
                "available": product.total_available,
                "needs_reorder": product.needs_reorder,
            },
            "lots": [
                {
                    "id": lot.id,
                    "lot_code": lot.lot_code,
                    "quantity_on_hand": lot.quantity_on_hand,
                    "quantity_reserved": lot.quantity_reserved,
                    "expiration_date": lot.expiration_date.isoformat() if lot.expiration_date else None,
                }
                for lot in lots
            ],
        }
    )


@stock_bp.route("/stock/move", methods=["POST"])
@login_required
def move_stock():
    data = request.get_json() or {}
    product_id = data.get("product_id")
    movement_type = (data.get("movement_type") or "").upper()
    quantity = int(data.get("quantity") or 0)
    reason = (data.get("reason") or "").strip() or None
    lot_id = data.get("lot_id")

    if not product_id or quantity <= 0:
        return api_error("invalid_payload", "product_id und positive quantity sind erforderlich.", 400)

    product = Product.query.get_or_404(product_id)
    if product.item_type != "consumable":
        return api_error("invalid_item_type", "Lot-basierte Bewegungen sind nur für Verbrauchsmaterial erlaubt.", 400)

    try:
        if movement_type in {"IN", "ADJUST"}:
            movement = StockService.add_stock(product, quantity, current_user.id, reason=reason, lot_id=lot_id)
        elif movement_type in {"OUT", "CONSUME"}:
            movement = StockService.consume_stock(product, quantity, current_user.id, reason=reason, lot_id=lot_id)
        elif movement_type == "RESERVE":
            movement = StockService.reserve_stock(product, quantity, current_user.id, reason=reason, lot_id=lot_id)
        elif movement_type == "RELEASE":
            movement = StockService.release_reserved_stock(product, quantity, current_user.id, reason=reason, lot_id=lot_id)
        else:
            return api_error("unsupported_movement", "movement_type wird nicht unterstützt.", 400)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return api_error("stock_operation_failed", str(exc), 409)

    return api_ok(
        {
            "movement": {
                "id": movement.id,
                "product_id": movement.product_id,
                "lot_id": movement.lot_id,
                "movement_type": movement.movement_type,
                "quantity_delta": movement.quantity_delta,
                "quantity_after": movement.quantity_after,
            },
            "summary": {
                "on_hand": product.total_on_hand,
                "reserved": product.total_reserved,
                "available": product.total_available,
                "needs_reorder": product.needs_reorder,
            },
        }
    )
