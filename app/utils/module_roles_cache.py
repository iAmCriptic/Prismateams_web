"""Request-scoped cache for UserModuleRole rows (one load per user per request)."""

from __future__ import annotations

from flask import g, has_request_context

_G_KEY = "_module_roles_by_user"
_listeners_registered = False


def get_user_module_roles(user_id) -> dict[str, bool]:
    """Return module_key → has_access for one user (loaded once per request)."""
    if user_id is None:
        return {}
    uid = int(user_id)

    store = None
    if has_request_context():
        store = getattr(g, _G_KEY, None)
        if not isinstance(store, dict):
            store = {}
            setattr(g, _G_KEY, store)
        cached = store.get(uid)
        if isinstance(cached, dict):
            return cached

    mapping: dict[str, bool] = {}
    try:
        from app.models.role import UserModuleRole

        mapping = {
            row.module_key: bool(row.has_access)
            for row in UserModuleRole.query.filter_by(user_id=uid).all()
        }
    except Exception:
        mapping = {}

    if store is not None:
        store[uid] = mapping
    return mapping


def role_has_access(user_id, module_key: str) -> bool:
    """True if a stored role grants access; missing key means no access."""
    if not module_key:
        return False
    return bool(get_user_module_roles(user_id).get(module_key))


def invalidate_module_roles_cache(user_id=None) -> None:
    """Drop cached roles for one user, or all users in this request."""
    if not has_request_context() or not hasattr(g, _G_KEY):
        return
    if user_id is None:
        delattr(g, _G_KEY)
        return
    store = getattr(g, _G_KEY, None)
    if isinstance(store, dict):
        store.pop(int(user_id), None)


def register_module_roles_cache_invalidation() -> None:
    """Clear cache when UserModuleRole rows change (idempotent)."""
    global _listeners_registered
    if _listeners_registered:
        return

    from sqlalchemy import event

    from app.models.role import UserModuleRole

    def _on_change(mapper, connection, target):  # noqa: ARG001
        invalidate_module_roles_cache(getattr(target, "user_id", None))

    event.listen(UserModuleRole, "after_insert", _on_change)
    event.listen(UserModuleRole, "after_update", _on_change)
    event.listen(UserModuleRole, "after_delete", _on_change)
    _listeners_registered = True
