"""Background cleanup for expired media downloader files."""

import logging
from datetime import datetime

from app import db
from app.models.media_downloader import MediaDownloadJob
from app.tasks.interval_scheduler import IntervalScheduler
from app.utils.media_downloader import delete_job_file

logger = logging.getLogger(__name__)

_scheduler = None


def cleanup_expired_downloads():
    """Delete expired download jobs and their files."""
    try:
        expired_jobs = MediaDownloadJob.query.filter(
            MediaDownloadJob.expires_at.isnot(None),
            MediaDownloadJob.expires_at < datetime.utcnow(),
        ).all()

        deleted_count = 0
        for job in expired_jobs:
            try:
                delete_job_file(job)
                db.session.delete(job)
                deleted_count += 1
            except Exception as exc:
                logger.error('Failed to cleanup media download job %s: %s', job.id, exc)
                db.session.rollback()
                continue

        if deleted_count:
            db.session.commit()
            logger.info('Removed %s expired media download job(s).', deleted_count)

        return deleted_count
    except Exception as exc:
        logger.error('Media downloader cleanup failed: %s', exc, exc_info=True)
        db.session.rollback()
        return 0


class MediaDownloaderCleanupScheduler(IntervalScheduler):
    name = "media-downloader-cleanup"
    wait_step_seconds = 60
    error_wait_seconds = 60

    def interval_seconds(self):
        return 900

    def run_job(self):
        from app.utils.common import is_module_enabled

        if not is_module_enabled('module_media_downloader'):
            logger.debug("module_media_downloader deaktiviert — Cleanup idle")
            return
        cleanup_expired_downloads()


def start_media_downloader_cleanup(app):
    global _scheduler
    if _scheduler is None:
        _scheduler = MediaDownloaderCleanupScheduler(app)
    _scheduler.start()
