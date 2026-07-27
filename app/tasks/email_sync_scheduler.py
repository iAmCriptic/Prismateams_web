"""
Background Task für E-Mail-Synchronisation (optional / ungenutzt vom Hauptpfad).

Der produktive Scheduler läuft in app.blueprints.email.start_email_sync
mit Leader-Election. Diese Klasse bleibt API-kompatibel und nutzt non-blocking Locks.
"""

import threading
import time
import logging
from app.models.settings import SystemSettings

logger = logging.getLogger(__name__)


class EmailSyncScheduler:
    """Scheduler für regelmäßige E-Mail-Synchronisation."""
    
    def __init__(self, app=None):
        self.app = app
        self.running = False
        self.thread = None
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialisiere den Scheduler mit der Flask-App."""
        self.app = app
        self.start()
    
    def start(self):
        """Starte den E-Mail-Synchronisations-Scheduler."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("E-Mail-Synchronisations-Scheduler gestartet")
    
    def stop(self):
        """Stoppe den E-Mail-Synchronisations-Scheduler."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("E-Mail-Synchronisations-Scheduler gestoppt")
    
    def _get_sync_interval(self):
        """Hole das Synchronisationsintervall aus den Einstellungen (in Sekunden)."""
        try:
            sync_setting = SystemSettings.query.filter_by(key='email_sync_interval_minutes').first()
            if sync_setting and sync_setting.value:
                interval_minutes = int(sync_setting.value)
                interval_minutes = max(15, min(60, interval_minutes))
                return interval_minutes * 60
        except Exception as e:
            logger.warning(f"Fehler beim Lesen des Synchronisationsintervalls: {e}")
        
        return 30 * 60
    
    def _run_scheduler(self):
        """Hauptschleife des Schedulers."""
        while self.running:
            try:
                with self.app.app_context():
                    from app.blueprints.email import sync_emails_from_server, cleanup_old_emails
                    from app.utils.lock_manager import acquire_email_sync_lock
                    
                    # Non-blocking — nie 300s hinter anderem Worker warten
                    with acquire_email_sync_lock(timeout=0) as acquired:
                        if acquired:
                            logger.info("Starte automatische E-Mail-Synchronisation...")
                            success, message = sync_emails_from_server()
                            
                            if success:
                                logger.info(f"E-Mail-Synchronisation erfolgreich: {message}")
                            else:
                                logger.warning(f"E-Mail-Synchronisation fehlgeschlagen: {message}")
                            
                            deleted_count = cleanup_old_emails()
                            if deleted_count > 0:
                                logger.info(f"E-Mail-Bereinigung: {deleted_count} E-Mails gelöscht")
                        else:
                            logger.debug(
                                "E-Mail-Synchronisation wird bereits von anderem Worker durchgeführt, überspringe..."
                            )
                    
                    interval_seconds = self._get_sync_interval()
                    logger.debug(f"Warte {interval_seconds // 60} Minuten bis zur nächsten Synchronisation...")
                
                waited = 0
                while self.running and waited < interval_seconds:
                    time.sleep(min(60, interval_seconds - waited))
                    waited += 60
                
            except Exception as e:
                logger.error(f"Fehler im E-Mail-Synchronisations-Scheduler: {e}", exc_info=True)
                time.sleep(300)


scheduler = EmailSyncScheduler()


def start_email_sync_scheduler(app):
    """Starte den E-Mail-Synchronisations-Scheduler für die gegebene App."""
    global scheduler
    scheduler.init_app(app)
    return scheduler


def stop_email_sync_scheduler():
    """Stoppe den E-Mail-Synchronisations-Scheduler."""
    global scheduler
    scheduler.stop()
