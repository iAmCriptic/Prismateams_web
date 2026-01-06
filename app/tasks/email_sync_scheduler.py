"""
Background Task für E-Mail-Synchronisation
Führt regelmäßig die Synchronisation von E-Mails vom IMAP-Server durch.
"""

import threading
import time
import logging
from datetime import datetime
from app import create_app
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
        
        # Starte Scheduler automatisch
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
        """Hole das Synchronisationsintervall aus den Einstellungen (in Sekunden).
        Muss innerhalb eines Application Contexts aufgerufen werden."""
        try:
            sync_setting = SystemSettings.query.filter_by(key='email_sync_interval_minutes').first()
            if sync_setting and sync_setting.value:
                interval_minutes = int(sync_setting.value)
                # Mindestens 15 Minuten, maximal 60 Minuten
                interval_minutes = max(15, min(60, interval_minutes))
                return interval_minutes * 60  # Konvertiere zu Sekunden
        except Exception as e:
            logger.warning(f"Fehler beim Lesen des Synchronisationsintervalls: {e}")
        
        # Standard: 30 Minuten
        return 30 * 60
    
    def _run_scheduler(self):
        """Hauptschleife des Schedulers."""
        while self.running:
            try:
                with self.app.app_context():
                    # Importiere hier, um zirkuläre Imports zu vermeiden
                    from app.blueprints.email import sync_emails_from_server, cleanup_old_emails
                    
                    logger.info("Starte automatische E-Mail-Synchronisation...")
                    success, message = sync_emails_from_server()
                    
                    if success:
                        logger.info(f"E-Mail-Synchronisation erfolgreich: {message}")
                    else:
                        logger.warning(f"E-Mail-Synchronisation fehlgeschlagen: {message}")
                    
                    # Führe E-Mail-Bereinigung durch
                    deleted_count = cleanup_old_emails()
                    if deleted_count > 0:
                        logger.info(f"E-Mail-Bereinigung: {deleted_count} E-Mails gelöscht")
                    
                    # Hole das Intervall innerhalb des Application Contexts
                    interval_seconds = self._get_sync_interval()
                    logger.debug(f"Warte {interval_seconds // 60} Minuten bis zur nächsten Synchronisation...")
                
                # Warte in kleinen Schritten, um auf Stop-Anfragen reagieren zu können
                waited = 0
                while self.running and waited < interval_seconds:
                    time.sleep(min(60, interval_seconds - waited))  # Warte max. 1 Minute pro Iteration
                    waited += 60
                
            except Exception as e:
                logger.error(f"Fehler im E-Mail-Synchronisations-Scheduler: {e}", exc_info=True)
                # Warte 5 Minuten bei Fehlern
                time.sleep(300)


# Globale Scheduler-Instanz
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

