"""Background cleanup for expired files trash (soft-delete retention)."""

import logging

from app.tasks.interval_scheduler import IntervalScheduler
from app.utils.files_trash_retention import purge_expired_trash

logger = logging.getLogger(__name__)

_scheduler = None


class FilesTrashCleanupScheduler(IntervalScheduler):
    name = "files-trash-cleanup"
    wait_step_seconds = 60
    error_wait_seconds = 120
    start_delay_seconds = 45

    def interval_seconds(self):
        return 3600  # hourly

    def run_job(self):
        result = purge_expired_trash()
        if result.get('disabled'):
            return
        if result.get('purged_files') or result.get('purged_folders'):
            logger.info('files-trash-cleanup: %s', result)


def start_files_trash_cleanup(app):
    global _scheduler
    if _scheduler is None:
        _scheduler = FilesTrashCleanupScheduler(app)
    _scheduler.start()
