from datetime import datetime, timedelta

from app import db
from app.models.inventory import InventoryItemLock


class InventoryLockService:
    """Soft-Lock-Logik für kollaborative Inventur."""

    DEFAULT_TTL_SECONDS = 90

    @staticmethod
    def purge_expired():
        now = datetime.utcnow()
        InventoryItemLock.query.filter(InventoryItemLock.expires_at <= now).delete(synchronize_session=False)
        db.session.flush()

    @staticmethod
    def get_active_lock(inventory_id, product_id):
        InventoryLockService.purge_expired()
        return InventoryItemLock.query.filter_by(inventory_id=inventory_id, product_id=product_id).first()

    @staticmethod
    def acquire(inventory_id, product_id, user_id, ttl_seconds=None, reason=None):
        ttl = int(ttl_seconds or InventoryLockService.DEFAULT_TTL_SECONDS)
        now = datetime.utcnow()
        lock = InventoryLockService.get_active_lock(inventory_id, product_id)

        if lock and lock.locked_by != user_id:
            return None, lock

        if not lock:
            lock = InventoryItemLock(
                inventory_id=inventory_id,
                product_id=product_id,
                locked_by=user_id,
                lock_reason=reason,
                last_heartbeat_at=now,
                expires_at=now + timedelta(seconds=ttl),
            )
            db.session.add(lock)
        else:
            lock.lock_reason = reason or lock.lock_reason
            lock.refresh(ttl_seconds=ttl)

        db.session.flush()
        return lock, None

    @staticmethod
    def refresh(inventory_id, product_id, user_id, ttl_seconds=None):
        ttl = int(ttl_seconds or InventoryLockService.DEFAULT_TTL_SECONDS)
        lock = InventoryLockService.get_active_lock(inventory_id, product_id)
        if not lock or lock.locked_by != user_id:
            return None
        lock.refresh(ttl_seconds=ttl)
        db.session.flush()
        return lock

    @staticmethod
    def release(inventory_id, product_id, user_id):
        lock = InventoryLockService.get_active_lock(inventory_id, product_id)
        if not lock or lock.locked_by != user_id:
            return False
        db.session.delete(lock)
        db.session.flush()
        return True
