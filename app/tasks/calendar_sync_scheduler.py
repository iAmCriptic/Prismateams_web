"""
Background Task für Kalender-Synchronisation (Inbound iCal-URLs).
"""

import threading
import time
import logging

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 30 * 60  # 30 Minuten


class CalendarSyncScheduler:
    """Scheduler für regelmäßige Kalender-URL-Synchronisation."""

    def __init__(self, app=None):
        self.app = app
        self.running = False
        self.thread = None

        if app:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        self.start()

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info('Kalender-Sync-Scheduler gestartet')

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info('Kalender-Sync-Scheduler gestoppt')

    def _run_scheduler(self):
        # Kurze Verzögerung beim Start, damit die App hochfahren kann
        time.sleep(15)
        while self.running:
            try:
                with self.app.app_context():
                    from app.utils.ical import sync_all_active_sources
                    logger.info('Starte automatische Kalender-Synchronisation...')
                    results = sync_all_active_sources()
                    logger.info(
                        'Kalender-Sync fertig: %s OK, %s Fehler',
                        results.get('ok', 0),
                        results.get('fail', 0),
                    )
            except Exception as exc:
                logger.error('Kalender-Sync-Scheduler Fehler: %s', exc, exc_info=True)

            # Intervall in kleinen Schritten, damit stop() schneller reagiert
            slept = 0
            while self.running and slept < SYNC_INTERVAL_SECONDS:
                time.sleep(5)
                slept += 5


scheduler = CalendarSyncScheduler()


def start_calendar_sync_scheduler(app):
    global scheduler
    scheduler.init_app(app)
    return scheduler


def stop_calendar_sync_scheduler():
    global scheduler
    scheduler.stop()
