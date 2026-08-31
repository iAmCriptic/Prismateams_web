"""Background cleanup for expired file converter jobs."""

import logging
import threading
import time
from datetime import datetime

from app import db
from app.models.file_converter import ConversionJob
from app.utils.file_converter import delete_job_files

logger = logging.getLogger(__name__)

_scheduler = None


def cleanup_expired_conversions():
    """Delete expired conversion jobs and their files."""
    try:
        expired_jobs = ConversionJob.query.filter(
            ConversionJob.expires_at.isnot(None),
            ConversionJob.expires_at < datetime.utcnow(),
        ).all()

        deleted_count = 0
        for job in expired_jobs:
            try:
                delete_job_files(job)
                db.session.delete(job)
                deleted_count += 1
            except Exception as exc:
                logger.error('Failed to cleanup conversion job %s: %s', job.id, exc)
                db.session.rollback()
                continue

        if deleted_count:
            db.session.commit()
            logger.info('Removed %s expired conversion job(s).', deleted_count)

        return deleted_count
    except Exception as exc:
        logger.error('File converter cleanup failed: %s', exc, exc_info=True)
        db.session.rollback()
        return 0


class FileConverterCleanupScheduler:
    def __init__(self, app):
        self.app = app
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
            name='file-converter-cleanup',
        )
        self.thread.start()

    def _run(self):
        while self.running:
            try:
                with self.app.app_context():
                    cleanup_expired_conversions()
            except Exception as exc:
                logger.error('File converter cleanup scheduler error: %s', exc, exc_info=True)
            time.sleep(900)


def start_file_converter_cleanup(app):
    global _scheduler
    if _scheduler is None:
        _scheduler = FileConverterCleanupScheduler(app)
    _scheduler.start()
