from flask import Blueprint, request
from flask_login import current_user, login_required

from app import db
from app.models.inventory import Product, ProductStatusHistory
from app.services.inventory import LifecycleService

from .common import api_error, api_ok

maintenance_bp = Blueprint("inventory_vnext_maintenance", __name__)


@maintenance_bp.route("/maintenance/<int:product_id>/defect", methods=["POST"])
@login_required
def mark_defective(product_id):
    product = Product.query.get_or_404(product_id)
    data = request.get_json() or {}
    note = (data.get("note") or "").strip() or None

    try:
        LifecycleService.change_status(
            product=product,
            new_status="defective",
            changed_by=current_user.id,
            reason="defect_reported",
            note=note,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return api_error("invalid_transition", str(exc), 409)
    return api_ok({"product_id": product.id, "status": product.status})


@maintenance_bp.route("/maintenance/<int:product_id>/repair/start", methods=["POST"])
@login_required
def start_repair(product_id):
    product = Product.query.get_or_404(product_id)
    data = request.get_json() or {}
    note = (data.get("note") or "").strip() or None
    try:
        LifecycleService.change_status(
            product=product,
            new_status="in_repair",
            changed_by=current_user.id,
            reason="repair_started",
            note=note,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return api_error("invalid_transition", str(exc), 409)
    return api_ok({"product_id": product.id, "status": product.status})


@maintenance_bp.route("/maintenance/<int:product_id>/repair/complete", methods=["POST"])
@login_required
def complete_repair(product_id):
    product = Product.query.get_or_404(product_id)
    data = request.get_json() or {}
    note = (data.get("note") or "").strip() or None
    try:
        LifecycleService.change_status(
            product=product,
            new_status="available",
            changed_by=current_user.id,
            reason="repair_completed",
            note=note,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return api_error("invalid_transition", str(exc), 409)
    return api_ok({"product_id": product.id, "status": product.status})


@maintenance_bp.route("/maintenance/<int:product_id>/retire", methods=["POST"])
@login_required
def retire_product(product_id):
    product = Product.query.get_or_404(product_id)
    data = request.get_json() or {}
    note = (data.get("note") or "").strip() or None
    try:
        LifecycleService.change_status(
            product=product,
            new_status="retired",
            changed_by=current_user.id,
            reason="retired",
            note=note,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return api_error("invalid_transition", str(exc), 409)
    return api_ok({"product_id": product.id, "status": product.status})


@maintenance_bp.route("/maintenance/<int:product_id>/history", methods=["GET"])
@login_required
def maintenance_history(product_id):
    Product.query.get_or_404(product_id)
    history = (
        ProductStatusHistory.query.filter_by(product_id=product_id)
        .order_by(ProductStatusHistory.changed_at.desc())
        .all()
    )
    return api_ok(
        {
            "history": [
                {
                    "id": row.id,
                    "old_status": row.old_status,
                    "new_status": row.new_status,
                    "reason": row.reason,
                    "note": row.note,
                    "changed_by": row.changed_by,
                    "changed_at": row.changed_at.isoformat() if row.changed_at else None,
                }
                for row in history
            ]
        }
    )
