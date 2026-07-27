from datetime import date, datetime

from flask import Blueprint, request
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, selectinload

from app import db
from app.models.inventory import Inventory, InventoryItem, Product
from app.services.inventory import InventoryLockService
from app.utils.dates import compute_dguv_next

from .common import api_error, api_ok

inventory_sessions_bp = Blueprint("inventory_vnext_inventory_sessions", __name__)

_DEFAULT_DGUV_INTERVAL_MONTHS = 12
_PRODUCT_STATUSES = {
    "available",
    "borrowed",
    "missing",
    "defective",
    "in_repair",
    "retired",
}


def _clean_text(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("none", "null", "undefined"):
        return None
    return text


def _parse_optional_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_optional_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dguv_due(product):
    if not product or not product.dguv_next_check:
        return False
    return product.dguv_next_check <= date.today()


def _expected_quantity(product):
    if not product:
        return 1
    if product.item_type == "consumable":
        return int(product.total_on_hand or 0)
    return 1 if product.status != "retired" else 0


def _sync_inventory_products(inventory):
    """Fehlende Produkte (inkl. Defekt/Fehlend) in aktive Inventur nachziehen."""
    if not inventory or inventory.status != "active":
        return 0
    existing_ids = {
        row[0]
        for row in db.session.query(InventoryItem.product_id)
        .filter_by(inventory_id=inventory.id)
        .all()
    }
    added = 0
    for product in Product.query.filter(Product.status != "retired").all():
        if product.id in existing_ids:
            continue
        db.session.add(InventoryItem(inventory_id=inventory.id, product_id=product.id))
        added += 1
    if added:
        db.session.commit()
    return added


@inventory_sessions_bp.route("/inventory/<int:inventory_id>/items", methods=["GET"])
@login_required
def inventory_items(inventory_id):
    inventory = Inventory.query.get_or_404(inventory_id)
    _sync_inventory_products(inventory)
    items = (
        InventoryItem.query.filter_by(inventory_id=inventory.id)
        .options(
            joinedload(InventoryItem.product).selectinload(Product.lots),
            joinedload(InventoryItem.checker),
        )
        .order_by(InventoryItem.updated_at.desc())
        .all()
    )

    payload_items = []
    for item in items:
        if not item.product:
            continue
        product = item.product
        expected_qty = _expected_quantity(product)
        payload_items.append(
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": product.name,
                "product_category": _clean_text(product.category),
                "product_location": _clean_text(product.location),
                "product_condition": _clean_text(product.condition),
                "product_status": product.status,
                "product_serial_number": _clean_text(product.serial_number),
                "product_image_path": product.image_path,
                "product_item_type": product.item_type or "asset",
                "expected_quantity": expected_qty,
                "counted_quantity": item.counted_quantity,
                "dguv_last_check": product.dguv_last_check.isoformat() if product.dguv_last_check else None,
                "dguv_next_check": product.dguv_next_check.isoformat() if product.dguv_next_check else None,
                "dguv_interval_months": product.dguv_interval_months,
                "dguv_due": _dguv_due(product),
                "checked": item.checked,
                "notes": item.notes,
                "location_changed": item.location_changed,
                "new_location": _clean_text(item.new_location),
                "condition_changed": item.condition_changed,
                "new_condition": _clean_text(item.new_condition),
                "version": item.version,
                "checked_by": item.checked_by,
                "checked_by_name": item.checker.full_name if item.checker else None,
                "last_changed_by": item.checker.full_name if item.checker else None,
                "last_changed_at": item.updated_at.isoformat() if item.updated_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
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
            "items": payload_items,
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
        raw_loc = (data.get("new_location") or "").strip()
        if raw_loc.lower() in ("none", "null", "undefined"):
            raw_loc = ""
        item.new_location = raw_loc or None
        item.location_changed = bool(item.new_location)
    if "new_condition" in data:
        item.new_condition = (data.get("new_condition") or "").strip() or None
        item.condition_changed = bool(item.new_condition)
    if "counted_quantity" in data:
        raw_qty = data.get("counted_quantity")
        if raw_qty is None or raw_qty == "":
            item.counted_quantity = None
        else:
            qty = _parse_optional_int(raw_qty)
            if qty is None or qty < 0:
                return api_error("invalid_counted_quantity", "Anzahl muss eine ganze Zahl >= 0 sein.", 400)
            item.counted_quantity = qty

    product = item.product
    if product:
        if "product_status" in data:
            status = (data.get("product_status") or "").strip()
            if status in _PRODUCT_STATUSES:
                product.status = status
        if "dguv_last_check" in data:
            last = _parse_optional_date(data.get("dguv_last_check"))
            interval = product.dguv_interval_months or _DEFAULT_DGUV_INTERVAL_MONTHS
            product.dguv_last_check = last
            if last and not product.dguv_interval_months:
                product.dguv_interval_months = interval
            product.dguv_next_check = compute_dguv_next(product.dguv_last_check, product.dguv_interval_months)
        # Intervall und nächste Prüfung werden in der Inventur nicht manuell gesetzt

    item.version = int(item.version) + 1
    db.session.commit()

    return api_ok(
        {
            "item": {
                "product_id": item.product_id,
                "checked": item.checked,
                "notes": item.notes,
                "counted_quantity": item.counted_quantity,
                "expected_quantity": _expected_quantity(product),
                "product_item_type": (product.item_type if product else "asset") or "asset",
                "location_changed": item.location_changed,
                "new_location": _clean_text(item.new_location),
                "condition_changed": item.condition_changed,
                "new_condition": _clean_text(item.new_condition),
                "product_status": product.status if product else None,
                "dguv_last_check": product.dguv_last_check.isoformat() if product and product.dguv_last_check else None,
                "dguv_next_check": product.dguv_next_check.isoformat() if product and product.dguv_next_check else None,
                "dguv_interval_months": product.dguv_interval_months if product else None,
                "dguv_due": _dguv_due(product),
                "version": item.version,
                "last_changed_by": current_user.full_name,
                "last_changed_at": item.updated_at.isoformat() if item.updated_at else None,
            }
        }
    )
