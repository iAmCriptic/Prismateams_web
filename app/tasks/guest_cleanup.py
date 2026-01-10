"""
Background Task für Gast-Account-Bereinigung
Löscht automatisch abgelaufene Gast-Accounts.
"""

import logging
from datetime import datetime
from app import db
from app.models.user import User
from app.models.guest import GuestShareAccess

logger = logging.getLogger(__name__)


def cleanup_expired_guests():
    """Löscht alle abgelaufenen Gast-Accounts."""
    try:
        # Finde alle abgelaufenen Gast-Accounts
        expired_guests = User.query.filter(
            User.is_guest == True,
            User.guest_expires_at.isnot(None),
            User.guest_expires_at < datetime.utcnow()
        ).all()
        
        deleted_count = 0
        for guest in expired_guests:
            try:
                # Lösche zuerst alle zugehörigen GuestShareAccess-Einträge
                GuestShareAccess.query.filter_by(user_id=guest.id).delete()
                
                # Lösche den Gast-Account (Cascade löscht automatisch alle zugehörigen Daten)
                db.session.delete(guest)
                deleted_count += 1
                logger.info(f"Abgelaufener Gast-Account gelöscht: {guest.guest_username}@{guest.email}")
            except Exception as e:
                logger.error(f"Fehler beim Löschen des Gast-Accounts {guest.id}: {e}")
                db.session.rollback()
                continue
        
        if deleted_count > 0:
            db.session.commit()
            logger.info(f"{deleted_count} abgelaufene Gast-Accounts wurden gelöscht.")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Fehler bei der Gast-Account-Bereinigung: {e}", exc_info=True)
        db.session.rollback()
        return 0
