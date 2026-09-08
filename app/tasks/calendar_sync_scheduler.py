"""Background Task für Kalender-Synchronisation (Inbound iCal-URLs)."""

import logging

from app.tasks.interval_scheduler import IntervalScheduler

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 30 * 60


class CalendarSyncScheduler(IntervalScheduler):
    """Scheduler für regelmäßige Kalender-URL-Synchronisation."""

    name = "calendar-sync-scheduler"
    start_delay_seconds = 15
    wait_step_seconds = 5
    error_wait_seconds = 60

    def interval_seconds(self):
        return SYNC_INTERVAL_SECONDS

    def run_job(self):
        from app.utils.common import is_module_enabled
        from app.utils.ical import sync_all_active_sources

        # PERF-02: Admin hat Modul abgeschaltet → keine iCal-Fetches
        if not is_module_enabled('module_calendar'):
            logger.debug("module_calendar deaktiviert — Kalender-Sync idle")
            return

        logger.info("Starte automatische Kalender-Synchronisation...")
        results = sync_all_active_sources()
        logger.info(
            "Kalender-Sync fertig: %s OK, %s Fehler",
            results.get("ok", 0),
            results.get("fail", 0),
        )


scheduler = CalendarSyncScheduler()


def start_calendar_sync_scheduler(app):
    global scheduler
    scheduler.init_app(app)
    return scheduler


def stop_calendar_sync_scheduler():
    global scheduler
    scheduler.stop()
