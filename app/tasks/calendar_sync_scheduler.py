"""Background Task für Kalender-Synchronisation (Inbound iCal-URLs)."""

import logging

from app.tasks.interval_scheduler import IntervalScheduler

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 30 * 60
# Keine aktiven Quellen: Thread wacht seltener auf (Small-VPS / Idle).
IDLE_INTERVAL_SECONDS = 60 * 60


class CalendarSyncScheduler(IntervalScheduler):
    """Scheduler für regelmäßige Kalender-URL-Synchronisation."""

    name = "calendar-sync-scheduler"
    start_delay_seconds = 45
    wait_step_seconds = 60
    error_wait_seconds = 120

    def __init__(self, app=None):
        self._has_active_sources = True  # bis zum ersten Job optimistisch
        super().__init__(app)

    def interval_seconds(self):
        if self._has_active_sources:
            return SYNC_INTERVAL_SECONDS
        return IDLE_INTERVAL_SECONDS

    def run_job(self):
        from app.utils.common import is_module_enabled
        from app.utils.ical import sync_all_active_sources
        from app.models.calendar import CalendarSyncSource

        # PERF-02: Admin hat Modul abgeschaltet → keine iCal-Fetches
        if not is_module_enabled('module_calendar'):
            self._has_active_sources = False
            logger.debug("module_calendar deaktiviert — Kalender-Sync idle")
            return

        # PERF-07: ohne aktive Quellen kein Sync-Log / kein HTTP
        active_count = CalendarSyncSource.query.filter_by(is_active=True).count()
        from app.utils.nextcloud_calendar_settings import is_nextcloud_calendar_active
        nc_active = is_nextcloud_calendar_active()
        self._has_active_sources = (active_count > 0) or nc_active
        if active_count == 0 and not nc_active:
            logger.debug("Keine aktiven Kalender-Sync-Quellen — idle")
            return

        if active_count > 0:
            logger.info(
                "Starte automatische Kalender-Synchronisation (%s Quellen)...",
                active_count,
            )
            results = sync_all_active_sources()
            logger.info(
                "Kalender-Sync fertig: %s OK, %s Fehler",
                results.get("ok", 0),
                results.get("fail", 0),
            )

        if nc_active:
            from app.utils.nextcloud_calendar_sync import sync_all_nextcloud_calendars
            nc_res = sync_all_nextcloud_calendars(force=True)
            logger.info(
                "Nextcloud-Kalender-Sync fertig: %s OK, %s Fehler",
                nc_res.get("ok", 0),
                nc_res.get("fail", 0),
            )

        self._has_active_sources = (
            CalendarSyncSource.query.filter_by(is_active=True).count() > 0 or is_nextcloud_calendar_active()
        )


scheduler = CalendarSyncScheduler()


def start_calendar_sync_scheduler(app):
    global scheduler
    scheduler.init_app(app)
    return scheduler


def stop_calendar_sync_scheduler():
    global scheduler
    scheduler.stop()
