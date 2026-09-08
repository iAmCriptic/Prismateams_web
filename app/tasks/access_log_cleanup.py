"""Background cleanup for expired session records and share access logs."""

import logging

from app.tasks.interval_scheduler import IntervalScheduler
from app.utils.access_log_retention import purge_expired_access_logs

logger = logging.getLogger(__name__)

_scheduler = None


class AccessLogCleanupScheduler(IntervalScheduler):
    name = "access-log-cleanup"
    wait_step_seconds = 60
    error_wait_seconds = 120
    start_delay_seconds = 90

    def interval_seconds(self):
        return 3600

    def run_job(self):
        result = purge_expired_access_logs()
        if result.get('deleted_sessions') or result.get('deleted_share_logs'):
            logger.info('access-log-cleanup: %s', result)


def start_access_log_cleanup(app):
    global _scheduler
    if _scheduler is None:
        _scheduler = AccessLogCleanupScheduler(app)
    _scheduler.start()
