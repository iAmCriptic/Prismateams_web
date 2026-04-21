from datetime import datetime

from flask import Blueprint, request
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app import db
from app.models.inventory import Inventory, InventoryItem
from app.services.inventory import InventoryLockService

from .common import api_error, api_ok

inventory_sessions_bp = Blueprint("inventory_vnext_inventory_sessions", __name__)


@inventory_sessions_bp.route("/inventory/<int:inventory_id>/items", methods=["GET"])
@login_required
def inventory_items(inventory_id):
    inventory = Inventory.query.get_or_404(inventory_id)
    items = (
        InventoryItem.query.filter_by(inventory_id=inventory.id)
        .options(joinedload(InventoryItem.product), joinedload(InventoryItem.checker))
        .order_by(InventoryItem.updated_at.desc())
        .all()
    )

    return api_ok(
        {
            "inventory": {
                "id": inventory.id,
                "name": inventory.name,
                "status": inventory.status,
                "checked_count": inventory.checked_count,
                "total_count": inventory.total_count,
            },
            "items": [
                {
                    "product_id": item.product_id,
                    "product_name": item.product.name,
                    "checked": item.checked,
                    "notes": item.notes,
                    "new_location": item.new_location,
                    "new_condition": item.new_condition,
                    "version": item.version,
                    "last_changed_by": item.checker.full_name if item.checker else None,
                    "last_changed_at": item.updated_at.isoformat() if item.updated_at else None,
                }
                for item in items
            ],
        }
    )


@inventory_sessions_bp.route("/inventory/<int:inventory_id>/locks/acquire", methods=["POST"])
@login_required
def acquire_lock(inventory_id):
    data = request.get_json() or {}
    product_id = data.get("product_id")
    ttl_seconds = int(data.get("ttl_seconds") or 90)
    reason = (data.get("reason") or "").strip() or None

    if not product_id:
        return api_error("product_id_required", "product_id ist erforderlich.", 400)

    lock, conflict = InventoryLockService.acquire(inventory_id, int(product_id), current_user.id, ttl_seconds, reason)
    if conflict:
        return api_error(
            "lock_conflict",
            "Produkt wird aktuell von einem anderen Nutzer bearbeitet.",
            409,
            details={
                "locked_by": conflict.locked_by,
                "expires_at": conflict.expires_at.isoformat(),
            },
        )

    db.session.commit()
    return api_ok(
        {
            "lock": {
                "inventory_id": lock.inventory_id,
                "product_id": lock.product_id,
                "locked_by": lock.locked_by,
                "expires_at": lock.expires_at.isoformat(),
            }
        }
    )


@inventory_sessions_bp.route("/inventory/<int:inventory_id>/locks/refresh", methods=["POST"])
@login_required
def refresh_lock(inventory_id):
    data = request.get_json() or {}
    product_id = data.get("product_id")
    ttl_seconds = int(data.get("ttl_seconds") or 90)
    if not product_id:
        return api_error("product_id_required", "product_id ist erforderlich.", 400)

    lock = InventoryLockService.refresh(inventory_id, int(product_id), current_user.id, ttl_seconds)
    if not lock:
        db.session.rollback()
        return api_error("lock_missing", "Kein aktiver Lock für diesen Nutzer vorhanden.", 404)

    db.session.commit()
    return api_ok({"expires_at": lock.expires_at.isoformat()})


@inventory_sessions_bp.route("/inventory/<int:inventory_id>/locks/release", methods=["POST"])
@login_required
def release_lock(inventory_id):
    data = request.get_json() or {}
    product_id = data.get("product_id")
    if not product_id:
        return api_error("product_id_required", "product_id ist erforderlich.", 400)

    released = InventoryLockService.release(inventory_id, int(product_id), current_user.id)
    if not released:
        db.session.rollback()
        return api_error("lock_missing", "Kein aktiver Lock für diesen Nutzer vorhanden.", 404)

    db.session.commit()
    return api_ok({"released": True})


@inventory_sessions_bp.route("/inventory/<int:inventory_id>/item/<int:product_id>", methods=["PUT"])
@login_required
def update_inventory_item(inventory_id, product_id):
    inventory = Inventory.query.get_or_404(inventory_id)
    if inventory.status != "active":
        return api_error("inventory_not_active", "Inventur ist nicht aktiv.", 400)

    item = InventoryItem.query.filter_by(inventory_id=inventory_id, product_id=product_id).first_or_404()
    data = request.get_json() or {}

    expected_version = data.get("version")
    if expected_version is None:
        if_match = request.headers.get("If-Match")
        if if_match and if_match.isdigit():
            expected_version = int(if_match)

    if expected_version is None:
        return api_error("version_required", "Version fehlt fuer konfliktfreie Aktualisierung.", 428)
    if int(expected_version) != int(item.version):
        return api_error(
            "version_conflict",
            "Datensatz wurde zwischenzeitlich geändert.",
            409,
            details={
                "current_version": item.version,
                "last_changed_at": item.updated_at.isoformat() if item.updated_at else None,
            },
        )

    if "checked" in data:
        item.checked = bool(data["checked"])
        if item.checked:
            item.checked_by = current_user.id
            item.checked_at = datetime.utcnow()
        else:
            item.checked_by = None
            item.checked_at = None

    if "notes" in data:
        item.notes = (data.get("notes") or "").strip() or None
    if "new_location" in data:
        item.new_location = (data.get("new_location") or "").strip() or None
        item.location_changed = bool(item.new_location)
    if "new_condition" in data:
        item.new_condition = (data.get("new_condition") or "").strip() or None
        item.condition_changed = bool(item.new_condition)

    item.version = int(item.version) + 1
    db.session.commit()

    return api_ok(
        {
            "item": {
                "product_id": item.product_id,
                "checked": item.checked,
                "version": item.version,
                "last_changed_by": current_user.full_name,
                "last_changed_at": item.updated_at.isoformat() if item.updated_at else None,
            }
        }
    )
