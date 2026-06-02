"""Background cleanup for expired media downloader files."""

import logging
import threading
import time

from datetime import datetime

from app import db
from app.models.media_downloader import MediaDownloadJob
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


class MediaDownloaderCleanupScheduler:
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
            name='media-downloader-cleanup',
        )
        self.thread.start()

    def _run(self):
        while self.running:
            try:
                with self.app.app_context():
                    cleanup_expired_downloads()
            except Exception as exc:
                logger.error('Media downloader cleanup scheduler error: %s', exc, exc_info=True)
            time.sleep(900)


def start_media_downloader_cleanup(app):
    global _scheduler
    if _scheduler is None:
        _scheduler = MediaDownloaderCleanupScheduler(app)
    _scheduler.start()
