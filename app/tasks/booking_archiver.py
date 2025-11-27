"""
Archivierungssystem für Buchungsanfragen.
Automatische Archivierung von vergangenen Events basierend auf archive_days.
"""
from datetime import datetime, timedelta
from app import db
from app.models.booking import BookingRequest, BookingForm


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
            print(f"[Booking Archiver] {archived_count} Buchungsanfragen wurden archiviert.")
            return archived_count
        
        return 0
        
    except Exception as e:
        db.session.rollback()
        print(f"[Booking Archiver] Fehler beim Archivieren: {e}")
        return 0


if __name__ == '__main__':
    # Für manuellen Aufruf
    from app import create_app
    app = create_app()
    with app.app_context():
        count = archive_old_booking_requests()
        print(f"Archivierung abgeschlossen. {count} Buchungen archiviert.")

