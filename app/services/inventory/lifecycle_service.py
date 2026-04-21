from datetime import datetime

from app import db
from app.models.inventory import ProductStatusHistory


class LifecycleService:
    """Regeln für Produkt-Lifecycle und Historie."""

    ALLOWED_TRANSITIONS = {
        "available": {"borrowed", "missing", "defective", "retired"},
        "borrowed": {"available", "missing", "defective", "retired"},
        "missing": {"available", "defective", "retired"},
        "defective": {"in_repair", "retired"},
        "in_repair": {"available", "defective", "retired"},
        "retired": set(),
    }

    @staticmethod
    def can_transition(old_status, new_status):
        if old_status == new_status:
            return True
        allowed = LifecycleService.ALLOWED_TRANSITIONS.get(old_status, set())
        return new_status in allowed

    @staticmethod
    def change_status(product, new_status, changed_by, reason=None, note=None):
        old_status = product.status
        if not LifecycleService.can_transition(old_status, new_status):
            raise ValueError(f"invalid_transition:{old_status}->{new_status}")

        if old_status == new_status and not reason and not note:
            return None

        product.status = new_status
        history = ProductStatusHistory(
            product_id=product.id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            note=note,
            changed_by=changed_by,
            changed_at=datetime.utcnow(),
        )
        db.session.add(history)
        db.session.flush()
        return history
