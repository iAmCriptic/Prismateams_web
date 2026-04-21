from datetime import datetime

from app import db
from app.models.inventory import ProductLot, StockMovement


class StockService:
    """Domänenlogik für lot-basierten Bestand."""

    DEFAULT_LOT_CODE = "AUTO-DEFAULT"

    @staticmethod
    def ensure_default_lot(product, user_id):
        lot = ProductLot.query.filter_by(product_id=product.id, lot_code=StockService.DEFAULT_LOT_CODE).first()
        if lot:
            return lot
        lot = ProductLot(
            product_id=product.id,
            lot_code=StockService.DEFAULT_LOT_CODE,
            quantity_on_hand=0,
            quantity_reserved=0,
            created_by=user_id,
        )
        db.session.add(lot)
        db.session.flush()
        return lot

    @staticmethod
    def add_stock(product, quantity, user_id, reason=None, lot_id=None, context_type="manual", context_id=None):
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if product.item_type != "consumable":
            raise ValueError("add_stock only valid for consumables")

        lot = ProductLot.query.filter_by(id=lot_id, product_id=product.id).first() if lot_id else None
        if not lot:
            lot = StockService.ensure_default_lot(product, user_id)

        lot.quantity_on_hand = int(lot.quantity_on_hand or 0) + int(quantity)
        movement = StockMovement(
            product_id=product.id,
            lot_id=lot.id,
            movement_type="IN",
            quantity_delta=int(quantity),
            quantity_after=lot.quantity_on_hand,
            reason=reason,
            context_type=context_type,
            context_id=str(context_id) if context_id else None,
            performed_by=user_id,
            created_at=datetime.utcnow(),
        )
        db.session.add(movement)
        db.session.flush()
        return movement

    @staticmethod
    def consume_stock(product, quantity, user_id, reason=None, lot_id=None, context_type="manual", context_id=None):
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if product.item_type != "consumable":
            raise ValueError("consume_stock only valid for consumables")

        lot = ProductLot.query.filter_by(id=lot_id, product_id=product.id).first() if lot_id else None
        if not lot:
            lot = StockService.ensure_default_lot(product, user_id)

        available = int(lot.quantity_on_hand or 0) - int(lot.quantity_reserved or 0)
        if available < quantity:
            raise ValueError("insufficient_stock")

        lot.quantity_on_hand = int(lot.quantity_on_hand or 0) - int(quantity)
        movement = StockMovement(
            product_id=product.id,
            lot_id=lot.id,
            movement_type="CONSUME",
            quantity_delta=-int(quantity),
            quantity_after=lot.quantity_on_hand,
            reason=reason,
            context_type=context_type,
            context_id=str(context_id) if context_id else None,
            performed_by=user_id,
            created_at=datetime.utcnow(),
        )
        db.session.add(movement)
        db.session.flush()
        return movement

    @staticmethod
    def reserve_stock(product, quantity, user_id, reason=None, lot_id=None, context_type="borrow", context_id=None):
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if product.item_type != "consumable":
            raise ValueError("reserve_stock only valid for consumables")

        lot = ProductLot.query.filter_by(id=lot_id, product_id=product.id).first() if lot_id else None
        if not lot:
            lot = StockService.ensure_default_lot(product, user_id)

        available = int(lot.quantity_on_hand or 0) - int(lot.quantity_reserved or 0)
        if available < quantity:
            raise ValueError("insufficient_stock")

        lot.quantity_reserved = int(lot.quantity_reserved or 0) + int(quantity)
        movement = StockMovement(
            product_id=product.id,
            lot_id=lot.id,
            movement_type="RESERVE",
            quantity_delta=int(quantity),
            quantity_after=lot.quantity_reserved,
            reason=reason,
            context_type=context_type,
            context_id=str(context_id) if context_id else None,
            performed_by=user_id,
            created_at=datetime.utcnow(),
        )
        db.session.add(movement)
        db.session.flush()
        return movement

    @staticmethod
    def release_reserved_stock(product, quantity, user_id, reason=None, lot_id=None, context_type="borrow", context_id=None):
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if product.item_type != "consumable":
            raise ValueError("release_reserved_stock only valid for consumables")

        lot = ProductLot.query.filter_by(id=lot_id, product_id=product.id).first() if lot_id else None
        if not lot:
            lot = StockService.ensure_default_lot(product, user_id)

        if int(lot.quantity_reserved or 0) < quantity:
            raise ValueError("insufficient_reserved_stock")

        lot.quantity_reserved = int(lot.quantity_reserved or 0) - int(quantity)
        movement = StockMovement(
            product_id=product.id,
            lot_id=lot.id,
            movement_type="RELEASE",
            quantity_delta=-int(quantity),
            quantity_after=lot.quantity_reserved,
            reason=reason,
            context_type=context_type,
            context_id=str(context_id) if context_id else None,
            performed_by=user_id,
            created_at=datetime.utcnow(),
        )
        db.session.add(movement)
        db.session.flush()
        return movement
