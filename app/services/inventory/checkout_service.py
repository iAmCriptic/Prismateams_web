"""Checkout service: create checkouts, return items, refresh status."""

from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Iterable, Optional, Sequence
import re

from app import db
from app.models.inventory import Checkout, CheckoutItem, Product
from app.utils.qr_code import generate_borrow_qr_code
from app.utils.common import portal_now_naive
import secrets
import string


BLOCKED_STATUSES = frozenset({"borrowed", "in_repair", "defective", "missing", "retired"})
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def generate_checkout_number() -> str:
    timestamp = portal_now_naive().strftime("%Y%m%d%H%M%S")
    random_part = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"CHK-{timestamp}-{random_part}"


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    raise ValueError("Invalid date/datetime")


def create_checkout(
    *,
    product_ids: Sequence[int],
    event_name: str,
    borrower_name: str,
    created_by_id: int,
    start_date=None,
    end_date=None,
    borrower_id: Optional[int] = None,
    contact_email: Optional[str] = None,
    require_event: bool = True,
    require_end_date: bool = True,
    event_id: Optional[int] = None,
    event_appointment_id: Optional[int] = None,
    product_source_sets: Optional[dict] = None,
) -> Checkout:
    event_name = (event_name or "").strip()
    borrower_name = (borrower_name or "").strip()
    contact_email = (contact_email or "").strip() or None

    if not require_event and not event_name:
        event_name = "Quick Scan"
    if require_event and not event_name:
        raise ValueError("event_name_required")
    if not borrower_name:
        raise ValueError("borrower_name_required")
    if not product_ids:
        raise ValueError("no_products")

    # Deduplicate IDs (preserve order) to avoid double CheckoutItems / double status flips
    seen_ids: set[int] = set()
    unique_ids: list[int] = []
    for raw_pid in product_ids:
        try:
            pid = int(raw_pid)
        except (TypeError, ValueError):
            continue
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        unique_ids.append(pid)
    if not unique_ids:
        raise ValueError("no_products")

    if not borrower_id:
        if not contact_email:
            raise ValueError("contact_email_required")
        if not EMAIL_RE.match(contact_email):
            raise ValueError("contact_email_invalid")
    else:
        # Portal-User: E-Mail optional speichern, aber nicht erzwingen
        contact_email = contact_email

    start_dt = _as_datetime(start_date) if start_date else portal_now_naive()
    if end_date:
        end_dt = _as_datetime(end_date)
    elif require_end_date:
        raise ValueError("end_date_required")
    else:
        end_dt = start_dt + timedelta(days=1)

    if end_dt < start_dt:
        raise ValueError("end_before_start")

    # Row-lock products (ordered by id → fewer deadlocks) before availability check
    products = (
        Product.query.filter(Product.id.in_(unique_ids))
        .order_by(Product.id.asc())
        .with_for_update()
        .all()
    )
    by_id = {p.id: p for p in products}
    available = []
    for pid in unique_ids:
        product = by_id.get(pid)
        if not product:
            continue
        if product.status != "available":
            continue
        available.append(product)

    if not available:
        raise ValueError("no_available_products")

    checkout_number = generate_checkout_number()
    checkout = Checkout(
        checkout_number=checkout_number,
        event_name=event_name,
        borrower_name=borrower_name,
        borrower_id=borrower_id,
        contact_email=contact_email,
        start_date=start_dt,
        end_date=end_dt,
        status="active",
        created_by=created_by_id,
        qr_code_data=generate_borrow_qr_code(checkout_number),
        event_id=event_id,
        event_appointment_id=event_appointment_id,
    )
    db.session.add(checkout)
    db.session.flush()

    for product in available:
        source_set_id = None
        if product_source_sets:
            raw = product_source_sets.get(product.id)
            if raw is None:
                raw = product_source_sets.get(str(product.id))
            try:
                source_set_id = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                source_set_id = None
        db.session.add(
            CheckoutItem(
                checkout_id=checkout.id,
                product_id=product.id,
                source_set_id=source_set_id,
                returned_at=None,
            )
        )
        product.status = "borrowed"

    checkout.refresh_status()
    db.session.commit()

    receipt_email_sent = False
    try:
        from app.utils.email_sender import send_borrow_receipt_email
        receipt_email_sent = bool(send_borrow_receipt_email(checkout))
    except Exception as email_err:
        import logging
        logging.error(f"Borrow receipt email failed for {checkout.checkout_number}: {email_err}")
        receipt_email_sent = False
    checkout.receipt_email_sent = receipt_email_sent
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        checkout.receipt_email_sent = receipt_email_sent

    return checkout


