"""Background Task für Benachrichtigungen."""

from datetime import datetime, timedelta

from app.tasks.guest_cleanup import cleanup_expired_guests
from app.tasks.interval_scheduler import IntervalScheduler
from app.utils.notifications import cleanup_inactive_subscriptions, schedule_calendar_reminders


class NotificationScheduler(IntervalScheduler):
    """Scheduler für regelmäßige Benachrichtigungen."""

    name = "notification-scheduler"
    wait_step_seconds = 5
    error_wait_seconds = 60

    def __init__(self, app=None):
        self._last_guest_cleanup = None
        super().__init__(app)

    def interval_seconds(self):
        return 300

    def run_job(self):
        schedule_calendar_reminders()
        now = datetime.utcnow()
        if now.hour == 2 and now.minute < 5:
            cleanup_inactive_subscriptions()
        if (
            self._last_guest_cleanup is None
            or (now - self._last_guest_cleanup) >= timedelta(hours=1)
        ):
            cleanup_expired_guests()
            self._last_guest_cleanup = now


scheduler = NotificationScheduler()


def start_notification_scheduler(app):
    global scheduler
    scheduler.init_app(app)
    return scheduler


def stop_notification_scheduler():
    global scheduler
    scheduler.stop()
