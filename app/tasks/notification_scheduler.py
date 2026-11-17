"""Background Task für Benachrichtigungen (Idle-sparsam)."""

from datetime import datetime, timedelta

from app.tasks.guest_cleanup import cleanup_expired_guests
from app.tasks.interval_scheduler import IntervalScheduler
from app.utils.notifications import cleanup_inactive_subscriptions, schedule_calendar_reminders

# Mit Kalender: 10 Min (Reminder-Fenster in schedule_calendar_reminders abgestimmt).
# Ohne Kalender: 15 Min — nur Guest-/Push-Cleanup-Gates.
INTERVAL_WITH_CALENDAR_SECONDS = 10 * 60
INTERVAL_IDLE_SECONDS = 15 * 60


class NotificationScheduler(IntervalScheduler):
    """Scheduler für Kalender-Reminder, Guest-Cleanup und Push-Subscription-Purge."""

    name = "notification-scheduler"
    wait_step_seconds = 60
    error_wait_seconds = 120
    start_delay_seconds = 60

    def __init__(self, app=None):
        self._last_guest_cleanup = None
        super().__init__(app)

    def interval_seconds(self):
        from app.utils.common import is_module_enabled

        if is_module_enabled('module_calendar'):
            return INTERVAL_WITH_CALENDAR_SECONDS
        return INTERVAL_IDLE_SECONDS

    def run_job(self):
        from app.utils.common import is_module_enabled

        # PERF-04: Kalender-Job nur bei aktivem Modul (kein leerer Tick + Inspector)
        if is_module_enabled('module_calendar'):
            schedule_calendar_reminders()

        now = datetime.utcnow()
        # Push-Subscriptions: einmal nachts im 2-Uhr-Fenster (Intervall 10–15 Min)
        if now.hour == 2 and now.minute < 15:
            cleanup_inactive_subscriptions()

        # Guest-Cleanup höchstens stündlich
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