def return_checkout_items(
    item_ids: Iterable[int],
    *,
    mark_defective: bool = False,
    damage_image_path: Optional[str] = None,
) -> list[CheckoutItem]:
    items = CheckoutItem.query.filter(CheckoutItem.id.in_(list(item_ids))).all()
    if not items:
        raise ValueError("no_items")

    now = portal_now_naive()
    checkouts = {}
    returned = []
    for item in items:
        if item.returned_at is not None:
            continue
        item.returned_at = now
        if item.product:
            if mark_defective:
                item.product.status = "defective"
                if damage_image_path:
                    item.product.damage_image_path = damage_image_path
            else:
                item.product.status = "available"
        checkouts[item.checkout_id] = item.checkout
        returned.append(item)

    for checkout in checkouts.values():
        if checkout:
            checkout.refresh_status()

    db.session.commit()

    return_email_sent = True
    if returned:
        try:
            from app.utils.email_sender import send_return_confirmation_email
            by_checkout = {}
            for item in returned:
                if item.checkout_id not in by_checkout:
                    by_checkout[item.checkout_id] = []
                by_checkout[item.checkout_id].append(item)
            for checkout_id, items in by_checkout.items():
                checkout = checkouts.get(checkout_id) or items[0].checkout
                if checkout:
                    if not send_return_confirmation_email(checkout, returned_items=items):
                        return_email_sent = False
        except Exception as email_err:
            import logging
            logging.error(f"Return confirmation email failed: {email_err}")
            return_email_sent = False

    for item in returned:
        item.return_email_sent = return_email_sent
    for checkout in checkouts.values():
        if checkout:
            checkout.return_email_sent = return_email_sent
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return returned


def return_checkout_by_ref(ref: str, item_ids: Optional[Sequence[int]] = None) -> Checkout:
    """Return items by checkout_number, qr payload, or numeric id."""
    checkout = find_checkout(ref)
    if not checkout:
        raise ValueError("checkout_not_found")

    targets = checkout.active_items
    if item_ids:
        id_set = set(int(i) for i in item_ids)
        targets = [i for i in targets if i.id in id_set]
    if not targets:
        raise ValueError("no_active_items")

    returned = return_checkout_items([i.id for i in targets])
    db.session.refresh(checkout)
    checkout.return_email_sent = (
        getattr(returned[0], "return_email_sent", True) if returned else True
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return checkout


def find_checkout(ref: str) -> Optional[Checkout]:
    if not ref:
        return None
    ref = ref.strip()
    if ref.upper().startswith("BORROW-"):
        ref = ref[7:]
    if ref.upper().startswith("CHECKOUT-"):
        ref = ref[9:]

    checkout = Checkout.query.filter_by(checkout_number=ref).first()
    if checkout:
        return checkout
    checkout = Checkout.query.filter_by(qr_code_data=ref).first()
    if checkout:
        return checkout
    checkout = Checkout.query.filter_by(qr_code_data=f"BORROW-{ref}").first()
    if checkout:
        return checkout
    checkout = Checkout.query.filter_by(legacy_borrow_group_id=ref).first()
    if checkout:
        return checkout
    if ref.isdigit():
        return Checkout.query.get(int(ref))
    return None


def find_active_checkout_item_for_product(product_id: int) -> Optional[CheckoutItem]:
    return (
        CheckoutItem.query.join(Checkout)
        .filter(
            CheckoutItem.product_id == product_id,
            CheckoutItem.returned_at.is_(None),
            Checkout.status.in_(("active", "partially_returned")),
        )
        .order_by(CheckoutItem.id.desc())
        .first()
    )


def looks_like_return_qr(ref: str) -> bool:
    """True if payload looks like a checkout/borrow return code."""
    if not ref:
        return False
    raw = ref.strip()
    upper = raw.upper()
    if upper.startswith("BORROW-") or upper.startswith("CHECKOUT-") or upper.startswith("CHK-"):
        return True
    return find_checkout(raw) is not None


def serialize_checkout(checkout: Checkout) -> dict:
    return {
        "id": checkout.id,
        "checkout_number": checkout.checkout_number,
        "event_name": checkout.event_name,
        "borrower_name": checkout.borrower_name,
        "borrower_id": checkout.borrower_id,
        "contact_email": checkout.contact_email,
        "start_date": checkout.start_date.isoformat() if checkout.start_date else None,
        "end_date": checkout.end_date.isoformat() if checkout.end_date else None,
        "status": checkout.status,
        "is_overdue": checkout.is_overdue,
        "qr_code_data": checkout.qr_code_data,
        "item_count": len(checkout.items),
        "active_count": len(checkout.active_items),
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name if item.product else None,
                "serial_number": item.product.serial_number if item.product else None,
                "returned_at": item.returned_at.isoformat() if item.returned_at else None,
                "is_out": item.is_out,
            }
            for item in checkout.items
        ],
    }
