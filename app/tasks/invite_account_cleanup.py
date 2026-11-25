"""
Background Task für zeitlich begrenzte Einladungs-Accounts.
Deaktiviert Accounts nach Ablauf von account_active_until (am Folgetag)
und löscht sie 7 Tage später endgültig, sofern sie nicht reaktiviert wurden.
"""

import logging
from datetime import datetime, timedelta

from app import db
from app.models.user import User
from app.utils.common import portal_now_naive
from app.utils.session_manager import revoke_all_sessions

logger = logging.getLogger(__name__)


def cleanup_expired_invite_accounts():
    """Deaktiviert abgelaufene Accounts und löscht nicht-reaktivierte Accounts nach 7 Tagen."""
    try:
        today = portal_now_naive().date()
        now_utc = datetime.utcnow()
        retention_cutoff = now_utc - timedelta(days=7)

        # 1) Aktive Accounts deaktivieren, deren account_active_until überschritten ist.
        # Beispiel: account_active_until = 2027-07-31 -> am 2027-08-01 gilt account_active_until < today.
        expired_active_users = User.query.filter(
            User.is_active == True,
            User.is_super_admin == False,
            User.email != 'anonymous@system.local',
            User.account_active_until.isnot(None),
            User.account_active_until < today,
        ).all()

        deactivated_count = 0
        for user in expired_active_users:
            try:
                user.is_active = False
                user.auto_deactivated_at = now_utc
                revoke_all_sessions(user.id, exclude_current=False)
                deactivated_count += 1
                logger.info(
                    "Befristeter Account deaktiviert: %s (id=%s, active_until=%s)",
                    user.email,
                    user.id,
                    user.account_active_until,
                )
            except Exception as e:
                logger.error("Fehler beim Deaktivieren des Accounts %s: %s", user.id, e)
                db.session.rollback()
                continue

        if deactivated_count > 0:
            db.session.commit()

        # 2) Automatisch deaktivierte Accounts nach 7 Tagen endgültig löschen (wenn nicht reaktiviert).
        deletable_users = User.query.filter(
            User.is_active == False,
            User.is_super_admin == False,
            User.email != 'anonymous@system.local',
            User.auto_deactivated_at.isnot(None),
            User.auto_deactivated_at <= retention_cutoff,
        ).all()

        deleted_count = 0
        from app.utils.account_deletion import erase_user_account

        for user in deletable_users:
            user_id = user.id
            user_email = user.email
            try:
                revoke_all_sessions(user_id, exclude_current=False)
                erase_user_account(user)
                db.session.commit()
                deleted_count += 1
                logger.info(
                    "Automatisch deaktivierter Account nach 7 Tagen gelöscht: %s (id=%s)",
                    user_email,
                    user_id,
                )
            except Exception as e:
                logger.error("Fehler beim Löschen des Accounts %s: %s", user_id, e)
                db.session.rollback()
                continue

        if deactivated_count > 0 or deleted_count > 0:
            logger.info(
                "Invite-Account-Bereinigung: %s deaktiviert, %s gelöscht.",
                deactivated_count,
                deleted_count,
            )

        return deactivated_count + deleted_count

    except Exception as e:
        logger.error("Fehler bei der Invite-Account-Bereinigung: %s", e, exc_info=True)
        db.session.rollback()
        return 0
