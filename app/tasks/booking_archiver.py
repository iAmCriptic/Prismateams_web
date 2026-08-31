"""
Archivierungssystem für Buchungsanfragen.
Automatische Archivierung von vergangenen Events basierend auf archive_days.
"""
import logging
from datetime import datetime, timedelta
from app import db
from app.models.booking import BookingRequest, BookingForm

logger = logging.getLogger(__name__)


def archive_old_booking_requests():
    """
    Archiviert Buchungsanfragen, deren Event-Datum mehr als archive_days Tage in der Vergangenheit liegt.
    Diese Funktion sollte regelmäßig (z.B. täglich) aufgerufen werden.
    """
    try:
        # Hole alle Formulare mit ihren archive_days Einstellungen
        forms = BookingForm.query.all()
        archived_count = 0
        
        for form in forms:
            # Berechne das Archivierungsdatum
            archive_date = datetime.utcnow().date() - timedelta(days=form.archive_days)
            
            # Finde alle akzeptierten oder abgelehnten Buchungen, die noch nicht archiviert sind
            # und deren Event-Datum vor dem Archivierungsdatum liegt
            old_requests = BookingRequest.query.filter(
                BookingRequest.form_id == form.id,
                BookingRequest.status.in_(['accepted', 'rejected']),
                BookingRequest.status != 'archived',
                BookingRequest.event_date < archive_date
            ).all()
            
            # Archiviere diese Buchungen
            for request in old_requests:
                request.status = 'archived'
                archived_count += 1
        
        # Speichere Änderungen
        if archived_count > 0:
            db.session.commit()
            logger.info("%s Buchungsanfragen wurden archiviert.", archived_count)
            return archived_count
        
        return 0
        
    except Exception as e:
        db.session.rollback()
        logger.error("Fehler beim Archivieren: %s", e, exc_info=True)
        return 0


if __name__ == '__main__':
    # Für manuellen Aufruf
    from app import create_app
    app = create_app()
    with app.app_context():
        count = archive_old_booking_requests()
        logger.info("Archivierung abgeschlossen. %s Buchungen archiviert.", count)

