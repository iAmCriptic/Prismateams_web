"""
Background Task für Gast-Account-Bereinigung
Deaktiviert abgelaufene Gast-Accounts und löscht sie nach 7 Tagen.
"""

import logging
from datetime import datetime, timedelta
from app import db
from app.models.user import User
from app.utils.common import portal_now_naive
from app.utils.session_manager import revoke_all_sessions

logger = logging.getLogger(__name__)


def cleanup_expired_guests():
    """Deaktiviert abgelaufene Gäste und löscht alte deaktivierte Gäste."""
    try:
        # guest_expires_at wird als Portal-Wandzeit (naive) gespeichert — nicht mit UTC vergleichen.
        now = portal_now_naive()
        # updated_at ist typischerweise UTC-naive — Retention daran messen.
        retention_cutoff = datetime.utcnow() - timedelta(days=7)

        # 1) Abgelaufene aktive Gäste deaktivieren.
        expired_active_guests = User.query.filter(
            User.is_guest == True,
            User.is_active == True,
            User.guest_expires_at.isnot(None),
            User.guest_expires_at < now
        ).all()

        deactivated_count = 0
        for guest in expired_active_guests:
            try:
                guest.is_active = False
                revoke_all_sessions(guest.id, exclude_current=False)
                deactivated_count += 1
                logger.info(
                    "Abgelaufener Gast-Account deaktiviert: %s (id=%s)",
                    guest.guest_username,
                    guest.id,
                )
            except Exception as e:
                logger.error(f"Fehler beim Deaktivieren des Gast-Accounts {guest.id}: {e}")
                db.session.rollback()
                continue

        if deactivated_count > 0:
            db.session.commit()

        # 2) Bereits deaktivierte Gäste nach 7 Tagen endgültig löschen (gleiche Pipeline wie Admin/Self-Service).
        deletable_guests = User.query.filter(
            User.is_guest == True,
            User.is_active == False,
            User.updated_at.isnot(None),
            User.updated_at < retention_cutoff
        ).all()

        deleted_count = 0
        from app.utils.account_deletion import erase_user_account

        for guest in deletable_guests:
            guest_id = guest.id
            guest_label = guest.guest_username
            try:
                revoke_all_sessions(guest_id, exclude_current=False)
                erase_user_account(guest)
                db.session.commit()
                deleted_count += 1
                logger.info(
                    "Deaktivierter Gast-Account gelöscht: %s (id=%s)",
                    guest_label,
                    guest_id,
                )
            except Exception as e:
                logger.error(f"Fehler beim Löschen des Gast-Accounts {guest_id}: {e}")
                db.session.rollback()
                continue

        if deactivated_count > 0 or deleted_count > 0:
            logger.info(
                f"Gast-Bereinigung: {deactivated_count} deaktiviert, {deleted_count} gelöscht."
            )

        return deactivated_count + deleted_count

    except Exception as e:
        logger.error(f"Fehler bei der Gast-Account-Bereinigung: {e}", exc_info=True)
        db.session.rollback()
        return 0
