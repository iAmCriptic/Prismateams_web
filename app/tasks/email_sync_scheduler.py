"""
Background Task für E-Mail-Synchronisation (optional / ungenutzt vom Hauptpfad).

Der produktive Scheduler läuft in app.blueprints.email.start_email_sync
mit Leader-Election. Diese Klasse bleibt API-kompatibel und nutzt non-blocking Locks.
"""

import logging

from app.models.settings import SystemSettings
from app.tasks.interval_scheduler import IntervalScheduler

logger = logging.getLogger(__name__)


class EmailSyncScheduler(IntervalScheduler):
    """Scheduler für regelmäßige E-Mail-Synchronisation."""

    name = "email-sync-scheduler"
    wait_step_seconds = 60
    error_wait_seconds = 300

    def interval_seconds(self):
        try:
            sync_setting = SystemSettings.query.filter_by(key='email_sync_interval_minutes').first()
            if sync_setting and sync_setting.value:
                interval_minutes = int(sync_setting.value)
                interval_minutes = max(15, min(60, interval_minutes))
                return interval_minutes * 60
        except Exception as exc:
            logger.warning("Fehler beim Lesen des Synchronisationsintervalls: %s", exc)
        return 30 * 60

    def run_job(self):
        from app.blueprints.email import cleanup_old_emails, sync_all_configured_mailboxes
        from app.utils.lock_manager import acquire_email_sync_lock

        with acquire_email_sync_lock(timeout=0) as acquired:
            if not acquired:
                logger.debug(
                    "E-Mail-Synchronisation wird bereits von anderem Worker durchgeführt, überspringe..."
                )
                return
            logger.info("Starte automatische E-Mail-Synchronisation...")
            success, message = sync_all_configured_mailboxes()
            if success:
                logger.info("E-Mail-Synchronisation erfolgreich: %s", message)
            else:
                logger.warning("E-Mail-Synchronisation fehlgeschlagen: %s", message)
            deleted_count = cleanup_old_emails()
            if deleted_count > 0:
                logger.info("E-Mail-Bereinigung: %s E-Mails gelöscht", deleted_count)


scheduler = EmailSyncScheduler()


def start_email_sync_scheduler(app):
    global scheduler
    scheduler.init_app(app)
    return scheduler


def stop_email_sync_scheduler():
    global scheduler
    scheduler.stop()
