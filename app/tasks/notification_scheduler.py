"""
Background Task für Benachrichtigungen
Führt regelmäßig Kalender-Erinnerungen und andere geplante Benachrichtigungen aus.
"""

import threading
import time
import logging
from datetime import datetime, timedelta
from app import create_app
from app.utils.notifications import schedule_calendar_reminders, cleanup_inactive_subscriptions
from app.tasks.guest_cleanup import cleanup_expired_guests

logger = logging.getLogger(__name__)


class NotificationScheduler:
    """Scheduler für regelmäßige Benachrichtigungen."""
    
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
        """Starte den Benachrichtigungs-Scheduler."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("Benachrichtigungs-Scheduler gestartet")
    
    def stop(self):
        """Stoppe den Benachrichtigungs-Scheduler."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Benachrichtigungs-Scheduler gestoppt")
    
    def _run_scheduler(self):
        """Hauptschleife des Schedulers."""
        while self.running:
            try:
                with self.app.app_context():
                    # Führe Kalender-Erinnerungen aus
                    schedule_calendar_reminders()
                    
                    # Bereinige inaktive Push-Subscriptions (nur einmal täglich)
                    now = datetime.utcnow()
                    if now.hour == 2 and now.minute < 5:  # Zwischen 2:00 und 2:05
                        cleanup_inactive_subscriptions()
                    
                    # Bereinige abgelaufene Gast-Accounts (einmal täglich, z.B. um 3:00)
                    if now.hour == 3 and now.minute < 5:  # Zwischen 3:00 und 3:05
                        cleanup_expired_guests()
                
                # Warte 5 Minuten bis zur nächsten Ausführung
                time.sleep(300)
                
            except Exception as e:
                logger.error(f"Fehler im Benachrichtigungs-Scheduler: {e}")
                time.sleep(60)  # Warte 1 Minute bei Fehlern


# Globale Scheduler-Instanz
scheduler = NotificationScheduler()


def start_notification_scheduler(app):
    """Starte den Benachrichtigungs-Scheduler für die gegebene App."""
    global scheduler
    scheduler.init_app(app)
    return scheduler


def stop_notification_scheduler():
    """Stoppe den Benachrichtigungs-Scheduler."""
    global scheduler
    scheduler.stop()
