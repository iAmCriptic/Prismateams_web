"""
Archivierungssystem für Buchungsanfragen.
Automatische Archivierung von vergangenen Events basierend auf archive_days.
"""
import logging
from datetime import datetime, timedelta

from app import db
from app.models.booking import BookingForm, BookingRequest
from app.tasks.interval_scheduler import IntervalScheduler

logger = logging.getLogger(__name__)

_scheduler = None


def archive_old_booking_requests():
    """
    Archiviert Buchungsanfragen, deren Event-Datum mehr als archive_days Tage
    in der Vergangenheit liegt. Für Background-Job und optionalen Lazy-Aufruf.
    """
    try:
        forms = BookingForm.query.all()
        archived_count = 0

        for form in forms:
            archive_date = datetime.utcnow().date() - timedelta(days=form.archive_days)

            old_requests = BookingRequest.query.filter(
                BookingRequest.form_id == form.id,
                BookingRequest.status.in_(['accepted', 'rejected']),
                BookingRequest.event_date < archive_date,
            ).all()

            for request in old_requests:
                request.status = 'archived'
                archived_count += 1

        if archived_count > 0:
            db.session.commit()
            logger.info("%s Buchungsanfragen wurden archiviert.", archived_count)
            return archived_count

        return 0

    except Exception as e:
        db.session.rollback()
        logger.error("Fehler beim Archivieren: %s", e, exc_info=True)
        return 0


class BookingArchiverScheduler(IntervalScheduler):
    name = "booking-archiver"
    wait_step_seconds = 60
    error_wait_seconds = 120
    start_delay_seconds = 120

    def interval_seconds(self):
        return 86400  # daily

    def run_job(self):
        from app.utils.common import is_module_enabled

        if not is_module_enabled('module_booking'):
            logger.debug("module_booking deaktiviert — Booking-Archiver idle")
            return
        archive_old_booking_requests()


def start_booking_archiver(app):
    global _scheduler
    if _scheduler is None:
        _scheduler = BookingArchiverScheduler(app)
    _scheduler.start()


if __name__ == '__main__':
    from app import create_app

    app = create_app()
    with app.app_context():
        count = archive_old_booking_requests()
        logger.info("Archivierung abgeschlossen. %s Buchungen archiviert.", count)
