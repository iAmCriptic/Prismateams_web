"""Shared per-user favorite row mutations (contacts, credentials, wiki)."""

from __future__ import annotations

from app import db


def _favorite_row(favorite_model, user_id, item_fk: str, item_id):
    return favorite_model.query.filter_by(user_id=user_id, **{item_fk: item_id}).first()


def count_user_favorites(favorite_model, user_id) -> int:
    return favorite_model.query.filter_by(user_id=user_id).count()


def toggle_user_favorite(user_id, favorite_model, item_fk: str, item_id):
    """Toggle a favorite row. Returns (is_favorite, favorites_count)."""
    existing = _favorite_row(favorite_model, user_id, item_fk, item_id)
    if existing:
        db.session.delete(existing)
        is_favorite = False
    else:
        db.session.add(favorite_model(user_id=user_id, **{item_fk: item_id}))
        is_favorite = True
    db.session.commit()
    return is_favorite, count_user_favorites(favorite_model, user_id)


def add_user_favorite(user_id, favorite_model, item_fk: str, item_id, *, max_count=None):
    """Add a favorite. Returns (status, is_favorite, favorites_count).

    status: 'ok' | 'already' | 'limit'
    """
    existing = _favorite_row(favorite_model, user_id, item_fk, item_id)
    count = count_user_favorites(favorite_model, user_id)
    if existing:
        return "already", True, count
    if max_count is not None and count >= max_count:
        return "limit", False, count
    db.session.add(favorite_model(user_id=user_id, **{item_fk: item_id}))
    db.session.commit()
    return "ok", True, count_user_favorites(favorite_model, user_id)


def remove_user_favorite(user_id, favorite_model, item_fk: str, item_id):
    """Remove a favorite. Returns (status, is_favorite, favorites_count).

    status: 'ok' | 'missing'
    """
    existing = _favorite_row(favorite_model, user_id, item_fk, item_id)
    if not existing:
        return "missing", False, count_user_favorites(favorite_model, user_id)
    db.session.delete(existing)
    db.session.commit()
    return "ok", False, count_user_favorites(favorite_model, user_id)
