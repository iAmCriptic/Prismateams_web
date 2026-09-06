"""Background cleanup for expired file converter jobs."""

import logging
from datetime import datetime

from app import db
from app.models.file_converter import ConversionJob
from app.tasks.interval_scheduler import IntervalScheduler
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


class FileConverterCleanupScheduler(IntervalScheduler):
    name = "file-converter-cleanup"
    wait_step_seconds = 60
    error_wait_seconds = 60

    def interval_seconds(self):
        return 900

    def run_job(self):
        cleanup_expired_conversions()


def start_file_converter_cleanup(app):
    global _scheduler
    if _scheduler is None:
        _scheduler = FileConverterCleanupScheduler(app)
    _scheduler.start()
